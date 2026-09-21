"""Active Directory / LDAP authentication and directory reads (plain LDAP by default)."""

from __future__ import annotations

import logging
import ssl
import uuid
from typing import Any

from app.config import get_settings
from app.services.ldap_config import (
    _escape_filter,
    clean_bind_password,
    expand_ldap_config,
    extract_sam_from_bind_dn,
    format_bind_identity,
    format_login_identity,
    infer_domain,
    infer_netbios_domain,
    parse_sync_ous,
)

_AD_USER_ATTRS = [
    "cn",
    "sAMAccountName",
    "userPrincipalName",
    "mail",
    "displayName",
    "company",
    "title",
    "department",
    "physicalDeliveryOfficeName",
    "manager",
]
_GROUP_ATTRS = ["cn", "description", "member"]

# Immutable identity, in preference order. Everything in the lists above (DN,
# sAMAccountName, mail) changes when an object is renamed or moved between OUs.
#
# These are NOT part of the fixed lists because no directory defines both:
# Active Directory has objectGUID and no entryUUID; RFC 4530 directories
# (OpenLDAP, 389DS) have entryUUID and no objectGUID. Connections are opened
# with get_info=ALL, so ldap3 reads the server schema and -- with check_names
# on by default -- validates every requested attribute name against it and
# raises "invalid attribute type <name>" BEFORE the search leaves the client.
# Asking for the wrong one therefore breaks user sync, group sync AND login on
# that directory. The list is narrowed per connection by identity_attrs_for().
IDENTITY_ATTRS: tuple[str, ...] = ("objectGUID", "entryUUID")

LOGGER = logging.getLogger("app.services.ldap_auth")


def _schema_attribute_names(conn: Any) -> set[str] | None:
    """Lowercased attribute names this server's schema defines, else None.

    None means "unknown", which is different from "empty": without a schema
    ldap3 performs no name validation and directories ignore attributes they do
    not recognise, so callers may then ask for everything.
    """
    schema = getattr(getattr(conn, "server", None), "schema", None)
    if schema is None:
        return None
    try:
        types = schema.attribute_types
    except Exception:  # noqa: BLE001 -- external/optional dependency; falls back (return None)
        return None
    if not types:
        return None
    try:
        names = {str(name).lower() for name in types}
    except Exception:  # noqa: BLE001 -- external/optional dependency; falls back (return None)
        return None
    return names or None


def identity_attrs_for(conn: Any) -> list[str]:
    """Identity attributes that are safe to request on this connection."""
    known = _schema_attribute_names(conn)
    if known is None:
        return list(IDENTITY_ATTRS)
    return [attr for attr in IDENTITY_ATTRS if attr.lower() in known]


def user_attrs_for(conn: Any) -> list[str]:
    return [*_AD_USER_ATTRS, *identity_attrs_for(conn)]


def group_attrs_for(conn: Any) -> list[str]:
    return [*_GROUP_ATTRS, *identity_attrs_for(conn)]


def _is_attribute_type_error(exc: BaseException) -> bool:
    if type(exc).__name__ == "LDAPAttributeError":
        return True
    return "invalid attribute type" in str(exc).lower()


def search_with_identity_attrs(conn: Any, base: str, search_filter: str, attributes: list[str], **kwargs: Any):
    """conn.search that degrades instead of failing on an unusable identity attr.

    identity_attrs_for() already narrows the list to the advertised schema; this
    is the backstop for a directory whose advertised schema does not match what
    it actually accepts. Losing the GUID only costs DN-based matching, which is
    what the sync did before -- far better than failing sync and login outright.
    """
    try:
        return conn.search(base, search_filter, attributes=attributes, **kwargs)
    except Exception as exc:
        if not _is_attribute_type_error(exc):
            raise
        reduced = [attr for attr in attributes if attr not in IDENTITY_ATTRS]
        if reduced == list(attributes):
            raise
        LOGGER.warning(
            "Directory rejected identity attribute(s) %s; retrying without them (%s)",
            [attr for attr in attributes if attr in IDENTITY_ATTRS],
            exc,
        )
        return conn.search(base, search_filter, attributes=reduced, **kwargs)


LDAP_UNAVAILABLE_MESSAGE = "LDAP directory is not available right now. Please try again later or use a local account."


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
        except Exception:  # noqa: BLE001 -- best-effort side effect, failure intentionally ignored (Phase 4: log at DEBUG)
            pass
    try:
        if hasattr(entry, name):
            val = getattr(entry, name)
            if val is not None:
                return val
    except Exception:  # noqa: BLE001 -- best-effort side effect, failure intentionally ignored (Phase 4: log at DEBUG)
        pass
    target = name.lower()
    for attr in getattr(entry, "entry_attributes", ()) or ():
        if str(attr).lower() == target:
            try:
                return entry[attr] if hasattr(entry, "__getitem__") else getattr(entry, attr)
            except Exception:  # noqa: BLE001 -- one bad item must not abort the batch
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


