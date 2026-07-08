"""Active Directory / LDAP authentication and directory reads (plain LDAP by default)."""

from __future__ import annotations

import asyncio
import ssl
from typing import Any

from app.config import get_settings
from app.services.ldap_config import (
    _escape_filter,
    expand_ldap_config,
    extract_sam_from_bind_dn,
    format_bind_identity,
    format_login_identity,
    infer_domain,
    infer_netbios_domain,
    parse_sync_ous,
    clean_bind_password,
)

_AD_USER_ATTRS = [
    "cn",
    "sAMAccountName",
    "userPrincipalName",
    "mail",
    "displayName",
    "title",
    "department",
    "physicalDeliveryOfficeName",
    "manager",
]
_GROUP_ATTRS = ["cn", "description", "member"]

LDAP_UNAVAILABLE_MESSAGE = (
    "LDAP directory is not available right now. Please try again later or use a local account."
)


class LdapUnavailableError(RuntimeError):
    """LDAP server cannot be reached (timeout, network, or connection failure)."""


def _ldap_timeouts() -> tuple[int, int]:
    s = get_settings()
    return (
        max(1, int(s.ldap_connect_timeout_seconds)),
        max(1, int(s.ldap_receive_timeout_seconds)),
    )


def _is_tls_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    name = type(exc).__name__.lower()
    if "ssl" in name or "tls" in name:
        return True
    needles = (
        "ssl wrapping",
        "ssl:",
        "tls",
        "certificate",
        "cert ",
        "hostname mismatch",
        "certificate verify failed",
        "self signed",
        "unable to get local issuer",
        "unexpected_eof",
    )
    return any(n in msg for n in needles)


def _is_ldap_unreachable(exc: Exception) -> bool:
    if _is_tls_error(exc):
        return False
    name = type(exc).__name__
    if name in ("LDAPSocketOpenError", "LDAPSocketReceiveError", "TimeoutError"):
        return True
    msg = str(exc).lower()
    needles = (
        "timed out",
        "timeout",
        "connection refused",
        "unreachable",
        "no route to host",
        "name or service not known",
        "getaddrinfo failed",
        "network is unreachable",
        "actively refused",
        "failed to establish",
        "can't connect",
        "cannot connect",
        "server not available",
    )
    return any(n in msg for n in needles)


def _is_invalid_credentials_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    name = type(exc).__name__.lower()
    return (
        "invalidcredentials" in name
        or "invalidcredentials" in msg
        or "invalid credentials" in msg
        or "data 52e" in msg
        or "data 775" in msg
        or "data 533" in msg
    )


def _clean_bind_password(password: str | None) -> str:
    return clean_bind_password(password)


def _attr_raw(entry: Any, name: str) -> Any | None:
    """Read an LDAP attribute case-insensitively (ldap3 + WinLdap entries)."""
    if hasattr(entry, "__getitem__"):
        try:
            val = entry[name]
            if val is not None:
                return val
        except Exception:
            pass
    try:
        if hasattr(entry, name):
            val = getattr(entry, name)
            if val is not None:
                return val
    except Exception:
        pass
    target = name.lower()
    for attr in getattr(entry, "entry_attributes", ()) or ():
        if str(attr).lower() == target:
            try:
                return entry[attr] if hasattr(entry, "__getitem__") else getattr(entry, attr)
            except Exception:
                continue
    for key, val in getattr(entry, "__dict__", {}).items():
        if key.startswith("_"):
            continue
        if key.lower() == target and val is not None:
            return val
    return None


def _attr_str(entry: Any, name: str) -> str | None:
    raw = _attr_raw(entry, name)
    if raw is None:
        return None
    if hasattr(raw, "values"):
        values = [str(v).strip() for v in raw.values if str(v).strip()]
        if not values:
            return None
        raw = values[0] if len(values) == 1 else values[0]
    text = str(raw).strip()
    return text if text and text != "[]" else None


