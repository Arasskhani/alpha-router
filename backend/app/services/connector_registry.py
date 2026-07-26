"""Allowlist registry of third-party connectors.

Adding a new connector = one entry in :data:`CONNECTORS`. No other code path
needs to change. The registry pins the remote MCP endpoint (SSRF control),
the OAuth endpoints, the scopes the user must grant (least-privilege), and
the auth strategy.

Auth types:
- ``oauth``: interactive OAuth Authorization Code; user supplies Client ID/Secret.
- ``api_key``: user pastes an API key (no OAuth dance).
- ``none``: public MCP server, no credentials (e.g. Context7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class ConnectorSpec:
    provider_id: str
    label: str
    auth_type: str  # "oauth" | "api_key" | "none"
    mcp_url: str
    scopes: tuple[str, ...] = field(default_factory=tuple)
    auth_endpoint: str | None = None
    token_endpoint: str | None = None
    revoke_endpoint: str | None = None
    logo: str | None = None
    docs_url: str | None = None
    # Provider-specific extra params appended to the OAuth authorize URL
    # (e.g. Google's access_type=offline&prompt=consent).
    extra_auth_params: dict[str, str] = field(default_factory=dict)
    # UI metadata: functional category tags shown in the list view.
    category: tuple[str, ...] = field(default_factory=tuple)
    # Optional small subtitle shown beneath the label in the list view.
    subtitle: str | None = None


_GOOGLE_OAUTH_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_OAUTH_TOKEN = "https://oauth2.googleapis.com/token"
_GOOGLE_OAUTH_REVOKE = "https://oauth2.googleapis.com/revoke"

_CONNECTORS: dict[str, ConnectorSpec] = {
    "gmail": ConnectorSpec(
        provider_id="gmail",
        label="Gmail",
        auth_type="oauth",
        mcp_url="https://gmailmcp.googleapis.com/mcp/v1",
        scopes=(
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.compose",
        ),
        auth_endpoint=_GOOGLE_OAUTH_AUTH,
        token_endpoint=_GOOGLE_OAUTH_TOKEN,
        revoke_endpoint=_GOOGLE_OAUTH_REVOKE,
        docs_url="https://developers.google.com/workspace/gmail/api/reference/mcp",
        extra_auth_params={"access_type": "offline", "prompt": "consent"},
        category=("Communication",),
    ),
    "google_drive": ConnectorSpec(
        provider_id="google_drive",
        label="Google Drive",
        auth_type="oauth",
        mcp_url="https://drivemcp.googleapis.com/mcp/v1",
        scopes=(
            "https://www.googleapis.com/auth/drive.readonly",
        ),
        auth_endpoint=_GOOGLE_OAUTH_AUTH,
        token_endpoint=_GOOGLE_OAUTH_TOKEN,
        revoke_endpoint=_GOOGLE_OAUTH_REVOKE,
        docs_url="https://developers.google.com/workspace/drive/api/reference/mcp",
        extra_auth_params={"access_type": "offline", "prompt": "consent"},
        category=("Productivity", "Data"),
    ),
    "google_calendar": ConnectorSpec(
        provider_id="google_calendar",
        label="Google Calendar",
        auth_type="oauth",
        mcp_url="https://calendarmcp.googleapis.com/mcp/v1",
        scopes=(
            "https://www.googleapis.com/auth/calendar.readonly",
        ),
        auth_endpoint=_GOOGLE_OAUTH_AUTH,
        token_endpoint=_GOOGLE_OAUTH_TOKEN,
        revoke_endpoint=_GOOGLE_OAUTH_REVOKE,
        docs_url="https://developers.google.com/workspace/calendar/api/reference/mcp",
        extra_auth_params={"access_type": "offline", "prompt": "consent"},
        category=("Productivity",),
    ),
    # —— Phase 3: non-Google providers ——
    "github": ConnectorSpec(
        provider_id="github",
        label="GitHub Integration",
        auth_type="oauth",
        mcp_url="https://api.githubcopilot.com/mcp/",
        scopes=("repo", "read:org"),
        auth_endpoint="https://github.com/login/oauth/authorize",
        token_endpoint="https://github.com/login/oauth/access_token",
        docs_url="https://github.com/github/github-mcp-server",
        category=("Development tools",),
    ),
    "notion": ConnectorSpec(
        provider_id="notion",
        label="Notion",
        auth_type="oauth",
        mcp_url="https://mcp.notion.com/mcp",
        scopes=(),
        auth_endpoint="https://api.notion.com/v1/oauth/authorize",
        token_endpoint="https://api.notion.com/v1/oauth/token",
        docs_url="https://github.com/makenotion/notion-mcp-server",
        category=("Productivity",),
    ),
    "figma": ConnectorSpec(
        provider_id="figma",
        label="Figma",
        auth_type="oauth",
        mcp_url="https://mcp.figma.com/mcp",
        scopes=("file_read",),
        auth_endpoint="https://www.figma.com/oauth",
        token_endpoint="https://api.figma.com/v1/oauth/token",
        docs_url="https://developers.figma.com/docs/figma-mcp-server/",
        subtitle="Interactive",
        category=("Design",),
    ),
    "huggingface": ConnectorSpec(
        provider_id="huggingface",
        label="Hugging Face",
        auth_type="api_key",
        mcp_url="https://huggingface.co/mcp",
        docs_url="https://huggingface.co/docs/huggingface_hub",
        category=("Code",),
    ),
    "context7": ConnectorSpec(
        provider_id="context7",
        label="Context7",
        auth_type="none",
        mcp_url="https://mcp.context7.com/mcp",
        docs_url="https://context7.com",
        category=("Code",),
    ),
    # —— Phase 4: social providers (API-key based; highest policy risk) ——
    "instagram": ConnectorSpec(
        provider_id="instagram",
        label="Instagram",
        auth_type="api_key",
        mcp_url="https://mcp.instagram.com/mcp",
        docs_url="https://developers.facebook.com/docs/instagram-api",
        category=("Social",),
    ),
    "linkedin": ConnectorSpec(
        provider_id="linkedin",
        label="LinkedIn",
        auth_type="api_key",
        mcp_url="https://mcp.linkedin.com/mcp",
        docs_url="https://learn.microsoft.com/linkedin/",
        category=("Social",),
    ),
    "twitter": ConnectorSpec(
        provider_id="twitter",
        label="Twitter / X",
        auth_type="api_key",
        mcp_url="https://mcp.twitter.com/mcp",
        docs_url="https://developer.x.com/",
        category=("Social",),
    ),
}


def get_connector(provider_id: str) -> ConnectorSpec | None:
    return _CONNECTORS.get(provider_id)


def list_connectors() -> Iterable[ConnectorSpec]:
    return _CONNECTORS.values()


def is_known_provider(provider_id: str) -> bool:
    return provider_id in _CONNECTORS


def is_allowed_mcp_url(url: str) -> bool:
    """SSRF guard: True only if ``url`` matches a registered connector endpoint."""
    return any(spec.mcp_url == url for spec in _CONNECTORS.values())
