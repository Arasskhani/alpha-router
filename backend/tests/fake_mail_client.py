"""An Exchange mailbox in memory, for tests of everything above the EWS client.

``FakeExchange`` holds mailboxes, messages, drafts, people and calendars;
``FakeMailClient`` is one login's view of it and implements
``exchange_ews_types.MailClient``. ``install(monkeypatch, exchange)`` makes
``exchange_mail.make_client`` hand out clients of that exchange, so the APIs,
the chat's mail tools and the needs-action check run against it unchanged.

It follows the rules the real client promises: a wrong password raises
``auth``, a mailbox the login has no Full Access to raises ``access_denied``,
a draft sent with an old change key raises ``conflict``, and ``whoami`` of
a login hidden from the address book works only from a hint (its email).
``calls`` records every call (method name and mailbox, or the hint), so a
test can check that nothing reached Exchange.
"""

from __future__ import annotations

import datetime
import itertools
from dataclasses import dataclass, field, replace
from typing import Any

from app.services.exchange_ews_types import (
    Address,
    Attachment,
    Availability,
    BusyInterval,
    DraftResult,
    EwsConfig,
    EwsError,
    MailboxInfo,
    MessageDetail,
    MessageSummary,
    Person,
    WorkingHours,
)

UTC = datetime.UTC


@dataclass
class FakeMessage:
    item_id: str
    mailbox: str
    subject: str
    sender: Address | None
    body: str = ""
    to: tuple[Address, ...] = ()
    cc: tuple[Address, ...] = ()
    received: datetime.datetime | None = None
    is_read: bool = False
    importance: str = "Normal"
    folder: str = "inbox"
    attachments: tuple[Attachment, ...] = ()
    is_meeting_request: bool = False
    flagged: bool = False
    hints: dict[str, str] = field(default_factory=dict)
    change_key: str = "ck1"
    is_draft: bool = False
    kind: str = ""


@dataclass
class FakeAccount:
    login: str
    password: str
    smtp: str
    display_name: str = ""
    #: Other mailboxes this login has Full Access to.
    full_access: tuple[str, ...] = ()
    #: Of those, the ones Autodiscover lists (automapped).
    automapped: tuple[str, ...] = ()
    #: Mailboxes it may send as.
    send_as: tuple[str, ...] = ()
    #: Hidden from the address book: ``whoami`` finds it only from a hint, and without its name.
    hidden: bool = False


class FakeExchange:
    def __init__(self) -> None:
        self.accounts: dict[str, FakeAccount] = {}
        self.mailboxes: dict[str, str] = {}  # smtp -> display name
        self.aliases: dict[str, str] = {}  # alias smtp -> primary smtp
        self.messages: dict[str, FakeMessage] = {}
        self.people: list[Person] = []
        self.busy: dict[str, list[BusyInterval]] = {}
        self.working_hours: dict[str, WorkingHours] = {}
        self.sent: list[FakeMessage] = []
        self.calls: list[tuple[str, str]] = []
        #: Set to an ``EwsError`` to make every call fail with it (Exchange down, say).
        self.fail_with: EwsError | None = None
        #: Set to make Autodiscover fail as the real client reports it: no mailboxes, and this reason.
        self.autodiscover_problem = ""
        self._ids = itertools.count(1)

    # --- setting it up ---

    def add_account(
        self,
        login: str,
        password: str,
        smtp: str,
        display_name: str = "",
        *,
        full_access: tuple[str, ...] = (),
        automapped: tuple[str, ...] | None = None,
        send_as: tuple[str, ...] = (),
        hidden: bool = False,
    ) -> FakeAccount:
        account = FakeAccount(
            login=login.lower(),
            password=password,
            smtp=smtp.lower(),
            display_name=display_name,
            full_access=tuple(s.lower() for s in full_access),
            automapped=tuple(s.lower() for s in (full_access if automapped is None else automapped)),
            send_as=tuple(s.lower() for s in send_as),
            hidden=hidden,
        )
        self.accounts[account.login] = account
        self.mailboxes.setdefault(account.smtp, display_name)
        return account

    def add_mailbox(self, smtp: str, display_name: str = "") -> None:
        self.mailboxes[smtp.lower()] = display_name

    def add_message(self, mailbox: str, subject: str, *, sender: str = "boss@corp.example", **kw: Any) -> FakeMessage:
        item_id = f"AAMk{next(self._ids):06d}" + "x" * 40
        sender_name = kw.pop("sender_name", sender.split("@", 1)[0].title())
        message = FakeMessage(
            item_id=item_id,
            mailbox=mailbox.lower(),
            subject=subject,
            sender=Address(sender.lower(), sender_name) if sender else None,
            received=kw.pop("received", datetime.datetime(2026, 10, 20, 9, 0, tzinfo=UTC)),
            **kw,
        )
        self.messages[item_id] = message
        return message

    def client(self, config: EwsConfig) -> FakeMailClient:
        return FakeMailClient(self, config)