def _attr_values(entry: Any, name: str) -> list[str]:
    if not hasattr(entry, name):
        return []
    raw = getattr(entry, name)
    if raw is None:
        return []
    if hasattr(raw, "values"):
        return [str(v).strip() for v in raw.values if str(v).strip()]
    if isinstance(raw, (list, tuple)):
        return [str(v).strip() for v in raw if str(v).strip()]
    text = str(raw).strip()
    return [text] if text and text != "[]" else []


def _sam_account_name(user: str) -> str:
    u = (user or "").strip()
    if "\\" in u:
        return u.split("\\", 1)[1]
    if "@" in u:
        return u.split("@", 1)[0]
    if u.upper().startswith("CN="):
        return extract_sam_from_bind_dn(u)
    return u


def bind_candidates(cfg: dict, override_user: str | None = None) -> list[str]:
    """Generate bind identity variants for Active Directory service accounts."""
    user = (override_user or cfg.get("bind_username") or "").strip()
    domain = (cfg.get("domain") or "").strip()
    if not domain:
        domain = infer_domain(user, cfg.get("base_dn"))
    bind_dn = (cfg.get("bind_dn") or "").strip()
    candidates: list[str] = []

    def add(value: str) -> None:
        value = (value or "").strip()
        if value and value not in candidates:
            candidates.append(value)

    netbios = infer_netbios_domain(domain, cfg.get("base_dn"))
    sam = _sam_account_name(user)

    add(user)
    add(format_bind_identity(user, domain))
    if sam and sam != user:
        add(sam)
    if netbios and sam and "\\" not in user and "@" not in user:
        add(f"{netbios}\\{sam}")
    if domain and sam and "@" not in user and "." in domain:
        add(f"{sam}@{domain}")
    add(bind_dn)

    sam_from_cn = extract_sam_from_bind_dn(bind_dn)
    if sam_from_cn:
        add(sam_from_cn)
        if netbios:
            add(f"{netbios}\\{sam_from_cn}")
        if domain and "." in domain:
            add(f"{sam_from_cn}@{domain}")

    return candidates


def _ntlm_md4_available() -> bool:
    """NTLM via ldap3 needs MD4; OpenSSL 3 / Python 3.11+ often require pycryptodome."""
    import hashlib

    try:
        hashlib.new("md4", b"")
        return True
    except ValueError:
        pass
    try:
        from Crypto.Hash import MD4

        MD4.new(b"")
        return True
    except ImportError:
        return False


def _ldap_tls(cfg: dict | None = None):
    """Build ldap3 TLS options (trusted CA vs accept untrusted/self-signed LDAPS)."""
    from ldap3 import Tls

    settings = cfg or {}
    trust_untrusted = bool(settings.get("trust_untrusted_cert"))
    if trust_untrusted:
        return Tls(validate=ssl.CERT_NONE, version=ssl.PROTOCOL_TLS_CLIENT)
    return Tls(validate=ssl.CERT_REQUIRED, version=ssl.PROTOCOL_TLS_CLIENT)


def ldap_connection_modes(cfg: dict) -> list[tuple[int, bool, bool]]:
    """Ordered (port, use_ssl, use_starttls) attempts for Active Directory."""
    port = int(cfg.get("port") or 389)
    want_ssl = bool(cfg.get("use_ssl")) or port == 636
    want_starttls = bool(cfg.get("use_starttls")) and not want_ssl
    modes: list[tuple[int, bool, bool]] = []

    def add(p: int, ssl_mode: bool, starttls: bool) -> None:
        starttls = bool(starttls) and not ssl_mode
        item = (p, ssl_mode, starttls)
        if item not in modes:
            modes.append(item)

    if want_ssl:
        add(636, True, False)
        return modes

    if port == 389:
        if want_starttls:
            add(389, False, True)
        else:
            add(389, False, True)
            add(389, False, False)
        add(636, True, False)
    else:
        add(port, False, want_starttls)
        if port != 389:
            add(389, False, True)
    return modes


