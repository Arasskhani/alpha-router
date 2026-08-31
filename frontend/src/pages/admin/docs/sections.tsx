import { ReactNode } from "react";
import AdminArchitectureDiagram from "../../../components/docs/AdminArchitectureDiagram";
import { PRODUCT_NAME_MARKED, TRADEMARK_OWNER } from "../../../lib/brand";

export type DocSection = {
  id: string;
  title: string;
  group?: string;
  content: ReactNode;
};

function Code({ children }: { children: string }) {
  return (
    <pre className="docs-code">
      <code>{children}</code>
    </pre>
  );
}

function Note({ children }: { children: ReactNode }) {
  return <div className="docs-callout docs-callout-info">{children}</div>;
}

function Warn({ children }: { children: ReactNode }) {
  return <div className="docs-callout docs-callout-warn">{children}</div>;
}

export const docSections: DocSection[] = [
  // ── Get started ───────────────────────────────────────────────────────────
  {
    id: "introduction",
    title: "Introduction",
    group: "Get started",
    content: (
      <>
        <h1>Admin Guide</h1>
        <p className="docs-lead">
          alpharouter is an organizational AI control plane. It sits between your employees (and optional external tools) and
          upstream LLM providers, enforcing budgets, roles, quotas, audit logging, and retention — while serving a
          built-in chat app and an OpenAI-compatible gateway.
        </p>
        <p>
          This guide is for operators and administrators. End-user help lives in the in-app{" "}
          <strong>User Manual</strong> (<code>/app/manual</code> or <code>/admin/manual</code>). Do not paste secrets
          into documentation; configure them only in your deployment environment and the admin UI.
        </p>
        <div className="docs-cards">
          <div className="docs-card">
            <h3>Three surfaces</h3>
            <p>
              User app <code>/app/*</code>, admin panel <code>/admin/*</code>, and gateway <code>/v1/*</code> — one
              FastAPI process.
            </p>
          </div>
          <div className="docs-card">
            <h3>Policy &amp; spend</h3>
            <p>Plans, monthly budgets, API-key credits, and per-request reservation before provider traffic.</p>
          </div>
          <div className="docs-card">
            <h3>Visibility</h3>
            <p>Dashboard analytics, Operations, API logs, reports, and activity exports.</p>
          </div>
        </div>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Section group</th>
              <th>What you will find</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <a href="#requirements">Get started</a>
              </td>
              <td>Hardware &amp; software requirements, architecture, services, deployment overview</td>
            </tr>
            <tr>
              <td>
                <a href="#security-overview">Security</a>
              </td>
              <td>Auth, sessions/CSRF, RBAC, encryption, hardening checklist</td>
            </tr>
            <tr>
              <td>
                <a href="#admin-dashboard">Overview / Models / People / …</a>
              </td>
              <td>
                Every admin menu: purpose, UI actions, and operational notes — including{" "}
                <a href="#admin-activity-scopes">Activity scopes</a>, <a href="#admin-projects">Projects</a>, and gateway API key policies
              </td>
            </tr>
            <tr>
              <td>
                <a href="#platform-api">Platform API &amp; Billing</a>
              </td>
              <td>
                <code>/v1</code> gateway, budgets, and pricing rules
              </td>
            </tr>
          </tbody>
        </table>
      </>
    ),
  },
  {
    id: "why-alpha-router",
    title: "Why alpharouter exists",
    group: "Get started",
    content: (
      <>
        <h2>Why alpharouter exists</h2>
        <p>Teams adopting LLMs across chat, IDEs, and automation usually hit the same problems:</p>
        <ul>
          <li>Provider API keys are shared or scattered, with no central policy.</li>
          <li>Spend is hard to attribute to people, teams, or departments.</li>
          <li>Model catalogs and pricing change often.</li>
          <li>Compliance needs a durable request history.</li>
        </ul>
        <p>alpharouter addresses this by:</p>
        <ol>
          <li>Terminating client traffic at a platform you operate.</li>
          <li>
            Syncing models and <strong>provider-native pricing</strong> from Connections (alpharouter does not rewrite
            catalog prices).
          </li>
          <li>
            Enforcing <strong>RBAC</strong>, <strong>plans</strong>, <strong>monthly budgets</strong>, and optional
            account deactivation (read-only history; no new spend).
          </li>
          <li>
            Supporting <strong>local</strong>, <strong>LDAP/Active Directory</strong>, <strong>SAML 2.0</strong>, and{" "}
            <strong>OIDC</strong> sign-in.
          </li>
          <li>
            Offering in-app chat, media libraries, Activity, and an optional OpenAI-compatible{" "}
            <code>/v1</code> API for external tools.
          </li>
        </ol>
      </>
    ),
  },
  {
    id: "requirements",
    title: "Hardware & software requirements",
    group: "Get started",
    content: (
      <>
        <h2>Hardware &amp; software requirements</h2>
        <p>
          alpharouter ships as a Docker Compose stack. Plan the host from two independent drivers: the always-on
          platform services (app, database, cache, object storage, Qdrant, ClamAV, Knowledge worker) and the Code
          Interpreter sandbox fleet, which is sized from its concurrent-execution ceiling rather than from the number of
          signed-in users.
        </p>

        <h3>Operating system &amp; platform</h3>
        <ul>
          <li>
            <strong>OS:</strong> a 64-bit Linux host is recommended for production (Ubuntu 22.04 LTS / 24.04 LTS,
            Debian 12, or an equivalent current kernel). macOS and Windows are supported for evaluation through Docker
            Desktop only.
          </li>
          <li>
            <strong>CPU architecture:</strong> <code>x86_64 / amd64</code> is required. The sandbox broker bundles the
            <code> x86_64</code> Docker CLI and the disposable sandbox image is built for amd64, so ARM hosts (Apple
            Silicon, Graviton) must run under amd64 emulation, which is not recommended for production.
          </li>
          <li>
            <strong>Container runtime:</strong> Docker Engine <code>24.0+</code> with the Compose v2 plugin
            (<code>docker compose</code>). The broker talks to the host Docker socket to spawn disposable containers, so
            a working Docker daemon is mandatory — rootless/podman substitutes are not validated.
          </li>
          <li>
            <strong>Networking:</strong> outbound HTTPS to your upstream LLM providers, and only the app port{" "}
            <code>8080</code> exposed to clients. Keep Postgres, Redis, SeaweedFS, Qdrant, ClamAV, and the broker on
            internal networks.
          </li>
        </ul>

        <h3>Pinned service versions</h3>
        <p>
          These are the images the repository <code>docker-compose.yml</code> pins. Keep them aligned when upgrading;
          they are validated together.
        </p>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Component</th>
              <th>Version</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>PostgreSQL</td>
              <td>
                <code>16</code> (alpine)
              </td>
              <td>Primary data store; fronted by PgBouncer in transaction pooling mode</td>
            </tr>
            <tr>
              <td>PgBouncer</td>
              <td>
                <code>1.22</code>
              </td>
              <td>
                SCRAM auth; listens on <code>6432</code>
              </td>
            </tr>
            <tr>
              <td>Redis</td>
              <td>
                <code>7</code> (alpine)
              </td>
              <td>Rate limits, SSO/2FA state, Code Interpreter capacity leases, LiteLLM cache, Knowledge job streams</td>
            </tr>
            <tr>
              <td>SeaweedFS</td>
              <td>
                <code>4.40</code>
              </td>
              <td>S3-compatible object storage for media and Knowledge source bytes</td>
            </tr>
            <tr>
              <td>Qdrant</td>
              <td>
                <code>v1.19.0</code>
              </td>
              <td>Derived vector/sparse index for published Knowledge releases</td>
            </tr>
            <tr>
              <td>ClamAV</td>
              <td>
                <code>1.5.4</code>
              </td>
              <td>Malware scan for Knowledge ingest (internal; no public port)</td>
            </tr>
            <tr>
              <td>Application runtime</td>
              <td>
                Python <code>3.12</code>
              </td>
              <td>FastAPI + uvicorn; bundled headless Chromium for server-side PDF rendering</td>
            </tr>
            <tr>
              <td>Frontend build</td>
              <td>
                Node <code>20</code>
              </td>
              <td>Build-time only (the SPA is served as static files by the app)</td>
            </tr>
          </tbody>
        </table>
        <Note>
          Local development without Docker needs Python <code>3.12</code> and Node <code>20</code> on the workstation.
          You still need reachable Postgres and Redis instances for a full run.
        </Note>

        <h3>Baseline platform sizing (excluding Code Interpreter)</h3>
        <p>
          The following covers the always-on services and moderate chat/gateway traffic. Code Interpreter sandboxes are
          sized separately below.
        </p>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Profile</th>
              <th>vCPU</th>
              <th>RAM</th>
              <th>Disk</th>
              <th>Use</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Evaluation / single box</td>
              <td>4</td>
              <td>8 GiB</td>
              <td>40 GiB SSD</td>
              <td>Trials and small teams; Code Interpreter kept at a low ceiling</td>
            </tr>
            <tr>
              <td>Small production</td>
              <td>8</td>
              <td>16 GiB</td>
              <td>100 GiB SSD</td>
              <td>Daily use for a department; light concurrent Code Interpreter</td>
            </tr>
            <tr>
              <td>Growing production</td>
              <td>16+</td>
              <td>32+ GiB</td>
              <td>250+ GiB SSD</td>
              <td>Higher concurrency; media growth; larger request logs</td>
            </tr>
          </tbody>
        </table>
        <Note>
          Disk grows with media and Knowledge objects (SeaweedFS), Qdrant collections, request logs, and the app{" "}
          <code>/tmp</code> tmpfs used to pack ZIP downloads (Compose reserves up to <code>10g</code>). Provision RAM
          above the tmpfs sizes so heavy exports do not compete with service memory.
        </Note>

        <h3>Sizing the Code Interpreter fleet</h3>
        <p>
          Capacity must be planned from the configured concurrent-sandbox ceiling, not from signed-in users. Each active
          execution is a disposable container. With the default per-sandbox memory limit of <code>256MiB</code>, 200
          simultaneous containers reach a theoretical sandbox ceiling of about <strong>50GiB RAM</strong> before adding
          Docker, the broker, API workers, database, Redis, object storage, tmpfs, and OS headroom. CPU demand can
          approach one vCPU per active sandbox.
        </p>
        <Warn>
          Do not advertise a 200-execution profile by only raising the concurrency ceiling. Validate 50, 100, 150, and
          200 concurrency stages with representative workspace and artifact sizes, then set the operational ceiling from
          Admin → Operations to the highest stage that passes latency, memory, cancellation, and soak-test gates. See{" "}
          <a href="#architecture">Architecture &amp; services</a> for the request path and broker trust boundary.
        </Warn>
      </>
    ),
  },
  {
    id: "architecture",
    title: "Architecture &amp; services",
    group: "Get started",
    content: (
      <>
        <h2>Architecture &amp; services</h2>
        <p>
          alpharouter is one application container that serves the React SPA and the API. Supporting services run beside it in
          Docker Compose.
        </p>
        <AdminArchitectureDiagram />
        <h3>Surfaces</h3>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Surface</th>
              <th>Path</th>
              <th>Auth</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>User app</td>
              <td>
                <code>/app/*</code>
              </td>
              <td>HttpOnly session cookie + CSRF on unsafe <code>/api/*</code> methods</td>
            </tr>
            <tr>
              <td>Admin panel</td>
              <td>
                <code>/admin/*</code>
              </td>
              <td>Same cookie; menus gated by RBAC</td>
            </tr>
            <tr>
              <td>OpenAI-compatible gateway</td>
              <td>
                <code>/v1/*</code>
              </td>
              <td>
                <code>Authorization: Bearer</code> — alpharouter API key, user API key, or gateway master key
              </td>
            </tr>
          </tbody>
        </table>
        <h3>Runtime services</h3>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Service</th>
              <th>Role</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <strong>alpha-router</strong> (uvicorn)
              </td>
              <td>FastAPI app, SPA static files, LiteLLM proxy, schedulers, billing, Agent runtime</td>
            </tr>
            <tr>
              <td>
                <strong>PostgreSQL</strong> + <strong>PgBouncer</strong>
              </td>
              <td>
                Primary data store (users, catalog, chat rows, Agent/Knowledge records, logs, reservations). App
                connects through PgBouncer in transaction pooling mode.
              </td>
            </tr>
            <tr>
              <td>
                <strong>Redis</strong>
              </td>
              <td>
                Rate limits, SSO/2FA pending state, LiteLLM cache, Knowledge job streams (in-memory fallback if Redis is
                unavailable)
              </td>
            </tr>
            <tr>
              <td>
                <strong>SeaweedFS</strong>
              </td>
              <td>
                S3-compatible object storage for media blobs and Knowledge source bytes (authenticated access via
                alpharouter APIs only)
              </td>
            </tr>
            <tr>
              <td>
                <strong>Qdrant</strong>
              </td>
              <td>
                Derived vector/sparse index for published Knowledge releases. Rebuild from PostgreSQL; never treat as
                source of truth.
              </td>
            </tr>
            <tr>
              <td>
                <strong>ClamAV</strong>
              </td>
              <td>Malware scan for Knowledge uploads in quarantine before parse and index</td>
            </tr>
            <tr>
              <td>
                <strong>alpha-router-knowledge-scheduler</strong> / <strong>-worker</strong>
              </td>
              <td>
                Same app image. Scheduler enqueues ingest and retention jobs; worker parses, scans, embeds, and
                publishes Qdrant aliases.
              </td>
            </tr>
            <tr>
              <td>
                <strong>sandbox-broker</strong>
              </td>
              <td>
                Internal HTTP service that spawns disposable code-interpreter containers. Listens on an internal Docker
                network; the Docker socket is a residual host trust boundary — never publish the broker port.
              </td>
            </tr>
          </tbody>
        </table>
        <Note>
          Hardware sizing, pinned service versions, and the Code Interpreter fleet calculation live in{" "}
          <a href="#requirements">Hardware &amp; software requirements</a>.
        </Note>
        <h3>LLM request path (summary)</h3>
        <ol>
          <li>
            Client calls <code>POST /api/chat/completions</code> or <code>POST /v1/chat/completions</code>, optionally
            with an explicit Agent or auto-route.
          </li>
          <li>
            alpharouter resolves an enabled model and Connection key. Code Interpreter requests validate their workspace
            and acquire a Redis capacity lease before alpharouter <strong>reserves</strong> budget (or API-key credit).
          </li>
          <li>
            Streaming goes through LiteLLM to the upstream provider. Optional tools: web search/fetch and code
            interpreter (via sandbox-broker).
          </li>
          <li>
            When a specialist Agent is in play, the runtime plans the turn, retrieves from authorized published
            Knowledge releases in Qdrant, requires citations when policy says so, and fail-closes to a localized safe
            message if citation integrity fails. Turn metadata is stored on <code>agent_runs</code> without raw prompts
            or provider output.
          </li>
          <li>
            Every upstream attempt is normalized into usage events and immutable ledger entries. The reservation is{" "}
            <strong>settled</strong> from the highest-confidence available cost; in-app chat also persists messages
            server-side during the stream.
          </li>
        </ol>
        <Note>
          Image generation uses <code>POST /api/images/generate</code> with its own model selection, retries, and the
          same reservation/settle billing pattern. Video generation uses <code>POST /api/videos/generate</code>{" "}
          (async OpenRouter <code>/videos</code> jobs) plus <code>GET /api/videos/jobs/{"{id}"}</code> polling — never
          inbound webhooks — and settles with <code>service_type=video</code>.
        </Note>
      </>
    ),
  },
  {
    id: "deployment",
    title: "Deployment overview",
    group: "Get started",
    content: (
      <>
        <h2>Deployment overview</h2>
        <p>
          Production deployments typically use the repository <code>docker-compose.yml</code>: Postgres, PgBouncer,
          Redis, SeaweedFS, Qdrant, ClamAV, sandbox-broker, a one-shot <code>db-init</code> Alembic migrate, Knowledge
          scheduler/worker, and the <code>alpha-router</code> app service (port <code>8080</code>).{" "}
          <code>docker compose up --build -d</code> prepares the disposable sandbox image through a one-shot
          initializer; its <code>Exited (0)</code> status is expected. The long-running{" "}
          <code>alpha-router-sandbox-broker</code> smoke-tests the image at startup and creates a short-lived container
          for each execution, so operators must not start a persistent sandbox manually.
        </p>
        <h3>Configuration</h3>
        <p>
          All settings load from environment / <code>.env</code> (see <code>.env.example</code>). Important groups:
        </p>
        <ul>
          <li>
            <strong>Environment gate</strong> — <code>ENVIRONMENT=production</code> enables the startup production
            guard; <code>PRODUCTION_GUARD_MODE</code> is <code>hard-fail</code> (default) or <code>warning</code>.
          </li>
          <li>
            <strong>Secrets</strong> — <code>SECRET_KEY</code>, <code>DATA_ENCRYPTION_KEY</code>, database/Redis/S3
            credentials, <code>QDRANT_API_KEY</code>, <code>SANDBOX_BROKER_TOKEN</code> (≥32 characters),{" "}
            <code>GATEWAY_MASTER_KEY</code>.
          </li>
          <li>
            <strong>URLs</strong> — <code>FRONTEND_URL</code>, <code>API_PUBLIC_URL</code> (used for SAML/OIDC
            callbacks and CORS/CSRF origin checks).
          </li>
          <li>
            <strong>Object storage</strong> — <code>S3_*</code> pointing at SeaweedFS (or another S3-compatible
            endpoint).
          </li>
        </ul>
        <Warn>
          Never commit real <code>.env</code> values. The production guard refuses to boot when known insecure defaults
          remain (placeholder secrets, missing broker token, unauthenticated Redis, cleartext public URLs, legacy Bearer
          auth, and related checks). Loopback and Compose-internal hostnames are deliberately allowed for single-box
          installs.
        </Warn>
        <h3>Health</h3>
        <p>
          <code>GET /health</code> returns a minimal liveness payload. Dependency readiness is owned by your
          orchestration layer (Compose healthchecks), not by expanding this endpoint into a data probe.
        </p>
        <h3>Schema &amp; migrations</h3>
        <p>
          On startup alpharouter creates ORM tables under a PostgreSQL advisory lock, applies nullable column patches for new
          fields, and creates any missing current-schema indexes. Greenfield deployments do not run historical data or storage
          migrations. There is no separate Alembic revision history for operators to apply by hand.
        </p>
      </>
    ),
  },
  {
    id: "quickstart",
    title: "First-time setup",
    group: "Get started",
    content: (
      <>
        <h2>First-time setup</h2>
        <ol>
          <li>
            Deploy Compose (or your equivalent) with a filled <code>.env</code>. Confirm <code>/health</code> and that
            you can open the UI.
          </li>
          <li>
            Sign in with the bootstrap local admin (<code>ADMIN_USERNAME</code> / <code>ADMIN_PASSWORD</code>). Change
            that password immediately after first login.
          </li>
          <li>
            Open <strong>Connections</strong> → create a provider connection → <strong>Sync now</strong>.
          </li>
          <li>
            Open <strong>Models</strong> and enable only the models you want employees to use.
          </li>
          <li>
            Create a <strong>Plan</strong> with a monthly USD budget and assign it to users, groups, or departments.
          </li>
          <li>
            Configure <strong>Authentication</strong> (LDAP / SAML / OIDC) if you are not staying on local accounts
            only.
          </li>
          <li>
            Optionally create <strong>API Keys</strong> for external OpenAI-compatible clients, and configure{" "}
            <strong>SMTP</strong> if you will email reports.
          </li>
          <li>
            Review <strong>Storage Management</strong> and <strong>Retention Policy</strong> before production traffic
            grows.
          </li>
        </ol>
        <Note>
          Users without an assigned (or inherited) budget plan receive HTTP 402 when they try to spend. Assign plans
          before inviting people to chat.
        </Note>
      </>
    ),
  },
  // ── Security ──────────────────────────────────────────────────────────────
  {
    id: "security-overview",
    title: "Security overview",
    group: "Security",
    content: (
      <>
        <h2>Security overview</h2>
        <p>
          alpharouter hardens the browser surface with cookie sessions and CSRF, encrypts secrets at rest, gates admin menus
          with RBAC, and isolates code execution in disposable containers. Upstream provider keys never leave the
          Connections table as plaintext in the API responses.
        </p>
        <ul>
          <li>
            <a href="#sign-in">Sign-in &amp; identity</a>
          </li>
          <li>
            <a href="#sessions-csrf">Sessions, cookies &amp; CSRF</a>
          </li>
          <li>
            <a href="#rbac-model">RBAC model</a>
          </li>
          <li>
            <a href="#secrets-encryption">Secrets &amp; encryption</a>
          </li>
          <li>
            <a href="#hardening">Production hardening checklist</a>
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "sign-in",
    title: "Sign-in &amp; identity",
    group: "Security",
    content: (
      <>
        <h2>Sign-in &amp; identity</h2>
        <p>
          Configure providers under <strong>Authentication</strong> (<code>/admin/authentication</code>). Env vars are
          only a fallback; database rows written from the admin UI take precedence.
        </p>
        <h3>Local</h3>
        <p>
          Username/password with bcrypt. Optional TOTP 2FA for local accounts (user Settings → Security). Super Admins
          can disable another user’s 2FA from the Users edit modal when needed.
        </p>
        <h3>LDAP / Active Directory</h3>
        <p>
          LDAPS bind with a service account, Sync OUs, optional prune of users/groups outside those OUs, and a daily
          sync schedule. Use <strong>Test</strong> before enabling for production, then <strong>Sync AD</strong>.
        </p>
        <h3>SAML 2.0</h3>
        <p>
          IdP metadata via public URL (SSRF-guarded) or uploaded XML (preferred for internal IdPs; XML wins when both
          are set), SP entity ID, ACS URL (shown read-only), attribute mapping, and signature options. Login uses a
          one-time exchange code (Redis, short TTL) so JWTs are never placed in redirect URLs.
        </p>
        <h3>OIDC</h3>
        <p>
          Issuer, client ID/secret, scopes, claim mapping, PKCE authorize/callback flow, and the same one-time exchange
          pattern as SAML.
        </p>
        <h3>Logout &amp; revocation</h3>
        <p>
          Logout increments the user’s <code>token_version</code>. Previously issued JWTs with a lower{" "}
          <code>ver</code> claim are rejected. Password reset and related admin actions also bump the version where
          applicable.
        </p>
      </>
    ),
  },
  {
    id: "sessions-csrf",
    title: "Sessions, cookies &amp; CSRF",
    group: "Security",
    content: (
      <>
        <h2>Sessions, cookies &amp; CSRF</h2>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Cookie</th>
              <th>Properties</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <code>alpha_router_session</code>
              </td>
              <td>HttpOnly, <code>path=/api</code>, SameSite=Lax — carries the JWT</td>
            </tr>
            <tr>
              <td>
                <code>alpha_router_csrf</code>
              </td>
              <td>
                Readable, <code>path=/</code> — double-submit token; SPA sends <code>X-CSRF-Token</code> on unsafe
                methods
              </td>
            </tr>
          </tbody>
        </table>
        <p>
          CSRF is enforced for unsafe methods under <code>/api/</code> when a session cookie is present. Login, 2FA, and
          SSO exchange paths keep Origin checks with defined exemptions; SAML ACS is fully exempt (IdP form POST). The{" "}
          <code>/v1</code> gateway is outside CSRF (API-key auth only).
        </p>
        <p>
          Allowed Origins include <code>FRONTEND_URL</code>, loopback <code>:8080</code>, and HTTP Origins on RFC1918
          addresses (single-box LAN). <code>Secure</code> cookies are set in production, with a carve-out for same-origin
          HTTP on private LAN installs.
        </p>
        <Warn>
          Legacy browser Bearer JWT auth (<code>ALLOW_LEGACY_BEARER_AUTH</code>) is off by default. Enabling it bypasses
          the CSRF cookie path for API calls that send only <code>Authorization</code> — keep it disabled in production.
        </Warn>
        <h3>Inactive users</h3>
        <p>
          Disabled accounts can still authenticate for read-only access to their own chat history and media, but cannot
          send new messages or create spend. Soft-deleted accounts (<code>deleted_at</code> set) cannot authenticate.
        </p>
      </>
    ),
  },
  {
    id: "rbac-model",
    title: "RBAC model",
    group: "Security",
    content: (
      <>
        <h2>RBAC model</h2>
        <p>
          Permissions are role slugs assigned per user (many roles supported). Admin menus are defined in seven
          categories matching the sidebar. Write access is least-privilege: if any of a user’s roles for a menu is
          read-only, writes are denied.
        </p>
        <h3>Primary assignable roles</h3>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Role</th>
              <th>Access</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <strong>User</strong>
              </td>
              <td>
                <code>/app</code> only (chat, media, activity, manual)
              </td>
            </tr>
            <tr>
              <td>
                <strong>Super Admin</strong>
              </td>
              <td>Full admin panel and destructive operations</td>
            </tr>
            <tr>
              <td>
                <strong>API Key Admin</strong>
              </td>
              <td>API Keys menu (full admin for that menu)</td>
            </tr>
            <tr>
              <td>
                <strong>Dashboard (read-only)</strong> / <strong>Reports Admin</strong>
              </td>
              <td>Scoped access re-enabled for those menus</td>
            </tr>
          </tbody>
        </table>
        <p>
          Most other historical per-menu roles were removed from the assignable catalog; Super Admin covers those
          menus. Assign roles from <strong>Roles</strong> (bulk assign) or inline on the <strong>Users</strong> table.
        </p>
        <Note>
          End-user menus (chat, media, user manual) are always writable for active accounts — they are not gated by
          admin RBAC write locks.
        </Note>
      </>
    ),
  },
  {
    id: "secrets-encryption",
    title: "Secrets &amp; encryption",
    group: "Security",
    content: (
      <>
        <h2>Secrets &amp; encryption</h2>
        <p>
          Provider API keys, SMTP passwords, LDAP/OIDC client secrets, and TOTP secrets are stored with Fernet
          encryption. The only encryption key is derived from <code>DATA_ENCRYPTION_KEY</code> (PBKDF2).
          Plaintext, malformed ciphertext, and ciphertext from another key are rejected instead of being forwarded upstream.
        </p>
        <h3>Sandbox trust boundary</h3>
        <p>
          Code interpreter workloads are sent to <code>alpha-router-sandbox-broker</code>, which authenticates with a
          long Bearer token (<code>SANDBOX_BROKER_TOKEN</code> / <code>CODE_SANDBOX_BROKER_TOKEN</code>, ≥32 characters)
          and starts disposable containers from <code>alpha-router-sandbox:latest</code> with{" "}
          <code>--network none</code>, read-only root, dropped capabilities, and resource limits. The broker’s Docker
          socket mount remains the residual host trust boundary — keep the broker on an internal network only and never
          publish port <code>8081</code>. Spreadsheet uploads are converted to CSV text before they reach the sandbox.
          Generated PDF/CSV/JSON/text artifacts are bounded and validated twice, then stored in the requesting
          user&apos;s Media library; no host volume is mounted into the sandbox. Each execution has a Job ID and an
          explicit cancel path, so Stop terminates the disposable container and releases its capacity slot.
        </p>
        <p>
          Workspace and artifact names may use any script (Persian, Arabic, Cyrillic, CJK), so a generated file such as{" "}
          <code>گزارش-مدیریتی.pdf</code> is stored and downloadable under its own name. The name policy rejects only
          deceptive or non-local components: path separators, <code>.</code>/<code>..</code>, control characters, BiDi
          and zero-width formatting characters that hide the real extension, a leading dot or dash, and names over 128
          characters or 255 UTF-8 bytes. The extension allowlist plus per-artifact content validation remain the
          controls that decide what may leave the sandbox.
        </p>
      </>
    ),
  },
  {
    id: "hardening",
    title: "Production hardening",
    group: "Security",
    content: (
      <>
        <h2>Production hardening checklist</h2>
        <ul>
          <li>
            Set <code>ENVIRONMENT=production</code> and keep <code>PRODUCTION_GUARD_MODE=hard-fail</code> until every
            flagged item is fixed.
          </li>
          <li>
            Replace all placeholder secrets; set a dedicated <code>DATA_ENCRYPTION_KEY</code>.
          </li>
          <li>
            Require Redis authentication; wire <code>REDIS_PASSWORD</code> (or an authenticated URL).
          </li>
          <li>
            Set <code>CODE_SANDBOX_BROKER_URL</code>, a ≥32-character <code>SANDBOX_BROKER_TOKEN</code>, and (for local
            API runs) matching <code>CODE_SANDBOX_BROKER_TOKEN</code>. Verify the sandbox initializer exits with code
            zero, the broker becomes healthy, and keep <code>ALLOW_INSECURE_CODE_SUBPROCESS=false</code>.
          </li>
          <li>
            Lock OpenAPI docs to Super Admin (<code>OPENAPI_ADMIN_ONLY=true</code>).
          </li>
          <li>
            Use HTTPS for public <code>FRONTEND_URL</code> / <code>API_PUBLIC_URL</code>; enable HSTS when the public
            surface is TLS-terminated.
          </li>
          <li>
            Keep all dangerous opt-in flags <code>false</code> (see table below). Startup logs a warning if any are
            enabled.
          </li>
          <li>
            Rotate the gateway master key away from any default; treat it as a full-power service credential.
          </li>
          <li>Never publish sandbox-broker ports to the host or public network.</li>
        </ul>
        <h3>Dangerous opt-in flags</h3>
        <p>
          These escape hatches default to <code>false</code>. Do not enable them on shared or internet-facing hosts.
          Prefer the safer alternative in the last column.
        </p>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Flag</th>
              <th>If enabled</th>
              <th>When (if ever)</th>
              <th>Safer alternative</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <code>ALLOW_LEGACY_BEARER_AUTH</code>
              </td>
              <td>Browser JWT in <code>Authorization</code> bypasses cookie + CSRF</td>
              <td>Never in production; rejected by production guard</td>
              <td>Session cookies for browsers; <code>/v1</code> API keys for machines</td>
            </tr>
            <tr>
              <td>
                <code>ALLOW_SSRF_PRIVATE_RANGES</code>
              </td>
              <td>
                <code>ssrf_guard</code> allows private/loopback/metadata fetches
              </td>
              <td>Isolated internal lab only, with a written exception</td>
              <td>Upload SAML Metadata XML; expose internal docs via a controlled proxy</td>
            </tr>
            <tr>
              <td>
                <code>ALLOW_INSECURE_CODE_SUBPROCESS</code>
              </td>
              <td>Code interpreter can run on the API host (development only)</td>
              <td>Local single-developer lab without Docker broker; never production</td>
              <td>
                Keep <code>CODE_SANDBOX_BROKER_URL</code> + <code>SANDBOX_BROKER_TOKEN</code>
              </td>
            </tr>
          </tbody>
        </table>
        <Warn>
          Copying <code>true</code> for these flags from an old lab <code>.env</code> into a shared server is a common
          misconfiguration. Leave them <code>false</code> unless you deliberately accept the risk.
        </Warn>
        <p>
          Browser hardening: CSP starts in Report-Only mode; enforced CSP is opt-in via{" "}
          <code>CONTENT_SECURITY_POLICY</code>. Review reports before enforcing.
        </p>
      </>
    ),
  },

  // ── Overview ──────────────────────────────────────────────────────────────
  {
    id: "admin-menu",
    title: "Admin menu map",
    group: "Overview",
    content: (
      <>
        <h2>Admin menu map</h2>
        <p>
          The admin sidebar groups match RBAC categories. Items you cannot access are hidden. A read-only role can open
          menus but cannot save destructive changes (writes show as locked).
        </p>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Group</th>
              <th>Menus</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>User panel</td>
              <td>Shortcuts into <code>/app</code> (Chat, Media, Activity, User Manual)</td>
            </tr>
            <tr>
              <td>Overview</td>
              <td>Dashboard, Operations, Database</td>
            </tr>
            <tr>
              <td>Agents &amp; Knowledge</td>
              <td>Overview, Agent Studio, Knowledge Bases, Tool Registry, Evaluations, Approvals, Audit</td>
            </tr>
            <tr>
              <td>Models &amp; API</td>
              <td>Connections, Models, API Keys</td>
            </tr>
            <tr>
              <td>People &amp; access</td>
              <td>Roles, Users, Deleted Users, Groups, Plans, Authentication</td>
            </tr>
            <tr>
              <td>Integrations</td>
              <td>SMTP Server</td>
            </tr>
            <tr>
              <td>Data &amp; reports</td>
              <td>Storage Management, Retention Policy, Memory, Reports, Projects, API Logs</td>
            </tr>
            <tr>
              <td>Developer</td>
              <td>Admin Guide, User Manual</td>
            </tr>
          </tbody>
        </table>
      </>
    ),
  },
  {
    id: "admin-dashboard",
    title: "Dashboard",
    group: "Overview",
    content: (
      <>
        <h2>Dashboard</h2>
        <p>
          Path: <code>/admin</code>. Service-wide <strong>Activity</strong> for administrators — spend, requests,
          tokens, heatmaps, trends, and exploration tools. The same tabbed Activity UI is reused wherever usage is scoped
          (see <a href="#admin-activity-scopes">Activity scopes</a>).
        </p>
        <ul>
          <li>
            <strong>Toolbar</strong> — period, group-by (model / app / user), timezone, filters (model, user, app,
            status, API key), CSV/PDF export.
          </li>
          <li>
            <strong>Overview</strong> — KPIs with sparklines, top users/apps, usage and token charts, request heatmap.
          </li>
          <li>
            <strong>Trends</strong> — models, users, API keys, and apps over time.
          </li>
          <li>
            <strong>Explore</strong> — custom metric, grouping, rollup, ranking, chart type, and table; PDF download.
          </li>
        </ul>
        <Note>
          Personal usage for any signed-in user (including admins) is under <strong>Activity</strong> in the user panel
          (<code>/app/my-activity</code> or <code>/admin/my-activity</code>). That view hides organization-wide
          dimensions such as “top users” and cannot filter by user.
        </Note>
      </>
    ),
  },
  {
    id: "admin-activity-scopes",
    title: "Activity scopes",
    group: "Overview",
    content: (
      <>
        <h2>Activity scopes</h2>
        <p>
          alpharouter uses one shared Activity experience (Overview · Trends · Explore) everywhere usage is analyzed.
          Each scope fixes the dataset and hides filters that would be meaningless (for example an API-key page does not
          offer an “API key” filter).
        </p>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Scope</th>
              <th>Path</th>
              <th>What it shows</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Service (Dashboard)</td>
              <td>
                <code>/admin</code>
              </td>
              <td>All organization traffic; full filters and Group-by</td>
            </tr>
            <tr>
              <td>My Activity</td>
              <td>
                <code>/admin/my-activity</code>
              </td>
              <td>Signed-in user only; no user filter or user trends</td>
            </tr>
            <tr>
              <td>User</td>
              <td>
                <code>/admin/users/&lt;id&gt;/activity</code>
              </td>
              <td>One user; no user filter</td>
            </tr>
            <tr>
              <td>Gateway API key</td>
              <td>
                <code>/admin/api-keys/&lt;id&gt;/activity</code>
              </td>
              <td>One gateway key; no API-key filter or API-key trends</td>
            </tr>
            <tr>
              <td>Connection</td>
              <td>
                <code>/admin/connections/&lt;id&gt;/activity</code>
              </td>
              <td>Models on that connection; Explore hides provider grouping</td>
            </tr>
            <tr>
              <td>Group</td>
              <td>
                <code>/admin/groups/&lt;id&gt;/activity</code>
              </td>
              <td>Members of the group; standard user/model/app filters</td>
            </tr>
            <tr>
              <td>Project</td>
              <td>
                <code>/app/projects/&lt;id&gt;/activity</code>
              </td>
              <td>
                One project&apos;s spend (Primary Owner, Owner, or Reports admin). Admin list:{" "}
                <code>/admin/project-usage</code>
              </td>
            </tr>
          </tbody>
        </table>
        <p>
          Gateway API key and User rows also link to scoped <strong>Logs</strong> (
          <code>/admin/api-keys/&lt;id&gt;/logs</code>) — the same API Logs table with the key pre-selected. User-scoped
          logs use query parameters on <code>/admin/logs</code>.
        </p>
        <Note>
          <strong>Agent Audit</strong> (<code>/admin/agent-activity</code>) is separate: runtime guardrail and retrieval
          metadata, not billing analytics.
        </Note>
      </>
    ),
  },
  {
    id: "admin-operations",
    title: "Operations",
    group: "Overview",
    content: (
      <>
        <h2>Operations</h2>
        <p>
          Path: <code>/admin/operations</code> (alias <code>/admin/debug</code>). Infrastructure and API health — not
          billing analytics.
        </p>
        <ul>
          <li>
            Time range selector and <strong>Check Now</strong> (records a metrics snapshot; the page also refreshes on
            an hourly cadence).
          </li>
          <li>
            <strong>Infrastructure</strong> — host CPU/memory, database size.
          </li>
          <li>
            <strong>API traffic</strong> — errors, latency, throughput.
          </li>
          <li>
            <strong>Model experience</strong> — slow requests, P95, slowest models table (links into API Logs).
          </li>
          <li>
            <strong>Code Interpreter capacity</strong> — active/available turn leases, global and per-user ceilings,
            broker job counts, and editable operational limits. The environment ceiling remains a hard upper bound;
            rejection and cancellation counters are exposed by observability.
          </li>
        </ul>
        <Note>
          Code Interpreter requests above the configured ceiling are rejected before provider billing with{" "}
          <code>HTTP 429</code> and <code>Retry-After</code>. Observability counters are also available via{" "}
          <code>GET /api/admin/operations/observability</code>.
        </Note>
      </>
    ),
  },
  {
    id: "admin-database",
    title: "Database",
    group: "Overview",
    content: (
      <>
        <h2>Database</h2>
        <p>
          Path: <code>/admin/database</code>. Read-only monitor: connection status, engine, host CPU/RAM, DB size, ping,
          alpharouter process RSS/CPU, and table row counts. Use <strong>Refresh</strong> to reload.
        </p>
      </>
    ),
  },

  // ── Agents & Knowledge ────────────────────────────────────────────────────
  {
    id: "agents-knowledge-overview",
    title: "Agents & Knowledge overview",
    group: "Agents & Knowledge",
    content: (
      <>
        <h2>Agents &amp; Knowledge overview</h2>
        <p>
          Path: <code>/admin/agents</code>. This area governs specialist behavior, immutable configuration versions,
          authorized Knowledge releases, Tool contracts, evaluation gates, and runtime evidence.
        </p>
        <ul>
          <li>
            <strong>Overview</strong> — KPIs and last-24-hour runtime health. The Knowledge number counts live
            documents only (<code>draft</code>, <code>active</code>, <code>superseded</code>), not revoked or deleted
            rows. Runtime tiles for Turns, Guardrail blocked, and Failed open <strong>Audit</strong> with matching
            Runtime filters; Success rate is a derived percentage and is not a link. Below the quick-start cards,
            <strong>Agent spend</strong> sums chat-turn cost for the same 24 hours (not Knowledge ingest). Top Agents
            open that Agent’s Activity dashboard.
          </li>
          <li>
            <strong>Agent Studio</strong> — create or clone a draft, edit the operator policy form, bind Knowledge,
            submit for review, publish, and roll back. The Agent ⋮ menu includes the same <strong>Activity</strong>
            usage dashboard as Users and Connections, scoped to that Agent’s chat turns.
          </li>
          <li>
            <strong>Knowledge Bases</strong> — upload and review documents, publish indexed releases, configure
            connectors, and retry durable jobs. Removing a file from Documents is a <em>revoke</em>, not a hard delete.
          </li>
          <li>
            <strong>Tool Registry</strong> — versioned schemas, side-effect classification, approvals, and execution
            limits.
          </li>
          <li>
            <strong>Evaluations</strong> — versioned FA/EN golden datasets, deterministic scorecards, and publish-gate
            readiness.
          </li>
          <li>
            <strong>Approvals</strong> — maker-checker queues for Agent versions, Knowledge bindings, document
            versions (including project Resource uploads), and tools. Each card shows the submitter&apos;s name (display
            name or username), not a user id.
          </li>
          <li>
            <strong>Audit</strong> — append-only lifecycle evidence, legal holds, retention, and metadata-only runtime
            outcomes (blocked/failed turns). This is not the usage/spend Activity page.
          </li>
        </ul>
        <Note>
          New Agents are configuration work in Agent Studio: create the Agent and its draft
          version, curate a Knowledge Base and evaluation set, complete approvals, then publish.
          No application code change is required.
        </Note>
      </>
    ),
  },
  {
    id: "agent-studio",
    title: "Agent Studio",
    group: "Agents & Knowledge",
    content: (
      <>
        <h2>Agent Studio</h2>
        <p>
          Path: <code>/admin/agents/studio</code>. Published versions are immutable. Edit a <strong>draft</strong>, or
          use <strong>Clone to draft</strong> on a published version, then publish the new version when review is
          complete.
        </p>
        <h3>Policy form</h3>
        <p>
          The primary editor is an operator form: primary model, routing keywords (chip list), example questions,
          English/Persian disclaimers, and retrieval toggles (enabled, require evidence, citations required). Raw policy
          JSON stays under collapsed <strong>Advanced policy JSON</strong>. Do not use the form to weaken fail-closed
          citation or guardrail hooks; those remain platform policy.
        </p>
        <h3>Knowledge bindings</h3>
        <ul>
          <li>
            On a draft, <strong>+ Add knowledge</strong> opens a search-and-select modal. Already-bound Knowledge Bases
            are hidden. Binding still requires Knowledge (and, for sensitive KBs, domain) approval unless Super Admin
            break-glass auto-approves.
          </li>
          <li>
            Draft chips include ×. Confirming sets the binding to <code>revoked</code> and writes audit; the row is not
            hard-deleted (unique constraint on version + Knowledge Base). Adding the same KB later reactivates that row.
          </li>
          <li>
            Published versions are read-only. Clone to draft, then add or remove bindings on the new draft. Clone copies
            live bindings and skips revoked/suspended ones.
          </li>
        </ul>
        <h3>Activity (usage)</h3>
        <p>
          The Agent ⋮ menu <strong>Activity</strong> item opens the same spend/requests/tokens dashboard used for Users,
          Connections, API Keys, and Groups, filtered to this Agent’s chat turns. Path:{" "}
          <code>/admin/agents/&lt;agent-id&gt;/activity</code>. Filters that still apply: user, model, API key, app, and
          success/fail. Group-by is omitted because the page is already scoped to one Agent.
        </p>
        <Note>
          Agent Activity counts chat-turn cost linked through <code>agent_runs</code>. It does not include Knowledge
          embedding or index-build jobs. For blocked-turn reasons, use <strong>Audit</strong>, not Activity.
        </Note>
      </>
    ),
  },
  {
    id: "knowledge-release-workflow",
    title: "Knowledge release workflow",
    group: "Agents & Knowledge",
    content: (
      <>
        <h2>Knowledge release workflow</h2>
        <ol>
          <li>Set the Knowledge Base owner, sensitivity, retention, and explicit ACL. Deny always wins.</li>
          <li>Upload an authoritative revision or configure a connector. Source bytes enter encrypted quarantine.</li>
          <li>
            Wait for malware, format, parser, OCR (when required), and prompt-injection checks. Failed jobs are visible
            and retriable; unsafe content remains unavailable.
          </li>
          <li>
            A reviewer other than the uploader approves the immutable document version. Blocked injection findings need
            an explicit recorded override.
          </li>
          <li>
            Create a release from reviewed versions. A different publisher submits the release for dense/sparse indexing.
          </li>
          <li>
            The worker builds and validates a blue/green Qdrant index, switches the alias atomically, and only then marks
            the release published.
          </li>
        </ol>
        <p>
          Removing a PDF from Documents is <strong>revoke</strong>: the document leaves retrieval immediately, but the
          row remains for audit and retention. After the configured days, <strong>Run cleanup</strong> purges stored
          files and vectors and marks the document <code>deleted</code> (hidden from the Documents list). The Overview
          Knowledge KPI ignores both <code>revoked</code> and <code>deleted</code> so it matches live corpus size.
        </p>
        <Note>
          Project <strong>Resources</strong> uploads use the same scan/extract/review path, stored on a private internal
          Knowledge Base per project. Approving the document version (Published) is what project members wait for.
          Ordinary project chat may then inject short PostgreSQL excerpts; it does <em>not</em> query the Qdrant release
          index. Bind that Knowledge Base to an Agent and publish a release only when specialist retrieval should use it.
        </Note>
        <Warn>
          PostgreSQL is the source of truth and Qdrant is rebuildable derived state. Never mark a release or index active
          manually to work around a failed job. Fix the dependency, retry the durable job, and preserve its audit trail.
        </Warn>
      </>
    ),
  },
  {
    id: "agent-evaluation-workflow",
    title: "Evaluation and publish gates",
    group: "Agents & Knowledge",
    content: (
      <>
        <h2>Evaluation and publish gates</h2>
        <p>
          Path: <code>/admin/agent-evaluations</code>. Publish-gate datasets must include Persian and English cases
          covering routing, retrieval, citation, abstention, ACL, and prompt injection. Active datasets are immutable;
          create a new dataset version to change expectations.
        </p>
        <ol>
          <li>Import or replace cases while the dataset is a draft and review every expected document-version ID.</li>
          <li>Activate the curated dataset to freeze its snapshot.</li>
          <li>Run the exact Agent version and upload observations for every enabled case.</li>
          <li>
            Confirm retrieval recall@10, routing accuracy, abstention, citation integrity, injection resistance, case
            pass rate, and zero ACL leaks meet the configured thresholds.
          </li>
          <li>Complete independent human review when required. A passing run applies only to that immutable snapshot and
            Agent-version fingerprint.</li>
        </ol>
        <Note>
          Publishing or rolling back an Agent version fails closed when any active publish-gate dataset lacks a passing,
          current evaluation.
        </Note>
      </>
    ),
  },
  {
    id: "agent-operations",
    title: "Agent operations & incidents",
    group: "Agents & Knowledge",
    content: (
      <>
        <h2>Agent operations &amp; incidents</h2>
        <p>
          Path: <code>/admin/agent-activity</code> (<strong>Audit</strong> in the sidebar). Runtime health on Overview
          deep-links here with <code>?source=runtime&amp;since_hours=24</code> and, for blocked or failed tiles,{" "}
          <code>status=blocked</code> or <code>status=failed</code>. Events are metadata-only: Agent name, reason code
          (for example <code>citation_validation_failed</code>), retrieval outcome, and guardrail evidence. Prompts and
          provider output are not stored.
        </p>
        <ul>
          <li>
            Scrape <code>/metrics</code> with its production Bearer token. Alert on failed Agent runs, retrieval failure,
            queue backlog/dead letters, ACL denials, and latency/error-budget burn.
          </li>
          <li>
            Correlate JSON logs with <code>x-request-id</code>, trace ID, and span ID. Prompts, retrieved text, secrets,
            and credentials are intentionally absent from telemetry.
          </li>
          <li>
            When citation integrity fails closed, the user sees a localized safe message (English or Persian) instead of
            the uncited model output. Do not relax fail-closed citation rules to make the KPI look healthier; fix
            retrieval, the draft prompt, or the Knowledge binding.
          </li>
          <li>
            For bad knowledge, revoke the document, verify it leaves the active release/index, and rerun citation/ACL
            evaluations. Apply a legal hold before retention when evidence must be preserved.
          </li>
          <li>
            For a bad Agent version, stop new publication, roll back only to a version that passes all current active
            gates, and verify UI plus <code>/v1/chat/completions</code>.
          </li>
          <li>
            Restore PostgreSQL, SeaweedFS, Redis durability as applicable, then rebuild Qdrant indexes from authoritative
            releases. Validate aliases and point counts before reopening traffic.
          </li>
        </ul>
      </>
    ),
  },

  // ── Models & API ──────────────────────────────────────────────────────────
  {
    id: "admin-connections",
    title: "Connections",
    group: "Models & API",
    content: (
      <>
        <h2>Connections</h2>
        <p>
          Path: <code>/admin/connections</code>. Each connection stores a provider type, encrypted API key, optional base
          URL, and sync schedule.
        </p>
        <h3>Create / edit</h3>
        <ul>
          <li>Name, provider (for example <code>openrouter</code>, <code>openai</code>, <code>custom</code>)</li>
          <li>Base URL (optional; provider defaults apply when empty)</li>
          <li>API key (required on create; leave blank on edit to keep the existing key)</li>
          <li>Sync interval in hours (<code>0</code> = manual sync only)</li>
        </ul>
        <h3>Actions</h3>
        <ul>
          <li>
            <strong>Sync now</strong> — fetch models/pricing from the provider (UI “flash” briefly disables catalog
            rows during refresh).
          </li>
          <li>
            <strong>Enable / Disable</strong> — toggles the connection and its models.
          </li>
          <li>
            <strong>Activity</strong> (<code>/admin/connections/&lt;id&gt;/activity</code>) / changelog — usage for
            models on this connection and audit of connection changes.
          </li>
        </ul>
        <Warn>
          Creating a connection does not sync automatically — run <strong>Sync now</strong> before enabling models for
          users.
        </Warn>
      </>
    ),
  },
  {
    id: "admin-models",
    title: "Models",
    group: "Models & API",
    content: (
      <>
        <h2>Models</h2>
        <p>
          Path: <code>/admin/models</code>. Catalog entries synced from Connections. Input/output cost per 1K tokens is
          displayed read-only from the provider.
        </p>
        <ul>
          <li>Search and kind filters (chat, image, …).</li>
          <li>
            <strong>New</strong> — dropdown of <code>1d</code> / <code>3d</code> / <code>7d</code> /{" "}
            <code>14d</code> / <code>30d</code> shows models first listed in Alpha Router in that
            window. Existing catalog rows without a first-seen time stay hidden from this filter.
          </li>
          <li>Browse (tiles) or table view; per-model enable toggle.</li>
          <li>
            Bulk edit: turn ON, OFF, or delete selected models.
          </li>
          <li>
            <strong>Set Default</strong> — select one public, enabled, text-capable model. New chats use it only when
            the user has not chosen a personal default. Existing user defaults are never overwritten.
          </li>
          <li>
            <strong>Access</strong> — Public (all users) or Private (assigned users and/or groups only). Super admins
            always see private models. Gateway keys inherit the owner&apos;s catalog access; they cannot widen access
            beyond the owner through key settings.
          </li>
          <li>
            <strong>Code Interpreter</strong> column — measured compatibility per model, with probe history and manual
            pinning.
          </li>
        </ul>
        <Note>
          Only enabled models on active connections appear in the chat model picker and <code>/v1/models</code>.
        </Note>
        <h3>Code Interpreter compatibility</h3>
        <p>
          Not every text model can complete the Code Interpreter flow: some never emit a <code>```python</code> block,
          and some providers reject the tool-calling schema (for example with <code>MALFORMED_FUNCTION_CALL</code>).
          alpharouter therefore <em>measures</em> compatibility per Connection + model instead of hardcoding vendor
          names, so newly released models are handled without a code change.
        </p>
        <ul>
          <li>
            <strong>Unknown</strong> — never measured. The model stays selectable so new releases are not lost.
          </li>
          <li>
            <strong>Verified</strong> — a probe or a real chat turn completed the whole flow (Python block → sandbox
            execution → artifact → follow-up answer).
          </li>
          <li>
            <strong>Quarantined</strong> — repeated or hard runtime failures. Hidden from the picker and rejected by the
            API until the quarantine expires and the next probe runs.
          </li>
          <li>
            <strong>Blocked</strong> — a probe proved the flow fails. Re-probed automatically about once a day.
          </li>
        </ul>
        <p>
          A scheduled job probes a small batch of due models every 30 minutes (claimed with row locks so multiple
          workers cannot pay for the same probe twice). Probe cost is recorded as a normal system usage operation.
        </p>
        <p>
          Evidence is weighted by what it actually proves. Transient provider problems (rate limits, timeouts, auth
          errors) and unclassified upstream errors never hide a model on their own — they lower the health score and
          schedule an earlier re-probe, and a model that already passed keeps its verified status. Only repeated
          unclassified failures escalate. Models the provider cannot serve interactively at all (batch-only ids, retired
          ids, no routable provider) are blocked with reason <code>model_unavailable</code> and re-checked weekly instead
          of daily.
        </p>
        <p>
          For OpenRouter Auto Router, alpharouter derives per-request routing constraints from this registry: verified
          models become the allowed pool and blocked models are excluded. The Auto Router entry itself is never hidden.
          Because the router reports its alias while streaming, the concretely selected model is resolved from the
          provider afterwards, so evidence is credited to the model that actually ran the flow rather than to the alias.
        </p>
        <p>
          Open the Code Interpreter cell to review evidence, run a probe on demand, or pin{" "}
          <strong>Force allow</strong> / <strong>Force block</strong>. Pinning overrides all automatic measurement until
          you switch back to <strong>Automatic</strong>. Because a pin silently outranks every measurement, each change
          is recorded in the same evidence list with the administrator who made it.
        </p>
      </>
    ),
  },
  {
    id: "admin-api-keys",
    title: "API Keys",
    group: "Models & API",
    content: (
      <>
        <h2>API Keys</h2>
        <p>
          Path: <code>/admin/api-keys</code>. Admin-issued <strong>gateway keys</strong> for OpenAI-compatible clients
          (Open WebUI, scripts, IDEs). These are separate from <strong>personal API keys</strong> that employees create in
          Settings → API Key (one per user, debits that user&apos;s monthly budget).
        </p>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Key type</th>
              <th>Created on</th>
              <th>Spend debited from</th>
              <th>Typical use</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Gateway API key</td>
              <td>API Keys</td>
              <td>Key credit limit (period pool)</td>
              <td>Integrations, shared service accounts</td>
            </tr>
            <tr>
              <td>User API key</td>
              <td>Users</td>
              <td>That user&apos;s monthly plan budget</td>
              <td>Personal automation for one employee</td>
            </tr>
          </tbody>
        </table>
        <h3>Key settings</h3>
        <ul>
          <li>
            <strong>Owner</strong> (required) — attribution in logs and Activity; also defines which catalog models the
            key may use through Public/Private ACL. Owner does <em>not</em> mean spend is taken from the owner&apos;s
            personal monthly budget.
          </li>
          <li>
            <strong>Name</strong> — label in admin UI and exports.
          </li>
          <li>
            <strong>Credit limit (USD)</strong> and <strong>reset period</strong> (daily / weekly / monthly). Empty or 0
            = no cap on the key itself.
          </li>
          <li>
            <strong>Expiration</strong> — never, or auto-deactivate after N days.
          </li>
          <li>
            <strong>Allowed connections</strong> — optional multi-select allowlist. When enabled, the key may only call
            models on those connections. When disabled, every active connection is eligible (subject to other rules
            below). If a restricted key loses all of its connections (disabled or deleted), it does <em>not</em> fall
            back to “all connections” — it stops working until you edit the key.
          </li>
          <li>
            <strong>Allowed models</strong> — optional multi-select allowlist by catalog model ID. When enabled, the key
            only sees and may call those models. The picker lists enabled models the owner can access, optionally
            narrowed by the connection allowlist. An empty selection while restriction is on denies all model traffic.
            Allowlist never grants models the owner cannot already access.
          </li>
        </ul>
        <h3>Policy layers (gateway keys)</h3>
        <p>
          For <code>/v1/models</code> and all gateway completion paths, a model must pass <strong>every</strong> enabled
          layer:
        </p>
        <ol>
          <li>Model enabled on an active connection</li>
          <li>Connection allowlist (if restricted)</li>
          <li>Catalog Public/Private ACL evaluated for the key owner</li>
          <li>Model allowlist (if restricted)</li>
          <li>Key active, not expired, and within credit limit</li>
        </ol>
        <h3>Client usage</h3>
        <p>
          The plaintext key is shown once at creation (and can be emailed to the owner). Clients call{" "}
          <code>/v1/*</code> with <code>Authorization: Bearer &lt;key&gt;</code>. See{" "}
          <a href="#platform-api">Platform API (/v1)</a>.
        </p>
        <h3>Table &amp; row actions</h3>
        <ul>
          <li>
            Columns include Connections and Models summaries (<strong>All</strong>, <strong>None</strong>, or named
            entries).
          </li>
          <li>
            <strong>Edit</strong> — change settings; header shortcuts to Activity and Logs.
          </li>
          <li>
            <strong>Activity</strong> — <code>/admin/api-keys/&lt;id&gt;/activity</code> (scoped Dashboard).
          </li>
          <li>
            <strong>Logs</strong> — <code>/admin/api-keys/&lt;id&gt;/logs</code> (scoped API Logs).
          </li>
          <li>Enable / disable, delete, bulk actions, change log on the Activity page footer.</li>
        </ul>
        <Warn>
          Restricted keys with an empty connection or model selection are intentionally unusable until an administrator
          adds at least one entry or turns restriction off.
        </Warn>
      </>
    ),
  },

  // ── People & access ───────────────────────────────────────────────────────
  {
    id: "admin-roles",
    title: "Roles",
    group: "People & access",
    content: (
      <>
        <h2>Roles</h2>
        <p>
          Path: <code>/admin/roles</code>. Lists the built-in RBAC catalog (name, description, category, read-only
          flag). You do not create custom role definitions here — you <strong>assign</strong> existing roles to users
          (bulk assign from selected roles).
        </p>
        <p>
          See <a href="#rbac-model">RBAC model</a> for the intended role set.
        </p>
      </>
    ),
  },
  {
    id: "admin-users",
    title: "Users",
    group: "People & access",
    content: (
      <>
        <h2>Users</h2>
        <p>
          Path: <code>/admin/users</code>. Directory of accounts with filters (status, email, department, job title,
          role, group, user plan).
        </p>
        <h3>Capabilities</h3>
        <ul>
          <li>
            Create local users (username, password, profile fields, role, optional group/plan).
          </li>
          <li>
            Inline edit of profile fields, multi-role assignment, and plan (direct / inherit from group / none).
          </li>
          <li>
            Activate / deactivate, reset budget period usage. Personal API keys are self-service (Settings → API Key);
            admins do not issue them from this page.
          </li>
          <li>
            Soft-delete local users (moves to Deleted Users). Directory-synced users follow LDAP/SSO lifecycle rules.
          </li>
          <li>
            Per-user Activity (<code>/admin/users/&lt;id&gt;/activity</code>) and User Storage (admin view of that
            user&apos;s media).
          </li>
          <li>Super Admin: disable TOTP for a local user from the edit modal.</li>
          <li>
            <strong>Online Users</strong> — status filter for accounts signed in with an open tab right now. A browser
            tab reports itself every 30s while visible and the marker expires after <code>PRESENCE_TTL_SECONDS</code>{" "}
            (90s by default), so a closed tab drops off within about a minute. While the filter is active the list
            refreshes every 20s. Presence lives only in Redis; set <code>PRESENCE_ENABLED=false</code> to turn it off.
            If Redis is unreachable the filter is ignored and the page says so rather than showing an empty table.
          </li>
          <li>
            <strong>User Plan</strong> — filters by the effective budget plan shown in the table: a direct user
            assignment, or a plan inherited from a group or department. <strong>No Plan</strong> includes accounts
            with an explicit block and those that inherit nothing. Combined with the other filters.
          </li>
          <li>
            <strong>Export to CSV</strong> downloads the current filtered set (same query as the table) via{" "}
            <code>GET /api/admin/users/export</code>. Columns include profile fields, roles, effective plan, plan
            source (assigned / group / department / none), budget, and status. The file is UTF-8 with BOM for Excel.
          </li>
        </ul>
        <Note>
          <strong>Online</strong> is not <strong>Active</strong>. Active means the account is enabled; Online means
          someone is signed in with an open tab right now. Deactivated users can still sign in to browse history but
          cannot send chat or create new spend, and they never show an online dot.
        </Note>
      </>
    ),
  },
  {
    id: "admin-deleted-users",
    title: "Deleted Users",
    group: "People & access",
    content: (
      <>
        <h2>Deleted Users</h2>
        <p>
          Path: <code>/admin/deleted-users</code>. Soft-deleted accounts that can no longer sign in. You can open
          historical Activity / media, or permanently delete (single or bulk) with confirmation. Permanent
          delete removes residual account data according to cleanup services — use carefully.
        </p>
      </>
    ),
  },
  {
    id: "admin-groups",
    title: "Groups",
    group: "People & access",
    content: (
      <>
        <h2>Groups</h2>
        <p>
          Path: <code>/admin/groups</code>. Local groups plus directory-synced groups (<code>ldap</code> /{" "}
          <code>saml</code> source).
        </p>
        <ul>
          <li>Create/edit local groups; assign a budget plan to the group.</li>
          <li>
            <strong>Sync LDAP</strong> when AD sync is configured.
          </li>
          <li>
            Show members (opens Users filtered),{" "}
            <strong>Activity</strong> (<code>/admin/groups/&lt;id&gt;/activity</code>), deactivate all members, delete
            group.
          </li>
          <li>Bulk assign plans or deactivate members.</li>
        </ul>
      </>
    ),
  },
  {
    id: "admin-plans",
    title: "Plans",
    group: "People & access",
    content: (
      <>
        <h2>Plans</h2>
        <p>
          Path: <code>/admin/plans</code>. A plan is a named monthly USD budget. Assign plans to a user, a group, or a
          department string. Users inherit the resolved monthly limit into their budget cache.
        </p>
        <ul>
          <li>Create/edit: name + monthly budget USD.</li>
          <li>Assign plan modal: choose target type and entity.</li>
          <li>Show members: who currently resolves to this plan.</li>
        </ul>
        <p>
          See also <a href="#budget-pricing">Budget &amp; pricing</a>.
        </p>
      </>
    ),
  },
  {
    id: "admin-authentication",
    title: "Authentication",
    group: "People & access",
    content: (
      <>
        <h2>Authentication</h2>
        <p>
          Path: <code>/admin/authentication</code>. Tabs for Active Directory (LDAP), SAML, and OIDC. Details of each
          protocol are under <a href="#sign-in">Sign-in &amp; identity</a>.
        </p>
        <ul>
          <li>
            <strong>LDAP</strong> — enable, DC host, service account, Sync OUs, prune option, daily schedule, Test /
            Sync.
          </li>
          <li>
            <strong>SAML</strong> — enable, metadata, entity ID, ACS (read-only), attribute mapping, signature options.
          </li>
          <li>
            <strong>OIDC</strong> — enable, issuer, client credentials, redirect URI (read-only), scopes, claim mapping.
          </li>
        </ul>
        <Warn>Store IdP credentials carefully; they are encrypted at rest. Prefer HTTPS IdP endpoints in production.</Warn>
      </>
    ),
  },

  // ── Integrations ──────────────────────────────────────────────────────────
  {
    id: "admin-smtp",
    title: "SMTP Server",
    group: "Integrations",
    content: (
      <>
        <h2>SMTP Server</h2>
        <p>
          Path: <code>/admin/smtp</code>. Outbound mail settings used when emailing reports or credentials.
        </p>
        <ul>
          <li>Host, port, username, password, from address, Use TLS</li>
          <li>
            <strong>Save</strong> and <strong>Test connection</strong>
          </li>
        </ul>
        <Note>Test uses the values you enter; point it only at trusted SMTP servers.</Note>
      </>
    ),
  },

  // ── Data & reports ────────────────────────────────────────────────────────
  {
    id: "admin-storage-management",
    title: "Storage Management",
    group: "Data & reports",
    content: (
      <>
        <h2>Storage Management</h2>
        <p>
          Path: <code>/admin/storage-management</code>. Object-storage usage for user and project media.
        </p>
        <ul>
          <li>Total size/files, expired count, breakdown by kind; refresh.</li>
          <li>
            <strong>DELETE ALL MEDIA</strong> — destructive, multi-step confirm.
          </li>
          <li>Per-user quota (GB) for each user&apos;s personal Media library.</li>
          <li>
            Per-project quota (GB) for each project&apos;s Media library (1–100 GB, default 1 GB). Lowering the limit
            does not delete existing files; projects over quota cannot upload until they free space.
          </li>
          <li>
            Global transfer limits: max upload (MB), max chat attachments total per message (MB), maximum files per
            upload, max ZIP download (MB).
          </li>
          <li>
            Code Interpreter workspace limits: maximum files per turn and maximum extracted-text size. The product
            limit can support 100 or more small files, while a higher broker hard ceiling still protects against
            pathological zero-byte file counts and payload abuse.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "admin-retention",
    title: "Retention Policy",
    group: "Data & reports",
    content: (
      <>
        <h2>Retention Policy</h2>
        <p>
          Path: <code>/admin/retention-policy</code>. Scheduled cleanup for media and chat messages (server timezone).
        </p>
        <ul>
          <li>
            <strong>Media</strong> — retention days, daily cleanup hour/minute, purge expired now.
          </li>
          <li>
            <strong>Chat</strong> — enable policy, retention days, daily schedule, purge expired messages now.
          </li>
        </ul>
        <Note>
          Users can also schedule personal media cleanup from the Media library; that schedule is separate from the
          global media retention settings here.
        </Note>
      </>
    ),
  },
  {
    id: "admin-memory",
    title: "Memory",
    group: "Data & reports",
    content: (
      <>
        <h2>Automatic user memory</h2>
        <p>
          Path: <code>/admin/memory</code>. Long-term memory for user chat: a background extractor mines durable facts
          after non-private turns, stores them in PostgreSQL (source of truth), and indexes IDs (never memory text) in
          Qdrant for semantic recall.
        </p>
        <ul>
          <li>
            <strong>Extraction model</strong> — required. Until you pick an enabled text model, extraction is a no-op
            (no surprise cost on upgrade). Cost is recorded as a system operation, not against the user budget.
          </li>
          <li>
            <strong>Embedding model</strong> — <code>provider:external_id</code>. Dimensions are filled from the selected
            model and stay editable if you need a smaller size. Clearing the model turns off vector search (PostgreSQL
            recency/lexical only). Changing the model or dimensions requires a rebuild.
          </li>
          <li>
            <strong>Sensitive categories</strong> — allow-list for storing classified facts (health, financial, …).
            Empty list means sensitive facts are dropped.
          </li>
          <li>
            <strong>Rebuild index</strong> — create a new Qdrant collection, re-embed every memory, swap the alias.
            Use after changing the embedding model or if Qdrant was wiped.
          </li>
          <li>
            Retention: per-fact <code>expires_at</code>, archive unused facts after the configured days, purge
            already-soft-deleted rows after 30 days (configurable). Users can delete or export their memories.
          </li>
        </ul>
        <h2>Automatic project memory</h2>
        <p>
          The same pipeline mines the <strong>Chat</strong> tab of projects into shared team memory. Facts belong to the
          project, not to the member who happened to post, so every member sees them. Rooms (
          <code>channel_kind=member</code>) and private chats are never mined.
        </p>
        <ul>
          <li>
            <strong>Project memory enabled</strong> — kill switch for the whole organization. Each project also has an{" "}
            <em>Automatically learn from project chats</em> switch in its Settings tab (Owners only), on by default.
          </li>
          <li>
            <strong>Personal memory is never used in project chats</strong>, in either direction: a project chat does
            not read the requesting member's personal memory and does not write to it. Only project memory is injected.
          </li>
          <li>
            <strong>Personal categories are hard-dropped</strong> in project scope —{" "}
            <code>health</code>, <code>financial</code>, <code>personal</code>, <code>family</code>,{" "}
            <code>identity</code> are discarded no matter what the sensitive-category allow-list above says, and that
            cannot be widened from this page.
          </li>
          <li>
            <strong>Retrieval</strong> — owner-authored (manual) facts are always injected as authoritative; learned
            facts go through the same hybrid Qdrant + PostgreSQL search, tenant-filtered by project.
          </li>
          <li>
            <strong>Cost</strong> — recorded as the system operation <code>project_memory_extract</code>, never against
            a member's budget. It shows separately in the KPI row above.
          </li>
          <li>
            <strong>Extraction and embedding models are shared</strong> with user memory; <strong>Rebuild index</strong>{" "}
            re-embeds user and project facts together. Cross-project memory grants still share manual facts only.
          </li>
          <li>
            Owners can delete a single learned fact or all of them from the project Settings tab. A deleted fact is
            suppressed so the extractor does not re-learn it from the same chats.
          </li>
        </ul>
        <Note>
          Stats include oldest pending extraction job age — if the Knowledge worker is not running, jobs queue
          harmlessly and chat is unaffected.
        </Note>
      </>
    ),
  },
  {
    id: "admin-reports",
    title: "Reports",
    group: "Data & reports",
    content: (
      <>
        <h2>Reports</h2>
        <p>
          Path: <code>/admin/reports</code>. Catalog of operational and cost reports with preview (table) and download
          (CSV / Excel / PDF). Parameters depend on the report (dates, user, Agent, plan, department, model, project,
          thresholds, …). <strong>Agent usage</strong> sums chat-turn spend, turns, and tokens from Agent runs for a date range;
          the Agent filter is optional (all Agents when empty). Knowledge ingest cost is excluded.
        </p>
        <h3>Project reports</h3>
        <p>
          Under the Projects category: <strong>All projects usage</strong> has no project picker (organization-wide).
          Single-project reports (<strong>usage summary</strong>, <strong>by model</strong>, <strong>by member</strong>,{" "}
          <strong>media usage</strong>) require a project from the catalog dropdown. Cost is attributed from the
          chat session&apos;s project — clients cannot spoof another project&apos;s <code>project_id</code> on the
          request.
        </p>
        <Note>
          Report generation is interactive from this page. Ensure SMTP is configured if you rely on email delivery
          elsewhere in your process.
        </Note>
      </>
    ),
  },
  {
    id: "admin-projects",
    title: "Projects",
    group: "Data & reports",
    content: (
      <>
        <h2>Projects (admin)</h2>
        <p>
          Employees create and join projects in <code>/app/projects</code>. Administrators do not manage day-to-day
          membership here; they report on spend and understand lifecycle. See the User Manual{" "}
          <a href="/app/manual#user-projects">Projects</a> section for roles and workspace UI.
        </p>
        <h3>Lifecycle</h3>
        <ul>
          <li>
            <strong>Archive</strong> hides a project from Explore and the active My list. Only the Primary Owner can
            archive or restore.
          </li>
          <li>
            <strong>Delete</strong> marks the project <code>deletion_pending</code>. Members still see it until purge.
            Only the Primary Owner can delete.
          </li>
          <li>
            <strong>Purge</strong> (Primary Owner, on pending deletion) permanently removes rows and object storage. A daily
            job also purges projects that stay pending past the retention window (
            <code>PROJECT_DELETION_RETENTION_DAYS</code>, default 30).
          </li>
        </ul>
        <h3>Billing and access</h3>
        <p>
          Path: <code>/admin/project-usage</code> (Data &amp; reports → Projects). Lists organization projects with
          period spend; <strong>Activity</strong> opens the shared page{" "}
          <code>/app/projects/&lt;id&gt;/activity</code> (same Overview / Trends / Explore as User or Group Activity).
          The Primary Owner and Owners of a project can open the same charts from the workspace <strong>Activity</strong>{" "}
          tab. Contributors and Viewers cannot. Request cost is charged from <code>ChatSession.project_id</code>{" "}
          (server-side) for AI chats only. Member rooms (<code>channel_kind=member</code>) cannot call completions or
          media generation, so they never appear as project spend. A client cannot attach another project&apos;s id to a
          personal chat to steal budget or reports. Deleting a user account reassigns remaining project chat sessions to
          another Owner (or member) so shared threads are not CASCADE-deleted with the account.
        </p>
        <h3>Rooms vs Knowledge</h3>
        <p>
          Rooms are human-only (<code>channel_kind=member</code>). Completions, image/video/speech generation, turn
          planning, and project memory extraction skip them. <strong>Send decision to Chat</strong> creates an empty AI
          session and puts the edited brief in the composer only — it does not send the brief to the model or copy the
          room transcript. Project resource files still need Knowledge review (same maker-checker as other documents)
          before they are Published; that is not the Agent release/index workflow. See{" "}
          <a href="#knowledge-release-workflow">Knowledge release workflow</a>.
        </p>
        <Warn>
          Purge is irreversible. Confirm the project is no longer needed before running Purge now.
        </Warn>
      </>
    ),
  },
  {
    id: "admin-logs",
    title: "API Logs",
    group: "Data & reports",
    content: (
      <>
        <h2>API Logs</h2>
        <p>
          Path: <code>/admin/logs</code>. Request-level billing/telemetry rows: time, user or API key, model, provider,
          app, tokens, cache hit, cost, duration, success/failure.
        </p>
        <ul>
          <li>Filters: user, gateway API key (<code>api_key_id</code>), model, status, prompt cache, date range.</li>
          <li>
            The table stays inside the page: narrower widths hide secondary columns (Provider, App, cache, duration,
            then tokens) and ellipsize long user/model names. Full values remain on hover; click a row for Cost details.
          </li>
          <li>
            Open a gateway key from <strong>API Keys → Logs</strong> or{" "}
            <code>/admin/api-keys/&lt;id&gt;/logs</code> — same table scoped to that key (username filter and Clear All
            hidden; banner shows key name).
          </li>
          <li>
            The badge next to Cost identifies its quality: <strong>Provider</strong>, <strong>Reconciled</strong>,{" "}
            <strong>Catalog</strong>, <strong>Estimated</strong>, or <strong>Unpriced</strong>. Hover it to compare the
            provider and calculated amounts.
          </li>
          <li>
            Click a row to open <strong>Cost details</strong>: user or API key, operation totals, each upstream attempt
            (tokens, sources, provider IDs), and line items from{" "}
            <code>GET /api/admin/logs/&lt;id&gt;/cost-details</code>. Pre-ledger rows show only the legacy summary.
          </li>
          <li>
            <strong>Export</strong> downloads the current filtered set (including date range) as CSV via{" "}
            <code>GET /api/admin/logs/export</code>. Inside Cost details, <strong>Export</strong> downloads that one
            request plus its ledger rows via <code>GET /api/admin/logs/&lt;id&gt;/export</code>.
          </li>
          <li>
            <strong>Clear All Logs</strong> — write-gated, multi-step confirm.
          </li>
        </ul>
        <Note>
          Clearing request logs does not erase the cost ledger. Accounting entries are retained so budget totals and
          reconciliation adjustments remain auditable.
        </Note>
        <p>
          Deep links from Operations (for example filtered by model) are supported via query parameters. Export and
          cost-details respect the active filters, including <code>api_key_id</code> when scoped to a gateway key.
        </p>
      </>
    ),
  },

  // ── End users ─────────────────────────────────────────────────────────────
  {
    id: "user-panel",
    title: "User panel",
    group: "End users",
    content: (
      <>
        <h2>User panel</h2>
        <p>
          Employees use <code>/app</code>: Chat, Projects, Media, Activity, and the User Manual. Admins with panel
          access can open the same Chat/Media experiences from the admin sidebar shortcuts, plus the full admin menus.
        </p>
        <p>
          Document every end-user capability in the <strong>User Manual</strong> — do not duplicate the full chat guide
          here. Link: <code>/app/manual</code>.
        </p>
        <ul>
          <li>Chat with enabled models, tools, voice, images, private mode, export.</li>
          <li>Projects: shared workspaces, rooms vs chats, membership, resources, and project media.</li>
          <li>Media library with quota and optional personal cleanup schedule.</li>
          <li>Personal Activity with CSV/PDF export.</li>
          <li>Settings: theme, font, voice language, chat import/export, password/2FA.</li>
        </ul>
      </>
    ),
  },

  // ── Platform API & Billing ────────────────────────────────────────────────
  {
    id: "platform-api",
    title: "Platform API (/v1)",
    group: "Platform API",
    content: (
      <>
        <h2>Platform API (/v1)</h2>
        <p>
          Streaming-first OpenAI-style gateway for external tools (IDEs, scripts, Open WebUI, automation). No CSRF —
          authenticate with a Bearer key only. Chat completions require <code>stream=true</code>; non-stream chat is
          rejected.
        </p>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Endpoint</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <code>GET /v1/models</code>
              </td>
              <td>
                Enabled catalog models after connection allowlist, owner ACL, and model allowlist (gateway keys)
              </td>
            </tr>
            <tr>
              <td>
                <code>POST /v1/chat/completions</code>
              </td>
              <td>Streaming SSE (stream required)</td>
            </tr>
            <tr>
              <td>
                <code>POST /v1/embeddings</code>
              </td>
              <td>Embeddings proxy</td>
            </tr>
          </tbody>
        </table>
        <h3>Authentication modes</h3>
        <ul>
          <li>
            <strong>alpharouter gateway API key</strong> — debits the key&apos;s period credit pool (not the owner&apos;s
            personal budget). Optional connection and model allowlists further restrict which providers and catalog
            entries appear. Owner controls Private-model ACL inheritance.
          </li>
          <li>
            <strong>User API key</strong> — debits that user’s monthly budget; user must be active.
          </li>
          <li>
            <strong>Gateway master key</strong> — maps to a fixed <code>gateway-service</code> account (no{" "}
            <code>body.user</code> impersonation). Treat as a high-privilege secret; assign that account a budget plan
            or requests receive 402.
          </li>
        </ul>
        <Code>{`curl -sS "$ALPHA_ROUTER_BASE/v1/models" \\
  -H "Authorization: Bearer $ALPHA_ROUTER_API_KEY"`}</Code>
        <p>
          Point OpenAI-compatible clients at your alpharouter base URL (for example{" "}
          <code>https://alpha-router.example.com/v1</code>) and use an alpharouter-issued key as the API key.
        </p>
      </>
    ),
  },
  {
    id: "budget-pricing",
    title: "Budget &amp; pricing",
    group: "Billing",
    content: (
      <>
        <h2>Budget &amp; pricing</h2>
        <h3>Pricing</h3>
        <p>
          Model prices come from provider sync (normalized to USD per 1K tokens where possible). alpharouter does not
          apply a markup in the catalog. Billing prefers a provider-reported request charge, then provider
          catalog/configured contract pricing, and finally a LiteLLM estimate. A request that cannot be priced is marked{" "}
          <strong>Unpriced</strong>; missing cost data is never presented as a confirmed zero.
        </p>
        <h3>Monthly user budgets</h3>
        <p>
          Resolved from plan assignment (user → group → department). Before a paid request, alpharouter places a{" "}
          <strong>reservation</strong> (hold) against <code>budget_reserved_usd</code>. After completion it{" "}
          <strong>settles</strong> the actual cost into <code>budget_used_usd</code> and releases the hold. Stale holds
          expire via a background sweeper.
        </p>
        <h3>What counts</h3>
        <ul>
          <li>Every chat/embedding/image provider attempt, including retry, fallback, tool loop, and code loop iterations</li>
          <li>Automatic title generation, prompt enhancement/translation, voice refinement, and transcription</li>
          <li>
            Web search/fetch requests; metered units such as request, credit, second, character, or image are supported
          </li>
          <li>User API key traffic on <code>/v1</code> and gateway key traffic against the key’s credit limit</li>
        </ul>
        <Note>
          Provider errors can still be billable. Failed attempts are retained as events; when the provider exposes no
          charge, the event remains Unpriced instead of silently assuming it was free.
        </Note>
        <h3>Resets</h3>
        <p>
          Monthly user budgets reset on a schedule (first of month). Gateway key credits reset according to each key’s
          daily/weekly/monthly setting. Admins can force a per-user budget reset from the Users page.
        </p>
      </>
    ),
  },
  {
    id: "cost-accounting",
    title: "Cost accounting & reconciliation",
    group: "Billing",
    content: (
      <>
        <h2>Cost accounting &amp; reconciliation</h2>
        <p>
          alpharouter uses a provider-agnostic usage ledger. A user action is a <code>UsageOperation</code>; every real
          upstream attempt is a <code>UsageEvent</code>; normalized quantities and unit prices are{" "}
          <code>CostLineItem</code> records; and the amount applied to a user budget or gateway key is an immutable{" "}
          <code>LedgerEntry</code>. Provider corrections create adjustment entries instead of rewriting history.
        </p>
        <p>
          Ledger entries themselves are immutable. Reconciliation may append an adjustment and update the event/request
          summary fields so the latest authoritative total is visible in API Logs. Original line items remain as they
          were calculated at capture time.
        </p>
        <h3>Cost-source precedence</h3>
        <ol>
          <li>
            <strong>Provider / Reconciled</strong> — a per-request charge returned by the provider or fetched later from
            its usage API.
          </li>
          <li>
            <strong>Catalog / Configured</strong> — the provider model catalog or an explicit contract rate for metered
            services.
          </li>
          <li>
            <strong>Estimated</strong> — LiteLLM model pricing when neither source above is available.
          </li>
          <li>
            <strong>Unpriced</strong> — usage is retained but no confirmed amount is added to the displayed total.
          </li>
        </ol>
        <p>
          LiteLLM remains the transport, usage normalizer, token counter, and final estimation fallback. It is not the
          accounting ledger and its estimates are not labelled as provider-confirmed charges.
        </p>
        <h3>Configured rates for credit/request-based providers</h3>
        <p>
          For services such as web search, audio, or external tools that do not return USD cost, create a versioned rate
          through <code>POST /api/admin/cost-accounting/pricing</code>. Supported units include{" "}
          <code>request</code>, <code>credit</code>, <code>second</code>, <code>minute</code>,{" "}
          <code>character</code>, and <code>image</code>. New rates expire the previous active rate; past events keep
          their original <code>PricingSnapshot</code>.
        </p>
        <p>
          Built-in web search emits <code>provider_type=duckduckgo</code> and <code>service_type=web_search</code>;
          direct URL fetch emits <code>provider_type=direct_http</code> and <code>service_type=web_fetch</code>. Both use
          the <code>request</code> unit unless the provider response exposes a more specific metered unit.
        </p>
        <Code>{`curl -X POST "$ALPHA_ROUTER_BASE/api/admin/cost-accounting/pricing" \\
  -H "Content-Type: application/json" \\
  -H "Cookie: $SESSION_COOKIE=$SESSION_VALUE; $CSRF_COOKIE=$CSRF_TOKEN" \\
  -H "X-CSRF-Token: $CSRF_TOKEN" \\
  -d '{
    "provider_type": "duckduckgo",
    "service_type": "web_search",
    "model_id": "duckduckgo-search",
    "unit": "request",
    "unit_price_usd": 0.008,
    "source": "contract"
  }'`}</Code>
        <h3>Reconciliation</h3>
        <p>
          Registered provider adapters periodically fetch final request charges and post signed ledger adjustments.
          Built-in adapters:
        </p>
        <ul>
          <li>
            <strong>OpenRouter</strong> — <code>GET /generation?id=…</code> returns the per-request{" "}
            <code>total_cost</code>.
          </li>
          <li>
            <strong>OpenAI</strong> — for Responses IDs (<code>resp_*</code>), alpharouter retrieves{" "}
            <code>/v1/responses/&lt;id&gt;</code>. If the payload includes a USD charge it is used; otherwise the
            provider&apos;s authoritative token usage is re-quoted against the local model catalog. Chat Completions IDs
            (<code>chatcmpl-*</code>) cannot be retrieved from OpenAI, so they stay unmatched until you post a manual
            reconciliation. OpenAI&apos;s organization Costs API is aggregate-only and is not used for per-event
            matching.
          </li>
        </ul>
        <p>
          Configure automatic runs with <code>COST_RECONCILIATION_ENABLED</code>,{" "}
          <code>COST_RECONCILIATION_INTERVAL_MINUTES</code>, and <code>COST_RECONCILIATION_BATCH_SIZE</code>. An admin
          can also trigger one connection with <code>POST /api/admin/cost-accounting/reconcile/provider</code>.
        </p>
        <p>
          Providers without an automatic adapter can submit authoritative event costs to{" "}
          <code>POST /api/admin/cost-accounting/reconcile</code>. Each item contains a usage-event ID and the actual USD
          charge. The operation, request log, user/key counter, and reconciliation run are updated in one transaction.
        </p>
        <h3>Audit and diagnostics</h3>
        <ul>
          <li>
            <code>GET /api/admin/cost-accounting/summary</code> — ledger totals by source/confidence, unpriced count,
            legacy pre-ledger spend, ledger start timestamp, and recent reconciliation runs.
          </li>
          <li>
            <code>GET /api/admin/logs/&lt;id&gt;/cost-details</code> — attempts, tokens, provider IDs, line items, and
            pricing sources for one request.
          </li>
          <li>
            <code>GET /api/admin/cost-accounting/pricing</code> — configured-rate history and effective windows.
          </li>
        </ul>
        <Warn>
          No library can guarantee exact USD cost when a provider supplies neither a request charge, a billable usage
          unit, nor invoice/usage reconciliation data. Treat Unpriced events as an operational alert and add a provider
          adapter or configured contract rate.
        </Warn>
      </>
    ),
  },
  {
    id: "schedulers",
    title: "Background jobs",
    group: "Billing",
    content: (
      <>
        <h2>Background jobs</h2>
        <p>APScheduler jobs inside the alpharouter process include (among others):</p>
        <ul>
          <li>Model sync due-check (interval)</li>
          <li>Monthly budget reset</li>
          <li>Budget reservation expiry</li>
          <li>Provider cost reconciliation for registered adapters</li>
          <li>Media and chat retention cleanup (cron from Retention Policy)</li>
          <li>Per-user media cleanup schedules</li>
          <li>System metrics snapshots</li>
          <li>Chat session stats reconcile</li>
          <li>Code Interpreter compatibility probes for due models (interval, small claimed batches)</li>
          <li>Auth directory sync schedules (when configured)</li>
        </ul>
      </>
    ),
  },

  // ── Legal ─────────────────────────────────────────────────────────────────
  {
    id: "copyright",
    title: "Copyright",
    group: "Legal",
    content: (
      <>
        <h2>Copyright</h2>
        <p>Copyright © 2026 Majid Arasskhani.</p>
        <p>
          The {PRODUCT_NAME_MARKED} source code is licensed under the MIT License. Use, modification, and
          redistribution are permitted under that license. The name and logos are not included; see{" "}
          <a href="#trademarks">Trademarks</a>.
        </p>
        <p>Contact: Majid.Arasskhani@gmail.com</p>
      </>
    ),
  },
  {
    id: "trademarks",
    title: "Trademarks",
    group: "Legal",
    content: (
      <>
        <h2>Trademarks</h2>
        <p>
          {PRODUCT_NAME_MARKED}, Alpha Router, AlphaRouter, and the product logos are trademarks of{" "}
          {TRADEMARK_OWNER}.
        </p>
        <p>
          The MIT License covers the source code only. It does not grant permission to use these
          marks for a fork, a competing product, or any use that implies an official relationship.
        </p>
      </>
    ),
  },
];
