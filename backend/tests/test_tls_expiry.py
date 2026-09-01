"""TLS expiry notices must not stamp a send when SMTP fails."""

import asyncio
import datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.models.security import TlsCertificate
from app.models.system import SystemSetting
from app.services.smtp_service import SmtpSendError
from app.services.tls_expiry_service import KEY_LAST_NOTICE, notify_expiring_certificates


async def _session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


def test_expiry_notice_does_not_stamp_when_smtp_fails(monkeypatch):
    async def _run():
        engine, factory = await _session()
        now = datetime.datetime.utcnow()
        async with factory() as db:
            db.add(
                TlsCertificate(
                    label="edge",
                    cert_pem="CERT",
                    key_pem_encrypted="KEY",
                    sha256_fingerprint="abc123",
                    not_after=now + datetime.timedelta(days=7),
                    is_active=True,
                )
            )
            await db.commit()

        async def _recipients(_db):
            return ["ops@example.com"]

        async def _fail(*_args, **_kwargs):
            raise SmtpSendError("smtp down")

        monkeypatch.setattr(
            "app.services.tls_expiry_service._notice_recipients",
            _recipients,
        )
        monkeypatch.setattr("app.services.tls_expiry_service.send_email", _fail)

        async with factory() as db:
            result = await notify_expiring_certificates(db, now=now)
            assert result["sent"] == 0
            stamp = await db.get(SystemSetting, KEY_LAST_NOTICE)
            assert stamp is None
        await engine.dispose()

    asyncio.run(_run())


def test_expiry_notice_stamps_after_successful_send(monkeypatch):
    async def _run():
        engine, factory = await _session()
        now = datetime.datetime.utcnow()
        async with factory() as db:
            db.add(
                TlsCertificate(
                    label="edge",
                    cert_pem="CERT",
                    key_pem_encrypted="KEY",
                    sha256_fingerprint="abc123",
                    not_after=now + datetime.timedelta(days=7),
                    is_active=True,
                )
            )
            await db.commit()

        async def _recipients(_db):
            return ["ops@example.com"]

        async def _ok(*_args, **_kwargs):
            return None

        monkeypatch.setattr(
            "app.services.tls_expiry_service._notice_recipients",
            _recipients,
        )
        monkeypatch.setattr("app.services.tls_expiry_service.send_email", _ok)

        async with factory() as db:
            result = await notify_expiring_certificates(db, now=now)
            assert result["sent"] == 1
            stamp = await db.get(SystemSetting, KEY_LAST_NOTICE)
            assert stamp is not None
            assert stamp.value.startswith("abc123:")
        await engine.dispose()

    asyncio.run(_run())
