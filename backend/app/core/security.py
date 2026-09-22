"""Password hashing, API key generation, and JWT helpers."""

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from app.branding import API_KEY_PREFIX
from app.config import get_settings

settings = get_settings()

#: bcrypt work factor. The same 12 passlib used, so new hashes cost what the
#: stored ones cost and look the same ($2b$12$...).
BCRYPT_ROUNDS = 12

#: bcrypt reads at most 72 bytes of the password. passlib truncated silently;
#: so does this, so a passphrase set before the swap keeps working after it.
_BCRYPT_MAX_BYTES = 72

#: What a bcrypt hash looks like. Checked before the library sees the value:
#: bcrypt 4.0 *panicked* (a BaseException, not an Exception) on a malformed
#: hash with a valid prefix, and a corrupted column must never take a worker
#: down.
_BCRYPT_HASH = re.compile(r"^\$2[abxy]\$\d{2}\$[./A-Za-z0-9]{53}$")


def _password_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt(BCRYPT_ROUNDS)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    """False for a wrong password *and* for a stored value that is not a bcrypt
    hash. passlib raised UnknownHashError on the latter, which turned a
    corrupted or blanked column into a 500 on the login form."""

    if not hashed or not _BCRYPT_HASH.match(hashed):
        return False
    try:
        return bcrypt.checkpw(_password_bytes(plain), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def create_access_token(
    subject: str,
    role: str,
    extra: dict | None = None,
    *,
    token_version: int = 0,
) -> str:
    # jti: the session's own identity, so a sign-in row and the sign-out that
    # ends it can be tied together. Tokens minted before this claim existed
    # stay valid — decode_access_token requires nothing of the payload.
    payload = {"sub": subject, "role": role, "ver": int(token_version or 0), "jti": str(uuid.uuid4())}
    if extra:
        payload.update(extra)
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    payload["exp"] = expire
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def session_id_from_request(request) -> str | None:
    """The ``jti`` of the session cookie on this request, if it carries one."""

    try:
        token = request.cookies.get(settings.session_cookie_name)
    except Exception:  # noqa: BLE001 -- a request without cookies has no session
        return None
    if not token:
        return None
    payload = decode_access_token(token)
    jti = payload.get("jti") if payload else None
    return str(jti) if jti else None


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, prefix, hash)."""
    return generate_api_key_for_user("admin")


def generate_api_key_for_user(email_local: str) -> tuple[str, str, str]:
    """Return an Alpharouter API key scoped to the supplied identity label."""
    safe = "".join(c for c in email_local if c.isalnum() or c in "._-")[:32] or "user"
    raw = f"{API_KEY_PREFIX}{safe}_{secrets.token_urlsafe(28)}"
    prefix = raw[:16]
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    return raw, prefix, key_hash


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