def _encryption_label(use_ssl: bool, use_starttls: bool) -> str:
    if use_ssl:
        return "LDAPS"
    if use_starttls:
        return "LDAP + STARTTLS"
    return "LDAP"


def _raise_bind_errors(errors: list[Exception]) -> None:
    if not errors:
        raise ValueError("No bind method available")
    if len(errors) == 1:
        raise errors[0]
    simple_err, ntlm_err = errors[0], errors[-1]
    ntlm_msg = str(ntlm_err).lower()
    if "md4" in ntlm_msg or "unsupported hash" in ntlm_msg:
        raise simple_err
    raise RuntimeError(f"{simple_err}; NTLM: {ntlm_err}") from ntlm_err


def _try_bind_ad(
    host: str,
    port: int,
    user: str,
    password: str,
    domain: str = "",
    *,
    use_ssl: bool = False,
    use_starttls: bool = False,
    cfg: dict | None = None,
):
    """Try SIMPLE then NTLM over plain LDAP, STARTTLS, or LDAPS."""
    import ldap3
    from ldap3 import (
        ALL,
        AUTO_BIND_NO_TLS,
        AUTO_BIND_TLS_BEFORE_BIND,
        Connection,
        NTLM,
        Server,
    )

    netbios = infer_netbios_domain(domain)
    connect_timeout, receive_timeout = _ldap_timeouts()
    tls_cfg = {**(cfg or {}), "dc_host": host}
    tls = _ldap_tls(tls_cfg) if use_ssl or use_starttls else None
    use_starttls = bool(use_starttls) and not use_ssl

    def _connect(authentication, bind_user: str):
        server = Server(
            host,
            port=port,
            use_ssl=use_ssl,
            tls=tls,
            get_info=ALL,
            connect_timeout=connect_timeout,
        )
        auto_bind = AUTO_BIND_TLS_BEFORE_BIND if use_starttls else AUTO_BIND_NO_TLS
        conn = Connection(
            server,
            user=bind_user,
            password=password,
            authentication=authentication,
            auto_bind=auto_bind,
            receive_timeout=receive_timeout,
            auto_referrals=False,
        )
        return conn

    def _ntlm_user() -> str | None:
        if "\\" in user:
            return user
        short = extract_sam_from_bind_dn(user) if user.upper().startswith("CN=") else user
        if "@" in short:
            short = short.split("@", 1)[0]
        if netbios and short:
            return f"{netbios}\\{short}"
        return None

    errors: list[Exception] = []
    try:
        return _connect(ldap3.SIMPLE, user), _encryption_label(use_ssl, use_starttls)
    except Exception as exc:
        errors.append(exc)

    ntlm_bind = _ntlm_user()
    if ntlm_bind and _ntlm_md4_available():
        try:
            return _connect(NTLM, ntlm_bind), _encryption_label(use_ssl, use_starttls)
        except Exception as exc:
            errors.append(exc)

    _raise_bind_errors(errors)


def _discover_base_dn(conn) -> str | None:
    import ldap3

    conn.search(
        "",
        "(objectClass=*)",
        search_scope=ldap3.BASE,
        attributes=["defaultNamingContext", "rootDomainNamingContext"],
    )
    if not conn.entries:
        return None
    entry = conn.entries[0]
    for attr in ("defaultNamingContext", "rootDomainNamingContext"):
        val = _attr_str(entry, attr)
        if val:
            return val
    return None


def _runtime_config(config: dict | None) -> dict:
    cfg = expand_ldap_config(config or {})
    if not cfg.get("enabled"):
        return cfg
    return cfg


def _needs_signed_ldap(errors: list[str]) -> bool:
    text = " ".join(errors).lower()
    return "strongerauthrequired" in text or "integrity checking" in text


