"""Simple Active Directory settings → full LDAP config (TLS, base DN, filters)."""

from __future__ import annotations

import re
import ssl
from typing import Any
from urllib.parse import urlparse

LDAPS_PORT = 636
_DEFAULT_PORT = LDAPS_PORT


def clean_bind_password(password: str | None) -> str:
    """Strip invisible bidi/format chars that break ldap3 SASLprep on NTLM bind."""
    if not password:
        return ""
    cleaned = password
    for ch in ("\u200e", "\u200f", "\u202a", "\u202b", "\u202c", "\u202d", "\u202e", "\ufeff"):
        cleaned = cleaned.replace(ch, "")
    return cleaned.strip()

_AD_USER_FILTER = (
    "(&"
    "(objectCategory=person)"
    "(objectClass=user)"
    "(|(sAMAccountName={username})(userPrincipalName={login})(userPrincipalName={upn}))"
    ")"
)
_AD_USER_LIST_FILTER = "(&(objectCategory=person)(objectClass=user))"
_AD_GROUP_FILTER = "(objectClass=group)"


def _escape_filter(value: str) -> str:
    return (
        (value or "")
        .replace("\\", "\\5c")
        .replace("*", "\\2a")
        .replace("(", "\\28")
        .replace(")", "\\29")
        .replace("\x00", "\\00")
    )


def discover_root_dse(host: str, port: int = _DEFAULT_PORT) -> dict[str, str]:
    """Anonymous rootDSE read (no credentials) to learn base DN and DNS domain name."""
    import ssl as _ssl

    import ldap3
    from ldap3 import ALL, ANONYMOUS, AUTO_BIND_NO_TLS, Connection, Server, Tls

    host = (host or "").strip()
    if not host:
        return {}
    port = int(port or _DEFAULT_PORT)
    use_ssl = port == LDAPS_PORT
    try:
        tls = Tls(validate=_ssl.CERT_NONE, version=_ssl.PROTOCOL_TLS_CLIENT) if use_ssl else None
        srv = Server(host, port=port, use_ssl=use_ssl, tls=tls, get_info=ALL, connect_timeout=10)
        conn = Connection(
            srv,
            authentication=ANONYMOUS,
            auto_bind=AUTO_BIND_NO_TLS,
            receive_timeout=10,
        )
        conn.search(
            "",
            "(objectClass=*)",
            search_scope=ldap3.BASE,
            attributes=["defaultNamingContext"],
        )
        base_dn = ""
        if conn.entries:
            raw = conn.entries[0]
            if hasattr(raw, "defaultNamingContext"):
                base_dn = str(raw.defaultNamingContext).strip()
        conn.unbind()
        domain = infer_domain("", base_dn) if base_dn else ""
        return {"base_dn": base_dn, "domain": domain}
    except Exception:
        return {}


def domain_to_base_dn(domain: str) -> str:
    domain = (domain or "").strip().rstrip(".")
    if not domain:
        return ""
    if "." not in domain and "\\" not in domain:
        return f"DC={domain}"
    parts = re.split(r"[./\\]+", domain)
    return ",".join(f"DC={p}" for p in parts if p)


def infer_netbios_domain(domain: str = "", base_dn: str | None = None) -> str:
    """First DNS label / first DC component (e.g. corp.example.com → corp)."""
    d = (domain or "").strip()
    if d and "." in d:
        return d.split(".", 1)[0]
    if d:
        return d
    if base_dn:
        parts = re.findall(r"DC=([^,]+)", base_dn, flags=re.I)
        if parts:
            return parts[0]
    return ""


def infer_domain(bind_username: str, discovered_base: str | None = None) -> str:
    u = (bind_username or "").strip()
    if "@" in u:
        return u.split("@", 1)[1]
    if discovered_base:
        parts = re.findall(r"DC=([^,]+)", discovered_base, flags=re.I)
        if parts:
            return ".".join(parts)
    if "\\" in u:
        netbios = u.split("\\", 1)[0].strip()
        if "." in netbios:
            return netbios
    return ""


def extract_sam_from_bind_dn(bind_dn: str) -> str:
    """Extract sAMAccountName-ish short name from a CN=... distinguished name."""
    bd = (bind_dn or "").strip()
    if not bd.upper().startswith("CN="):
        return ""
    return bd.split(",", 1)[0][3:].strip()


def format_bind_identity(username: str, domain: str) -> str:
    u = (username or "").strip()
    if not u:
        return u
    if "@" in u or u.upper().startswith("CN=") or "\\" in u:
        return u
    if domain and "." in domain:
        return f"{u}@{domain}"
    if domain:
        return f"{domain}\\{u}"
    return u


def format_login_identity(username: str, domain: str) -> tuple[str, str, str]:
    """Returns (bind_string, sAMAccountName-ish, userPrincipalName for filter)."""
    raw = (username or "").strip()
    domain = (domain or "").strip()
    if "@" in raw:
        sam = raw.split("@", 1)[0]
        return raw, sam, raw
    if "\\" in raw:
        return raw, raw.split("\\", 1)[1], f"{raw.split('\\', 1)[1]}@{domain}" if domain else raw
    if domain:
        upn = f"{raw}@{domain}"
        return upn, raw, upn
    return raw, raw, raw