def _normalize_guid(value: Any) -> str | None:
    """Canonical lowercase UUID string, or None when the value is not a GUID.

    ldap3 usually hands back ``{xxxxxxxx-....}``; WinLdap and raw reads hand
    back the 16 packed bytes, which Active Directory lays out mixed-endian
    (``bytes_le``) for display.
    """
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        if len(raw) != 16:
            return None
        try:
            return str(uuid.UUID(bytes_le=raw))
        except Exception:  # noqa: BLE001 -- external/optional dependency; falls back (return None)
            return None
    text = str(value).strip().strip("{}").strip()
    if not text:
        return None
    try:
        return str(uuid.UUID(text))
    except Exception:  # noqa: BLE001 -- external/optional dependency; falls back (return None)
        return None


def _stable_entry_id(entry: Any) -> str | None:
    """Immutable directory identity for an entry: objectGUID, else entryUUID.

    Returns None when the directory exposes neither, in which case callers
    fall back to the DN and keep the pre-GUID behaviour.
    """
    for attr in ("objectGUID", "entryUUID"):
        raw = _attr_raw(entry, attr)
        if raw is None:
            continue
        if hasattr(raw, "values"):
            candidates: list[Any] = list(raw.values or [])
        elif isinstance(raw, (list, tuple)):
            candidates = list(raw)
        else:
            candidates = [raw]
        for candidate in candidates:
            guid = _normalize_guid(candidate)
            if guid:
                return guid
    return None


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
    """LDAPS-only connection modes for Active Directory."""
    return [(636, True, False)]


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
        NTLM,
        Connection,
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
    except Exception as exc:  # noqa: BLE001 -- error text is surfaced to the caller
        errors.append(exc)

    ntlm_bind = _ntlm_user()
    if ntlm_bind and _ntlm_md4_available():
        try:
            return _connect(NTLM, ntlm_bind), _encryption_label(use_ssl, use_starttls)
        except Exception as exc:  # noqa: BLE001 -- error text is surfaced to the caller
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
    domain = (cfg.get("domain") or "").strip() or infer_domain(cfg.get("bind_username", ""), cfg.get("base_dn"))
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
            except Exception as exc:  # noqa: BLE001 -- error text is surfaced to the caller
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
        except Exception as exc:  # noqa: BLE001 -- error text is surfaced to the caller
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
                f"{msg} — Active Directory requires LDAPS. Configure a valid certificate on the domain "
                "controller for port 636, then retry from Alpharouter."
            ) from ldap3_error
        lower = msg.lower()
        if _is_tls_error(RuntimeError(msg)) or "starttls failed" in lower:
            if "unexpected_eof" in lower or "eof occurred" in lower or "10054" in lower or "forcibly closed" in lower:
                hint = (
                    "TCP to port 636 may succeed while LDAPS/TLS is not actually configured on the domain "
                    "controller. Install and bind an LDAPS certificate on the DC, then retry."
                )
            else:
                hint = (
                    "Enable Support Untrusted Certificate if the DC uses a self-signed LDAPS cert, "
                    "or install a CA-trusted certificate on the domain controller."
                )
            raise RuntimeError(
                f"{msg} — LDAPS could not be negotiated with the domain controller. {hint}"
            ) from ldap3_error
        raise ldap3_error
    raise RuntimeError("LDAP connection failed")


