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
  {
    id: "introduction",
    title: "Introduction",
    group: "Get started",
    content: (
      <>
        <h1>Admin Guide</h1>
        <p className="docs-lead">
          Alpha Router is an organizational AI platform: a built-in web app for chat, media, and administration, plus an
          optional OpenAI-compatible <code>/v1</code> API for external tools. It connects teams to upstream LLM providers
          (OpenRouter, OpenAI, Anthropic, Google, and others) while enforcing budgets, roles, plans, and audit logging.
        </p>
        <p>
          This guide is for administrators and integrators. It reflects current product behaviour: grouped admin
          navigation with a dedicated <strong>User panel</strong> section, scoped RBAC with a single{" "}
          <strong>Super Admin</strong> role, LDAP directory sync, SAML/OIDC SSO, chat with attachments and tools, connection
          sync schedules, object storage for media, per-user budgets and deactivation, Usage &amp; Activity views,
          Operations and Database monitoring (for Super Admin), and optional gateway access via <code>/v1</code>. End-user
          help lives in the in-app <strong>User Manual</strong> (<code>/app/manual</code>). This guide does not contain
          secrets—configure keys only in your deployment.
        </p>
        <div className="docs-cards">
          <div className="docs-card">
            <h3>Built-in app</h3>
            <p>
              User panel (<code>/app</code>) and admin panel (<code>/admin</code>) — chat, media, recommendations, and
              full administration in one product.
            </p>
          </div>
          <div className="docs-card">
            <h3>Budget control</h3>
            <p>Monthly USD pools per user, enforced before traffic reaches providers.</p>
          </div>
          <div className="docs-card">
            <h3>Visibility</h3>
            <p>
              Dashboards, <a href="#admin-operations">Operations</a>, API logs, reports, and optional scheduled exports.
            </p>
          </div>
        </div>
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
          <li>Provider keys are shared or scattered, with no central policy.</li>
          <li>Spend is hard to attribute to people, teams, or departments.</li>
          <li>Model catalogs and pricing change often.</li>
          <li>Compliance needs a durable request history.</li>
        </ul>
        <p>Alpha Router addresses this by:</p>
        <ol>
          <li>Terminating client traffic at the organizational AI platform you operate.</li>
          <li>Syncing models and <strong>provider-native pricing</strong> from connections (no markup).</li>
          <li>
            Applying <strong>Super Admin</strong> (full platform access), <strong>API Key Admin</strong> (API Keys menu
            only), <strong>plans</strong>, <strong>monthly budgets</strong>, and optional{" "}
            <strong>deactivation</strong> (account read-only — users can still browse chat history but cannot send new
            messages).
          </li>
          <li>
            Supporting <strong>local, LDAP/Active Directory, SAML 2.0, and generic OIDC</strong> sign-in, with scheduled
            LDAP directory sync for users and groups.
          </li>
          <li>
            Offering in-app chat, per-user media libraries, Usage &amp; Activity analytics (CSV/PDF export), and
            scheduled cost reports.
          </li>
          <li>
            Exposing an optional OpenAI-compatible <code>/v1</code> API so external tools (IDE extensions, scripts,
            automation) can share the same models and budgets when administrators issue Alpha Router API keys.
          </li>
        </ol>
      </>
    ),
  },
  {
    id: "architecture",
    title: "Architecture",
    group: "Get started",
    content: (
      <>
        <h2>Architecture</h2>
        <p>
          Alpha Router is one FastAPI app plus a React SPA. External tools use the OpenAI-compatible <code>/v1</code> surface;
          the built-in chat UI uses separate <code>/api/*</code> routes with JWT session auth. Both paths share the same{" "}
          <code>stream_chat</code> pipeline (budget, model resolution, LiteLLM, logging).
        </p>
        <AdminArchitectureDiagram />
        <p className="docs-muted" style={{ fontSize: "0.84rem", marginTop: "-0.25rem" }}>
          Diagram uses simplified monochrome icons for each component. Arrows show the main request and data flow; provider
          API keys never leave the <strong>Connections</strong> table in PostgreSQL.
        </p>
        <h3>Request path — external clients (<code>/v1</code>)</h3>
        <ol>
          <li>
            Client calls <code>POST /v1/chat/completions</code> with <code>Authorization: Bearer &lt;Alpha Router key&gt;</code>{" "}
            and <code>stream: true</code> (non-streaming is rejected on this route).
          </li>
          <li>
            Alpha Router resolves the key (shared gateway key or per-user API key), provisions or maps the{" "}
            <code>user</code> field when needed, checks monthly budget, and loads an enabled model plus its{" "}
            <strong>Connection</strong> from the database.
          </li>
          <li>
            <code>stream_chat</code> invokes LiteLLM with the connection&apos;s provider credentials; tokens, USD cost, and
            latency are written to API logs (<code>source</code> e.g. gateway key, user key, alpha_router_chat).
          </li>
        </ol>
        <h3>Request path — Alpha Router Chat (<code>/api/chat</code>)</h3>
        <ol>
          <li>
            Browser sends the session JWT to <code>POST /api/chat/completions</code> (see <code>ChatPanel</code> in the
            frontend—not <code>/v1</code>). Optional <code>persist_chat: true</code> enables{" "}
            <strong>server-owned persistence</strong> during the SSE stream via <code>ChatCompletionPersister</code>.
          </li>
          <li>
            Optional <code>POST /api/chat/enhance-prompt</code> — the composer <strong>To ENG</strong> button calls a lightweight
            non-streaming model pass to <strong>translate</strong> the draft in the text box to English. Body fields:{" "}
            <code>model</code>, <code>prompt</code>, <code>mode</code> (
            <code>translate</code> from the UI; server also supports <code>improve</code> and{" "}
            <code>translate_improve</code> for API clients), and <code>context</code> (<code>image</code> |{" "}
            <code>chat</code>). Implemented in <code>image_prompt_service.py</code>; skips translation when the prompt is
            already English; falls back to the original text on error or when output diverges too much. Legacy alias:{" "}
            <code>POST /api/chat/enhance-image-prompt</code> (image context only). Counts toward user budget like other
            chat calls.
          </li>
          <li>
            <code>get_current_user</code> identifies the signed-in user; budget is checked the same way as for external
            keys.
          </li>
          <li>
            The same <code>stream_chat</code> helper runs with <code>source=alpha_router_chat</code>; optional tools (web search,
            attachments, image generation, composer translation via To ENG) are handled in this API layer before or alongside the LLM call.
          </li>
          <li>
            In parallel, the React client syncs session metadata and message appends through{" "}
            <code>/api/user/chats</code> and <code>/api/user/chat-sessions/…/messages</code> (append-only,{" "}
            <code>clientMessageId</code> dedupe, <code>revision</code> on sessions).
          </li>
        </ol>
        <h3>Chat data flow (web UI → database)</h3>
        <p>
          The built-in chat uses a <strong>hybrid local-first + server-authoritative</strong> model. The diagram below
          summarizes layers; a detailed HTML reference lives in the repository at{" "}
          <code>docs/chat-storage-diagram.html</code>.
        </p>
        <ol>
          <li>
            <strong>UI</strong> — <code>ChatPanel.tsx</code> holds in-memory sessions, a per-tab <strong>prompt
            queue</strong>, scroll pinning, and streaming state. <code>chatStorage.ts</code> debounces sync to the server;{" "}
            <code>composerDrafts.ts</code> keeps per-session composer text/attachments in tab memory (cleared on refresh).{" "}
            The composer bar includes a <strong>To ENG</strong> button (globe icon; translate draft to English via{" "}
            <code>enhance-prompt</code>) and a <strong>scroll-to-bottom</strong> control when the user scrolls up in a
            long thread. Code interpreter blocks render via <code>ChatCodeBlock.tsx</code> with Copy and Expand/Collapse
            toolbars at the top and bottom.
          </li>
          <li>
            <strong>Text turn</strong> — client appends user + assistant placeholder, then opens{" "}
            <code>POST /api/chat/completions</code>. The persister writes throttled partial content to{" "}
            <code>chat_messages</code> during SSE and sets <code>receivedAt</code> on finalize.
          </li>
          <li>
            <strong>Image turn</strong> — client syncs placeholders, calls <code>POST /api/images/generate</code> with an{" "}
            <code>aspect_ratio</code> (text-to-image) or source dimensions (image-to-image). The server finalizes the
            assistant row when the image is ready. With <strong>Private Mode</strong>, the client sends{" "}
            <code>persist: false</code> — the image is returned to the browser only and is not written to MinIO or{" "}
            <code>media_assets</code>.
          </li>
          <li>
            <strong>Multi-tab</strong> — <code>BroadcastChannel</code> + <code>since=</code> incremental refresh merge
            remote sessions. Leader election (<code>navigator.locks</code>) applies to <strong>folder</strong> sync only;
            any tab may append messages and patch session metadata.
          </li>
          <li>
            <strong>PostgreSQL</strong> — normalized <code>chat_sessions</code> + <code>chat_messages</code> (not JSON
            blobs). Message <code>meta</code> JSON holds <code>streaming</code>, <code>receivedAt</code>,{" "}
            <code>modelId</code>, and <code>cancelRequested</code> when relevant.
          </li>
        </ol>
        <h3>Data and caching</h3>
        <ul>
          <li>
            <strong>PostgreSQL</strong> via <code>DATABASE_URL</code>. In the default Docker stack the app connects through{" "}
            <strong>PgBouncer</strong> (transaction pooling) to the <code>postgres</code> service — see{" "}
            <a href="#deployment">Deployment &amp; database</a>.
          </li>
          <li>
            <strong>Chat history</strong> — normalized PostgreSQL tables:{" "}
            <code>chat_sessions</code> (includes <code>revision</code> for sync conflicts), <code>chat_messages</code>,{" "}
            <code>chat_folders</code>, and <code>user_chat_prefs</code>. No chat JSON blobs. Chat is <strong>not</strong>{" "}
            stored in Redis.
          </li>
          <li>
            <strong>Chat sync</strong> — append-only message writes (<code>POST …/messages</code> with{" "}
            <code>clientMessageId</code>), session metadata via <code>PATCH</code>, idempotent{" "}
            <code>POST …/sessions</code> (duplicate create returns existing row). Paginated reads: session list (
            <code>limit</code>/<code>offset</code>/<code>since</code>), messages (<code>limit</code>/<code>before</code>
            ). <code>POST …/cancel-stream</code> marks the in-flight assistant message for early finalize. Optional{" "}
            <code>DATABASE_READ_URL</code> routes chat GET traffic to a read replica when configured.
          </li>
          <li>
            <strong>Media</strong> — file bytes in <strong>MinIO/S3</strong> (<code>S3_*</code> env vars); metadata in{" "}
            <code>media_assets</code> (hash, path, prompt, retention). Object keys use{" "}
            <code>cdn/u/&lt;username&gt;/&lt;content_hash&gt;&lt;ext&gt;</code>. Identical content per user is deduplicated by
            SHA-256.
          </li>
          <li>
            <strong>MinIO</strong> — required object storage (Docker Compose <code>minio</code> service). Not exposed to
            end users; the app serves files through authenticated <code>/api/chat/media/…</code> routes.
          </li>
          <li>
            <strong>Redis</strong> is used for LiteLLM prompt caching when Redis is reachable; otherwise caching falls
            back to in-memory.
          </li>
          <li>
            Provider secrets never leave <strong>Connections</strong>; clients only ever see Alpha Router-issued keys or the web
            login session.
          </li>
        </ul>
        <Note>
          Upstream <strong>provider API keys</strong> live only in <strong>Connections</strong> (stored in the database).
          LiteLLM is called directly from the app after reading connection settings—not as a separate tier below the
          database. See <a href="#deployment">Deployment & database</a> for Docker and PostgreSQL.
        </Note>
      </>
    ),
  },
  {
    id: "deployment",
    title: "Deployment & database",
    group: "Get started",
    content: (
      <>
        <h2>Deployment & database</h2>
        <p>
          The Alpha Router Docker image contains only the application (FastAPI + built React UI). PostgreSQL, PgBouncer, and
          Redis are separate services—you do not install them on the host when using the provided{" "}
          <code>docker-compose.yml</code>. Copy <code>.env.example</code> to <code>.env</code>; Compose loads it via{" "}
          <code>env_file</code>.
        </p>
        <h3>Which database runs?</h3>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Environment</th>
              <th>Database</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <code>docker compose up</code> (production-style stack)
              </td>
              <td>
                <strong>PostgreSQL</strong> + <strong>PgBouncer</strong>
              </td>
              <td>
                <code>DATABASE_URL</code> points at <code>pgbouncer:6432</code>; PgBouncer pools to{" "}
                <code>postgres</code>. <code>minio</code> stores media blobs; Redis supplies optional LiteLLM prompt
                cache. Default stack targets ~5k concurrent users (see scale env vars below).
              </td>
            </tr>
            <tr>
              <td>Custom deploy (K8s, VM)</td>
              <td>Your choice</td>
              <td>
                Set <code>DATABASE_URL</code> to Postgres or PgBouncer. Redis is recommended but optional (in-memory
                cache fallback). Use <code>DATABASE_READ_URL</code> when you have a read replica.
              </td>
            </tr>
          </tbody>
        </table>
        <h3>Scale &amp; database tuning (.env)</h3>
        <p>
          The shipped <code>.env.example</code> profile assumes <strong>~5,000 concurrent signed-in users</strong>,{" "}
          <strong>~25,000 active chat sessions</strong> fleet-wide, and users with <strong>10+ browser tabs</strong>{" "}
          (incremental <code>since=</code> refresh + <code>BroadcastChannel</code>; leader tab writes folder changes
          only — message/session sync may run from any tab).
        </p>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Variable</th>
              <th>Default (Compose)</th>
              <th>Purpose</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><code>DATABASE_URL</code></td>
              <td><code>…@pgbouncer:6432/alpha-router</code></td>
              <td>Primary DB (through PgBouncer in Docker)</td>
            </tr>
            <tr>
              <td><code>DATABASE_READ_URL</code></td>
              <td><em>(optional)</em></td>
              <td>Read replica for chat GET routes (list, search, messages). Falls back to primary when unset.</td>
            </tr>
            <tr>
              <td><code>DB_POOL_SIZE</code></td>
              <td>12</td>
              <td>SQLAlchemy pool per uvicorn worker (keep moderate behind PgBouncer)</td>
            </tr>
            <tr>
              <td><code>DB_MAX_OVERFLOW</code></td>
              <td>20</td>
              <td>Extra connections per worker at peak (4 workers → up to ~128 client conns to PgBouncer)</td>
            </tr>
            <tr>
              <td><code>DB_POOL_TIMEOUT</code></td>
              <td>45</td>
              <td>Seconds to wait for a free pool connection before error</td>
            </tr>
            <tr>
              <td><code>UVICORN_WORKERS</code></td>
              <td>4</td>
              <td>Process count for the <code>alpha-router</code> container</td>
            </tr>
            <tr>
              <td><code>CHAT_EMPTY_SESSION_HIDE_DAYS</code></td>
              <td>30</td>
              <td>Hide empty sessions older than N days from the default session list</td>
            </tr>
            <tr>
              <td><code>CHAT_LIST_RATE_LIMIT_PER_MIN</code></td>
              <td>200</td>
              <td>Per-user limit for session list / <code>since=</code> refresh (shared across tabs)</td>
            </tr>
            <tr>
              <td><code>CHAT_SEARCH_RATE_LIMIT_PER_MIN</code></td>
              <td>45</td>
              <td>Per-user title search limit</td>
            </tr>
            <tr>
              <td><code>CHAT_MESSAGE_SEARCH_RATE_LIMIT_PER_MIN</code></td>
              <td>45</td>
              <td>Per-user full-text message search limit</td>
            </tr>
          </tbody>
        </table>
        <Note>
          PgBouncer in Compose uses transaction pooling (<code>MAX_CLIENT_CONN=4000</code>,{" "}
          <code>DEFAULT_POOL_SIZE=90</code> to Postgres). Postgres is tuned with <code>max_connections=200</code>. Adjust
          workers and pool sizes together—do not raise per-worker pools without PgBouncer or you may exhaust Postgres
          connections.
        </Note>
        <h3>Environment variables (production)</h3>
        <p>
          Compose wires Postgres, MinIO, and Redis automatically. Before exposing Alpha Router to real users, change at least:
        </p>
        <ul>
          <li>
            <code>SECRET_KEY</code> — JWT signing
          </li>
          <li>
            <code>ADMIN_PASSWORD</code>, <code>SERVICE_ADMIN_PASSWORD</code>
          </li>
          <li>
            <code>GATEWAY_MASTER_KEY</code> — shared <code>/v1</code> clients
          </li>
          <li>
            <code>API_PUBLIC_URL</code> and <code>FRONTEND_URL</code> — public HTTPS URLs (shown in API key modals)
          </li>
          <li>
            <code>S3_ACCESS_KEY</code>, <code>S3_SECRET_KEY</code>, <code>MINIO_ROOT_PASSWORD</code> — object storage
            credentials (defaults are for local dev only)
          </li>
        </ul>
        <p>
          Provider keys and business policy are configured in the admin UI after login (<strong>Connections</strong>,{" "}
          <strong>Models</strong>, <strong>Plans</strong>)—not via these env vars.
        </p>
        <h3>Monitoring</h3>
        <p>
          After deploy, use the <strong>Monitoring</strong> sidebar group (see <a href="#admin-monitoring">Monitoring</a>):
        </p>
        <ul>
          <li>
            <a href="#admin-operations">Operations</a> — hourly infra snapshots, 24h API traffic charts, and model
            experience (slow requests, P95, slowest models).
          </li>
          <li>
            <a href="#admin-database">Database</a> — read-only health: connection, engine, size, ping, host/process CPU
            and RAM, row counts per Alpha Router table. No SQL editor or schema changes.
          </li>
        </ul>
        <Note>
          Backups and managed Postgres consoles (RDS, etc.) remain outside Alpha Router. Use your infrastructure tooling for
          backup/restore; use the in-app pages for day-to-day visibility.
        </Note>
      </>
    ),
  },
  {
    id: "quickstart",
    title: "Quickstart",
    group: "Get started",
    content: (
      <>
        <h2>Quickstart (administrator)</h2>
        <ol className="docs-steps">
          <li>
            <strong>Deploy Alpha Router</strong> with HTTPS in production. Copy <code>.env.example</code> to <code>.env</code> and
            set <code>API_PUBLIC_URL</code> to the URL clients will use (shown when you create API keys). Review database
            pool and worker settings for your expected concurrent load (see{" "}
            <a href="#deployment">Deployment &amp; database</a>).
          </li>
          <li>
            <strong>Sign in as Super Admin</strong> — the default local account (<code>admin</code>) receives the{" "}
            <strong>Super Admin</strong> role automatically (full read/write on every admin menu). SSO users need roles
            assigned in <strong>Users</strong> after directory sync.
          </li>
          <li>
            <strong>Connections</strong> — Add each provider account and API key. Use <em>Sync Now</em> to import models
            (see <a href="#admin-connections">Connections</a>).
          </li>
          <li>
            <strong>Models</strong> — Enable only models you want exposed. Use search and bulk <em>ON/OFF</em> for large
            catalogs.
          </li>
          <li>
            <strong>Plans & Users</strong> — Assign monthly budgets. The Users table shows <strong>Budget</strong> as{" "}
            <code>used/total $</code>.
          </li>
          <li>
            <strong>API Keys</strong> — Create a gateway key for external integrations, or per-user keys from Users.
          </li>
          <li>
            <strong>Integrate clients</strong> — Base URL <code>https://&lt;your-host&gt;/v1</code> + Alpha Router key (not the
            provider key). See <a href="#platform-api">Platform API</a> and <a href="#kilo-code">Kilo Code</a>.
          </li>
          <li>
            <strong>Storage Management</strong> (Super Admin) — Platform media usage, global per-user storage quota, and{" "}
            <strong>DELETE ALL MEDIA</strong>. See <a href="#admin-storage-management">Storage Management</a>.
          </li>
          <li>
            <strong>Retention Policy</strong> (Super Admin) — Media and chat retention days, scheduled cleanup, overview
            stats, and manual purge. See <a href="#admin-storage">Retention Policy</a>.
          </li>
          <li>
            <strong>Monitoring</strong> — Open <a href="#admin-operations">Operations</a> and click <em>Check Now</em> for
            an infra snapshot; use <a href="#admin-database">Database</a> to confirm Postgres connectivity and table
            growth.
          </li>
        </ol>
        <Warn>Rotate and revoke keys if they are copied into tickets, chat, or public repos.</Warn>
      </>
    ),
  },
  {
    id: "sign-in",
    title: "Sign in",
    group: "Get started",
    content: (
      <>
        <h2>Sign in</h2>
        <p>
          The login page summarizes what Alpha Router offers today — not only an API gateway, but a full organizational AI
          platform with six feature highlights:
        </p>
        <ul>
          <li>
            <strong>Many models, one platform</strong> — unified provider connections, sync, and model catalog.
          </li>
          <li>
            <strong>Chat &amp; media built in</strong> — team chat, image generation, folders, and a shared media library.
          </li>
          <li>
            <strong>Full admin control plane</strong> — users, groups, roles, plans, connections, retention policy,
            reports, and operations in <code>/admin</code>.
          </li>
          <li>
            <strong>Budgets &amp; visibility</strong> — plan-based limits, dashboards, and API logs.
          </li>
          <li>
            <strong>Enterprise access</strong> — LDAP, SAML/OIDC SSO, local accounts, and scoped RBAC with Super Admin.
          </li>
          <li>
            <strong>Optional /v1 API</strong> — OpenAI-compatible gateway for external tools when you need it.
          </li>
        </ul>
        <h3>After sign-in</h3>
        <ul>
          <li>
            <strong>End users</strong> (role <strong>User</strong> only) land on <code>/app/chat</code>.
          </li>
          <li>
            <strong>Administrators</strong> are redirected to their <strong>first allowed admin menu</strong> — for
            example <code>/admin/api-keys</code> for <strong>API Key Admin</strong>, or the Dashboard for Super Admin.
            They do not need Dashboard access to use the admin panel.
          </li>
          <li>
            Every admin account also sees the <strong>User panel</strong> group at the top of the admin sidebar (links
            to <code>/app/chat</code>, Media, Recommendations, and so on).
          </li>
        </ul>
        <Note>
          Local, LDAP, SAML, and OIDC sign-in methods appear based on <strong>Authentication</strong> configuration. LDAP
          users sign in with directory credentials; SAML/OIDC use the SSO links when enabled.
        </Note>
      </>
    ),
  },
  {
    id: "admin-menu",
    title: "Admin menu",
    group: "Admin panel",
    content: (
      <>
        <h2>Admin menu (grouped sidebar)</h2>
        <p>
          The left sidebar is grouped so related tasks sit together. The top group — <strong>User panel</strong> — links
          to the end-user app (<code>/app</code>) and is always visible to every administrator, regardless of scoped
          roles. Configuration lives in the middle groups; health and traffic live under <strong>Monitoring</strong>.
          Only menus your roles grant appear below User panel; Super Admin sees every group.{" "}
          <strong>API Key Admin</strong> sees API Keys under Models &amp; API.
        </p>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Group</th>
              <th>Items</th>
              <th>Assignable roles</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>User panel</strong></td>
              <td>Chat, Media, Recommendations, My Usage &amp; Activity, User Manual (<code>/app/*</code>)</td>
              <td>Always shown (not RBAC-gated)</td>
            </tr>
            <tr>
              <td><strong>Overview</strong></td>
              <td>Dashboard, Chat, Media, My Usage &amp; Activity, Recommendations</td>
              <td>Super Admin only</td>
            </tr>
            <tr>
              <td><strong>Models &amp; API</strong></td>
              <td>Connections, Models, API Keys</td>
              <td>API Keys: <strong>API Key Admin</strong>; Connections &amp; Models: Super Admin only</td>
            </tr>
            <tr>
              <td><strong>People &amp; access</strong></td>
              <td>Roles, Users, Deleted Users, Groups, Plans, Authentication</td>
              <td>Super Admin only</td>
            </tr>
            <tr>
              <td><strong>Integrations</strong></td>
              <td>SMTP Server</td>
              <td>Super Admin only</td>
            </tr>
            <tr>
              <td><strong>Data &amp; reports</strong></td>
              <td>Storage Management, Retention Policy, Reports, API Logs</td>
              <td>Super Admin only</td>
            </tr>
            <tr>
              <td><strong>Monitoring</strong></td>
              <td>Operations (incl. model experience), Database (read-only monitor)</td>
              <td>Super Admin only</td>
            </tr>
            <tr>
              <td><strong>Developer</strong></td>
              <td>Admin Guide, User Manual</td>
              <td>Super Admin only</td>
            </tr>
          </tbody>
        </table>
        <p>
          <strong>Dashboard</strong> vs <strong>Monitoring</strong>: Dashboard summarizes spend, top models/users, and
          heatmaps for business review. Monitoring focuses on runtime health (CPU, DB ping, errors, latency, slow models)
          and links into <a href="#admin-logs">API Logs</a> for single-request detail.
        </p>
        <p>
          If you open a URL outside your allowed menus, Alpha Router redirects you to your <strong>first allowed admin path</strong>{" "}
          (for example <code>/admin/api-keys</code> for API Key Admin), not to the user chat page.
        </p>
      </>
    ),
  },
  {
    id: "admin-dashboard",
    title: "Dashboard",
    group: "Admin panel",
    content: (
      <>
        <h2>Dashboard</h2>
        <p>
          The admin home is the service-wide <strong>Usage &amp; Activity</strong> view: spend, tokens, requests,
          heatmaps, top models, guardrails, and exports. Use the period selector and timezone (local / UTC). Pair
          trends here with <strong>API Logs</strong> for per-request investigation and{" "}
          <a href="#admin-operations">Operations</a> for latency and infra context.
        </p>
      </>
    ),
  },
  {
    id: "admin-chat",
    title: "Chat",
    group: "Admin panel",
    content: (
      <>
        <h2>Chat</h2>
        <p>
          Full-screen chat for testing enabled models. The left column is the <strong>chat sidebar</strong> (full height);
          profile and theme controls sit above the message area only.
        </p>
        <h3>Sidebar tabs</h3>
        <ul>
          <li>
            <strong>Chats</strong> — Virtualized history list (loads more as you scroll), hybrid search (local filter +
            server title search after 2+ characters), folders (create, rename, delete). Deleting a folder can keep chats
            or remove them.
          </li>
          <li>
            <strong>Media</strong> — Files from attachments and generated images. Re-uploading the same file reuses
            storage (hash dedup) and bumps the item to the top of the list.
          </li>
        </ul>
        <h3>Composer</h3>
        <ul>
          <li>
            <strong>Model picker</strong> — Choose among enabled models. The <strong>checkmark</strong> control sets the
            user&apos;s default model for new chats; it is persisted in <code>user_chat_prefs.default_model</code> (and
            cached in browser localStorage) so it survives refresh.
          </li>
          <li>
            <strong>Tools</strong> — Web search, web fetch, image generation (with aspect-ratio presets), code
            interpreter (only when enabled in Chat Tools). New chats start with all tools off. Session tool state is
            persisted per chat. <strong>Chat Memory</strong> is not a product feature (removed). The composer bar also has{" "}
            <strong>To ENG</strong> (globe icon; translate; not a Tools toggle).
          </li>
          <li>
            <strong>Composer drafts</strong> — <code>composerDrafts.ts</code> stores draft text and pending attachments
            per session while switching chats in the same tab; lost on full page reload.
          </li>
          <li>
            <strong>Scroll to bottom</strong> — when the message list is scrolled away from the bottom, a floating
            down-arrow above the composer jumps back to the latest messages (<code>chatScroll.ts</code> pin threshold).
          </li>
          <li>
            <strong>Attachments</strong> — PDF and documents: text is extracted server-side; images use vision when the
            model supports it.
          </li>
          <li>
            <strong>Voice</strong> — Record audio; transcript is sent as the message.
          </li>
          <li>
            <strong>Prompt queue</strong> — while the assistant is still generating (text stream or background image),
            new prompts are queued above the composer (numbered list). Queued items appear immediately in the UI. When the
            current turn finishes, queued prompts are sent <strong>one after another</strong> automatically. Edit (✎)
            moves a queued item back into the composer; × removes it.
          </li>
          <li>
            <strong>Stop (■)</strong> — aborts the active stream in this tab. Queued prompts still run afterward unless
            you remove them from the queue.
          </li>
          <li>
            <strong>Code blocks</strong> — Python and interpreter output use <code>ChatCodeBlock.tsx</code> with Copy and
            Expand/Collapse actions on toolbars at the <strong>top and bottom</strong> of each block.
          </li>
        </ul>
        <p>
          Your message appears immediately when you send; the assistant streams in place. Switching chats does not mix
          streams from another session. Sending a follow-up in the same thread scrolls the view to the latest messages
          after your prompt is painted. If you refresh the page mid-stream, live token display stops (normal web
          behaviour); the server may continue persisting the reply — reopening the chat polls until the assistant row is
          finalized.
        </p>
        <h3>Chat persistence (same as end users)</h3>
        <ul>
          <li>
            Non-private chats sync to PostgreSQL: the sidebar loads the session list in pages (metadata only); opening a
            chat loads the <strong>latest ~50 messages</strong>; scroll up in the thread for older messages.
          </li>
          <li>
            New messages are appended incrementally (<code>POST</code> with idempotency keys), not as full-thread
            rewrites. Each session has a <code>revision</code>; conflicting writes from multiple tabs return{" "}
            <strong>409</strong> and the client merges.
          </li>
          <li>
            <strong>Multiple browser tabs</strong> — tabs stay in sync via in-browser broadcast and lightweight{" "}
            <code>since=</code> refresh. Any tab may create sessions, append messages, and update titles; only the{" "}
            <strong>leader tab</strong> syncs folder tree changes to the server. The <strong>prompt queue</strong> is
            per-tab (not shared across tabs).
          </li>
          <li>
            <strong>Private Mode</strong> — keeps the current chat on the client only; it is never written to PostgreSQL
            or server media storage. Chat metadata lives in browser <strong>localStorage</strong> (
            <code>alpha_router_private_chats:&lt;username&gt;</code>); image blobs and private image attachments live in{" "}
            <strong>IndexedDB</strong> (<code>alpha_router_private_media</code>). Image generation (text-to-image and
            image-to-image) works locally with <code>persist: false</code>. Turning Private Mode off triggers client-side
            migration that uploads local media to the server when possible.
          </li>
          <li>
            Global chat retention (message age limits and scheduled purge) is configured under{" "}
            <a href="#admin-storage">Retention Policy</a> (Super Admin only). Platform media usage, quotas, and{" "}
            <strong>DELETE ALL MEDIA</strong> live under{" "}
            <a href="#admin-storage-management">Storage Management</a>.
          </li>
        </ul>
        <p>
          Each message has an <strong>info</strong> icon: hover to see when a user prompt was sent and when the assistant
          response was received (when timestamps are recorded).
        </p>
        <Note>
          Profile menu includes <strong>My Usage &amp; Activity</strong> (your usage only) and live{" "}
          <strong>Budget</strong> <code>used/total $</code>.
        </Note>
      </>
    ),
  },
  {
    id: "admin-media",
    title: "Media",
    group: "Admin panel",
    content: (
      <>
        <h2>Media</h2>
        <p>
          Standalone view of <strong>your</strong> admin account media library—the same component users see at{" "}
          <code>/app/media</code>, useful for testing uploads and retention. Files are stored in MinIO/S3 with metadata in{" "}
          <code>media_assets</code>. To manage another user&apos;s files, open{" "}
          <strong>Users → row menu → Media</strong> (<code>/admin/users/:id/media</code>).
        </p>
        <p>
          See also <a href="#admin-storage-management">Storage Management</a> for quotas and platform media usage,{" "}
          <a href="#admin-storage">Retention Policy</a> for global retention settings, and{" "}
          <a href="#admin-chat">Chat</a> for
          how files enter the library from attachments and image generation.
        </p>
      </>
    ),
  },
  {
    id: "admin-authentication",
    title: "Authentication",
    group: "Admin panel",
    content: (
      <>
        <h2>Authentication</h2>
        <p>Controls sign-in to the Alpha Router web UI (not gateway API keys):</p>
        <ul>
          <li>
            <strong>Local</strong> — Accounts created under Users.
          </li>
          <li>
            <strong>LDAP / Active Directory</strong> — Direct <strong>LDAPS on port 636</strong> only (no plaintext LDAP,
            no Windows bridge). Enter the domain controller host and a service account, optionally enable{" "}
            <em>Support Untrusted Certificate</em> for self-signed DC certs, then <em>Test</em> and <em>Save</em>.{" "}
            <em>Sync AD</em> imports users and groups; optional <strong>Sync OUs</strong> limits both user and group
            search to those OUs; optional <strong>sync schedule</strong> (daily time) runs automatically. Prune only
            removes out-of-scope directory objects from Alpha Router after sync. Users sync with{" "}
            <strong>sAMAccountName</strong> as username; display name is stored separately.
          </li>
          <li>
            <strong>SAML 2.0</strong> — Alpha Router acts as a SAML Service Provider. Configure IdP metadata (URL or XML),
            register the fixed ACS URL and SP metadata with your Identity Provider, then use <em>Sign in with SAML</em>.
            Users are created or updated on first successful SSO login (no directory sync).
          </li>
          <li>
            <strong>OIDC</strong> — Generic OpenID Connect (Authorization Code + PKCE). Configure Issuer, Client ID, and
            Client Secret, register the fixed redirect URI on your IdP, then use <em>Sign in with OIDC</em>. JIT
            provisioning only (no directory sync).
          </li>
        </ul>
        <h3>SAML Service Provider</h3>
        <p>
          On the Authentication → SAML tab: enable SAML, provide an IdP metadata URL and/or upload an IdP metadata XML
          file (URL wins if both are set), set the SP Entity ID, and adjust attribute mapping if needed. ACS is fixed at{" "}
          <code>/api/auth/saml/acs</code>. When SAML is enabled,
          SP metadata is available at <code>/api/auth/saml/metadata</code> for your IdP (standard unauthenticated
          SAML practice); when disabled the URL returns 404. Require signed assertions in production.{" "}
          <code>API_PUBLIC_URL</code> must be reachable by the IdP (HTTPS in production).
        </p>
        <h3>OIDC (OpenID Connect)</h3>
        <p>
          On the Authentication → OIDC tab: enable OIDC, set the Issuer URL (discovery at{" "}
          <code>{"{issuer}/.well-known/openid-configuration"}</code>), Client ID, and Client Secret (encrypted at rest;
          admin GET shows <code>********</code>). Redirect URI is server-pinned to{" "}
          <code>/api/auth/oidc/callback</code> and cannot be changed in the UI — register that exact URI on the IdP.
          Login uses Authorization Code + mandatory PKCE S256, signed state/nonce cookies, and JWKS validation of the ID
          token (<code>RS256</code>/<code>ES256</code> only). Session delivery uses a one-time exchange code (JWT never
          appears in the redirect URL). In production the Issuer and non-loopback <code>API_PUBLIC_URL</code> must be
          HTTPS. Default JIT role is <code>user</code>; usernames already bound to another provider are rejected (no
          takeover).
        </p>
        <h3>LDAPS certificate on the domain controller</h3>
        <p>
          Alpha Router connects with LDAPS only. On the DC, create a certificate for the server FQDN, then trust it locally so
          Active Directory can present it on port 636. The Alpha Router container must reach the DC on TCP{" "}
          <strong>636</strong>.
        </p>
        <ol>
          <li>
            Open an elevated PowerShell on the domain controller and run, for example:
            <pre>
              New-SelfSignedCertificate -DnsName dc01.alpha-router.local -CertStoreLocation cert:\localmachine\my
            </pre>
            Replace <code>dc01.alpha-router.local</code> with your domain controller FQDN.
          </li>
          <li>
            The certificate is created under <strong>Local Computer → Personal</strong> (
            <code>Cert:\\LocalMachine\\My</code>).
          </li>
          <li>
            Copy that certificate to <strong>Local Computer → Trusted Root Certification Authorities</strong> (
            <code>Cert:\\LocalMachine\\Root</code>).
          </li>
          <li>Confirm LDAPS with ldp.exe (or equivalent) on port 636, then use <em>Test</em> in Alpha Router.</li>
        </ol>
      </>
    ),
  },
  {
    id: "admin-smtp",
    title: "SMTP Server",
    group: "Integrations",
    content: (
      <>
        <h2>SMTP Server</h2>
        <p>
          Outbound mail for scheduled reports and notifications. Configure host, port, TLS, and sender. Use{" "}
          <em>Test</em> before enabling schedules in Reports.
        </p>
      </>
    ),
  },
  {
    id: "admin-connections",
    title: "Connections",
    group: "Models & API",
    content: (
      <>
        <h2>Connections</h2>
        <p>Each connection is one upstream provider account (OpenRouter, OpenAI, Anthropic, Google, …).</p>
        <ol>
          <li>
            <strong>Add Connection</strong> — Name, provider type, API key, optional base URL.
          </li>
          <li>
            <strong>Sync schedule</strong> — Hours between automatic syncs (<code>sync_interval_hours</code>). A
            background job checks every 30 minutes and syncs connections that are due.
          </li>
          <li>
            <strong>Sync Now</strong> — Immediate sync for one connection.
          </li>
          <li>
            <strong>Models page flash</strong> — Both manual <em>Sync Now</em> and scheduled sync briefly disable all
            catalog models, refresh from the provider, then re-enable them so the Models list stays consistent (you may
            see a quick off/on flash on the Models page if it is open).
          </li>
        </ol>
        <p>
          The table shows provider, logged <strong>Usage (USD)</strong>, <strong>Last sync</strong>, and schedule label
          (e.g. every 6h).
        </p>
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
          Models appear after a connection sync. Only <strong>enabled</strong> models are returned by{" "}
          <code>GET /v1/models</code> and appear in chat and external clients.
        </p>
        <ul>
          <li>
            <strong>Search</strong> — Filters the table as you type.
          </li>
          <li>
            <strong>ON/OFF</strong> column — Toggle one model, or select many rows and use <strong>Bulk Edit</strong> →
            ON, OFF, or Delete.
          </li>
          <li>
            <strong>Pricing</strong> — Input/output per 1K tokens from the provider at sync time; used for cost
            attribution in logs and budgets.
          </li>
        </ul>
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
          Admin <strong>API Keys</strong> lists gateway keys only (product/service integrations). Per-user keys are not
          shown here—create them from <strong>Users</strong> or the user panel.
        </p>
        <h3>Create / edit (popup)</h3>
        <ul>
          <li>
            <strong>Owner</strong> — searchable user from the Users directory (organizational owner)
          </li>
          <li>
            <strong>Name</strong> — label for the key (any characters)
          </li>
          <li>
            <strong>Credit limit</strong> — USD cap per reset period (0 = unlimited)
          </li>
          <li>
            <strong>Reset limit every</strong> — Daily, Weekly, or Monthly (resets period usage only)
          </li>
          <li>
            <strong>Expiration</strong> — active for N days, or Never
          </li>
        </ul>
        <p>
          Table columns: <strong>Name</strong>, <strong>Expire</strong>, <strong>Last used</strong>,{" "}
          <strong>Usage</strong> (lifetime USD, never reset), <strong>Limit</strong> (period cap). Row menu: Edit,
          Activity, Disable, Delete. Disabled keys appear faded.
        </p>
        <p>
          After create, copy the secret and <code>API_PUBLIC_URL/v1</code> immediately—they are shown once.
        </p>
        <Note>
          Gateway keys are <em>not</em> provider keys. Never paste OpenRouter/OpenAI keys into clients when Alpha Router is your
          platform.
        </Note>
      </>
    ),
  },
  {
    id: "admin-roles",
    title: "Roles (RBAC)",
    group: "People & access",
    content: (
      <>
        <h2>Roles (RBAC)</h2>
        <p>
          Alpha Router uses role-based access control (RBAC) for the admin panel. Open <strong>People &amp; access → Roles</strong>{" "}
          (<code>/admin/roles</code>) — visible only to <strong>Super Admin</strong> — to review every built-in role in a
          flat table with columns <strong>Name</strong>, <strong>Description</strong>, and <strong>Category</strong>.
          Use the search box to filter by name, description, or category.
        </p>
        <h3>Roles page workflow</h3>
        <ol>
          <li>
            Each row has a <strong>checkbox</strong>. The header checkbox selects or clears all roles currently visible
            after search.
          </li>
          <li>
            When one or more roles are selected, <strong>Assign Roles</strong> appears in the page header.
          </li>
          <li>
            In the modal, choose <strong>one role</strong> from your selection, then tick one or more users and confirm.
            This bulk action <strong>sets that single role</strong> on each chosen user (replacing their previous role
            list). To give a user <strong>multiple roles at once</strong>, use the Users table instead (see below).
          </li>
        </ol>
        <p>
          <strong>Super Admin</strong> uses category <strong>All sections</strong> (not a sidebar group name).{" "}
          <strong>API Key Admin</strong> is listed under <strong>Models &amp; API</strong>.
        </p>
        <h3>Assignable roles</h3>
        <ul>
          <li>
            <strong>Super Admin</strong> — Full read/write on every admin menu and the entire platform. Legacy{" "}
            <code>admin</code> / <strong>Full Administrator</strong> accounts migrate to this role on startup.
          </li>
          <li>
            <strong>API Key Admin</strong> — Full read/write on the API Keys admin menu only (
            <code>/admin/api-keys</code>). Does not grant Users, Roles, Connections, or other admin pages.
          </li>
          <li>
            <strong>User</strong> — Standard end-user panel only: Chat, Media, Recommendations, My Usage &amp; Activity,
            User Manual (<code>/app</code>). No admin sidebar.
          </li>
        </ul>
        <Note>
          Former per-menu roles (Users Full Administrator, Groups Full Administrator, API Keys Read Only, and so on) were
          removed from the catalog. Existing assignments for those retired roles are cleared on migration; former platform
          Full / Read Only Full admins remap to <strong>Super Admin</strong>. Keep or re-assign{" "}
          <strong>API Key Admin</strong> only where API Keys management is needed.
        </Note>
        <h3>Everything else is Super Admin only</h3>
        <p>
          Connections, Models, Users, Groups, Plans, Authentication, SMTP, Reports, API Logs, Operations, Dashboard,
          Database, Storage, Roles, Deleted Users, and Developer docs have <strong>no</strong> dedicated assignable role.
          Only <strong>Super Admin</strong> can open them.
        </p>
        <h3>User panel</h3>
        <p>
          Every administrator still sees the <strong>User panel</strong> group (Chat, Media, Recommendations on{" "}
          <code>/app</code>). Those paths are not gated by admin menu roles. Only deactivated accounts lose write access
          there — see <a href="#user-panel">User panel</a> and the User Manual.
        </p>
        <h3>Assigning roles</h3>
        <p>A user can hold more than one role. Assign roles in two places:</p>
        <ul>
          <li>
            <strong>Roles → Assign Roles</strong> — Super Admin only. Bulk-apply <strong>one</strong> role to many users
            (replaces each user&apos;s role list with that role).
          </li>
          <li>
            <strong>Users → Role column</strong> — Open the role dropdown, tick <strong>checkboxes</strong> for every
            role the user should keep (for example <strong>User</strong> plus <strong>API Key Admin</strong>), then click{" "}
            <strong>Apply</strong>. Only Super Admin may grant or revoke Super Admin.
          </li>
        </ul>
        <p>
          The sidebar and API enforce the same boundaries. On menus where the user cannot write, a banner appears and
          create/edit/delete controls are grayed out.
        </p>
        <Warn>
          Keep at least one active <strong>Super Admin</strong>. Alpha Router prevents demoting, disabling, or deleting the last
          account with full platform access.
        </Warn>
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
          Define monthly USD budgets and optional model allow-lists. Assign plans on the Users table (
          <strong>Assign Budget</strong>) or via Groups. Users without an assignment use the default plan.
        </p>
        <p>Budget resets on the first day of each calendar month.</p>
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
          Search and filter users by username, email, department, job title, or group. Open{" "}
          <code>/admin/users?group_id=&lt;id&gt;</code> from <strong>Groups → Show members</strong> to see one group&apos;s
          members.
        </p>
        <ul>
          <li>
            <strong>Role</strong> — Multi-select dropdown with a checkbox beside each built-in role (see{" "}
            <a href="#admin-roles">Roles</a>). Choose one or more roles and click <strong>Apply</strong>; permissions
            combine across all selected roles using the lowest access rule per menu (see{" "}
            <a href="#admin-roles">Roles</a>). Legacy <code>admin</code> accounts were migrated to{" "}
            <strong>Super Admin</strong>. After role changes, users may need to sign out and back in; scoped admins land
            on their first allowed admin menu after login.
          </li>
          <li>
            <strong>Budget</strong> column — <code>used/total $</code> for the current month.
          </li>
          <li>
            <strong>Activate / Deactivate</strong> — Deactivated users sign in in <strong>read-only</strong> mode: they
            can browse chat history and media but cannot send new messages or write data.
          </li>
          <li>
            <strong>Bulk Edit</strong> — Select rows; update plan, department, or office in one step.
          </li>
          <li>
            <strong>Get API Key</strong> — Issue a user-scoped key for external clients.
          </li>
          <li>
            <strong>Usage &amp; Activity</strong> — Per-user analytics and export (row menu).
          </li>
          <li>
            <strong>Media</strong> — Admin view of a user&apos;s media library (row menu).
          </li>
          <li>
            <strong>Budget reset</strong> — Admin override to zero consumed budget this month.
          </li>
        </ul>
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
          Sync LDAP groups, attach plans at group level, and keep membership aligned with your directory.
        </p>
        <ul>
          <li>
            <strong>Show members</strong> — Opens Users filtered to that group.
          </li>
          <li>
            <strong>Deactive all members</strong> — Deactivates every user in the group (read-only mode; reversible per
            user).
          </li>
          <li>
            <strong>Usage &amp; Activity</strong> — Combined analytics for all members.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "admin-recommendations",
    title: "Recommendations",
    group: "Admin panel",
    content: (
      <>
        <h2>Recommendations</h2>
        <p>
          The admin <strong>Recommendations</strong> page (<code>/admin/recommendations</code>) mirrors the user panel view:
          model suggestions based on your usage profile, quality fit scores, and estimated value. Super Admin only — there
          is no per-menu Recommendations administrator role. End users open the same experience at{" "}
          <code>/app/recommendations</code>.
        </p>
      </>
    ),
  },
  {
    id: "admin-storage-management",
    title: "Storage Management",
    group: "Data & reports",
    content: (
      <>
        <h2>Storage Management</h2>
        <p>
          Admin menu <strong>Storage Management</strong> (<code>/admin/storage-management</code>; legacy{" "}
          <code>/admin/storage</code> redirects here) shows platform-wide media usage, sets the global per-user storage
          quota, and provides destructive maintenance actions. Super Admin only — there are no per-menu Storage
          administrator roles.
        </p>
        <h3>Media &amp; files — usage</h3>
        <ul>
          <li>
            <strong>Overview</strong> — total file count, total size, breakdown by type, and how many files are past the
            media retention window (same counts inform the overview on <a href="#admin-storage">Retention Policy</a>).
          </li>
          <li>
            <strong>Refresh</strong> — reload usage stats from the database and object storage metadata.
          </li>
        </ul>
        <h3>Per-user storage quota</h3>
        <p>
          Set how much media storage each user may consume (1–100 GB). The default is 1 GB until changed. Users see their
          quota and usage on the <strong>Media</strong> page in the user panel; uploads and generated images count toward
          the limit.
        </p>
        <h3>Maintenance — DELETE ALL MEDIA</h3>
        <ul>
          <li>
            Permanently deletes <strong>all</strong> media blobs for <strong>all users</strong> from object storage and
            clears <code>media_assets</code> metadata.
          </li>
          <li>
            Does <strong>not</strong> delete chat message text in PostgreSQL, but image and attachment links inside old
            chats may break until users re-upload files.
          </li>
          <li>
            Requires <strong>three sequential confirmation dialogs</strong> (step 1 of 3 → step 2 of 3 → final
            confirmation) before anything is removed. The button sits next to <strong>Refresh</strong> on this page.
          </li>
        </ul>
        <Warn>
          Use DELETE ALL MEDIA only for emergencies or test resets. For routine cleanup, configure retention on{" "}
          <a href="#admin-storage">Retention Policy</a> and run <strong>Purge expired media now</strong> when needed.
        </Warn>
        <Note>
          Object storage configuration (<code>S3_*</code> env vars) is shared with chat media uploads. See{" "}
          <a href="#admin-storage">Retention Policy</a> for architecture notes on MinIO/S3 keys and{" "}
          <code>media_assets</code>.
        </Note>
      </>
    ),
  },
  {
    id: "admin-storage",
    title: "Retention Policy",
    group: "Data & reports",
    content: (
      <>
        <h2>Retention Policy</h2>
        <p>
          Admin menu <strong>Retention Policy</strong> (<code>/admin/retention-policy</code>) configures how long{" "}
          <strong>media files</strong> and <strong>chat messages</strong> are kept, plus overview stats and manual purge
          actions. Super Admin only. Platform usage, quotas, and <strong>DELETE ALL MEDIA</strong> are on{" "}
          <a href="#admin-storage-management">Storage Management</a>.
        </p>
        <p>
          At the top of the page, a note shows the <strong>server timezone</strong> (from the <code>TZ</code> environment
          variable when set, otherwise the host OS zone). Scheduled cleanup hour and minute fields on this page use that
          zone — for example set <code>TZ=America/New_York</code> in Docker Compose so daily jobs run in Eastern Time.
        </p>
        <h3>Chat storage (architecture)</h3>
        <ul>
          <li>
            Tables <code>chat_sessions</code> (with <code>revision</code>, <code>message_count</code>,{" "}
            <code>last_message_at</code>), <code>chat_messages</code>, <code>chat_folders</code>, and{" "}
            <code>user_chat_prefs</code> — normalized rows in PostgreSQL (per-user <code>default_model</code>,{" "}
            <code>theme</code>).
          </li>
          <li>
            <strong>Reads</strong> — paginated <code>GET /api/user/chats</code> (optional <code>q</code>,{" "}
            <code>since</code>, <code>offset</code>), <code>GET …/messages</code> (tail + <code>before</code> cursor),{" "}
            <code>GET /api/user/chats/search-messages</code> for message-body search. Routed to{" "}
            <code>DATABASE_READ_URL</code> when set.
          </li>
          <li>
            <strong>Writes</strong> — <code>POST …/sessions</code> (idempotent create), <code>POST …/messages</code>{" "}
            append (primary), <code>PATCH</code> session metadata (title, model, tools, <code>private_mode</code>),{" "}
            throttled <code>PATCH …/messages/last</code> during streaming (also used by{" "}
            <code>ChatCompletionPersister</code>), <code>POST …/cancel-stream</code> for client stop after refresh.
            Full <code>PUT</code> replace is reserved for repair/migration only.
          </li>
          <li>
            <strong>Message meta</strong> — JSON column on <code>chat_messages</code>: <code>streaming</code>,{" "}
            <code>receivedAt</code>, <code>modelId</code>/<code>modelName</code>, <code>sentAt</code>,{" "}
            <code>cancelRequested</code>. Used for stream recovery and multi-tab merge.
          </li>
          <li>
            PostgreSQL indexes: trigram title search (<code>pg_trgm</code>), full-text on message content,{" "}
            <code>created_at</code> for batched retention purge.
          </li>
          <li>
            Inline image bytes are not kept in chat rows; persisted images reference{" "}
            <code>/api/chat/media/&lt;id&gt;/file</code> URLs. <strong>Private Mode</strong> sessions skip server
            persistence entirely — images stay in the user&apos;s browser (IndexedDB) until Private Mode is turned off
            and migration uploads them.
          </li>
        </ul>
        <h3>Media files</h3>
        <ul>
          <li>
            Blobs live in <strong>MinIO/S3</strong> (<code>S3_BUCKET</code>, default <code>alpha-router-media</code>). Keys:{" "}
            <code>cdn/u/&lt;username&gt;/&lt;content_hash&gt;&lt;ext&gt;</code> (username is sanitized, not numeric id).
          </li>
          <li>
            Table <code>media_assets</code> — per-user metadata (filename, MIME, prompt, model, chat session, expiry).
          </li>
          <li>
            <strong>Deduplication</strong> — identical file content (SHA-256) is stored once per user in object storage;
            the Media UI shows one entry per unique hash. Re-uploading the same file refreshes metadata and moves it up
            the list.
          </li>
          <li>
            Files are served only through authenticated API routes, not as public bucket URLs.
          </li>
        </ul>
        <h3>Admin Retention Policy page</h3>
        <p>
          The page has overview cards and retention settings for media and chat. All settings require Super Admin. Manual
          purge buttons ask for confirmation before running.
        </p>
        <h4>Media &amp; files — overview</h4>
        <ul>
          <li>
            Summary of total file count, size, breakdown by type, and files past the media retention window (same data as
            on <a href="#admin-storage-management">Storage Management</a>).
          </li>
        </ul>
        <h4>Media &amp; files — retention</h4>
        <ul>
          <li>
            <strong>Retention days</strong> — default lifetime for new <code>media_assets</code> rows (also drives user
            expiry timestamps).
          </li>
          <li>
            <strong>Scheduled cleanup</strong> — optional daily job at a chosen hour/minute in the{" "}
            <strong>server&apos;s local timezone</strong> to purge expired media.
          </li>
          <li>
            <strong>Purge expired media now</strong> — immediately removes media rows (and blobs) older than the configured
            media retention days. A confirmation dialog runs before deletion starts.
          </li>
        </ul>
        <h4>Chat history — overview</h4>
        <ul>
          <li>
            Total sessions and messages in PostgreSQL, plus count of messages older than the chat retention window when
            policy is enabled.
          </li>
        </ul>
        <h4>Chat history — retention</h4>
        <ul>
          <li>
            <strong>Enable chat retention policy</strong> — master switch; when off, scheduled and manual chat purges do
            nothing.
          </li>
          <li>
            <strong>Keep chat messages for (days)</strong> — messages with <code>created_at</code> older than this age are
            eligible for removal.
          </li>
          <li>
            <strong>Scheduled cleanup</strong> — daily job at a chosen hour/minute in the <strong>server&apos;s local timezone</strong>{" "}
            (<code>TZ</code> env when set) deletes eligible messages when both retention policy and schedule are enabled.
          </li>
          <li>
            <strong>Purge expired messages now</strong> — manual run of the same chat purge logic without waiting for the
            schedule. A confirmation dialog runs before deletion starts.
          </li>
        </ul>
        <Warn>
          Chat purge runs in batches and removes message rows. Sessions that become empty during a purge are
          deleted immediately so they no longer appear in the sidebar. Sessions that still have newer messages are kept.
          Media referenced from deleted messages is not automatically deleted from object storage unless media retention
          also applies.
        </Warn>
        <h3>Environment (object storage)</h3>
        <p>
          Configure via <code>S3_ENDPOINT_URL</code>, <code>S3_ACCESS_KEY</code>, <code>S3_SECRET_KEY</code>,{" "}
          <code>S3_BUCKET</code>, and optional <code>S3_REGION</code> / <code>S3_USE_SSL</code>. In Docker Compose the{" "}
          <code>minio</code> service listens on port 9000 inside the stack; keep it off the public internet in
          production.
        </p>
        <Note>
          Back up PostgreSQL (normalized chat tables + <code>media_assets</code> metadata) and your MinIO bucket/volume
          together for a full restore. The in-app <a href="#admin-database">Database</a> page shows row counts only—it
          does not browse object storage.
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
        <p>Export usage and cost (CSV, Excel, PDF). Configure scheduled delivery when SMTP is set up.</p>
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
          Every platform API and in-app request: user, model, tokens, USD cost, latency, success, prompt cache hits,
          and client source (gateway key, user key, in-app chat, etc.). Use filters to debug errors, cache behaviour,
          or budget spikes.
        </p>
        <h3>Columns</h3>
        <ul>
          <li>
            <strong>Prompt Cache</strong> — rounded badge with a check (cache hit) or cross (no cached prompt tokens).
            Hover for cached token count and share of input tokens.
          </li>
          <li>
            <strong>Cost $</strong> — provider-reported USD for the request (unchanged when cache hits reduce billable
            input).
          </li>
        </ul>
        <h3>Filters</h3>
        <ul>
          <li>
            <strong>User / API key</strong> and <strong>Model</strong> — click the field to load values that appear in
            logs; type to narrow the list, then choose a value or press <strong>Filter</strong>. Partial text matches
            substring on the server.
          </li>
          <li>
            <strong>Prompt Cache</strong> — <em>Cache hit</em> (<code>cached_tokens &gt; 0</code>) or{" "}
            <em>No cache</em>.
          </li>
          <li>
            <strong>Response Status</strong>, date range, and refresh as before.
          </li>
        </ul>
        <p>
          The <strong>model</strong> filter accepts a substring of <code>model_id</code>. The slowest-models table on{" "}
          <a href="#admin-operations">Operations</a> opens this page with <code>?model_id=…</code> pre-filled.
        </p>
      </>
    ),
  },
  {
    id: "admin-monitoring",
    title: "Monitoring overview",
    group: "Monitoring",
    content: (
      <>
        <h2>Monitoring overview</h2>
        <p>
          The <strong>Monitoring</strong> sidebar group is for observing Alpha Router and traffic without changing configuration.
          It replaced the legacy <strong>Debug</strong> latency page with richer, card-based dashboards.
        </p>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Page</th>
              <th>Route</th>
              <th>Use when</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>Operations</strong></td>
              <td><code>/admin/operations</code></td>
              <td>
                Hourly trends: host CPU/RAM, DB ping, API errors, latency P95, throughput, and per-model slowness.
              </td>
            </tr>
            <tr>
              <td><strong>Database</strong></td>
              <td><code>/admin/database</code></td>
              <td>
                Point-in-time DB connection, engine, size, ping, masked URL, CPU/RAM snapshot, and per-table row counts.
              </td>
            </tr>
          </tbody>
        </table>
        <p>
          Typical flow when users report slow models: check <a href="#admin-operations">Operations → Model experience</a>,
          open a model from the slowest-models table into <a href="#admin-logs">API Logs</a>, then confirm DB and disk
          health on <a href="#admin-database">Database</a>.
        </p>
        <Note>
          <code>/admin/debug</code> redirects to Operations for old bookmarks.
        </Note>
      </>
    ),
  },
  {
    id: "admin-operations",
    title: "Operations",
    group: "Monitoring",
    content: (
      <>
        <h2>Operations</h2>
        <p>
          <strong>Monitoring → Operations</strong> (<code>/admin/operations</code>) is the operational dashboard. Nine metric
          cards (same visual style as the main Dashboard) in three rows: infrastructure from hourly{" "}
          <strong>system metric snapshots</strong>, API traffic from <strong>request_logs</strong>, and model experience
          for perceived slowness.
        </p>
        <h3>Infrastructure (snapshots)</h3>
        <ul>
          <li>
            <strong>CPU</strong> — host vs Alpha Router process CPU %
          </li>
          <li>
            <strong>Memory</strong> — host RAM %; footer shows Alpha Router process RSS
          </li>
          <li>
            <strong>Database</strong> — DB ping (ms); footer shows database size
          </li>
        </ul>
        <h3>API traffic (request logs, 24h)</h3>
        <ul>
          <li>
            <strong>Errors</strong> — failed requests, stacked by client source; footer shows error rate %
          </li>
          <li>
            <strong>Latency</strong> — headline P95 (ms); chart avg vs P95 per hour; footer shows period average
          </li>
          <li>
            <strong>Throughput</strong> — total requests, stacked by source; footer shows successful count
          </li>
        </ul>
        <h3>P95 latency (95th percentile)</h3>
        <p>
          Alpha Router reads <code>response_time_ms</code> from <code>request_logs</code> and sorts those values from fastest to
          slowest. <strong>P95</strong> is the latency at rank 95%: about 95% of requests finished in that time or less,
          and about 5% were slower. It highlights tail slowness better than a simple average—a few very long calls do not
          dominate the headline as much as they would with a mean.
        </p>
        <p>
          On this page, P95 is computed over the <strong>last 24 hours</strong> (UTC hourly buckets on charts). Per-model
          P95 needs at least <strong>3 requests</strong> in the window. The model-experience card compares current 24h P95
          to the <strong>previous 24h</strong> as a percentage change.
        </p>
        <h3>Time range</h3>
        <p>
          Use the dropdown in the page header (same pattern as the main Dashboard activity picker).{" "}
          <strong>Relative</strong> presets (15 minutes through 1 year) and <strong>Periods</strong> (Today, Yesterday,
          This Week, Prev Week) filter both <code>request_logs</code> charts and infra snapshots. Default is{" "}
          <strong>Past 1 Day</strong> (<code>past_1d</code>). The API accepts <code>?range=</code> on{" "}
          <code>GET /api/admin/operations/dashboard</code> and <code>POST …/check-now</code>.
        </p>
        <ul>
          <li>
            <strong>Check Now</strong> — records an infrastructure snapshot and refreshes all charts (
            <code>POST /api/admin/operations/check-now</code>).
          </li>
          <li>
            <strong>Auto-refresh</strong> — UI reloads every 1 hour; production also records infra snapshots hourly via the
            scheduler.
          </li>
          <li>
            Point-in-time DB tables and connection: <a href="#admin-database">Database</a>. Spend and models:{" "}
            <a href="#admin-dashboard">Dashboard</a>.
          </li>
        </ul>
        <h3>Model experience</h3>
        <ul>
          <li>
            <strong>Slow requests</strong> — calls ≥ 10s (<code>SLOW_REQUEST_MS</code>), hourly chart by client source
          </li>
          <li>
            <strong>P95 latency</strong> — current 24h P95 with % change vs the previous 24h
          </li>
          <li>
            <strong>Model P95 (top traffic)</strong> — hourly P95 for the three busiest models
          </li>
          <li>
            <strong>Slowest models table</strong> — P95 ranking (min. 3 requests); link to filtered{" "}
            <a href="#admin-logs">API Logs</a>
          </li>
        </ul>
        <p>
          Chart bucket size adapts to the selected range (minutes for short windows, hours for days, days/weeks for
          longer spans). Infra snapshots older than 14 days are pruned automatically.
        </p>
      </>
    ),
  },
  {
    id: "admin-database",
    title: "Database",
    group: "Monitoring",
    content: (
      <>
        <h2>Database (read-only monitor)</h2>
        <p>
          <strong>Monitoring → Database</strong> (<code>/admin/database</code>) shows live status of the application
          database only—no query editor, no schema changes, no backup/restore buttons.
        </p>
        <h3>Supported engines</h3>
        <ul>
          <li>
            <strong>PostgreSQL</strong> — production via <code>docker compose</code>. Displays database size and count of
            other active sessions on the same database.
          </li>
        </ul>
        <h3>Overview panel</h3>
        <ul>
          <li>
            <strong>Connected / Unreachable</strong> — result of a lightweight <code>SELECT 1</code> ping
          </li>
          <li>
            <strong>Engine badge</strong> — PostgreSQL
          </li>
          <li>
            <strong>Version</strong> — <code>sqlite_version()</code> or PostgreSQL <code>version()</code>
          </li>
          <li>
            <strong>Size</strong> — file size (SQLite) or <code>pg_database_size</code> (PostgreSQL)
          </li>
          <li>
            <strong>Ping</strong> — round-trip time in milliseconds
          </li>
          <li>
            <strong>Connection (masked)</strong> — <code>DATABASE_URL</code> with credentials hidden
          </li>
        </ul>
        <h3>CPU & memory panel</h3>
        <ul>
          <li>
            <strong>Host</strong> — CPU % and RAM used/total for the machine or Docker container running the Alpha Router API
            (via <code>psutil</code>)
          </li>
          <li>
            <strong>Alpha Router process</strong> — PID, process name, CPU %, and RSS memory for the current API worker
          </li>
        </ul>
        <p>
          These metrics are a snapshot when you click <strong>Refresh</strong>. They do not include separate Postgres or
          Redis containers unless those services run inside the same container as Alpha Router.
        </p>
        <h3>Tables panel</h3>
        <p>Row counts for Alpha Router tables, for example:</p>
        <ul>
          <li>
            <code>users</code>, <code>chat_sessions</code>, <code>chat_messages</code>, <code>request_logs</code>,{" "}
            <code>ai_models</code>,{" "}
            <code>connections</code>
          </li>
          <li>
            <code>media_assets</code>, <code>alpha_router_api_keys</code>, <code>user_api_keys</code>, <code>budget_plans</code>
          </li>
          <li>
            and other application tables (groups, assignments, SMTP, schedules, auth providers)
          </li>
        </ul>
        <p>
          Use <strong>Refresh</strong> to reload stats. Large <code>request_logs</code> counts are normal on busy
          instances; retention is not managed from this page (see <a href="#admin-storage">Retention Policy</a> for files
          and chat retention, and <a href="#admin-storage-management">Storage Management</a> for quotas and usage).
        </p>
        <h3>API</h3>
        <p>
          Admins only: <code>GET /api/admin/database/monitor</code> returns the same JSON payload the UI uses.
        </p>
        <Warn>
          This is not a replacement for pgAdmin, DBeaver, or cloud database consoles. Do not expose Postgres port 5432 to
          the public internet without network controls.
        </Warn>
      </>
    ),
  },
  {
    id: "user-panel",
    title: "User panel",
    group: "End users",
    content: (
      <>
        <h2>User panel (<code>/app</code>)</h2>
        <p>
          End users and administrators share the same user-facing app under <code>/app</code>. Standard users see a
          focused sidebar: <strong>Chat</strong>, <strong>Media</strong>, <strong>Recommendations</strong>,{" "}
          <strong>My Usage &amp; Activity</strong>, and <strong>User Manual</strong>. Administrators additionally use the
          admin sidebar; its top group — also labeled <strong>User panel</strong> — links to the same{" "}
          <code>/app</code> routes so admins can chat and test models without leaving the admin shell.
        </p>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Area</th>
              <th>Purpose</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Chat</td>
              <td>Same chat experience as admin chat, within budget and enabled models.</td>
            </tr>
            <tr>
              <td>Media</td>
              <td>Personal file library from chat uploads and generated images.</td>
            </tr>
            <tr>
              <td>Recommendations</td>
              <td>Usage-based model suggestions (quality fit and value picks for your token mix).</td>
            </tr>
            <tr>
              <td>My Usage &amp; Activity</td>
              <td>Personal spend, tokens, heatmap, exports (CSV/PDF).</td>
            </tr>
            <tr>
              <td>User Manual</td>
              <td>In-app help for all user-facing features.</td>
            </tr>
          </tbody>
        </table>
        <p>
          Profile menu: <strong>My Usage &amp; Activity</strong>, <strong>Budget</strong> (<code>used/total $</code>),
          theme, sign out. On the standard user layout, administrators also see an <strong>Administration</strong> link
          that opens their first allowed admin menu.
        </p>
        <Note>
          Holding <strong>API Key Admin</strong> does <strong>not</strong> restrict the user panel — chat, media, and
          recommendations stay fully writable. Only <strong>deactivated accounts</strong> enter account-wide read-only
          mode (see User Manual → Deactivated accounts).
        </Note>
      </>
    ),
  },
  {
    id: "platform-api",
    title: "Platform API",
    group: "Integration",
    content: (
      <>
        <h2>Platform API</h2>
        <p>
          OpenAI-compatible HTTPS. Base path: <code>https://&lt;your-alpha-router-host&gt;/v1</code>. Use Alpha Router-issued keys
          only—never upstream provider keys in clients.
        </p>
        <Note>
          Alpha Router can act as an organizational <strong>AI gateway</strong> for OpenAI-compatible apps (for example{" "}
          <strong>Open WebUI</strong>): point the client&apos;s API base URL to <code>/v1</code> and paste a Alpha Router
          gateway or per-user key from <strong>API Keys</strong> or <strong>Users → Get API Key</strong>. Enable models
          in Alpha Router first; budgets and logs stay centralized.
        </Note>
        <h3 id="using-api-keys">Using API keys in clients</h3>
        <p>
          After you create a gateway or user key, copy the <strong>URL</strong> and <strong>API Key</strong> from the
          one-time modal. Paste into any OpenAI-compatible client (IDE extensions, automation scripts, compatible chat
          front-ends). The URL must end with <code>/v1</code>.
        </p>
        <h3>List models</h3>
        <Code>{`GET https://<your-alpha-router-host>/v1/models
Authorization: Bearer <ALPHA_ROUTER_KEY>`}</Code>
        <h3>Chat completions (streaming required)</h3>
        <Code>{`POST https://<your-alpha-router-host>/v1/chat/completions
Authorization: Bearer <ALPHA_ROUTER_KEY>
Content-Type: application/json

{
  "model": "<enabled-model-id-from-models-page>",
  "messages": [{ "role": "user", "content": "Hello" }],
  "stream": true,
  "user": "person@company.com"
}`}</Code>
        <p>
          The optional <code>user</code> field helps attribute usage when using a shared gateway key (pass a stable email
          or username). Per-user API keys already bind requests to that user&apos;s budget.
        </p>
        <h3>Python (OpenAI SDK)</h3>
        <Code>{`from openai import OpenAI

client = OpenAI(
    base_url="https://<your-alpha-router-host>/v1",
    api_key="<ALPHA_ROUTER_KEY>",
)

client.chat.completions.create(
    model="<enabled-model-id>",
    messages=[{"role": "user", "content": "Hello"}],
    stream=True,
)`}</Code>
      </>
    ),
  },
  {
    id: "kilo-code",
    title: "Kilo Code",
    group: "Integration",
    content: (
      <>
        <h2 id="kilo-code">Kilo Code + Alpha Router</h2>
        <p>
          <a href="https://kilo.ai">Kilo Code</a> (VS Code extension) supports OpenAI-compatible providers. Use Alpha Router as
          that provider so IDE usage respects the same models and budgets as the rest of your organization.
        </p>

        <h3>Part A — Get a Alpha Router API key</h3>
        <ol className="docs-steps">
          <li>
            In Alpha Router, enable the models you need (<strong>Models</strong>).
          </li>
          <li>
            Create a key using one of:
            <ul>
              <li>
                <strong>API Keys</strong> → gateway key (shared), or
              </li>
              <li>
                <strong>Users → Get API Key</strong> / user <strong>API Key</strong> page (per developer).
              </li>
            </ul>
          </li>
          <li>
            Copy <strong>URL</strong> and <strong>API Key</strong> from the creation modal.
          </li>
          <li>
            Note the exact <strong>model id</strong> string from Alpha Router (Models table, <code>external_id</code> column)—you
            will need it in Kilo Code.
          </li>
        </ol>

        <h3>Part B — VS Code UI (Kilo Code settings)</h3>
        <ol className="docs-steps">
          <li>
            Install / open <strong>Kilo Code</strong> in VS Code.
          </li>
          <li>
            Open <strong>Settings</strong> (gear icon in Kilo) → <strong>Providers</strong>.
          </li>
          <li>
            Add or select <strong>OpenAI Compatible</strong> (not the official OpenAI provider unless you are truly using
            OpenAI directly).
          </li>
          <li>
            <strong>Base URL:</strong> Alpha Router URL, e.g. <code>https://alpha-router.company.com/v1</code>
          </li>
          <li>
            <strong>API Key:</strong> paste the Alpha Router key from the modal.
          </li>
          <li>
            <strong>Model:</strong> pick from auto-detected list (fetched from <code>/v1/models</code>) or enter the model
            id manually, e.g. <code>anthropic/claude-sonnet-4</code> (must match an enabled model in Alpha Router).
          </li>
          <li>
            Save and run a short prompt in the Kilo sidebar to confirm streaming works.
          </li>
        </ol>

        <h3>Part C — Optional <code>kilo.jsonc</code> config</h3>
        <p>
          Kilo can store the same settings in config (global <code>~/.config/kilo/kilo.jsonc</code> or project{" "}
          <code>kilo.jsonc</code>). Example:
        </p>
        <Code>{`{
  "provider": {
    "openai-compatible": {
      "options": {
        "apiKey": "{env:ALPHA_ROUTER_API_KEY}",
        "baseURL": "https://<your-alpha-router-host>/v1"
      }
    }
  },
  "model": "openai-compatible/<enabled-model-id>"
}`}</Code>
        <p>
          Prefer <code>{`{env:VAR}`}</code> for the key instead of hard-coding secrets. See{" "}
          <a href="https://kilo.ai/docs/ai-providers/openai-compatible" target="_blank" rel="noreferrer">
            Kilo: OpenAI-compatible providers
          </a>
          .
        </p>

        <h3>Troubleshooting</h3>
        <ul>
          <li>
            <strong>Model not found</strong> — Model must be enabled in Alpha Router and id must match exactly (case-sensitive).
          </li>
          <li>
            <strong>Connection errors</strong> — Verify TLS, VPN, and that <code>API_PUBLIC_URL</code> matches what you
            entered in Base URL.
          </li>
          <li>
            <strong>Budget exceeded</strong> — Check the user&apos;s <strong>Budget</strong> in Alpha Router; per-user keys use
            that user&apos;s pool.
          </li>
          <li>
            <strong>Azure GPT-5 / special providers</strong> — Use native provider support in Kilo when required; generic
            OpenAI-compatible mode targets Alpha Router&apos;s OpenAI-style <code>/v1/chat/completions</code>.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "budget-pricing",
    title: "Budget & pricing",
    group: "Integration",
    content: (
      <>
        <h2>Budget & pricing</h2>
        <ul>
          <li>Monthly USD budget from plan or per-user override.</li>
          <li>Each request deducts provider-reported cost from <code>budget_used_usd</code>.</li>
          <li>Resets on the first day of each calendar month.</li>
          <li>When exhausted, new requests are rejected until reset or admin adjustment.</li>
        </ul>
        <p>Alpha Router does not markup provider prices.</p>
      </>
    ),
  },
  {
    id: "security",
    title: "Security & operations",
    group: "Integration",
    content: (
      <>
        <h2>Security & operations</h2>
        <ul>
          <li>Rotate provider and Alpha Router keys regularly; disable unused keys.</li>
          <li>TLS in production; restrict admin access by network or SSO.</li>
          <li>
            Use <strong>least-privilege RBAC</strong>: assign <strong>API Key Admin</strong> instead of Super Admin when
            a colleague only needs API Keys. Super Admin remains for platform owners.
          </li>
          <li>
            Back up PostgreSQL and the MinIO/S3 media bucket outside Alpha Router; use{" "}
            <a href="#admin-database">Database</a> only to inspect size and row counts.
          </li>
          <li>Do not expose MinIO port 9000 or Postgres 5432 to the public internet without network controls.</li>
          <li>Use least-privilege upstream keys where vendors allow scopes.</li>
          <li>
            Monitor <a href="#admin-operations">Operations</a>, <a href="#admin-database">Database</a>, Dashboard, and API
            Logs for anomalies.
          </li>
          <li>
            Change default compose passwords and <code>SECRET_KEY</code> before production (
            <a href="#deployment">Deployment & database</a>).
          </li>
        </ul>
      </>
    ),
  },
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