def _parse_legacy_server(server: str) -> tuple[str, int, bool]:
    s = (server or "").strip()
    if not s:
        return "", _DEFAULT_PORT, False
    if "://" in s:
        p = urlparse(s)
        host = p.hostname or ""
        port = p.port or (636 if p.scheme == "ldaps" else 389)
        return host, port, p.scheme == "ldaps"
    if ":" in s and not s.startswith("["):
        host, _, port_s = s.rpartition(":")
        try:
            return host, int(port_s), False
        except ValueError:
            return s, _DEFAULT_PORT, False
    return s, _DEFAULT_PORT, False


def parse_sync_ous(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [line.strip() for line in str(value).splitlines() if line.strip()]


def sync_ous_to_text(ous: list[str] | Any) -> str:
    return "\n".join(parse_sync_ous(ous))


def simple_public_view(cfg: dict) -> dict:
    """Fields shown in admin UI (simple fields only — not internal bind_dn)."""
    ous_text = sync_ous_to_text(cfg.get("sync_ous"))
    stored_user = (cfg.get("bind_username") or "").strip()
    if cfg.get("dc_host"):
        host = cfg.get("dc_host") or ""
    else:
        host, _, _ = _parse_legacy_server(cfg.get("server", ""))
    # Alpha Router supports LDAPS only — always present fixed transport to the admin UI.
    return {
        "enabled": bool(cfg.get("enabled")),
        "dc_host": host,
        "bind_username": stored_user,
        "bind_password": "********" if cfg.get("bind_password") else "",
        "port": LDAPS_PORT,
        "use_ssl": True,
        "trust_untrusted_cert": bool(cfg.get("trust_untrusted_cert")),
        "sync_ous": ous_text,
        "sync_ous_prune": bool(cfg.get("sync_ous_prune")),
        "sync_schedule_enabled": bool(cfg.get("sync_schedule_enabled")),
        "sync_schedule_hour": int(cfg.get("sync_schedule_hour", 3)),
        "sync_schedule_minute": int(cfg.get("sync_schedule_minute", 0)),
    }


def expand_ldap_config(raw: dict) -> dict:
    """Ensure runtime LDAP operations always have derived AD fields."""
    if not raw:
        return {"enabled": False}
    if raw.get("server") and raw.get("base_dn") and raw.get("bind_dn"):
        out = dict(raw)
        bind_username = (out.get("bind_username") or "").strip()
        bind_dn_stored = (out.get("bind_dn") or "").strip()
        domain = (out.get("domain") or "").strip()
        if not domain:
            domain = infer_domain(bind_username or bind_dn_stored, out.get("base_dn"))
        out["domain"] = domain
        if bind_username and not bind_username.upper().startswith("CN="):
            out["bind_dn"] = format_bind_identity(bind_username, domain)
        else:
            out["bind_dn"] = bind_dn_stored
        out.setdefault("user_filter", _AD_USER_FILTER)
        out.setdefault("user_list_filter", _AD_USER_LIST_FILTER)
        out.setdefault("group_filter", _AD_GROUP_FILTER)
        out["sync_ous"] = parse_sync_ous(out.get("sync_ous"))
        out["port"] = LDAPS_PORT
        out["use_ssl"] = True
        out["use_starttls"] = False
        out["server"] = f"ldaps://{(out.get('dc_host') or '').strip()}:{LDAPS_PORT}"
        out.setdefault("trust_untrusted_cert", bool(out.get("trust_untrusted_cert")))
        out.setdefault("sync_ous_prune", bool(out.get("sync_ous_prune")))
        return out

    simple = simple_public_view(raw)
    if not simple.get("dc_host"):
        return {**raw, "enabled": bool(raw.get("enabled"))}

    domain = infer_domain(simple["bind_username"], raw.get("base_dn"))
    port = LDAPS_PORT
    host = simple["dc_host"]
    base_dn_existing = (raw.get("base_dn") or "").strip()
    if host and not base_dn_existing:
        discovered = discover_root_dse(host, port)
        if discovered.get("base_dn"):
            raw = {**raw, "base_dn": discovered["base_dn"]}
            domain = discovered.get("domain") or infer_domain(simple["bind_username"], discovered["base_dn"]) or domain
    bind_password = raw.get("bind_password") or ""
    bind_username = simple["bind_username"]

    return {
        "enabled": bool(raw.get("enabled")),
        "dc_host": host,
        "bind_username": bind_username,
        "bind_password": bind_password,
        "port": port,
        "use_ssl": True,
        "use_starttls": False,
        "trust_untrusted_cert": bool(raw.get("trust_untrusted_cert")),
        "sync_ous_prune": bool(raw.get("sync_ous_prune")),
        "server": f"ldaps://{host}:{port}",
        "bind_dn": format_bind_identity(bind_username, domain),
        "base_dn": raw.get("base_dn") or domain_to_base_dn(domain),
        "domain": domain,
        "user_filter": _AD_USER_FILTER,
        "user_list_filter": _AD_USER_LIST_FILTER,
        "group_base_dn": raw.get("group_base_dn") or raw.get("base_dn") or domain_to_base_dn(domain),
        "group_filter": _AD_GROUP_FILTER,
        "sync_ous": parse_sync_ous(raw.get("sync_ous")),
    }


def merge_simple_ldap_config(
    enabled: bool,
    dc_host: str,
    bind_username: str,
    bind_password: str,
    port: int,
    *,
    use_ssl: bool | None = None,
    trust_untrusted_cert: bool | None = None,
    sync_ous_prune: bool | None = None,
    sync_ous: list[str] | None = None,
    existing: dict | None = None,
) -> dict[str, Any]:
    """Persist admin form values without requiring a live LDAP connection."""
    existing = dict(existing or {})
    host = (dc_host or "").strip()
    if not host:
        raise ValueError("Domain Controller name or IP is required")
    user = (bind_username or "").strip()
    if not user:
        raise ValueError("Username is required")

    # LDAPS-only product path — ignore legacy port/use_ssl inputs.
    port = LDAPS_PORT
    use_ssl = True
    use_starttls = False
    if trust_untrusted_cert is None:
        trust_untrusted_cert = bool(existing.get("trust_untrusted_cert"))
    if sync_ous_prune is None:
        sync_ous_prune = bool(existing.get("sync_ous_prune"))

    base_dn = (existing.get("base_dn") or "").strip()
    domain = infer_domain(user, base_dn)
    if host and not base_dn:
        discovered = discover_root_dse(host, port)
        base_dn = discovered.get("base_dn") or base_dn
        domain = discovered.get("domain") or infer_domain(user, base_dn) or domain
    elif base_dn:
        domain = infer_domain(user, base_dn) or domain
    base_dn = base_dn or domain_to_base_dn(domain)
    if user.upper().startswith("CN="):
        bind_dn = user
    else:
        bind_dn = format_bind_identity(user, domain) or existing.get("bind_dn") or user

    ous = sync_ous if sync_ous is not None else parse_sync_ous(existing.get("sync_ous"))
    pwd = clean_bind_password(bind_password or existing.get("bind_password") or "")

    return {
        **existing,
        "enabled": enabled,
        "dc_host": host,
        "bind_username": user,
        "bind_password": pwd,
        "port": port,
        "use_ssl": use_ssl,
        "use_starttls": use_starttls,
        "trust_untrusted_cert": bool(trust_untrusted_cert),
        "sync_ous_prune": bool(sync_ous_prune),
        "server": f"ldaps://{host}:{port}",
        "bind_dn": bind_dn,
        "base_dn": base_dn,
        "domain": domain or existing.get("domain") or "",
        "user_filter": existing.get("user_filter") or _AD_USER_FILTER,
        "user_list_filter": existing.get("user_list_filter") or _AD_USER_LIST_FILTER,
        "group_base_dn": existing.get("group_base_dn") or base_dn,
        "group_filter": existing.get("group_filter") or _AD_GROUP_FILTER,
        "sync_ous": ous,
    }


def build_ldap_config_from_simple(
    enabled: bool,
    dc_host: str,
    bind_username: str,
    bind_password: str,
    port: int,
    *,
    sync_ous: list[str] | None = None,
    existing: dict | None = None,
) -> dict[str, Any]:
    """Probe directory and build storable config from simple admin inputs."""
    from app.services.ldap_auth import probe_directory

    host = (dc_host or "").strip()
    if not host:
        raise ValueError("Domain Controller name or IP is required")
    if not (bind_username or "").strip():
        raise ValueError("Username is required")
    if not bind_password:
        raise ValueError("Password is required")

    port = int(port or _DEFAULT_PORT)
    discovered = probe_directory(host, port, bind_username.strip(), bind_password)
    domain = discovered.get("domain") or infer_domain(bind_username, discovered.get("base_dn"))
    base_dn = discovered.get("base_dn") or domain_to_base_dn(domain)

    ous = sync_ous if sync_ous is not None else parse_sync_ous((existing or {}).get("sync_ous"))

    return {
        "enabled": enabled,
        "dc_host": host,
        "bind_username": bind_username.strip(),
        "bind_password": bind_password,
        "port": discovered.get("port", port),
        "use_ssl": bool(discovered.get("use_ssl")),
        "use_starttls": bool(discovered.get("use_starttls")),
        "server": discovered.get("server", f"ldap://{host}:{port}"),
        "bind_dn": discovered.get("bind_dn") or format_bind_identity(bind_username, domain),
        "base_dn": base_dn,
        "domain": domain,
        "user_filter": _AD_USER_FILTER,
        "user_list_filter": _AD_USER_LIST_FILTER,
        "group_base_dn": base_dn,
        "group_filter": _AD_GROUP_FILTER,
        "sync_ous": ous,
    }


def resolve_password(incoming: str, existing: dict) -> str:
    if incoming and incoming != "********":
        return clean_bind_password(incoming)
    return clean_bind_password(existing.get("bind_password") or "")