def _open_connection_ldap3(cfg: dict, *, user: str | None = None, password: str | None = None):
    host = (cfg.get("dc_host") or "").strip()
    if not host and cfg.get("server"):
        from urllib.parse import urlparse

        p = urlparse(cfg["server"])
        host = p.hostname or ""
    bind_pw = _clean_bind_password(password if password is not None else cfg.get("bind_password") or "")
    domain = (cfg.get("domain") or "").strip() or infer_domain(
        cfg.get("bind_username", ""), cfg.get("base_dn")
    )
    candidates = [user] if user else bind_candidates(cfg)
    bind_errors: list[str] = []
    unreachable_modes: list[str] = []
    for port, use_ssl, use_starttls in ldap_connection_modes(cfg):
        enc = _encryption_label(use_ssl, use_starttls)
        mode_unreachable = False
        for candidate in candidates:
            try:
                conn, _ = _try_bind_ad(
                    host,
                    port,
                    candidate,
                    bind_pw,
                    domain,
                    use_ssl=use_ssl,
                    use_starttls=use_starttls,
                    cfg=cfg,
                )
                cfg["_resolved_port"] = port
                cfg["_resolved_use_ssl"] = use_ssl
                cfg["_resolved_use_starttls"] = use_starttls
                cfg["_resolved_encryption"] = enc
                return conn
            except LdapUnavailableError:
                mode_unreachable = True
                break
            except Exception as exc:
                if _is_ldap_unreachable(exc):
                    mode_unreachable = True
                    break
                msg = str(exc).strip() or exc.__class__.__name__
                bind_errors.append(f"{candidate} @ {enc} {host}:{port}: {msg}")
        if mode_unreachable:
            unreachable_modes.append(f"{enc} {host}:{port}")
    if bind_errors:
        raise RuntimeError("LDAP bind failed. " + "; ".join(bind_errors[-6:]))
    if unreachable_modes:
        raise LdapUnavailableError(LDAP_UNAVAILABLE_MESSAGE)
    raise RuntimeError("LDAP connection failed")


def _open_connection_winldap(cfg: dict, *, user: str | None = None, password: str | None = None):
    from app.services.ldap_winldap import WinLdapConnection, winldap_available

    if not winldap_available():
        return None
    bind_pw = _clean_bind_password(password if password is not None else cfg.get("bind_password") or "")
    candidates = [user] if user else bind_candidates(cfg)
    errors: list[str] = []
    for candidate in candidates:
        try:
            return WinLdapConnection(cfg, user=candidate, password=bind_pw)
        except Exception as exc:
            msg = str(exc).strip() or exc.__class__.__name__
            errors.append(f"{candidate}: {msg}")
    if errors:
        raise RuntimeError("Windows signed LDAP bind failed. " + "; ".join(errors[-4:]))
    return None


