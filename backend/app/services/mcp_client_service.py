"""Per-user MCP client: lists and calls tools on remote MCP servers.

Talks to remote MCP endpoints (HTTP transport, JSON-RPC) using the user's
decrypted OAuth access token as a Bearer credential. Refreshes expired
tokens transparently before each call and re-encrypts the new tokens into
the database.

Security:
- Only operates on rows owned by ``user_id`` (IDOR guard).
- Only contacts ``mcp_url`` from the registry allowlist (SSRF guard).
- Never logs tokens.
- On 401 from the remote server, refreshes once and retries.
"""

from __future__ import annotations

import datetime
import json
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_connector import UserConnector
from app.services.connector_registry import get_connector, is_allowed_mcp_url
from app.services.secret_crypto import decrypt_secret, encrypt_secret

logger = logging.getLogger("alpha_router.mcp")

_JSONRPC_HEADERS = {
    "content-type": "application/json",
    "accept": "application/json, text/event-stream",
}


class McpError(Exception):
    """Raised when a remote MCP server returns an error."""


async def _get_connector_row(db: AsyncSession, user_id: int, provider_id: str) -> UserConnector | None:
    return (
        await db.execute(
            select(UserConnector).where(
                UserConnector.user_id == user_id,
                UserConnector.provider_id == provider_id,
            )
        )
    ).scalars().first()


async def _refresh_if_needed(db: AsyncSession, row: UserConnector, provider_id: str, *, force: bool = False) -> str:
    """Return a live access token, refreshing first if expired/empty or ``force``."""
    spec = get_connector(provider_id)
    if spec is None or spec.auth_type != "oauth":
        raise McpError(f"Provider {provider_id} does not support OAuth tool calls")

    access = decrypt_secret(row.access_token_encrypted) or ""
    refresh = decrypt_secret(row.refresh_token_encrypted) or ""
    client_id = decrypt_secret(row.client_id_encrypted) or ""
    client_secret = decrypt_secret(row.client_secret_encrypted) or ""

    # Still valid and not forced?
    if not force and access and row.expires_at and row.expires_at > datetime.datetime.utcnow() + datetime.timedelta(seconds=30):
        return access

    if not refresh or not client_id or not client_secret or not spec.token_endpoint:
        raise McpError(f"Cannot refresh token for {provider_id}: missing credentials")

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            spec.token_endpoint,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
            headers={"Accept": "application/json"},
        )
    if resp.status_code != 200:
        logger.warning("mcp token refresh failed provider=%s status=%s", provider_id, resp.status_code)
        raise McpError(f"Token refresh failed for {provider_id}")
    data = resp.json()
    new_access = data.get("access_token") or ""
    if not new_access:
        raise McpError(f"Refresh response missing access_token for {provider_id}")
    row.access_token_encrypted = encrypt_secret(new_access)
    new_refresh = data.get("refresh_token")
    if new_refresh:
        row.refresh_token_encrypted = encrypt_secret(new_refresh)
    expires_in = data.get("expires_in")
    if isinstance(expires_in, (int, float)) and expires_in > 0:
        row.expires_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=int(expires_in))
    await db.commit()
    return new_access


async def _rpc(url: str, token: str, method: str, params: dict | None = None, *, req_id: int = 1) -> dict:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            url,
            content=json.dumps(payload),
            headers={**_JSONRPC_HEADERS, "Authorization": f"Bearer {token}"},
        )
    if resp.status_code == 401:
        raise McpError("unauthorized")
    if resp.status_code != 200:
        raise McpError(f"MCP {method} returned HTTP {resp.status_code}")
    # Remote MCP may return JSON or SSE-framed JSON. Parse the JSON object.
    body = resp.text
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        # SSE: lines like "data: {...}". Extract the last data line.
        for line in reversed(body.splitlines()):
            line = line.strip()
            if line.startswith("data:"):
                try:
                    return json.loads(line[len("data:"):].strip())
                except json.JSONDecodeError:
                    continue
        raise McpError(f"MCP {method} returned non-JSON body")


async def list_tools_for_user(db: AsyncSession, user_id: int) -> list[dict]:
    """Aggregate OpenAI-style tool schemas from every connected connector."""
    rows = (
        await db.execute(select(UserConnector).where(UserConnector.user_id == user_id))
    ).scalars().all()
    tools: list[dict] = []
    for row in rows:
        if row.revoked_at is not None:
            continue
        spec = get_connector(row.provider_id)
        if spec is None or not is_allowed_mcp_url(spec.mcp_url):
            continue
        try:
            token = await _refresh_if_needed(db, row, row.provider_id)
            result = await _rpc(spec.mcp_url, token, "tools/list", req_id=row.id)
            for tool in result.get("result", {}).get("tools", []) or []:
                tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": f"{row.provider_id}.{tool.get('name', '')}",
                            "description": tool.get("description", ""),
                            "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
                        },
                        "_alpha_router_provider": row.provider_id,
                        "_alpha_router_tool": tool.get("name", ""),
                    }
                )
        except McpError as exc:
            logger.warning("list_tools failed user=%s provider=%s: %s", user_id, row.provider_id, exc)
            continue
    return tools


async def call_tool(
    db: AsyncSession,
    user_id: int,
    provider_id: str,
    tool_name: str,
    arguments: dict | None = None,
) -> dict:
    """Invoke a single MCP tool on behalf of the user. Refreshes on 401."""
    spec = get_connector(provider_id)
    if spec is None or not is_allowed_mcp_url(spec.mcp_url):
        raise McpError(f"Unknown or disallowed provider: {provider_id}")
    row = await _get_connector_row(db, user_id, provider_id)
    if row is None or row.revoked_at is not None:
        raise McpError(f"Not connected to {provider_id}")
    token = await _refresh_if_needed(db, row, provider_id)
    try:
        result = await _rpc(
            spec.mcp_url,
            token,
            "tools/call",
            {"name": tool_name, "arguments": arguments or {}},
            req_id=row.id,
        )
    except McpError as exc:
        if str(exc) != "unauthorized":
            raise
        # 401 → force refresh and retry.
        token = await _refresh_if_needed(db, row, provider_id, force=True)
        result = await _rpc(
            spec.mcp_url,
            token,
            "tools/call",
            {"name": tool_name, "arguments": arguments or {}},
            req_id=row.id,
        )
    return result.get("result", {})
