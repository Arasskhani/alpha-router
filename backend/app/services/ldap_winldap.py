"""Windows LDAP with signing (required by many AD DCs when plain SIMPLE bind is blocked)."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

from app.services.ldap_config import clean_bind_password, infer_netbios_domain


def winldap_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import clr  # noqa: F401

        return True
    except ImportError:
        return False


def _load_clr() -> None:
    import clr

    clr.AddReference("System.DirectoryServices.Protocols")


def _dotnet_attr_value(raw: Any) -> str:
    """Normalize .NET LDAP attribute values (incl. byte[] DNs) to str."""
    if raw is None:
        return ""
    type_name = type(raw).__name__
    if type_name == "Byte[]":
        try:
            data = bytes(raw)
            if len(data) >= 2 and data[1] == 0:
                return data.decode("utf-16-le").rstrip("\x00")
            return data.decode("utf-8", errors="replace")
        except Exception:
            return ""
    return str(raw).strip()


class _WinEntry:
    def __init__(self, dn: str, attrs: dict[str, Any]):
        self.entry_dn = dn
        for key, val in attrs.items():
            setattr(self, key, val)


class WinLdapConnection:
    """Minimal ldap3-compatible surface for directory reads."""

    def __init__(self, cfg: dict, *, user: str | None = None, password: str | None = None):
        if not winldap_available():
            raise RuntimeError(
                "Signed LDAP requires Windows with pythonnet (pip install pythonnet). "
                "Alternatively, adjust AD LDAP signing / enable LDAPS on the domain controller."
            )
        _load_clr()
        from System.DirectoryServices.Protocols import (  # type: ignore
            LdapConnection,
            LdapDirectoryIdentifier,
            SearchRequest,
            SearchScope,
        )
        from System.Net import NetworkCredential  # type: ignore

        host = (cfg.get("dc_host") or "").strip()
        if not host:
            raise ValueError("dc_host is required")
        port = int(cfg.get("_resolved_port") or cfg.get("port") or 389)
        use_ssl = bool(cfg.get("_resolved_use_ssl", cfg.get("use_ssl"))) or port == 636
        trust_untrusted = bool(cfg.get("trust_untrusted_cert"))
        bind_user = (user or cfg.get("bind_username") or "").strip()
        bind_pw = clean_bind_password(password if password is not None else (cfg.get("bind_password") or ""))
        domain = (cfg.get("domain") or "").strip()
        netbios = infer_netbios_domain(domain, cfg.get("base_dn"))

        if "\\" in bind_user:
            sam, dom = bind_user.split("\\", 1)
            cred = NetworkCredential(sam, bind_pw, dom)
        elif "@" in bind_user:
            cred = NetworkCredential(bind_user, bind_pw)
        elif netbios:
            cred = NetworkCredential(bind_user, bind_pw, netbios)
        else:
            cred = NetworkCredential(bind_user, bind_pw)

        directory = LdapDirectoryIdentifier(host, port)
        conn = LdapConnection(directory)
        conn.SessionOptions.SecureSocketLayer = use_ssl
        conn.SessionOptions.Signing = not use_ssl
        if use_ssl and trust_untrusted:
            from System.DirectoryServices.Protocols import VerifyServerCertificateCallback  # type: ignore

            def _accept_server_cert(_connection, _certificate):
                return True

            conn.SessionOptions.VerifyServerCertificate = VerifyServerCertificateCallback(_accept_server_cert)
        conn.Bind(cred)

        self._conn = conn
        self._SearchRequest = SearchRequest
        self._SearchScope = SearchScope
        self.entries: list[_WinEntry] = []

    def _resolve_search_scope(self, search_scope: Any) -> Any:
        if search_scope is None:
            return self._SearchScope.Subtree
        try:
            import ldap3

            if search_scope == ldap3.BASE:
                return self._SearchScope.Base
            if search_scope == ldap3.LEVEL:
                return self._SearchScope.OneLevel
            if search_scope == ldap3.SUBTREE:
                return self._SearchScope.Subtree
        except Exception:
            pass
        name = str(search_scope).strip().upper()
        if name in ("BASE", "0"):
            return self._SearchScope.Base
        if name in ("ONELEVEL", "LEVEL", "1"):
            return self._SearchScope.OneLevel
        return self._SearchScope.Subtree

    def search(
        self,
        base: str,
        search_filter: str,
        attributes: list[str] | None = None,
        size_limit: int = 0,
        search_scope: Any = None,
        **_kwargs: Any,
    ) -> bool:
        scope = self._resolve_search_scope(search_scope)
        req = self._SearchRequest(base, search_filter, scope, attributes)
        if size_limit > 0:
            req.SizeLimit = size_limit
        try:
            resp = self._conn.SendRequest(req)
        except Exception as exc:
            if size_limit <= 0 or "size limit" not in str(exc).lower():
                raise
            resp = None
        self.entries = []
        if resp is None or not getattr(resp, "Entries", None):
            return True
        for ent in resp.Entries:
            dn = str(ent.DistinguishedName)
            attrs: dict[str, Any] = {}
            if ent.Attributes:
                for attr in ent.Attributes.AttributeNames:
                    vals = ent.Attributes[attr]
                    if vals is None or len(vals) == 0:
                        continue
                    if len(vals) == 1:
                        attrs[attr] = _dotnet_attr_value(vals[0])
                    else:
                        attrs[attr] = SimpleNamespace(
                            values=[_dotnet_attr_value(v) for v in vals if _dotnet_attr_value(v)]
                        )
            self.entries.append(_WinEntry(dn, attrs))
        return True

    def unbind(self) -> None:
        self._conn.Dispose()
