# Alpha Router Fresh Security Audit Report

**Engagement:** Zero-assumption, read-only Static + Dynamic assessment  
**Date:** 2026-07-20  
**Target:** Local Docker Compose (`alpha-router`, `postgres`, `pgbouncer`, `redis`, `minio`, `sandbox-broker`)  
**Rules:** No remediation · No secret values · No weaponized exploits · No credential rotation  

---

## 1. Executive summary

This engagement treated Alpha Router as never previously audited. Controls were re-verified from source and from live local behavior. No application code, live `.env` values, databases, or volumes were modified for remediation.

| Severity | Count |
|----------|------:|
| Critical / architectural host risk | 1 |
| High | 3 |
| Medium | 6 |
| Low / Informational | 4 |

### Top risks right now

1. **Sandbox broker holds Docker socket** — compromise of broker or its token equals host Docker control.
2. **Production guard runs in `warning` mode while `ENVIRONMENT=production`** — insecure configurations do not hard-fail boot.
3. **Legacy Bearer auth remains enabled** — CSRF is skipped when no session cookie is present; JWT from login can mutate APIs without CSRF.
4. **App published on `0.0.0.0:8080` without HSTS / enforced CSP** — LAN exposure and weaker browser defense-in-depth.
5. **Redis rate-limit fail-open** — Redis outage weakens login brute-force protection across workers.

**Also confirmed working:** no anonymous `/v1`; broker rejects missing/wrong tokens and is not host-published; docs locked for anonymous callers; alpha-router has no docker.sock; Redis requires auth; no confirmed cross-user IDOR for normal users on chat/media.

---

## 2. Methodology

### In scope
- Static review: auth, gateway, admin, SSRF, sandbox, IDOR, frontend XSS/storage, crypto, Compose, CI
- Dynamic probes against localhost only (HTTP status/headers/inspect facts)
- Secret *categories* and length/presence checks only

### Out of scope
- Remediation, commits, dependency upgrades, credential rotation
- Weaponized exploits / PoCs, volume deletion, destructive load
- Attacks against external OpenRouter / corporate LDAP / remote Keycloak
- Full red-team exploitation of Docker socket beyond architecture documentation

### Severity scale
Critical · High · Medium · Low · Informational

---

## 3. Recon baseline (live evidence)

| Check | Result |
|-------|--------|
| `GET /health` | 200 · `{"status":"ok","service":"alpha-router"}` (minimal) |
| Docs/OpenAPI unauthenticated | `/docs`, `/redoc`, `/openapi.json`, `/api/docs`, `/api/openapi.json`, `/api/redoc` → **404** |
| `/v1/models` no key | **401** |
| `/v1/models` bad key | **401** |
| Login with `Origin: https://evil.example` | **403** |
| Admin unauthenticated | **401** |
| Broker from host `127.0.0.1:8081` | Not reachable (unpublished) |
| Broker from alpha-router network `/health` | **200** |
| Broker `/v1/execute` no/bad token | **401 / 401** |
| alpha-router container | user=`alpha-router`, ReadonlyRootfs=true, CapDrop=ALL, no-new-privileges, **no** docker.sock |
| sandbox-broker container | docker.sock mounted RW; published ports null; CapDrop ALL; read_only; **Config.User empty** |
| alpha-router published ports | `0.0.0.0:8080` and `:::8080` |
| Redis unauthenticated ping | `NOAUTH Authentication required` |
| Security headers on `/` | CSP **Report-Only** present; enforcing CSP absent; HSTS absent; `X-Content-Type-Options: nosniff`; `X-Frame-Options: DENY` |

### Runtime flags (non-secret facts only)

```text
ENVIRONMENT=production
PRODUCTION_GUARD_MODE=warning
OPENAPI_ADMIN_ONLY=true
allow_legacy_bearer_auth=True
enable_csrf=True
enable_cookie_auth=True
allow_ssrf_private_ranges=False
enable_ssrf_dns_pinning=True
allow_insecure_code_subprocess=False
enable_hsts=False
DATA_ENCRYPTION_KEY=SET
REDIS_PASSWORD=SET
SANDBOX_BROKER_TOKEN=SET (len>=32)
GATEWAY_MASTER_KEY=CUSTOM (not default sk-alpha-router-master)
SECRET_KEY=CUSTOM (not default change-me-in-production)
```

