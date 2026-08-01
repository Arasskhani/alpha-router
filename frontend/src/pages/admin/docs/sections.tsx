import { ReactNode } from "react";
import AdminArchitectureDiagram from "../../../components/docs/AdminArchitectureDiagram";

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
          Alpha Router is an organizational AI control plane. It sits between your employees (and optional external tools) and
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
                <a href="#architecture">Get started</a>
              </td>
              <td>Architecture, services, deployment overview, first-time setup</td>
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
              <td>Every admin menu: purpose, UI actions, and operational notes</td>
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
    title: "Why Alpha Router exists",
    group: "Get started",
    content: (
      <>
        <h2>Why Alpha Router exists</h2>
        <p>Teams adopting LLMs across chat, IDEs, and automation usually hit the same problems:</p>
        <ul>
          <li>Provider API keys are shared or scattered, with no central policy.</li>
          <li>Spend is hard to attribute to people, teams, or departments.</li>
          <li>Model catalogs and pricing change often.</li>
          <li>Compliance needs a durable request history.</li>
        </ul>
        <p>Alpha Router addresses this by:</p>
        <ol>
          <li>Terminating client traffic at a platform you operate.</li>
          <li>
            Syncing models and <strong>provider-native pricing</strong> from Connections (Alpha Router does not rewrite
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
            Offering in-app chat, media libraries, Usage &amp; Activity, and an optional OpenAI-compatible{" "}
            <code>/v1</code> API for external tools.
          </li>
        </ol>
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
          Alpha Router is one application container that serves the React SPA and the API. Supporting services run beside it in
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
                <code>Authorization: Bearer</code> — Alpha Router API key, user API key, or gateway master key
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
                <strong>alpha</strong> (uvicorn)
              </td>
              <td>FastAPI app, SPA static files, LiteLLM proxy, schedulers, billing</td>
            </tr>
            <tr>
              <td>
                <strong>PostgreSQL</strong> + <strong>PgBouncer</strong>
              </td>
              <td>
                Primary data store (users, catalog, chat rows, logs, reservations). App connects through PgBouncer in
                transaction pooling mode.
              </td>
            </tr>
            <tr>
              <td>
                <strong>Redis</strong>
              </td>
              <td>Rate limits, SSO/2FA pending state, LiteLLM cache (in-memory fallback if Redis is unavailable)</td>
            </tr>
            <tr>
              <td>
                <strong>SeaweedFS</strong>
              </td>
              <td>S3-compatible object storage for media blobs (authenticated access via Alpha Router APIs only)</td>
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
        <h3>LLM request path (summary)</h3>
        <ol>
          <li>
            Client calls <code>POST /api/chat/completions</code> or <code>POST /v1/chat/completions</code>.
          </li>
          <li>
            Alpha Router resolves an enabled model and Connection key, then <strong>reserves</strong> budget (or API-key
            credit).
          </li>
          <li>
            Streaming goes through LiteLLM to the upstream provider. Optional tools: web search/fetch, MCP connectors,
            code interpreter (via sandbox-broker).
          </li>
          <li>
            Usage is logged and the reservation is <strong>settled</strong> to the actual cost. In-app chat also
            persists messages server-side during the stream.
          </li>
        </ol>
        <Note>
          Image generation uses <code>POST /api/images/generate</code> with its own model selection, retries, and the
          same reservation/settle billing pattern.
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
          Redis, SeaweedFS, sandbox-broker, and the <code>alpha</code> app (port <code>8080</code>). Build the sandbox
          image separately when you need the code interpreter (<code>docker compose build sandbox</code>).
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
            credentials, <code>SANDBOX_BROKER_TOKEN</code> (≥32 characters), <code>GATEWAY_MASTER_KEY</code>.
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
          On startup Alpha Router creates ORM tables under a PostgreSQL advisory lock, applies nullable column patches for new
          fields, then runs flagged one-time data migrations stored in <code>system_settings</code>. There is no
          separate Alembic revision history for operators to apply by hand.
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
          Alpha Router hardens the browser surface with cookie sessions and CSRF, encrypts secrets at rest, gates admin menus
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
          IdP metadata URL or uploaded XML, SP entity ID, ACS URL (shown read-only), attribute mapping, and signature
          options. Login uses a one-time exchange code (Redis, short TTL) so JWTs are never placed in redirect URLs.
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
              <td>Full admin panel and destructive operations (for example data-key rotation API)</td>
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
          Provider API keys, SMTP passwords, LDAP/OIDC client secrets, connector tokens, and TOTP secrets are stored
          with Fernet encryption. The primary key is derived from <code>DATA_ENCRYPTION_KEY</code> (PBKDF2). When that
          variable is empty, Alpha Router falls back to a key derived from <code>SECRET_KEY</code> for compatibility.
        </p>
        <p>
          Data-key rotation is available to Super Admins via the Operations API endpoint{" "}
          <code>POST /api/admin/operations/data-key-rotation</code> (not a button on the Operations page). Follow your
          operations runbook when rotating keys so existing ciphertext is re-encrypted.
        </p>
        <h3>Sandbox trust boundary</h3>
        <p>
          Code interpreter workloads are sent to <code>sandbox-broker</code>, which authenticates with a long Bearer
          token and starts containers with <code>--network none</code>, read-only root, dropped capabilities, and
          resource limits. The broker’s Docker socket mount remains the residual host trust boundary — keep the broker
          on an internal network only.
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
            Set <code>CODE_SANDBOX_BROKER_URL</code> and a ≥32-character <code>SANDBOX_BROKER_TOKEN</code>. Keep{" "}
            <code>ALLOW_INSECURE_CODE_SUBPROCESS=false</code>.
          </li>
          <li>
            Lock OpenAPI docs to Super Admin (<code>OPENAPI_ADMIN_ONLY=true</code>).
          </li>
          <li>
            Use HTTPS for public <code>FRONTEND_URL</code> / <code>API_PUBLIC_URL</code>; enable HSTS when the public
            surface is TLS-terminated.
          </li>
          <li>
            Keep <code>ALLOW_LEGACY_BEARER_AUTH=false</code> and <code>ALLOW_SSRF_PRIVATE_RANGES=false</code> unless you
            have a documented internal exception.
          </li>
          <li>
            Rotate the gateway master key away from any default; treat it as a full-power service credential.
          </li>
          <li>Never publish sandbox-broker ports to the host or public network.</li>
        </ul>
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
              <td>Shortcuts into <code>/app</code> (Chat, Media, Usage &amp; Activity, User Manual)</td>
            </tr>
            <tr>
              <td>Overview</td>
              <td>Dashboard, Operations, Database</td>
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
              <td>Storage Management, Retention Policy, Reports, API Logs</td>
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
          Path: <code>/admin</code>. Service-wide Usage &amp; Activity for administrators — spend, requests, tokens, and
          exploration tools.
        </p>
        <ul>
          <li>
            <strong>Toolbar</strong> — period, group-by (model / app / user), timezone, filters (model, user, app,
            status, API key), CSV/PDF export.
          </li>
          <li>
            <strong>Overview</strong> — KPIs with sparklines, top users/apps, usage and token charts.
          </li>
          <li>
            <strong>Trends</strong> — models, users, API keys, apps over time.
          </li>
          <li>
            <strong>Explore</strong> — custom metric, grouping, rollup, ranking, chart type, and table; PDF download.
          </li>
        </ul>
        <Note>
          Personal usage for any signed-in user (including admins) is under <strong>Usage &amp; Activity</strong> in the
          user panel (<code>/app/my-activity</code> or <code>/admin/my-activity</code>).
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
        </ul>
        <Note>
          Observability counters are also available via <code>GET /api/admin/operations/observability</code>. Data-key
          rotation is a Super Admin API operation, not a button on this page — use your security runbook.
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
          Alpha Router process RSS/CPU, and table row counts. Use <strong>Refresh</strong> to reload.
        </p>
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
            <strong>Usage &amp; Activity</strong> / changelog — audit of connection changes and traffic.
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
          <li>Browse (tiles) or table view; per-model enable toggle.</li>
          <li>
            Bulk edit: turn ON, OFF, or delete selected models.
          </li>
        </ul>
        <Note>
          Only enabled models on active connections appear in the chat model picker and <code>/v1/models</code>.
        </Note>
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
          (separate from per-user keys created on the Users page).
        </p>
        <h3>Key settings</h3>
        <ul>
          <li>Owner (optional user association for attribution)</li>
          <li>Name</li>
          <li>Credit limit (USD) and reset period: daily / weekly / monthly (empty or 0 = no cap)</li>
          <li>Expiration: never, or auto-deactivate after N days</li>
        </ul>
        <p>
          The plaintext key is shown once at creation. Clients call <code>/v1/*</code> with{" "}
          <code>Authorization: Bearer &lt;key&gt;</code>. Usage debits the key’s credit pool (not a personal monthly
          budget) when the key is a Alpha Router gateway key.
        </p>
        <p>Row actions include edit, usage, enable/disable, delete, bulk actions, and changelog.</p>
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
          role, group).
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
            Activate / deactivate, reset budget period usage, generate a <strong>per-user API key</strong> (debits the
            user’s monthly budget).
          </li>
          <li>
            Soft-delete local users (moves to Deleted Users). Directory-synced users follow LDAP/SSO lifecycle rules.
          </li>
          <li>
            Per-user Usage &amp; Activity and User Storage (admin view of that user’s media).
          </li>
          <li>Super Admin: disable TOTP for a local user from the edit modal.</li>
        </ul>
        <Note>
          Deactivated users can still sign in to browse history but cannot send chat or create new spend.
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
          historical Usage &amp; Activity / media, or permanently delete (single or bulk) with confirmation. Permanent
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
          <li>Show members (opens Users filtered), group activity, deactivate all members, delete group.</li>
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
          Path: <code>/admin/storage-management</code>. Object-storage usage for user media.
        </p>
        <ul>
          <li>Total size/files, expired count, breakdown by kind; refresh.</li>
          <li>
            <strong>DELETE ALL MEDIA</strong> — destructive, multi-step confirm.
          </li>
          <li>Per-user quota (GB).</li>
          <li>
            Global transfer limits (MB): max upload, max chat attachments total per message, max ZIP download.
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
    id: "admin-reports",
    title: "Reports",
    group: "Data & reports",
    content: (
      <>
        <h2>Reports</h2>
        <p>
          Path: <code>/admin/reports</code>. Catalog of operational and cost reports with preview (table) and download
          (CSV / Excel / PDF). Parameters depend on the report (dates, user, plan, department, model, thresholds, …).
        </p>
        <Note>
          Report generation is interactive from this page. Ensure SMTP is configured if you rely on email delivery
          elsewhere in your process.
        </Note>
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
          <li>Filters: user/key, model, status, prompt cache, date range.</li>
          <li>
            <strong>Clear All Logs</strong> — write-gated, multi-step confirm.
          </li>
        </ul>
        <p>Deep links from Operations (for example filtered by model) are supported via query parameters.</p>
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
          Employees use <code>/app</code>: Chat, Media, Usage &amp; Activity, and the User Manual. Admins with panel
          access can open the same Chat/Media experiences from the admin sidebar shortcuts, plus the full admin menus.
        </p>
        <p>
          Document every end-user capability in the <strong>User Manual</strong> — do not duplicate the full chat guide
          here. Link: <code>/app/manual</code>.
        </p>
        <ul>
          <li>Chat with enabled models, tools, voice, images, private mode, export.</li>
          <li>Media library with quota and optional personal cleanup schedule.</li>
          <li>Personal Usage &amp; Activity with CSV/PDF export.</li>
          <li>Settings: theme, voice language, chat import/export, password/2FA, MCP connectors.</li>
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
          OpenAI-compatible gateway for external tools (IDEs, scripts, Open WebUI, automation). No CSRF — authenticate
          with a Bearer key only.
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
              <td>Enabled catalog models</td>
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
            <strong>Alpha Router gateway API key</strong> — credits the key’s period limit; optional owner for attribution.
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
          Point OpenAI-compatible clients at your Alpha Router base URL (for example <code>https://alpha-router.example.com/v1</code>
          ) and use a Alpha Router-issued key as the API key.
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
          Model prices come from provider sync (normalized to USD per 1K tokens where possible). Alpha Router does not apply a
          markup in the catalog. Billing math prefers catalog rates, then LiteLLM cost helpers, then zero if unknown.
          Negative provider prices are treated as unset.
        </p>
        <h3>Monthly user budgets</h3>
        <p>
          Resolved from plan assignment (user → group → department). Before a paid request, Alpha Router places a{" "}
          <strong>reservation</strong> (hold) against <code>budget_reserved_usd</code>. After completion it{" "}
          <strong>settles</strong> the actual cost into <code>budget_used_usd</code> and releases the hold. Stale holds
          expire via a background sweeper.
        </p>
        <h3>What counts</h3>
        <ul>
          <li>In-app chat completions and image generation</li>
          <li>User API key traffic on <code>/v1</code></li>
          <li>Gateway key traffic against the key’s credit limit</li>
        </ul>
        <Warn>
          Some lightweight helper calls (for example automatic chat titles or prompt enhancement) may invoke models
          without a full reservation path — keep an eye on Operations/logs if you rely on those features heavily, and
          prefer enabling only necessary models.
        </Warn>
        <h3>Resets</h3>
        <p>
          Monthly user budgets reset on a schedule (first of month). Gateway key credits reset according to each key’s
          daily/weekly/monthly setting. Admins can force a per-user budget reset from the Users page.
        </p>
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
        <p>APScheduler jobs inside the Alpha Router process include (among others):</p>
        <ul>
          <li>Model sync due-check (interval)</li>
          <li>Monthly budget reset</li>
          <li>Budget reservation expiry</li>
          <li>Media and chat retention cleanup (cron from Retention Policy)</li>
          <li>Per-user media cleanup schedules</li>
          <li>System metrics snapshots</li>
          <li>Chat session stats reconcile</li>
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
        <p>
          Alpha Router was designed by <strong>Majid Arasskhani</strong> and developed by <strong>Cursor AI</strong> within
          the <strong>BitPin IT Department</strong>.
        </p>
        <p>
          <strong>About BitPin Exchange</strong> — Iranian digital asset platform focused on reliability, security, and
          transparent operations.
        </p>
        <div style={{ marginTop: "1rem" }}>
          <p style={{ margin: 0 }}>Copyright: BitPin IT Department</p>
          <p style={{ margin: "0.2rem 0 0" }}>Contact: IT@BitPin.co</p>
        </div>
      </>
    ),
  },
];
