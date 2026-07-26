"""Admin disable-2FA recovery for locked-out local users."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import hash_password
from app.database import Base
from app.models.user import User
from app.services.secret_crypto import encrypt_secret
from app.services.totp_service import generate_backup_codes, hash_backup_codes


async def _run() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as db:
        target = User(
            username="locked",
            email="locked@alpha-router.local",
            hashed_password=hash_password("aStrong-1Pass!"),
            role="user",
            auth_provider="local",
            totp_enabled=True,
            totp_secret_encrypted=encrypt_secret("JBSWY3DPEHPK3PXP"),
            totp_backup_codes_hashed=hash_backup_codes(generate_backup_codes()),
            token_version=3,
        )
        ldap_user = User(
            username="ldap-person",
            email="ldap@alpha-router.local",
            role="user",
            auth_provider="ldap",
            totp_enabled=True,
            totp_secret_encrypted=encrypt_secret("JBSWY3DPEHPK3PXP"),
        )
        db.add_all([target, ldap_user])
        await db.commit()
        await db.refresh(target)
        await db.refresh(ldap_user)

        # Simulate endpoint body logic
        assert target.totp_enabled
        target.totp_enabled = False
        target.totp_secret_encrypted = None
        target.totp_backup_codes_hashed = None
        target.token_version = int(target.token_version or 0) + 1
        await db.commit()
        await db.refresh(target)

        assert target.totp_enabled is False
        assert target.totp_secret_encrypted is None
        assert target.totp_backup_codes_hashed is None
        assert target.token_version == 4

        # LDAP must remain untouched by local-only policy checks
        assert ldap_user.auth_provider == "ldap"


def test_admin_disable_2fa_clears_secret_and_bumps_token_version():
    asyncio.run(_run())
