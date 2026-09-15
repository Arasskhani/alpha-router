"""Invitation email is best-effort: SMTP success, SMTP absence, and no secrets in the body."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.user import User
from app.services.project_service import create_invitation, create_project
from app.services.smtp_service import SmtpNotConfiguredError

SENT: list[dict] = []


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _user(db, username, *, email=None):
    user = User(
        username=username,
        email=email or f"{username}@test",
        hashed_password="super-secret-password-hash",
        auth_provider="local",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def test_invite_sends_when_smtp_configured(monkeypatch):
    async def fake_send(db, *, to_address, subject, body_text, cc=None):
        SENT.append(
            {
                "to_address": to_address,
                "subject": subject,
                "body_text": body_text,
            }
        )

    monkeypatch.setattr("app.services.smtp_service.send_email", fake_send)
    SENT.clear()
    factory, engine = await _factory()
    try:
        async with factory() as db:
            owner = await _user(db, "owner")
            invitee = await _user(db, "invitee", email="invitee@example.com")
            proj = await create_project(db, user=owner, name="Mail Me")
            result = await create_invitation(
                db,
                project_id=proj["id"],
                user=owner,
                role="viewer",
                notify_user_id=invitee.id,
            )
            assert result["token"]
            assert result["emailSent"] is True
            assert result["emailWarning"] is None
            assert len(SENT) == 1
            assert SENT[0]["to_address"] == "invitee@example.com"
            assert result["token"] in SENT[0]["body_text"]
    finally:
        await engine.dispose()


async def test_invite_succeeds_without_smtp(monkeypatch):
    async def fake_send(db, *, to_address, subject, body_text, cc=None):
        raise SmtpNotConfiguredError("SMTP is not configured")

    monkeypatch.setattr("app.services.smtp_service.send_email", fake_send)
    factory, engine = await _factory()
    try:
        async with factory() as db:
            owner = await _user(db, "owner")
            invitee = await _user(db, "invitee")
            proj = await create_project(db, user=owner, name="No Mail")
            result = await create_invitation(
                db,
                project_id=proj["id"],
                user=owner,
                role="contributor",
                notify_user_id=invitee.id,
            )
            assert result["token"]
            assert result["emailSent"] is False
            assert "Copy the invitation link" in (result["emailWarning"] or "")
    finally:
        await engine.dispose()


async def test_invite_email_never_includes_raw_password(monkeypatch):
    captured: list[str] = []

    async def fake_send(db, *, to_address, subject, body_text, cc=None):
        captured.append(body_text)

    monkeypatch.setattr("app.services.smtp_service.send_email", fake_send)
    factory, engine = await _factory()
    try:
        async with factory() as db:
            owner = await _user(db, "owner")
            invitee = await _user(db, "invitee")
            proj = await create_project(db, user=owner, name="Secret")
            await create_invitation(
                db,
                project_id=proj["id"],
                user=owner,
                role="viewer",
                notify_user_id=invitee.id,
            )
            assert captured
            blob = captured[0].lower()
            assert "super-secret-password-hash" not in blob
            assert "password" not in blob
    finally:
        await engine.dispose()