def _open_connection(cfg: dict, *, user: str | None = None, password: str | None = None):
    bind_pw = _clean_bind_password(password) if password is not None else None
    ldap3_error: RuntimeError | None = None
    winldap_error: RuntimeError | None = None

    try:
        win_conn = _open_connection_winldap(cfg, user=user, password=bind_pw)
        if win_conn is not None:
            cfg["_resolved_encryption"] = cfg.get("_resolved_encryption") or (
                "LDAPS" if bool(cfg.get("use_ssl")) or int(cfg.get("port") or 389) == 636 else "LDAP (signed)"
            )
            return win_conn
    except RuntimeError as exc:
        winldap_error = exc

    try:
        return _open_connection_ldap3(cfg, user=user, password=bind_pw)
    except LdapUnavailableError:
        raise
    except RuntimeError as exc:
        ldap3_error = exc
        err_text = str(exc)
        if _is_ldap_unreachable(exc) or _is_ldap_unreachable(RuntimeError(err_text)):
            raise LdapUnavailableError(LDAP_UNAVAILABLE_MESSAGE) from exc

    if winldap_error and ldap3_error:
        raise RuntimeError(f"{ldap3_error}; {winldap_error}") from ldap3_error
    if winldap_error:
        raise winldap_error
    if ldap3_error:
        msg = str(ldap3_error)
        if _needs_signed_ldap([msg]):
            raise RuntimeError(
                f"{msg} — Active Directory requires a signed or encrypted LDAP bind from non-Windows hosts. "
                "Install a valid LDAPS certificate on the domain controller and use port 636 (or check Use LDAPS), "
                "run scripts/start-ldap-bridge.ps1 on the Windows host and set LDAP_BRIDGE_URL for Docker, "
                "or run the NITRO backend on Windows with pythonnet for signed LDAP on port 389."
            ) from ldap3_error
        lower = msg.lower()
        if _is_tls_error(RuntimeError(msg)) or "starttls failed" in lower:
            if "unexpected_eof" in lower or "eof occurred" in lower:
                hint = (
                    "Port 636 accepts TCP connections but LDAPS/TLS is not configured on the domain controller. "
                    "Install an LDAPS certificate on the DC, or use port 389 with NITRO on Windows for signed LDAP."
                )
            else:
                hint = (
                    "Enable Support Untrusted Certificate if the DC uses a self-signed LDAPS cert, "
                    "or install a CA-trusted certificate on the domain controller."
                )
            raise RuntimeError(
                f"{msg} — LDAPS/STARTTLS could not be negotiated with the domain controller. {hint}"
            ) from ldap3_error
        raise ldap3_error
    raise RuntimeError("LDAP connection failed")


def _ldap_bridge_enabled() -> bool:
    from app.services.ldap_bridge_client import ldap_bridge_enabled

    return ldap_bridge_enabled()


def probe_directory(host: str, port: int, bind_username: str, password: str) -> dict[str, Any]:
    """Probe AD using the same bind candidate logic as sync/test."""
    if _ldap_bridge_enabled():
        from app.services.ldap_bridge_client import bridge_probe_directory

        return bridge_probe_directory(host, port, bind_username, password)
    try_port = int(port or 389)
    domain_guess = infer_domain(bind_username)
    cfg = {
        "enabled": True,
        "dc_host": host,
        "port": try_port,
        "use_ssl": try_port == 636,
        "bind_username": bind_username.strip(),
        "bind_password": password,
        "bind_dn": format_bind_identity(bind_username, domain_guess),
        "base_dn": "",
        "domain": domain_guess,
    }
    conn = _open_connection(cfg)
    try:
        base_dn = _discover_base_dn(conn) or ""
        domain = infer_domain(bind_username, base_dn) or domain_guess
        resolved_port = int(cfg.get("_resolved_port") or try_port)
        use_ssl = bool(cfg.get("_resolved_use_ssl"))
        use_starttls = bool(cfg.get("_resolved_use_starttls"))
        scheme = "ldaps" if use_ssl else "ldap"
        return {
            "port": resolved_port,
            "use_ssl": use_ssl,
            "use_starttls": use_starttls,
            "server": f"{scheme}://{host}:{resolved_port}",
            "bind_dn": cfg["bind_dn"],
            "base_dn": base_dn,
            "domain": domain,
            "encryption": cfg.get("_resolved_encryption"),
        }
    finally:
        conn.unbind()


def _resolve_username(entry: Any) -> str | None:
    """Prefer AD logon name (sAMAccountName); never use cn before UPN/mail."""
    for attr in ("sAMAccountName", "uid"):
        val = _attr_str(entry, attr)
        if val:
            return val
    for attr in ("userPrincipalName", "mail"):
        val = _attr_str(entry, attr)
        if val and "@" in val:
            local = val.split("@", 1)[0].strip()
            if local:
                return local
    val = _attr_str(entry, "cn")
    return val or None


def _entry_to_profile(entry: Any, fallback_username: str) -> dict[str, Any]:
    username = _resolve_username(entry) or fallback_username
    email = _attr_str(entry, "mail") or _attr_str(entry, "userPrincipalName")
    return {
        "username": username,
        "email": email,
        "display_name": _attr_str(entry, "displayName") or _attr_str(entry, "cn") or username,
        "job_title": _attr_str(entry, "title"),
        "department": _attr_str(entry, "department"),
        "office": _attr_str(entry, "physicalDeliveryOfficeName"),
        "reporting_to": _attr_str(entry, "manager"),
        "external_id": entry.entry_dn,
    }


