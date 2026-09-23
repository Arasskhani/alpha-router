"""A small SMTP server for tests: real sockets, real TLS, each way to secure a session.

The SMTP code is exercised against it end to end, so a test sees what a mail
server really does with each client setting — including the
"[SSL: WRONG_VERSION_NUMBER]" an implicit-TLS client gets from a STARTTLS port,
and whether a password ever crosses the wire unencrypted.

Certificates are made per test run with ``cryptography`` (already a runtime
dependency). The client trusts them the way it trusts any CA: point
``SSL_CERT_FILE`` at ``TlsMaterial.ca_path``, which OpenSSL reads whenever a
default context is created. No hook in the code under test.

Not a general SMTP implementation: EHLO/HELO, STARTTLS, AUTH PLAIN, MAIL, RCPT,
DATA, RSET, NOOP and QUIT — what aiosmtplib uses.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import datetime
import ipaddress
import ssl
from dataclasses import dataclass, field
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

MODE_STARTTLS = "starttls"
MODE_SSL = "ssl"
MODE_PLAIN = "plain"


@dataclass(frozen=True)
class TlsMaterial:
    #: PEM of the CA that signed ``server_context``'s certificate.
    ca_path: Path
    #: For localhost and 127.0.0.1, signed by that CA.
    server_context: ssl.SSLContext
    #: A self-signed certificate for the same names that nothing trusts.
    self_signed_context: ssl.SSLContext
    #: Signed by the CA, but only for mail.invalid.
    wrong_name_context: ssl.SSLContext
    #: Signed by the CA for localhost and 127.0.0.1, expired yesterday.
    expired_context: ssl.SSLContext


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _server_context(
    directory: Path, stem: str, cert: x509.Certificate, key: ec.EllipticCurvePrivateKey
) -> ssl.SSLContext:
    cert_path = directory / f"{stem}.pem"
    key_path = directory / f"{stem}.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(cert_path, key_path)
    return context


def make_tls_material(directory: Path) -> TlsMaterial:
    now = datetime.datetime.now(datetime.UTC)
    names = x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))])

    def certificate(
        subject: x509.Name,
        issuer: x509.Name,
        public_key,
        signer,
        *,
        ca: bool,
        san: x509.SubjectAlternativeName = names,
        expired: bool = False,
    ) -> x509.Certificate:
        start, end = now - datetime.timedelta(minutes=5), now + datetime.timedelta(days=1)
        if expired:
            start, end = now - datetime.timedelta(days=30), now - datetime.timedelta(days=1)
        builder = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(public_key)
            .serial_number(x509.random_serial_number())
            .not_valid_before(start)
            .not_valid_after(end)
        )
        if ca:
            builder = builder.add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        else:
            builder = builder.add_extension(san, critical=False)
        return builder.sign(signer, hashes.SHA256())

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_cert = certificate(
        _name("Alpharouter test CA"), _name("Alpharouter test CA"), ca_key.public_key(), ca_key, ca=True
    )
    ca_path = directory / "test-ca.pem"
    ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))

    server_key = ec.generate_private_key(ec.SECP256R1())
    server_cert = certificate(_name("localhost"), ca_cert.subject, server_key.public_key(), ca_key, ca=False)

    lone_key = ec.generate_private_key(ec.SECP256R1())
    lone_cert = certificate(_name("localhost"), _name("localhost"), lone_key.public_key(), lone_key, ca=False)

    other_key = ec.generate_private_key(ec.SECP256R1())
    other_cert = certificate(
        _name("mail.invalid"),
        ca_cert.subject,
        other_key.public_key(),
        ca_key,
        ca=False,
        san=x509.SubjectAlternativeName([x509.DNSName("mail.invalid")]),
    )

    old_key = ec.generate_private_key(ec.SECP256R1())
    old_cert = certificate(_name("localhost"), ca_cert.subject, old_key.public_key(), ca_key, ca=False, expired=True)

    return TlsMaterial(
        ca_path=ca_path,
        server_context=_server_context(directory, "server", server_cert, server_key),
        self_signed_context=_server_context(directory, "self-signed", lone_cert, lone_key),
        wrong_name_context=_server_context(directory, "wrong-name", other_cert, other_key),
        expired_context=_server_context(directory, "expired", old_cert, old_key),
    )


@dataclass(frozen=True)
class AuthAttempt:
    username: str
    password: str
    #: Whether the session was encrypted when the password arrived.
    tls: bool


@dataclass(frozen=True)
class ReceivedMessage:
    mail_from: str
    recipients: tuple[str, ...]
    data: bytes
    tls: bool


@dataclass
class SmtpTestServer:
    """``async with SmtpTestServer(...) as server:`` listens on 127.0.0.1:``server.port``.

    * ``starttls``: plain greeting; STARTTLS offered unless ``advertise_starttls`` is False.
    * ``ssl``: TLS from the first byte.
    * ``plain``: never any TLS.

    ``refuse_recipients`` get "554 ... Relay access denied" at RCPT, and
    ``refuse_sender`` refuses every MAIL FROM, as a real server might.
    """

    mode: str = MODE_STARTTLS
    tls_context: ssl.SSLContext | None = None
    advertise_starttls: bool = True
    username: str = "alpha"
    password: str = "s3cret"
    refuse_recipients: frozenset[str] = frozenset()
    refuse_sender: bool = False
    auth_attempts: list[AuthAttempt] = field(default_factory=list)
    messages: list[ReceivedMessage] = field(default_factory=list)
    #: Every command received, with whether it arrived encrypted.
    commands: list[tuple[str, bool]] = field(default_factory=list)
    port: int = 0

    def __post_init__(self) -> None:
        if self.mode in (MODE_STARTTLS, MODE_SSL) and self.tls_context is None:
            raise ValueError(f"mode {self.mode!r} needs a tls_context")
        self._server: asyncio.Server | None = None
        self._writers: list[asyncio.StreamWriter] = []

    async def __aenter__(self) -> SmtpTestServer:
        self._server = await asyncio.start_server(
            self._handle,
            "127.0.0.1",
            0,
            ssl=self.tls_context if self.mode == MODE_SSL else None,
        )
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        assert self._server is not None
        self._server.close()
        # Since 3.12 wait_closed() also waits for open connections; a client
        # that gave up mid-handshake must not hold the test up.
        for writer in self._writers:
            transport = writer.transport
            if transport is not None:
                transport.abort()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._server.wait_closed(), 5)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.append(writer)
        session = _Session(server=self, reader=reader, writer=writer, tls=self.mode == MODE_SSL)
        try:
            await session.reply("220 localhost ESMTP test server")
            while await session.step():
                pass
        except (ConnectionError, ssl.SSLError, asyncio.IncompleteReadError, ValueError):
            return
        finally:
            # After a failed STARTTLS the stream may have no transport left.
            with contextlib.suppress(AttributeError, RuntimeError):
                writer.close()


@dataclass
class _Session:
    """One client connection: reads a command, answers it, reports whether to go on."""

    server: SmtpTestServer
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    tls: bool
    mail_from: str = ""
    recipients: list[str] = field(default_factory=list)

    async def reply(self, *lines: str) -> None:
        self.writer.write("".join(f"{line}\r\n" for line in lines).encode())
        await self.writer.drain()

    async def step(self) -> bool:
        raw = await self.reader.readline()
        if not raw:
            return False
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        verb = line.split(" ", 1)[0].upper()
        self.server.commands.append((verb, self.tls))
        handler = {
            "EHLO": self._ehlo,
            "HELO": self._ehlo,
            "STARTTLS": self._starttls,
            "AUTH": self._auth,
            "MAIL": self._mail,
            "RCPT": self._rcpt,
            "DATA": self._data,
        }.get(verb)
        if verb == "QUIT":
            await self.reply("221 Bye")
            return False
        if handler is None:
            await self.reply("250 OK")
            return True
        return await handler(line)

    async def _ehlo(self, _line: str) -> bool:
        capabilities = ["localhost"]
        if self.server.mode == MODE_STARTTLS and self.server.advertise_starttls and not self.tls:
            capabilities.append("STARTTLS")
        capabilities.append("AUTH PLAIN")
        await self.reply(*[f"250-{c}" for c in capabilities[:-1]], f"250 {capabilities[-1]}")
        return True

    async def _starttls(self, _line: str) -> bool:
        server = self.server
        if server.mode != MODE_STARTTLS or not server.advertise_starttls or self.tls:
            await self.reply("502 STARTTLS not available")
            return True
        await self.reply("220 Ready to start TLS")
        assert server.tls_context is not None
        plain = self.writer.transport
        try:
            await self.writer.start_tls(server.tls_context)
        finally:
            if self.writer.transport is None:
                # The client refused the handshake. CPython then leaves the
                # writer without a transport, and its __del__ fails on that
                # later, in some other test.
                self.writer._transport = plain  # noqa: SLF001
        if self.writer.transport is plain:
            return False
        self.tls = True
        return True

    async def _auth(self, line: str) -> bool:
        parts = line.split(" ")
        if len(parts) < 3 or parts[1].upper() != "PLAIN":
            await self.reply("504 Only AUTH PLAIN with an initial response")
            return True
        _, user, password = base64.b64decode(parts[2]).split(b"\0", 2)
        attempt = AuthAttempt(user.decode(), password.decode(), self.tls)
        self.server.auth_attempts.append(attempt)
        if attempt.username == self.server.username and attempt.password == self.server.password:
            await self.reply("235 2.7.0 Authentication successful")
        else:
            await self.reply("535 5.7.8 Authentication credentials invalid")
        return True

    @staticmethod
    def _address(line: str) -> str:
        return line.split(":", 1)[1].strip().strip("<>").split(">")[0]

    async def _mail(self, line: str) -> bool:
        sender = self._address(line)
        if self.server.refuse_sender:
            await self.reply(f"553 5.7.1 <{sender}>: Sender address rejected: not owned by user")
            return True
        self.mail_from = sender
        self.recipients = []
        await self.reply("250 OK")
        return True

    async def _rcpt(self, line: str) -> bool:
        recipient = self._address(line)
        if recipient in self.server.refuse_recipients:
            await self.reply(f"554 5.7.1 <{recipient}>: Relay access denied")
            return True
        self.recipients.append(recipient)
        await self.reply("250 OK")
        return True

    async def _data(self, _line: str) -> bool:
        await self.reply("354 End data with <CR><LF>.<CR><LF>")
        chunks: list[bytes] = []
        while True:
            chunk = await self.reader.readline()
            if not chunk or chunk == b".\r\n":
                break
            chunks.append(chunk)
        self.server.messages.append(ReceivedMessage(self.mail_from, tuple(self.recipients), b"".join(chunks), self.tls))
        await self.reply("250 OK queued")
        return True