---

## 4. Findings

### F-01 · Critical · Docker socket on sandbox-broker

- **Location:** `docker-compose.yml` (sandbox-broker volume), `backend/app/sandbox_broker.py`
- **Finding:** Broker mounts host `/var/run/docker.sock` and runs Docker CLI with a hardcoded policy. Shared bearer token auth. Broker/token compromise ⇒ host Docker control.
- **Evidence:** Live inspect sock RW; host 8081 unpublished; alpha-router has no sock; execute rejects bad/missing token with 401.
- **Impact:** Host compromise class — highest privilege surface.
- **Advisory:** Isolate broker host/VM; rotate token; never publish broker; consider rootless/alternative isolation.

### F-02 · High · Production guard soft-fail in production

- **Location:** `backend/app/main.py`; runtime `PRODUCTION_GUARD_MODE=warning` + `ENVIRONMENT=production`
- **Finding:** Production labeled correctly, but guard warns and continues instead of hard-failing.
- **Evidence:** Settings probe; service is up under warning mode.
- **Impact:** Future insecure defaults may boot into “production” with logs only.
- **Advisory:** Switch to `hard-fail` after config checklist.

### F-03 · High · Legacy Bearer auth bypasses CSRF

- **Location:** `backend/app/api/deps.py`, `csrf_protection.py`, `auth.py`
- **Finding:** Cookie+CSRF enabled, but `allow_legacy_bearer_auth=True`. CSRF skipped without session cookie. Login JWT can mutate `/api/*` without CSRF.
- **Evidence:** Runtime `allow_legacy_bearer_auth=True`, `enable_csrf=True`; code path confirms exemption.
- **Impact:** XSS / leaked JWT regain CSRF-immune API access.
- **Advisory:** Disable legacy Bearer for browsers; stop returning SPA access tokens; keep `/v1` on API keys.

### F-04 · High · App bound to all interfaces on :8080

- **Location:** `docker-compose.yml` alpha-router ports; live inspect
- **Finding:** App on `0.0.0.0:8080` / `:::8080`; DB/Redis/MinIO are localhost-bound; HSTS off; no TLS terminator verified.
- **Evidence:** Inspect ports; `enable_hsts=False`; no HSTS header.
- **Impact:** LAN/WAN cleartext reachability if host firewall open.
- **Advisory:** Bind `127.0.0.1` behind TLS reverse proxy, or strict network ACLs + TLS.

### F-05 · Medium · Redis / login rate-limit fail-open

- **Location:** `backend/app/services/rate_limit.py`
- **Finding:** Redis authenticated live (good), but Redis errors fall back to per-worker memory limits (including login).
- **Impact:** During Redis outage, brute-force limits weaken × workers.
- **Advisory:** Fail-closed for login; alert on `redis_fallback`.

### F-06 · Medium · CSP Report-Only only

- **Location:** security headers / config; live headers
- **Finding:** Report-Only CSP present; enforcing CSP absent.
- **Impact:** Browser XSS not blocked by CSP; relies on Markdown/URL policy.
- **Advisory:** Enforce CSP after soak; HSTS only behind HTTPS.

### F-07 · Medium · SSRF kill-switches exist

- **Location:** `ssrf_guard.py`, config flags
- **Finding:** Defaults safe (`ALLOW_SSRF_PRIVATE_RANGES=false`, DNS pinning on). Kill-switches can disable private checks or rebinding protection.
- **Impact:** Misconfig turns authenticated fetch features into internal scanners.
- **Advisory:** Keep defaults; dual-approve changes; alert on deviation.

### F-08 · Medium · Legacy plaintext decrypt fallback

- **Location:** `secret_crypto.py` `decrypt_secret`
- **Finding:** Non-Fernet values returned as plaintext; undecryptable tokens returned as-is.
- **Impact:** Unmigrated DB rows / dumps may expose live secrets.
- **Advisory:** Confirm migration complete; reject plaintext post-cutover.