def _bind_login_connection(cfg: dict, login_bind: str, password: str) -> Any | None:
    try:
        return _open_connection(cfg, user=login_bind, password=password)
    except LdapUnavailableError:
        raise
    except Exception:
        return None


def _login_bind_identities(username: str, domain: str, base_dn: str | None = None) -> list[str]:
    """Bind identity variants for user login (DOMAIN\\user, UPN, or short name)."""
    raw = (username or "").strip()
    if not raw:
        return []
    domain = (domain or "").strip() or infer_domain(raw, base_dn)
    netbios = infer_netbios_domain(domain, base_dn)
    sam = _sam_account_name(raw)
    identities: list[str] = []

    def add(value: str) -> None:
        value = (value or "").strip()
        if value and value not in identities:
            identities.append(value)

    add(raw)
    if "\\" not in raw and "@" not in raw:
        if netbios and sam:
            add(f"{netbios}\\{sam}")
        if domain and sam and "." in domain:
            add(f"{sam}@{domain}")
    elif "@" in raw and netbios and sam:
        add(f"{netbios}\\{sam}")
    elif "\\" in raw and domain and sam and "." in domain:
        add(f"{sam}@{domain}")
    return identities


def authenticate_ldap_sync(username: str, password: str, config: dict | None = None) -> dict | None:
    cfg = _runtime_config(config)
    if not cfg.get("enabled") or not password:
        return None
    if _ldap_bridge_enabled():
        from app.services.ldap_bridge_client import bridge_authenticate

        return bridge_authenticate(username, password, cfg)

    domain = cfg.get("domain") or ""
    base = (cfg.get("base_dn") or "").strip()
    if not base:
        return None

    _, sam, upn = format_login_identity(username, domain)
    conn = None
    login_bind = ""
    for candidate in _login_bind_identities(username, domain, base):
        conn = _bind_login_connection(cfg, candidate, password)
        if conn is not None:
            login_bind = candidate
            break
    if conn is None:
        return None

    esc_sam = _escape_filter(sam)
    esc_upn = _escape_filter(upn)
    filt = (
        f"(&(objectCategory=person)(objectClass=user)"
        f"(|(sAMAccountName={esc_sam})(userPrincipalName={esc_upn})))"
    )
    conn.search(base, filt, attributes=_AD_USER_ATTRS, size_limit=1)
    if conn.entries:
        profile = _entry_to_profile(conn.entries[0], sam)
        conn.unbind()
        return profile

    conn.unbind()
    return {
        "username": sam,
        "email": upn if "@" in upn else None,
        "display_name": sam,
        "external_id": login_bind,
    }


async def authenticate_ldap(username: str, password: str, config: dict | None = None) -> dict | None:
    return await asyncio.to_thread(authenticate_ldap_sync, username, password, config)


def _sync_search_bases(cfg: dict) -> list[str]:
    """User sync: optional sync_ous, else domain base_dn."""
    ous = parse_sync_ous(cfg.get("sync_ous"))
    if ous:
        return ous
    base = (cfg.get("base_dn") or "").strip()
    return [base] if base else []


def _group_search_bases(cfg: dict) -> list[str]:
    """Group sync: sync OUs when prune enabled, else domain base."""
    if bool(cfg.get("sync_ous_prune")):
        ous = parse_sync_ous(cfg.get("sync_ous"))
        if ous:
            return ous
    gbase = (cfg.get("group_base_dn") or cfg.get("base_dn") or "").strip()
    return [gbase] if gbase else []


