"""Windows LDAP bridge — exposes signed Active Directory access to Alpha Router in Docker/Linux."""

from __future__ import annotations

import sys

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.ldap_auth import (
    authenticate_ldap_sync,
    fetch_ldap_groups,
    fetch_ldap_users,
    probe_directory,
    test_ldap_connection,
)
from app.services.ldap_config import expand_ldap_config
from app.services.ldap_winldap import winldap_available

if sys.platform != "win32":
    raise RuntimeError("LDAP bridge must run on Windows (signed LDAP via pythonnet).")

if not winldap_available():
    raise RuntimeError("LDAP bridge requires pythonnet: pip install pythonnet")

app = FastAPI(title="Alpha Router LDAP Bridge", version="1.0.0")


class ConfigBody(BaseModel):
    config: dict = Field(default_factory=dict)


class ProbeBody(BaseModel):
    host: str
    port: int = 389
    bind_username: str
    bind_password: str


class AuthenticateBody(BaseModel):
    username: str
    password: str
    config: dict = Field(default_factory=dict)


def _authorize(authorization: str | None) -> None:
    token = (get_settings().ldap_bridge_token or "").strip()
    if not token:
        return
    expected = f"Bearer {token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "platform": sys.platform}


@app.post("/v1/probe")
def bridge_probe(body: ProbeBody, authorization: str | None = Header(default=None)) -> dict:
    _authorize(authorization)
    try:
        return probe_directory(body.host, body.port, body.bind_username, body.bind_password)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/test")
def bridge_test(body: ConfigBody, authorization: str | None = Header(default=None)) -> dict:
    _authorize(authorization)
    cfg = expand_ldap_config({**body.config, "enabled": True})
    try:
        return test_ldap_connection(cfg)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/users")
def bridge_users(body: ConfigBody, authorization: str | None = Header(default=None)) -> list:
    _authorize(authorization)
    cfg = expand_ldap_config(body.config)
    try:
        return fetch_ldap_users(cfg)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/groups")
def bridge_groups(body: ConfigBody, authorization: str | None = Header(default=None)) -> list:
    _authorize(authorization)
    cfg = expand_ldap_config(body.config)
    try:
        return fetch_ldap_groups(cfg)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/authenticate")
def bridge_authenticate(body: AuthenticateBody, authorization: str | None = Header(default=None)) -> dict | None:
    _authorize(authorization)
    cfg = expand_ldap_config(body.config)
    try:
        return authenticate_ldap_sync(body.username, body.password, cfg)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
