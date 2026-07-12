import subprocess

ROOT = r"C:\APPS\NITRO"
msg = (
    "feat(security): phase 6 Keycloak SSO hardening\n\n"
    "CSRF + replay protection (OIDC):\n"
    "- New app/services/oidc.py: random state bound to a short-lived signed\n"
    "  HttpOnly SameSite=Lax cookie, PKCE (S256) code_challenge/verifier, and\n"
    "  nonce validated inside the ID token. ID-token validation verifies the\n"
    "  signature via the realm JWKS (cached) plus iss/aud/exp/nonce.\n"
    "- keycloak_login builds the authorize URL with state+PKCE+nonce and sets\n"
    "  the signed state cookie. keycloak_callback verifies the cookie+state,\n"
    "  exchanges the code WITH the PKCE verifier, and validates the ID token.\n"
    "- realm (no path segments) and server_url (https in production) validated.\n\n"
    "Account takeover prevention:\n"
    "- _upsert_directory_user now binds Keycloak identity by\n"
    "  (auth_provider='keycloak', external_id=sub) instead of username-only.\n"
    "  Cross-provider username collisions (e.g. a Keycloak user named 'admin'\n"
    "  taking over the local admin) are rejected with 409.\n\n"
    "JWT no longer in URL:\n"
    "- New app/services/oidc_exchange.py stores the minted JWT under a one-time\n"
    "  opaque code in Redis (TTL 30s, single-use). The callback redirects to\n"
    "  /login?code=<opaque>; new POST /api/auth/keycloak/exchange returns the\n"
    "  JWT in the body. Frontend Login.tsx uses the exchange endpoint.\n\n"
    "SSO logout:\n"
    "- New GET /api/auth/keycloak/logout redirects to the Keycloak end_session\n"
    "  endpoint; frontend session.logout() routes Keycloak users through it.\n"
    "- /api/auth/session now exposes auth_provider.\n\n"
    "Tests: test_oidc.py (state/PKCE/nonce/JWKS with a generated RSA keypair),\n"
    "test_keycloak_upsert.py (collision rejection, sub binding),\n"
    "test_oidc_exchange.py (single-use code). 20 new tests, all green.\n"
)

r = subprocess.run(["git", "-C", ROOT, "add", "-A"], capture_output=True, text=True)
print("add:", r.returncode, r.stderr[:200])
r = subprocess.run(["git", "-C", ROOT, "commit", "-m", msg], capture_output=True, text=True)
print("commit:", r.returncode)
print(r.stdout[-800:])
print(r.stderr[-200:])
