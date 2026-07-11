import subprocess

ROOT = r"C:\APPS\NITRO"
msg = (
    "feat(security): phase 5 SSRF guard + SPA containment + security headers\n\n"
    "SSRF (layer 1):\n"
    "- New app/services/ssrf_guard.py: reject user-supplied fetches that resolve\n"
    "  to loopback / private / link-local / metadata IPs, with post-redirect\n"
    "  re-validation. ALLOW_SSRF_PRIVATE_RANGES env flag opts out (default off).\n"
    "- Wired into chat_tools_service.fetch_url_text (web-fetch chat tool),\n"
    "  images._reference_image_dimensions (reference image URL), and\n"
    "  storage_service._download_url (media import source_url). Admin-configured\n"
    "  LLM/Keycloak/LDAP outbound calls are unaffected.\n\n"
    "SPA:\n"
    "- Path-traversal containment in spa_fallback: resolve+containment check\n"
    "  keeps FileResponse within frontend dist.\n"
    "- Unmatched /api/* and /v1/* now return JSON 404 instead of the HTML shell.\n\n"
    "Security headers:\n"
    "- SecurityHeadersMiddleware adds nosniff, X-Frame-Options DENY, Referrer-Policy,\n"
    "  Permissions-Policy, COOP. HSTS gated on ENABLE_HSTS + production. CSP opt-in\n"
    "  via CONTENT_SECURITY_POLICY env.\n"
    "- CORS tightened to explicit methods/headers instead of '*'.\n\n"
    "Tests: test_ssrf_guard.py + test_spa_and_headers.py (17 new, all green).\n"
)

r = subprocess.run(["git", "-C", ROOT, "add", "-A"], capture_output=True, text=True)
print("add:", r.returncode, r.stderr)
r = subprocess.run(["git", "-C", ROOT, "commit", "-m", msg], capture_output=True, text=True)
print("commit:", r.returncode)
print(r.stdout[-800:])
print(r.stderr[-200:])