class FakeMailClient:
    def __init__(self, exchange: FakeExchange, config: EwsConfig) -> None:
        self.exchange = exchange
        self.config = config
        self.closed = False
        self.autodiscover_problem = ""

    # --- helpers ---

    def _account(self, method: str, mailbox: str = "") -> FakeAccount:
        self.exchange.calls.append((method, mailbox))
        if self.exchange.fail_with is not None:
            raise self.exchange.fail_with
        account = self.exchange.accounts.get(self.config.login.lower())
        if account is None or account.password != self.config.password:
            raise EwsError("auth", "Exchange did not accept the user name or password.")
        return account

    def _primary(self, smtp: str) -> str:
        smtp = smtp.lower()
        return self.exchange.aliases.get(smtp, smtp)

    def _open(self, method: str, mailbox: str) -> FakeAccount:
        account = self._account(method, mailbox)
        box = self._primary(mailbox)
        if box not in self.exchange.mailboxes:
            raise EwsError("not_found", f"There is no mailbox {mailbox}.")
        if box != account.smtp and box not in account.full_access:
            raise EwsError("access_denied", f"You do not have access to the mailbox {mailbox}.")
        return account

    @staticmethod
    def _summary(message: FakeMessage) -> MessageSummary:
        return MessageSummary(
            item_id=message.item_id,
            change_key=message.change_key,
            mailbox=message.mailbox,
            subject=message.subject,
            sender=message.sender,
            to=message.to,
            cc=message.cc,
            received=message.received,
            is_read=message.is_read,
            has_attachments=bool(message.attachments),
            importance=message.importance,
            preview=" ".join(message.body.split())[:255],
            folder=message.folder,
            is_meeting_request=message.is_meeting_request,
            flagged=message.flagged,
            owa_url=f"https://mail.corp.example/owa/?ItemID={message.item_id[:12]}",
            hints=dict(message.hints),
        )

    def _draft(self, message: FakeMessage) -> DraftResult:
        return DraftResult(
            item_id=message.item_id,
            change_key=message.change_key,
            mailbox=message.mailbox,
            subject=message.subject,
            to=message.to,
            cc=message.cc,
            body_text=message.body,
            owa_url=f"https://mail.corp.example/owa/?ItemID={message.item_id[:12]}",
        )

    # --- MailClient ---

    def whoami(self, hint_smtp: str = "") -> MailboxInfo:
        account = self._account("whoami", hint_smtp)
        if hint_smtp and self._primary(hint_smtp) == account.smtp:
            # The hint is the login's own mailbox: no address book needed (a hidden person has no name there).
            return MailboxInfo(smtp=account.smtp, display_name="" if account.hidden else account.display_name)
        if account.hidden:
            raise EwsError("server", "Exchange accepted the login, but its address book did not say whose it is.")
        return MailboxInfo(smtp=account.smtp, display_name=account.display_name)

    def same_mailbox(self, smtp: str) -> bool:
        account = self._account("same_mailbox", smtp)
        return self._primary(smtp) == account.smtp

    def discover_full_access(self) -> list[MailboxInfo]:
        account = self._account("discover_full_access")
        self.autodiscover_problem = self.exchange.autodiscover_problem
        if self.autodiscover_problem:
            return []
        return [MailboxInfo(smtp=s, display_name=self.exchange.mailboxes.get(s, "")) for s in account.automapped]

    def check_mailbox(self, smtp: str) -> MailboxInfo:
        self._open("check_mailbox", smtp)
        box = self._primary(smtp)
        return MailboxInfo(smtp=box, display_name=self.exchange.mailboxes.get(box, ""))

    def search(
        self,
        mailbox: str,
        *,
        query: str = "",
        folder: str = "inbox",
        sender: str = "",
        since: datetime.datetime | None = None,
        until: datetime.datetime | None = None,
        unread_only: bool = False,
        limit: int = 25,
        offset: int = 0,
    ) -> list[MessageSummary]:
        self._open("search", mailbox)
        box = self._primary(mailbox)
        words = [w.lower() for w in query.split() if ":" not in w]
        found = []
        for m in self.exchange.messages.values():
            if m.mailbox != box or m.is_draft and folder != "drafts":
                continue
            if folder == "all":
                if m.folder not in ("inbox", "sent") and not m.folder.startswith("inbox/"):
                    continue
            elif m.folder != folder:
                continue
            text = f"{m.subject} {m.body} {m.sender.email if m.sender else ''} {m.sender.name if m.sender else ''}"
            if words and not all(w in text.lower() for w in words):
                continue
            if sender and (not m.sender or sender.lower() not in f"{m.sender.email} {m.sender.name}".lower()):
                continue
            if since and m.received and m.received < since:
                continue
            if until and m.received and m.received > until:
                continue
            if unread_only and m.is_read:
                continue
            found.append(m)
        found.sort(key=lambda m: m.received or datetime.datetime.min.replace(tzinfo=UTC), reverse=True)
        return [self._summary(m) for m in found[offset : offset + limit]]

    def list_received(self, mailbox: str, *, since: datetime.datetime, limit: int = 50) -> list[MessageSummary]:
        self._open("list_received", mailbox)
        box = self._primary(mailbox)
        found = [
            m
            for m in self.exchange.messages.values()
            if m.mailbox == box and m.folder == "inbox" and not m.is_draft and m.received and m.received > since
        ]
        found.sort(key=lambda m: m.received)  # type: ignore[arg-type,return-value]
        return [self._summary(m) for m in found[:limit]]

    def read(self, mailbox: str, item_id: str, *, body_chars: int = 8000) -> MessageDetail:
        self._open("read", mailbox)
        message = self.exchange.messages.get(item_id)
        if message is None or message.mailbox != self._primary(mailbox):
            raise EwsError("not_found", "That email is no longer in the mailbox.")
        return MessageDetail(
            summary=self._summary(message),
            body_text=message.body[:body_chars],
            truncated=len(message.body) > body_chars,
            attachments=message.attachments,
        )

    def create_draft(
        self,
        mailbox: str,
        *,
        kind: str,
        body_text: str,
        to: tuple[Address, ...] = (),
        cc: tuple[Address, ...] = (),
        subject: str = "",
        source_item_id: str = "",
    ) -> DraftResult:
        account = self._open("create_draft", mailbox)
        box = self._primary(mailbox)
        if kind == "new":
            if not to:
                raise EwsError("invalid", "A new email needs at least one recipient.")
            recipients, copies, title, body = to, cc, subject, body_text
        else:
            source = self.exchange.messages.get(source_item_id)
            if source is None or source.mailbox != box:
                raise EwsError("not_found", "The email to answer is no longer in the mailbox.")
            prefix = "FW: " if kind == "forward" else "RE: "
            title = subject or (
                source.subject if source.subject.upper().startswith(prefix) else prefix + source.subject
            )
            body = f"{body_text}\n\n-----Original Message-----\n{source.body}"
            if kind == "forward":
                if not to:
                    raise EwsError("invalid", "A forward needs at least one recipient.")
                recipients, copies = to, cc
            else:
                own = {account.smtp, box}
                recipients = ((source.sender,) if source.sender else ()) + tuple(to)
                copies = tuple(cc)
                if kind == "reply_all":
                    recipients += tuple(a for a in source.to if a.email not in own)
                    copies += tuple(a for a in source.cc if a.email not in own)
        draft = self.exchange.add_message(
            box,
            title,
            sender=box,
            body=body,
            to=tuple(recipients),
            cc=tuple(copies),
            folder="drafts",
            is_draft=True,
            is_read=True,
            kind=kind,
        )
        return self._draft(draft)

    def get_draft(self, mailbox: str, item_id: str) -> DraftResult:
        self._open("get_draft", mailbox)
        message = self.exchange.messages.get(item_id)
        if message is None or not message.is_draft or message.mailbox != self._primary(mailbox):
            raise EwsError("not_found", "The draft is no longer in Drafts.")
        return self._draft(message)

    def send_draft(self, mailbox: str, item_id: str, change_key: str) -> None:
        account = self._open("send_draft", mailbox)
        box = self._primary(mailbox)
        message = self.exchange.messages.get(item_id)
        if message is None or not message.is_draft or message.mailbox != box:
            raise EwsError("not_found", "The draft is no longer in Drafts.")
        if message.change_key != change_key:
            raise EwsError("conflict", "The draft changed since it was read. Read it again before sending.")
        if box != account.smtp and box not in account.send_as:
            raise EwsError("access_denied", f"You may not send as {mailbox}. Ask for Send As or Send on Behalf.")
        del self.exchange.messages[item_id]
        sent = replace(message, folder="sent", is_draft=False)
        self.exchange.messages[item_id] = sent
        self.exchange.sent.append(sent)

    def delete_draft(self, mailbox: str, item_id: str) -> None:
        self._open("delete_draft", mailbox)
        message = self.exchange.messages.get(item_id)
        if message is not None and message.is_draft and message.mailbox == self._primary(mailbox):
            message.folder = "deleted"
            message.is_draft = False

    def find_people(self, query: str, *, limit: int = 10) -> list[Person]:
        self._account("find_people")
        needle = query.strip().lower()
        if not needle:
            raise EwsError("invalid", "Give a name or an address to look up.")
        return [p for p in self.exchange.people if needle in f"{p.name} {p.email}".lower()][:limit]

    def availability(
        self, emails: list[str], *, start: datetime.datetime, end: datetime.datetime
    ) -> list[Availability]:
        self._account("availability")
        out = []
        for email in emails:
            key = email.lower()
            if key not in self.exchange.mailboxes:
                out.append(Availability(email=key, busy=(), error="No mailbox has this address."))
                continue
            busy = tuple(b for b in self.exchange.busy.get(key, []) if b.end > start and b.start < end)
            out.append(Availability(email=key, busy=busy, working_hours=self.exchange.working_hours.get(key)))
        return out

    def close(self) -> None:
        self.closed = True


def install(monkeypatch: Any, exchange: FakeExchange) -> FakeExchange:
    """Point ``exchange_mail.make_client`` at ``exchange``; returns it, for chaining."""
    from app.services import exchange_mail

    monkeypatch.setattr(exchange_mail, "make_client", exchange.client)
    return exchange
