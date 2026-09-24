#!/usr/bin/env python3
"""Run the application production guard against the current environment / .env."""

from __future__ import annotations

import sys

from app.config import get_settings
from app.main import _collect_production_insecurities, _tls_edge_enabled_from_disk


def main() -> int:
    settings = get_settings()
    insecure = _collect_production_insecurities(
        environment=settings.environment,
        secret_key=settings.secret_key,
        admin_password=settings.admin_password,
        service_admin_password=settings.service_admin_password,
        gateway_master_key=settings.gateway_master_key,
        code_sandbox_broker_url=settings.code_sandbox_broker_url,
        code_sandbox_broker_token=settings.code_sandbox_broker_token,
        redis_url=settings.redis_url,
        redis_password=settings.redis_password,
        data_encryption_key=settings.data_encryption_key,
        openapi_admin_only=settings.openapi_admin_only,
        database_url=settings.database_url,
        saml_enabled=settings.saml_enabled,
        oidc_enabled=settings.oidc_enabled,
        oidc_issuer=settings.oidc_issuer or "",
        s3_endpoint_url=settings.s3_endpoint_url,
        s3_use_ssl=settings.s3_use_ssl,
        frontend_url=settings.frontend_url,
        api_public_url=settings.api_public_url,
        enable_hsts=settings.enable_hsts,
        allow_insecure_code_subprocess=settings.allow_insecure_code_subprocess,
        s3_access_key=settings.s3_access_key,
        s3_secret_key=settings.s3_secret_key,
        allow_legacy_bearer_auth=settings.allow_legacy_bearer_auth,
        session_cookie_name=settings.session_cookie_name,
        csrf_cookie_name=settings.csrf_cookie_name,
        clamav_required=settings.clamav_required,
        knowledge_ocr_required=settings.knowledge_ocr_required,
        tls_edge_enabled=_tls_edge_enabled_from_disk(),
        http_bind=settings.alpharouter_http_bind,
        trusted_proxy_cidrs=settings.trusted_proxy_cidrs,
        trust_local_gateway_proxy=settings.trust_local_gateway_proxy,
        allow_insecure_saml=bool(getattr(settings, "allow_insecure_saml", False)),
    )
    if settings.environment.lower() != "production":
        print("ENVIRONMENT is not production; guard checks skipped.")
        return 0
    if insecure:
        findings = ", ".join(insecure)
        # Match the application itself: PRODUCTION_GUARD_MODE="warning" lets the
        # app start with these findings (see _apply_production_guard in
        # backend/app/main.py), so this pre-flight must not fail the deploy for
        # a configuration the app will happily run.
        if getattr(settings, "production_guard_mode", "hard-fail") == "warning":
            print(
                "Production guard findings (PRODUCTION_GUARD_MODE=warning):",
                findings,
                file=sys.stderr,
            )
            return 0
        print("Production guard would refuse to start:", findings, file=sys.stderr)
        return 1
    print("Production guard checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