### F-09 · Medium · Private Mode client-side confidentiality

- **Location:** frontend private chat/media stores
- **Finding:** Confidentiality depends on client not syncing; shared browser / persist flags can leave local data.
- **Impact:** Local shared-device leakage (not server cross-user IDOR).
- **Advisory:** Document; wipe on logout by default; avoid persist on kiosks.

### F-10 · Medium · Broker without explicit non-root USER

- **Location:** live inspect sandbox-broker `Config.User` empty
- **Finding:** Unlike alpha-router (`user=alpha-router`), broker user empty (typically root) while holding docker.sock.
- **Impact:** Increases blast radius with F-01.
- **Advisory:** Non-root broker where possible; tighten socket access.

### F-11 · Low · Gateway master key compared with `==`

- **Location:** `gateway.py`
- **Finding:** Non-constant-time compare; broker correctly uses `hmac.compare_digest`.
- **Impact:** Theoretical timing side-channel.
- **Advisory:** Use `hmac.compare_digest`.

### F-12 · Low · Admin masked secrets reveal last 4 chars

- **Location:** `mask_secret` / admin connections
- **Finding:** Masked keys expose short plaintext tail after decrypt.
- **Impact:** Key confirmation for privileged admins.
- **Advisory:** Mask without decrypting tails.

### F-13 · Low · ChatCodeBlock `dangerouslySetInnerHTML`

- **Location:** `frontend/src/components/chat/ChatCodeBlock.tsx`
- **Finding:** Only identified HTML sink via highlight.js; Markdown has no `rehype-raw` (positive).
- **Impact:** Residual library XSS risk.
- **Advisory:** CSP enforce; pin/review hljs.

### F-14 · Informational · Users-menu admins can read any media by design

- **Location:** `media_authorization_service.py`
- **Finding:** Cross-user media READ for Users menu is intentional admin capability.
- **Impact:** High-trust role must be tightly assigned.
- **Advisory:** Audit assignments; log cross-user media access.

---

## 5. Positive controls verified

- Alpha Router: non-root, read-only rootfs, cap_drop ALL, no-new-privileges, no docker.sock
- Broker policy hardcoded; extras forbidden; missing/wrong token → 401; not host-published
- Insecure subprocess disabled; SSRF private ranges off; DNS pinning on
- Gateway anonymous/bad key → 401
- Evil Origin on login → 403; admin unauth → 401
- OpenAPI/docs locked anonymously with `OPENAPI_ADMIN_ONLY=true`
- Redis requires authentication
- Custom (non-default) SECRET_KEY / gateway master; data encryption key set; broker token length ≥ 32
- Minimal health payload
- Media/chat ownership checks for normal users (no confirmed cross-user IDOR)
- Markdown without raw HTML; URL policy; JWT localStorage keys cleared on logout paths
- Headers: nosniff, DENY framing, CSP Report-Only baseline

---

## 6. Residual / limitations

- Docker socket on broker is an architectural residual Critical until redesign.
- CSP enforce and reverse-proxy/TLS remain operational follow-ups.
- LDAP bridge / Keycloak federation not dynamically tested against live external IdPs.
- Full dual-account authenticated CSRF/IDOR browser matrix remains a recommended follow-up with disposable test users.
- No secret values appear in this report by design.
- Findings reflect the observed local Compose state on 2026-07-20.

---

## 7. Suggested next steps (advisory only — not performed)

1. Set `PRODUCTION_GUARD_MODE=hard-fail` after a config checklist.
2. Plan disablement of legacy Bearer for browser clients; keep API keys on `/v1`.
3. Put Alpha Router behind TLS reverse proxy; bind app port to localhost if proxy is local.
4. Schedule CSP enforce + HSTS rollout.
5. Architectural review of broker/docker.sock isolation.
6. Optional: dual-user authenticated IDOR/CSRF matrix with disposable accounts.
7. Only after explicit approval: separate remediation phase.

---

**Statement:** Penetration testing and analysis only. No remediation of findings was applied. This Markdown report is the audit deliverable (HTML export can be generated on request when Agent mode is allowed).
