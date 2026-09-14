"""Dedicated SMTP server configuration (admin only)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_smtp, require_smtp_write
from app.database import get_db
from app.models.system import SmtpSettings
from app.models.user import User
from app.services.secret_crypto import encrypt_secret

router = APIRouter(prefix="/api/admin/smtp", tags=["smtp"])


class SmtpIn(BaseModel):
    host: str
    port: int = 587
    username: str | None = None
    password: str | None = None
    from_address: str
    use_tls: bool = True
    use_ssl: bool = False


@router.get("")
async def get_smtp(db: AsyncSession = Depends(get_db), _: User = Depends(require_smtp)):
    row = (await db.execute(select(SmtpSettings).limit(1))).scalars().first()
    if not row:
        return None
    return {
        "host": row.host,
        "port": row.port,
        "username": row.username,
        "password": "********" if row.password_encrypted else None,
        "from_address": row.from_address,
        "use_tls": row.use_tls,
        "use_ssl": getattr(row, "use_ssl", False),
    }


@router.put("")
async def save_smtp(body: SmtpIn, db: AsyncSession = Depends(get_db), _: User = Depends(require_smtp_write)):
    row = (await db.execute(select(SmtpSettings).limit(1))).scalars().first()
    if not row:
        row = SmtpSettings(host=body.host, port=body.port, from_address=body.from_address)
        db.add(row)
    row.host = body.host
    row.port = body.port
    row.username = body.username
    if body.password and body.password != "********":
        row.password_encrypted = encrypt_secret(body.password)
    row.from_address = body.from_address
    row.use_tls = body.use_tls
    await db.commit()
    return {"ok": True}


@router.post("/test")
async def test_smtp(body: SmtpIn, _: User = Depends(require_smtp_write)):
    """Validate SMTP settings (connection only)."""
    import aiosmtplib

    try:
        client = aiosmtplib.SMTP(hostname=body.host, port=body.port, use_tls=body.use_tls)
        await client.connect()
        if body.username and body.password and body.password != "********":
            await client.login(body.username, body.password)
        await client.quit()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
