"""Authentication policy shared by the Windows LDAP bridge and its tests."""

import hmac

from fastapi import HTTPException


def authorize_bridge_request(authorization: str | None, token: str | None) -> None:
    """Require a configured bearer token and compare it in constant time."""
    expected_token = (token or "").strip()
    if not expected_token:
        raise HTTPException(status_code=503, detail="LDAP bridge token is not configured")

    scheme, separator, supplied_token = (authorization or "").partition(" ")
    if separator != " " or scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not hmac.compare_digest(supplied_token.strip(), expected_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
