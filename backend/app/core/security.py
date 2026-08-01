"""Password hashing, API key generation, and JWT helpers."""

import hashlib
import secrets
from datetime import datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
settings = get_settings()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(
    subject: str,
    role: str,
    extra: dict | None = None,
    *,
    token_version: int = 0,
) -> str:
    payload = {"sub": subject, "role": role, "ver": int(token_version or 0)}
    if extra:
        payload.update(extra)
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    payload["exp"] = expire
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, prefix, hash)."""
    return generate_api_key_for_user("admin")


def generate_api_key_for_user(email_local: str) -> tuple[str, str, str]:
    """API key starts with alpha_{email_local}_ for user-specific keys."""
    safe = "".join(c for c in email_local if c.isalnum() or c in "._-")[:32] or "user"
    raw = f"alpha_{safe}_{secrets.token_urlsafe(28)}"
    prefix = raw[:16]
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    return raw, prefix, key_hash


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