def probe_directory(host: str, port: int, bind_username: str, password: str) -> dict[str, Any]:
    """Probe AD using the same bind candidate logic as sync/test."""
    domain_guess = infer_domain(bind_username)
    cfg = {
        "enabled": True,
        "dc_host": host,
        "port": 636,
        "use_ssl": True,
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
        return {
            "port": 636,
            "use_ssl": True,
            "use_starttls": False,
            "server": f"ldaps://{host}:636",
            "bind_dn": cfg["bind_dn"],
            "base_dn": base_dn,
            "domain": domain,
            "encryption": cfg.get("_resolved_encryption") or "LDAPS",
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
    dn = getattr(entry, "entry_dn", None) or None
    stable_id = _stable_entry_id(entry)
    return {
        "username": username,
        "email": email,
        "display_name": _attr_str(entry, "displayName") or _attr_str(entry, "cn") or username,
        "company": _attr_str(entry, "company"),
        "job_title": _attr_str(entry, "title"),
        "department": _attr_str(entry, "department"),
        "office": _attr_str(entry, "physicalDeliveryOfficeName"),
        "reporting_to": _attr_str(entry, "manager"),
        # Identity is the GUID when the directory has one; the DN is kept as a
        # separate field because group membership (``member``) is DN-valued and
        # because it still matches rows stored before the GUID migration.
        "external_id": stable_id or dn,
        "dn": dn,
        "identity_source": "guid" if stable_id else "dn",
    }


def _bind_login_connection(cfg: dict, login_bind: str, password: str) -> Any | None:
    try:
        return _open_connection(cfg, user=login_bind, password=password)
    except LdapUnavailableError:
        raise
    except Exception:  # noqa: BLE001 -- external/optional dependency; falls back (return None)
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
    filt = f"(&(objectCategory=person)(objectClass=user)(|(sAMAccountName={esc_sam})(userPrincipalName={esc_upn})))"
    search_with_identity_attrs(conn, base, filt, user_attrs_for(conn), size_limit=1)
    if conn.entries:
        profile = _entry_to_profile(conn.entries[0], sam)
        conn.unbind()
        return profile

    conn.unbind()
    # The directory search found nothing (restricted read, or a bind identity
    # outside the search base). ``login_bind`` is a bind string such as
    # ``CORP\jdoe`` -- NOT a directory identity -- so it must never be written
    # to ``external_id``: doing so overwrites the real GUID/DN and makes the
    # next sync treat the user as unknown (and, with prune on, delete them).
    del login_bind
    return {
        "username": sam,
        "email": upn if "@" in upn else None,
        "display_name": sam,
        "external_id": None,
        "dn": None,
        "identity_source": "none",
    }


def _sync_search_bases(cfg: dict) -> list[str]:
    """User sync: optional sync_ous, else domain base_dn."""
    ous = parse_sync_ous(cfg.get("sync_ous"))
    if ous:
        return ous
    base = (cfg.get("base_dn") or "").strip()
    return [base] if base else []


def _group_search_bases(cfg: dict) -> list[str]:
    """Group sync: same OU scope as users when sync_ous is set.

    ``sync_ous_prune`` only controls post-sync DB cleanup, not the LDAP search base.
    """
    ous = parse_sync_ous(cfg.get("sync_ous"))
    if ous:
        return ous
    gbase = (cfg.get("group_base_dn") or cfg.get("base_dn") or "").strip()
    return [gbase] if gbase else []


def fetch_ldap_users(config: dict) -> list[dict[str, Any]]:
    cfg = expand_ldap_config(config)
    bases = _sync_search_bases(cfg)
    if not bases:
        raise ValueError("No search base: set sync OUs or configure domain base DN")
    filt = (cfg.get("user_list_filter") or "").strip()
    conn = _open_connection(cfg)
    attributes = user_attrs_for(conn)
    seen_dn: set[str] = set()
    users: list[dict[str, Any]] = []
    for base in bases:
        search_with_identity_attrs(conn, base, filt, attributes)
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
    cfg = expand_ldap_config(config)
    bases = _group_search_bases(cfg)
    if not bases:
        raise ValueError("No search base: set sync OUs or configure domain base DN")
    filt = (cfg.get("group_filter") or "").strip()
    conn = _open_connection(cfg)
    attributes = group_attrs_for(conn)
    seen_dn: set[str] = set()
    groups = []
    for base in bases:
        search_with_identity_attrs(conn, base, filt, attributes)
        for entry in conn.entries:
            dn = entry.entry_dn
            if dn in seen_dn:
                continue
            seen_dn.add(dn)
            name = _attr_str(entry, "cn") or dn
            stable_id = _stable_entry_id(entry)
            groups.append(
                {
                    "name": name,
                    "external_id": stable_id or dn,
                    "dn": dn,
                    "identity_source": "guid" if stable_id else "dn",
                    "description": _attr_str(entry, "description"),
                    "members": _attr_values(entry, "member"),
                }
            )
    conn.unbind()
    return groups


def test_ldap_connection(config: dict) -> dict[str, Any]:
    cfg = expand_ldap_config({**config, "enabled": True})
    conn = _open_connection(cfg)
    encryption = str(cfg.get("_resolved_encryption") or "LDAPS")
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
        except Exception as exc:  # noqa: BLE001 -- error text is surfaced to the caller
            warnings.append(f"User search: {exc}")
    if group_bases:
        try:
            conn.search(group_bases[0], cfg.get("group_filter", ""), attributes=["cn"], size_limit=3)
            sample_groups = len(conn.entries)
        except Exception as exc:  # noqa: BLE001 -- error text is surfaced to the caller
            warnings.append(f"Group search: {exc}")

    conn.unbind()
    resolved_port = 636
    use_ssl = True
    scheme = "ldaps"
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