def fetch_ldap_users(config: dict) -> list[dict[str, Any]]:
    if _ldap_bridge_enabled():
        from app.services.ldap_bridge_client import bridge_fetch_users

        return bridge_fetch_users(expand_ldap_config(config))
    cfg = expand_ldap_config(config)
    bases = _sync_search_bases(cfg)
    if not bases:
        raise ValueError("No search base: set sync OUs or configure domain base DN")
    filt = (cfg.get("user_list_filter") or "").strip()
    conn = _open_connection(cfg)
    seen_dn: set[str] = set()
    users: list[dict[str, Any]] = []
    for base in bases:
        conn.search(base, filt, attributes=_AD_USER_ATTRS)
        for entry in conn.entries:
            dn = entry.entry_dn
            if dn in seen_dn:
                continue
            seen_dn.add(dn)
            username = _resolve_username(entry)
            if not username:
                continue
            users.append(_entry_to_profile(entry, username))
    conn.unbind()
    return users


def fetch_ldap_groups(config: dict) -> list[dict[str, Any]]:
    if _ldap_bridge_enabled():
        from app.services.ldap_bridge_client import bridge_fetch_groups

        return bridge_fetch_groups(expand_ldap_config(config))
    cfg = expand_ldap_config(config)
    bases = _group_search_bases(cfg)
    if not bases:
        raise ValueError("No search base: set sync OUs or configure domain base DN")
    filt = (cfg.get("group_filter") or "").strip()
    conn = _open_connection(cfg)
    seen_dn: set[str] = set()
    groups = []
    for base in bases:
        conn.search(base, filt, attributes=_GROUP_ATTRS)
        for entry in conn.entries:
            dn = entry.entry_dn
            if dn in seen_dn:
                continue
            seen_dn.add(dn)
            name = _attr_str(entry, "cn") or dn
            groups.append(
                {
                    "name": name,
                    "external_id": dn,
                    "description": _attr_str(entry, "description"),
                    "members": _attr_values(entry, "member"),
                }
            )
    conn.unbind()
    return groups


def test_ldap_connection(config: dict) -> dict[str, Any]:
    from app.services.ldap_winldap import WinLdapConnection

    cfg = expand_ldap_config({**config, "enabled": True})
    if _ldap_bridge_enabled():
        from app.services.ldap_bridge_client import bridge_test_connection

        return bridge_test_connection(cfg)
    conn = _open_connection(cfg)
    if isinstance(conn, WinLdapConnection):
        encryption = "LDAP (signed)"
    else:
        encryption = str(cfg.get("_resolved_encryption") or "LDAP")
    base = (cfg.get("base_dn") or "").strip()
    warnings: list[str] = []
    sample_users = 0
    sample_groups = 0

    user_bases = _sync_search_bases(cfg) or ([base] if base else [])
    group_bases = _group_search_bases(cfg) or user_bases
    if user_bases:
        try:
            conn.search(user_bases[0], cfg.get("user_list_filter", ""), attributes=["cn"], size_limit=3)
            sample_users = len(conn.entries)
        except Exception as exc:
            warnings.append(f"User search: {exc}")
    if group_bases:
        try:
            conn.search(group_bases[0], cfg.get("group_filter", ""), attributes=["cn"], size_limit=3)
            sample_groups = len(conn.entries)
        except Exception as exc:
            warnings.append(f"Group search: {exc}")

    conn.unbind()
    resolved_port = int(cfg.get("_resolved_port") or cfg.get("port") or 389)
    use_ssl = bool(cfg.get("_resolved_use_ssl", cfg.get("use_ssl")))
    scheme = "ldaps" if use_ssl else "ldap"
    return {
        "bind_ok": True,
        "server": f"{scheme}://{cfg.get('dc_host')}:{resolved_port}",
        "base_dn": base,
        "domain": cfg.get("domain"),
        "port": resolved_port,
        "use_ssl": use_ssl,
        "encryption": encryption,
        "sample_users": sample_users,
        "sample_groups": sample_groups,
        "warnings": warnings,
    }


def map_ldap_profile(profile: dict) -> dict:
    return profile
