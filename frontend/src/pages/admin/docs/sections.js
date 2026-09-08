import { Fragment, jsx, jsxs } from "react/jsx-runtime";
import AdminArchitectureDiagram from "../../../components/docs/AdminArchitectureDiagram";
import { PRODUCT_NAME_MARKED, TRADEMARK_OWNER } from "../../../lib/brand";
function Code({ children }) {
  return /* @__PURE__ */ jsx("pre", { className: "docs-code", children: /* @__PURE__ */ jsx("code", { children }) });
}
function Note({ children }) {
  return /* @__PURE__ */ jsx("div", { className: "docs-callout docs-callout-info", children });
}
function Warn({ children }) {
  return /* @__PURE__ */ jsx("div", { className: "docs-callout docs-callout-warn", children });
}
const docSections = [
  // ── Get started ───────────────────────────────────────────────────────────
  {
    id: "introduction",
    title: "Introduction",
    group: "Get started",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h1", { children: "Admin Guide" }),
      /* @__PURE__ */ jsx("p", { className: "docs-lead", children: "Alpharouter is an organizational AI control plane. It sits between your employees (and optional external tools) and upstream LLM providers, enforcing budgets, roles, quotas, audit logging, and retention \u2014 while serving a built-in chat app and an OpenAI-compatible gateway." }),
      /* @__PURE__ */ jsxs("p", { children: [
        "This guide is for operators and administrators. End-user help lives in the in-app",
        " ",
        /* @__PURE__ */ jsx("strong", { children: "User Manual" }),
        " (",
        /* @__PURE__ */ jsx("code", { children: "/app/manual" }),
        " or ",
        /* @__PURE__ */ jsx("code", { children: "/admin/manual" }),
        "). Do not paste secrets into documentation; configure them only in your deployment environment and the admin UI."
      ] }),
      /* @__PURE__ */ jsxs("div", { className: "docs-cards", children: [
        /* @__PURE__ */ jsxs("div", { className: "docs-card", children: [
          /* @__PURE__ */ jsx("h3", { children: "Three surfaces" }),
          /* @__PURE__ */ jsxs("p", { children: [
            "User app ",
            /* @__PURE__ */ jsx("code", { children: "/app/*" }),
            ", admin panel ",
            /* @__PURE__ */ jsx("code", { children: "/admin/*" }),
            ", and gateway ",
            /* @__PURE__ */ jsx("code", { children: "/v1/*" }),
            " \u2014 one FastAPI process."
          ] })
        ] }),
        /* @__PURE__ */ jsxs("div", { className: "docs-card", children: [
          /* @__PURE__ */ jsx("h3", { children: "Policy & spend" }),
          /* @__PURE__ */ jsx("p", { children: "Plans, monthly budgets, API-key credits, and per-request reservation before provider traffic." })
        ] }),
        /* @__PURE__ */ jsxs("div", { className: "docs-card", children: [
          /* @__PURE__ */ jsx("h3", { children: "Visibility" }),
          /* @__PURE__ */ jsx("p", { children: "Dashboard analytics, Operations, API logs, reports, and activity exports." })
        ] })
      ] }),
      /* @__PURE__ */ jsxs("table", { className: "docs-table", children: [
        /* @__PURE__ */ jsx("thead", { children: /* @__PURE__ */ jsxs("tr", { children: [
          /* @__PURE__ */ jsx("th", { children: "Section group" }),
          /* @__PURE__ */ jsx("th", { children: "What you will find" })
        ] }) }),
        /* @__PURE__ */ jsxs("tbody", { children: [
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("a", { href: "#requirements", children: "Get started" }) }),
            /* @__PURE__ */ jsx("td", { children: "Hardware & software requirements, architecture, services, deployment overview" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("a", { href: "#security-overview", children: "Security" }) }),
            /* @__PURE__ */ jsx("td", { children: "Auth, sessions/CSRF, RBAC, encryption, hardening checklist" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("a", { href: "#admin-dashboard", children: "Overview / Models / People / \u2026" }) }),
            /* @__PURE__ */ jsxs("td", { children: [
              "Every admin menu: purpose, UI actions, and operational notes \u2014 including",
              " ",
              /* @__PURE__ */ jsx("a", { href: "#admin-activity-scopes", children: "Activity scopes" }),
              ", ",
              /* @__PURE__ */ jsx("a", { href: "#admin-projects", children: "Projects" }),
              ", and gateway API key policies"
            ] })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("a", { href: "#platform-api", children: "Platform API & Billing" }) }),
            /* @__PURE__ */ jsxs("td", { children: [
              /* @__PURE__ */ jsx("code", { children: "/v1" }),
              " gateway, budgets, and pricing rules"
            ] })
          ] })
        ] })
      ] })
    ] })
  },
  {
    id: "why-alpha-router",
    title: "Why Alpharouter exists",
    group: "Get started",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Why Alpharouter exists" }),
      /* @__PURE__ */ jsx("p", { children: "Teams adopting LLMs across chat, IDEs, and automation usually hit the same problems:" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Provider API keys are shared or scattered, with no central policy." }),
        /* @__PURE__ */ jsx("li", { children: "Spend is hard to attribute to people, teams, or departments." }),
        /* @__PURE__ */ jsx("li", { children: "Model catalogs and pricing change often." }),
        /* @__PURE__ */ jsx("li", { children: "Compliance needs a durable request history." })
      ] }),
      /* @__PURE__ */ jsx("p", { children: "Alpharouter addresses this by:" }),
      /* @__PURE__ */ jsxs("ol", { children: [
        /* @__PURE__ */ jsx("li", { children: "Terminating client traffic at a platform you operate." }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Syncing models and ",
          /* @__PURE__ */ jsx("strong", { children: "provider-native pricing" }),
          " from Connections (Alpharouter does not rewrite catalog prices)."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Enforcing ",
          /* @__PURE__ */ jsx("strong", { children: "RBAC" }),
          ", ",
          /* @__PURE__ */ jsx("strong", { children: "plans" }),
          ", ",
          /* @__PURE__ */ jsx("strong", { children: "monthly budgets" }),
          ", and optional account deactivation (read-only history; no new spend)."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Supporting ",
          /* @__PURE__ */ jsx("strong", { children: "local" }),
          ", ",
          /* @__PURE__ */ jsx("strong", { children: "LDAP/Active Directory" }),
          ", ",
          /* @__PURE__ */ jsx("strong", { children: "SAML 2.0" }),
          ", and",
          " ",
          /* @__PURE__ */ jsx("strong", { children: "OIDC" }),
          " sign-in."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Offering in-app chat, media libraries, Activity, and an optional OpenAI-compatible",
          " ",
          /* @__PURE__ */ jsx("code", { children: "/v1" }),
          " API for external tools."
        ] })
      ] })
    ] })
  },
  {
    id: "requirements",
    title: "Hardware & software requirements",
    group: "Get started",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Hardware & software requirements" }),
      /* @__PURE__ */ jsx("p", { children: "Alpharouter ships as a Docker Compose stack. Plan the host from two independent drivers: the always-on platform services (app, database, cache, object storage, Qdrant, ClamAV, Knowledge worker) and the Code Interpreter sandbox fleet, which is sized from its concurrent-execution ceiling rather than from the number of signed-in users." }),
      /* @__PURE__ */ jsx("h3", { children: "Operating system & platform" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "OS:" }),
          " a 64-bit Linux host is recommended for production (Ubuntu 22.04 LTS / 24.04 LTS, Debian 12, or an equivalent current kernel). macOS and Windows are supported for evaluation through Docker Desktop only."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "CPU architecture:" }),
          " ",
          /* @__PURE__ */ jsx("code", { children: "x86_64 / amd64" }),
          " is required. The sandbox broker bundles the",
          /* @__PURE__ */ jsx("code", { children: " x86_64" }),
          " Docker CLI and the disposable sandbox image is built for amd64, so ARM hosts (Apple Silicon, Graviton) must run under amd64 emulation, which is not recommended for production."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Container runtime:" }),
          " Docker Engine ",
          /* @__PURE__ */ jsx("code", { children: "24.0+" }),
          " with the Compose v2 plugin (",
          /* @__PURE__ */ jsx("code", { children: "docker compose" }),
          "). The broker talks to the host Docker socket to spawn disposable containers, so a working Docker daemon is mandatory \u2014 rootless/podman substitutes are not validated."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Networking:" }),
          " outbound HTTPS to your upstream LLM providers, and only the app port",
          " ",
          /* @__PURE__ */ jsx("code", { children: "8080" }),
          " exposed to clients. Keep Postgres, Redis, SeaweedFS, Qdrant, ClamAV, and the broker on internal networks."
        ] })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Pinned service versions" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "These are the images the repository ",
        /* @__PURE__ */ jsx("code", { children: "docker-compose.yml" }),
        " pins. Keep them aligned when upgrading; they are validated together."
      ] }),
      /* @__PURE__ */ jsxs("table", { className: "docs-table", children: [
        /* @__PURE__ */ jsx("thead", { children: /* @__PURE__ */ jsxs("tr", { children: [
          /* @__PURE__ */ jsx("th", { children: "Component" }),
          /* @__PURE__ */ jsx("th", { children: "Version" }),
          /* @__PURE__ */ jsx("th", { children: "Notes" })
        ] }) }),
        /* @__PURE__ */ jsxs("tbody", { children: [
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "PostgreSQL" }),
            /* @__PURE__ */ jsxs("td", { children: [
              /* @__PURE__ */ jsx("code", { children: "16" }),
              " (alpine)"
            ] }),
            /* @__PURE__ */ jsx("td", { children: "Primary data store; fronted by PgBouncer in transaction pooling mode" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "PgBouncer" }),
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "1.22" }) }),
            /* @__PURE__ */ jsxs("td", { children: [
              "SCRAM auth; listens on ",
              /* @__PURE__ */ jsx("code", { children: "6432" })
            ] })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Redis" }),
            /* @__PURE__ */ jsxs("td", { children: [
              /* @__PURE__ */ jsx("code", { children: "7" }),
              " (alpine)"
            ] }),
            /* @__PURE__ */ jsx("td", { children: "Rate limits, SSO/2FA state, Code Interpreter capacity leases, LiteLLM cache, Knowledge job streams" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "SeaweedFS" }),
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "4.40" }) }),
            /* @__PURE__ */ jsx("td", { children: "S3-compatible object storage for media and Knowledge source bytes" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Qdrant" }),
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "v1.19.0" }) }),
            /* @__PURE__ */ jsx("td", { children: "Derived vector/sparse index for published Knowledge releases" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "ClamAV" }),
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "1.5.4" }) }),
            /* @__PURE__ */ jsx("td", { children: "Malware scan for Knowledge ingest (internal; no public port)" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Application runtime" }),
            /* @__PURE__ */ jsxs("td", { children: [
              "Python ",
              /* @__PURE__ */ jsx("code", { children: "3.12" })
            ] }),
            /* @__PURE__ */ jsx("td", { children: "FastAPI + uvicorn; bundled headless Chromium for server-side PDF rendering" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Frontend build" }),
            /* @__PURE__ */ jsxs("td", { children: [
              "Node ",
              /* @__PURE__ */ jsx("code", { children: "20" })
            ] }),
            /* @__PURE__ */ jsx("td", { children: "Build-time only (the SPA is served as static files by the app)" })
          ] })
        ] })
      ] }),
      /* @__PURE__ */ jsxs(Note, { children: [
        "Local development without Docker needs Python ",
        /* @__PURE__ */ jsx("code", { children: "3.12" }),
        " and Node ",
        /* @__PURE__ */ jsx("code", { children: "20" }),
        " on the workstation. You still need reachable Postgres and Redis instances for a full run."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Baseline platform sizing (excluding Code Interpreter)" }),
      /* @__PURE__ */ jsx("p", { children: "The following covers the always-on services and moderate chat/gateway traffic. Code Interpreter sandboxes are sized separately below." }),
      /* @__PURE__ */ jsxs("table", { className: "docs-table", children: [
        /* @__PURE__ */ jsx("thead", { children: /* @__PURE__ */ jsxs("tr", { children: [
          /* @__PURE__ */ jsx("th", { children: "Profile" }),
          /* @__PURE__ */ jsx("th", { children: "vCPU" }),
          /* @__PURE__ */ jsx("th", { children: "RAM" }),
          /* @__PURE__ */ jsx("th", { children: "Disk" }),
          /* @__PURE__ */ jsx("th", { children: "Use" })
        ] }) }),
        /* @__PURE__ */ jsxs("tbody", { children: [
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Evaluation / single box" }),
            /* @__PURE__ */ jsx("td", { children: "4" }),
            /* @__PURE__ */ jsx("td", { children: "8 GiB" }),
            /* @__PURE__ */ jsx("td", { children: "40 GiB SSD" }),
            /* @__PURE__ */ jsx("td", { children: "Trials and small teams; Code Interpreter kept at a low ceiling" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Small production" }),
            /* @__PURE__ */ jsx("td", { children: "8" }),
            /* @__PURE__ */ jsx("td", { children: "16 GiB" }),
            /* @__PURE__ */ jsx("td", { children: "100 GiB SSD" }),
            /* @__PURE__ */ jsx("td", { children: "Daily use for a department; light concurrent Code Interpreter" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Growing production" }),
            /* @__PURE__ */ jsx("td", { children: "16+" }),
            /* @__PURE__ */ jsx("td", { children: "32+ GiB" }),
            /* @__PURE__ */ jsx("td", { children: "250+ GiB SSD" }),
            /* @__PURE__ */ jsx("td", { children: "Higher concurrency; media growth; larger request logs" })
          ] })
        ] })
      ] }),
      /* @__PURE__ */ jsxs(Note, { children: [
        "Disk grows with media and Knowledge objects (SeaweedFS), Qdrant collections, request logs, and the app",
        " ",
        /* @__PURE__ */ jsx("code", { children: "/tmp" }),
        " tmpfs used to pack ZIP downloads (Compose reserves up to ",
        /* @__PURE__ */ jsx("code", { children: "10g" }),
        "). Provision RAM above the tmpfs sizes so heavy exports do not compete with service memory."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Sizing the Code Interpreter fleet" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Capacity must be planned from the configured concurrent-sandbox ceiling, not from signed-in users. Each active execution is a disposable container. With the default per-sandbox memory limit of ",
        /* @__PURE__ */ jsx("code", { children: "256MiB" }),
        ", 200 simultaneous containers reach a theoretical sandbox ceiling of about ",
        /* @__PURE__ */ jsx("strong", { children: "50GiB RAM" }),
        " before adding Docker, the broker, API workers, database, Redis, object storage, tmpfs, and OS headroom. CPU demand can approach one vCPU per active sandbox."
      ] }),
      /* @__PURE__ */ jsxs(Warn, { children: [
        "Do not advertise a 200-execution profile by only raising the concurrency ceiling. Validate 50, 100, 150, and 200 concurrency stages with representative workspace and artifact sizes, then set the operational ceiling from Admin \u2192 Operations to the highest stage that passes latency, memory, cancellation, and soak-test gates. See",
        " ",
        /* @__PURE__ */ jsx("a", { href: "#architecture", children: "Architecture & services" }),
        " for the request path and broker trust boundary."
      ] })
    ] })
  },
  {
    id: "architecture",
    title: "Architecture &amp; services",
    group: "Get started",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Architecture & services" }),
      /* @__PURE__ */ jsx("p", { children: "Alpharouter is one application container that serves the React SPA and the API. Supporting services run beside it in Docker Compose." }),
      /* @__PURE__ */ jsx(AdminArchitectureDiagram, {}),
      /* @__PURE__ */ jsx("h3", { children: "Surfaces" }),
      /* @__PURE__ */ jsxs("table", { className: "docs-table", children: [
        /* @__PURE__ */ jsx("thead", { children: /* @__PURE__ */ jsxs("tr", { children: [
          /* @__PURE__ */ jsx("th", { children: "Surface" }),
          /* @__PURE__ */ jsx("th", { children: "Path" }),
          /* @__PURE__ */ jsx("th", { children: "Auth" })
        ] }) }),
        /* @__PURE__ */ jsxs("tbody", { children: [
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "User app" }),
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "/app/*" }) }),
            /* @__PURE__ */ jsxs("td", { children: [
              "HttpOnly session cookie + CSRF on unsafe ",
              /* @__PURE__ */ jsx("code", { children: "/api/*" }),
              " methods"
            ] })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Admin panel" }),
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "/admin/*" }) }),
            /* @__PURE__ */ jsx("td", { children: "Same cookie; menus gated by RBAC" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "OpenAI-compatible gateway" }),
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "/v1/*" }) }),
            /* @__PURE__ */ jsxs("td", { children: [
              /* @__PURE__ */ jsx("code", { children: "Authorization: Bearer" }),
              " \u2014 Alpharouter API key, user API key, or gateway master key"
            ] })
          ] })
        ] })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Runtime services" }),
      /* @__PURE__ */ jsxs("table", { className: "docs-table", children: [
        /* @__PURE__ */ jsx("thead", { children: /* @__PURE__ */ jsxs("tr", { children: [
          /* @__PURE__ */ jsx("th", { children: "Service" }),
          /* @__PURE__ */ jsx("th", { children: "Role" })
        ] }) }),
        /* @__PURE__ */ jsxs("tbody", { children: [
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsxs("td", { children: [
              /* @__PURE__ */ jsx("strong", { children: "alpha-router" }),
              " (uvicorn)"
            ] }),
            /* @__PURE__ */ jsx("td", { children: "FastAPI app, SPA static files, LiteLLM proxy, schedulers, billing, Agent runtime" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsxs("td", { children: [
              /* @__PURE__ */ jsx("strong", { children: "PostgreSQL" }),
              " + ",
              /* @__PURE__ */ jsx("strong", { children: "PgBouncer" })
            ] }),
            /* @__PURE__ */ jsx("td", { children: "Primary data store (users, catalog, chat rows, Agent/Knowledge records, logs, reservations). App connects through PgBouncer in transaction pooling mode." })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("strong", { children: "Redis" }) }),
            /* @__PURE__ */ jsx("td", { children: "Rate limits, SSO/2FA pending state, LiteLLM cache, Knowledge job streams (in-memory fallback if Redis is unavailable)" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("strong", { children: "SeaweedFS" }) }),
            /* @__PURE__ */ jsx("td", { children: "S3-compatible object storage for media blobs and Knowledge source bytes (authenticated access via Alpharouter APIs only)" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("strong", { children: "Qdrant" }) }),
            /* @__PURE__ */ jsx("td", { children: "Derived vector/sparse index for published Knowledge releases. Rebuild from PostgreSQL; never treat as source of truth." })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("strong", { children: "ClamAV" }) }),
            /* @__PURE__ */ jsx("td", { children: "Malware scan for Knowledge uploads in quarantine before parse and index" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsxs("td", { children: [
              /* @__PURE__ */ jsx("strong", { children: "alpha-router-knowledge-scheduler" }),
              " / ",
              /* @__PURE__ */ jsx("strong", { children: "-worker" })
            ] }),
            /* @__PURE__ */ jsx("td", { children: "Same app image. Scheduler enqueues ingest and retention jobs; worker parses, scans, embeds, and publishes Qdrant aliases." })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("strong", { children: "sandbox-broker" }) }),
            /* @__PURE__ */ jsx("td", { children: "Internal HTTP service that spawns disposable code-interpreter containers. Listens on an internal Docker network; the Docker socket is a residual host trust boundary \u2014 never publish the broker port." })
          ] })
        ] })
      ] }),
      /* @__PURE__ */ jsxs(Note, { children: [
        "Hardware sizing, pinned service versions, and the Code Interpreter fleet calculation live in",
        " ",
        /* @__PURE__ */ jsx("a", { href: "#requirements", children: "Hardware & software requirements" }),
        "."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "LLM request path (summary)" }),
      /* @__PURE__ */ jsxs("ol", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          "Client calls ",
          /* @__PURE__ */ jsx("code", { children: "POST /api/chat/completions" }),
          " or ",
          /* @__PURE__ */ jsx("code", { children: "POST /v1/chat/completions" }),
          ", optionally with an explicit Agent or auto-route."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Alpharouter resolves an enabled model and Connection key. Code Interpreter requests validate their workspace and acquire a Redis capacity lease before Alpharouter ",
          /* @__PURE__ */ jsx("strong", { children: "reserves" }),
          " budget (or API-key credit)."
        ] }),
        /* @__PURE__ */ jsx("li", { children: "Streaming goes through LiteLLM to the upstream provider. Optional tools: web search/fetch and code interpreter (via sandbox-broker)." }),
        /* @__PURE__ */ jsxs("li", { children: [
          "When a specialist Agent is in play, the runtime plans the turn, retrieves from authorized published Knowledge releases in Qdrant, requires citations when policy says so, and fail-closes to a localized safe message if citation integrity fails. Turn metadata is stored on ",
          /* @__PURE__ */ jsx("code", { children: "agent_runs" }),
          " without raw prompts or provider output."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Every upstream attempt is normalized into usage events and immutable ledger entries. The reservation is",
          " ",
          /* @__PURE__ */ jsx("strong", { children: "settled" }),
          " from the highest-confidence available cost; in-app chat also persists messages server-side during the stream."
        ] })
      ] }),
      /* @__PURE__ */ jsxs(Note, { children: [
        "Image generation uses ",
        /* @__PURE__ */ jsx("code", { children: "POST /api/images/generate" }),
        " with its own model selection, retries, and the same reservation/settle billing pattern. Video generation uses ",
        /* @__PURE__ */ jsx("code", { children: "POST /api/videos/generate" }),
        " ",
        "(async OpenRouter ",
        /* @__PURE__ */ jsx("code", { children: "/videos" }),
        " jobs) plus ",
        /* @__PURE__ */ jsxs("code", { children: [
          "GET /api/videos/jobs/",
          "{id}"
        ] }),
        " polling \u2014 never inbound webhooks \u2014 and settles with ",
        /* @__PURE__ */ jsx("code", { children: "service_type=video" }),
        "."
      ] })
    ] })
  },
  {
    id: "deployment",
    title: "Deployment overview",
    group: "Get started",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Deployment overview" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Production deployments typically use the repository ",
        /* @__PURE__ */ jsx("code", { children: "docker-compose.yml" }),
        ": Postgres, PgBouncer, Redis, SeaweedFS, Qdrant, ClamAV, sandbox-broker, a one-shot ",
        /* @__PURE__ */ jsx("code", { children: "db-init" }),
        " Alembic migrate, Knowledge scheduler/worker, and the ",
        /* @__PURE__ */ jsx("code", { children: "alpha-router" }),
        " app service (port ",
        /* @__PURE__ */ jsx("code", { children: "8080" }),
        ").",
        " ",
        /* @__PURE__ */ jsx("code", { children: "docker compose up --build -d" }),
        " prepares the disposable sandbox image through a one-shot initializer; its ",
        /* @__PURE__ */ jsx("code", { children: "Exited (0)" }),
        " status is expected. The long-running",
        " ",
        /* @__PURE__ */ jsx("code", { children: "alpha-router-sandbox-broker" }),
        " smoke-tests the image at startup and creates a short-lived container for each execution, so operators must not start a persistent sandbox manually."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Configuration" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "All settings load from environment / ",
        /* @__PURE__ */ jsx("code", { children: ".env" }),
        " (see ",
        /* @__PURE__ */ jsx("code", { children: ".env.example" }),
        "). Important groups:"
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Environment gate" }),
          " \u2014 ",
          /* @__PURE__ */ jsx("code", { children: "ENVIRONMENT=production" }),
          " enables the startup production guard; ",
          /* @__PURE__ */ jsx("code", { children: "PRODUCTION_GUARD_MODE" }),
          " is ",
          /* @__PURE__ */ jsx("code", { children: "hard-fail" }),
          " (default) or ",
          /* @__PURE__ */ jsx("code", { children: "warning" }),
          "."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Secrets" }),
          " \u2014 ",
          /* @__PURE__ */ jsx("code", { children: "SECRET_KEY" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: "DATA_ENCRYPTION_KEY" }),
          ", database/Redis/S3 credentials, ",
          /* @__PURE__ */ jsx("code", { children: "QDRANT_API_KEY" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: "SANDBOX_BROKER_TOKEN" }),
          " (\u226532 characters),",
          " ",
          /* @__PURE__ */ jsx("code", { children: "GATEWAY_MASTER_KEY" }),
          "."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "URLs" }),
          " \u2014 ",
          /* @__PURE__ */ jsx("code", { children: "FRONTEND_URL" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: "API_PUBLIC_URL" }),
          " (used for SAML/OIDC callbacks and CORS/CSRF origin checks)."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Object storage" }),
          " \u2014 ",
          /* @__PURE__ */ jsx("code", { children: "S3_*" }),
          " pointing at SeaweedFS (or another S3-compatible endpoint)."
        ] })
      ] }),
      /* @__PURE__ */ jsxs(Warn, { children: [
        "Never commit real ",
        /* @__PURE__ */ jsx("code", { children: ".env" }),
        " values. The production guard refuses to boot when known insecure defaults remain (placeholder secrets, missing broker token, unauthenticated Redis, cleartext public URLs, legacy Bearer auth, and related checks). Loopback and Compose-internal hostnames are deliberately allowed for single-box installs."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Health" }),
      /* @__PURE__ */ jsxs("p", { children: [
        /* @__PURE__ */ jsx("code", { children: "GET /health" }),
        " returns a minimal liveness payload. Dependency readiness is owned by your orchestration layer (Compose healthchecks), not by expanding this endpoint into a data probe."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Schema & migrations" }),
      /* @__PURE__ */ jsx("p", { children: "On startup Alpharouter creates ORM tables under a PostgreSQL advisory lock, applies nullable column patches for new fields, and creates any missing current-schema indexes. Greenfield deployments do not run historical data or storage migrations. There is no separate Alembic revision history for operators to apply by hand." })
    ] })
  },
  {
    id: "quickstart",
    title: "First-time setup",
    group: "Get started",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "First-time setup" }),
      /* @__PURE__ */ jsxs("ol", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          "Deploy Compose (or your equivalent) with a filled ",
          /* @__PURE__ */ jsx("code", { children: ".env" }),
          ". Confirm ",
          /* @__PURE__ */ jsx("code", { children: "/health" }),
          " and that you can open the UI."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Sign in with the bootstrap local admin (",
          /* @__PURE__ */ jsx("code", { children: "ADMIN_USERNAME" }),
          " / ",
          /* @__PURE__ */ jsx("code", { children: "ADMIN_PASSWORD" }),
          "). Change that password immediately after first login."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Open ",
          /* @__PURE__ */ jsx("strong", { children: "Connections" }),
          " \u2192 create a provider connection \u2192 ",
          /* @__PURE__ */ jsx("strong", { children: "Sync now" }),
          "."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Open ",
          /* @__PURE__ */ jsx("strong", { children: "Models" }),
          " and enable only the models you want employees to use."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Create a ",
          /* @__PURE__ */ jsx("strong", { children: "Plan" }),
          " with a monthly USD budget and assign it to users, groups, or departments."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Configure ",
          /* @__PURE__ */ jsx("strong", { children: "Authentication" }),
          " (LDAP / SAML / OIDC) if you are not staying on local accounts only."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Optionally create ",
          /* @__PURE__ */ jsx("strong", { children: "API Keys" }),
          " for external OpenAI-compatible clients, and configure",
          " ",
          /* @__PURE__ */ jsx("strong", { children: "SMTP" }),
          " if you will email reports."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Review ",
          /* @__PURE__ */ jsx("strong", { children: "Storage Management" }),
          " and ",
          /* @__PURE__ */ jsx("strong", { children: "Retention Policy" }),
          " before production traffic grows."
        ] })
      ] }),
      /* @__PURE__ */ jsx(Note, { children: "Users without an assigned (or inherited) budget plan receive HTTP 402 when they try to spend. Assign plans before inviting people to chat." })
    ] })
  },
  // ── Security ──────────────────────────────────────────────────────────────
  {
    id: "security-overview",
    title: "Security overview",
    group: "Security",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Security overview" }),
      /* @__PURE__ */ jsx("p", { children: "Alpharouter hardens the browser surface with cookie sessions and CSRF, encrypts secrets at rest, gates admin menus with RBAC, and isolates code execution in disposable containers. Upstream provider keys never leave the Connections table as plaintext in the API responses." }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: /* @__PURE__ */ jsx("a", { href: "#sign-in", children: "Sign-in & identity" }) }),
        /* @__PURE__ */ jsx("li", { children: /* @__PURE__ */ jsx("a", { href: "#sessions-csrf", children: "Sessions, cookies & CSRF" }) }),
        /* @__PURE__ */ jsx("li", { children: /* @__PURE__ */ jsx("a", { href: "#rbac-model", children: "RBAC model" }) }),
        /* @__PURE__ */ jsx("li", { children: /* @__PURE__ */ jsx("a", { href: "#secrets-encryption", children: "Secrets & encryption" }) }),
        /* @__PURE__ */ jsx("li", { children: /* @__PURE__ */ jsx("a", { href: "#hardening", children: "Production hardening checklist" }) })
      ] })
    ] })
  },
  {
    id: "sign-in",
    title: "Sign-in &amp; identity",
    group: "Security",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Sign-in & identity" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Configure providers under ",
        /* @__PURE__ */ jsx("strong", { children: "Authentication" }),
        " (",
        /* @__PURE__ */ jsx("code", { children: "/admin/authentication" }),
        "). Env vars are only a fallback; database rows written from the admin UI take precedence."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Local" }),
      /* @__PURE__ */ jsx("p", { children: "Username/password with bcrypt. Optional TOTP 2FA for local accounts (user Settings \u2192 Security). Super Admins can disable another user\u2019s 2FA from the Users edit modal when needed." }),
      /* @__PURE__ */ jsx("h3", { children: "LDAP / Active Directory" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "LDAPS bind with a service account, Sync OUs, optional prune of users/groups outside those OUs, and a daily sync schedule. Use ",
        /* @__PURE__ */ jsx("strong", { children: "Test" }),
        " before enabling for production, then ",
        /* @__PURE__ */ jsx("strong", { children: "Sync AD" }),
        "."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "SAML 2.0" }),
      /* @__PURE__ */ jsx("p", { children: "IdP metadata via public URL (SSRF-guarded) or uploaded XML (preferred for internal IdPs; XML wins when both are set), SP entity ID, ACS URL (shown read-only), attribute mapping, and signature options. Login uses a one-time exchange code (Redis, short TTL) so JWTs are never placed in redirect URLs." }),
      /* @__PURE__ */ jsx("h3", { children: "OIDC" }),
      /* @__PURE__ */ jsx("p", { children: "Issuer, client ID/secret, scopes, claim mapping, PKCE authorize/callback flow, and the same one-time exchange pattern as SAML." }),
      /* @__PURE__ */ jsx("h3", { children: "Logout & revocation" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Logout increments the user\u2019s ",
        /* @__PURE__ */ jsx("code", { children: "token_version" }),
        ". Previously issued JWTs with a lower",
        " ",
        /* @__PURE__ */ jsx("code", { children: "ver" }),
        " claim are rejected. Password reset and related admin actions also bump the version where applicable."
      ] })
    ] })
  },
  {
    id: "sessions-csrf",
    title: "Sessions, cookies &amp; CSRF",
    group: "Security",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Sessions, cookies & CSRF" }),
      /* @__PURE__ */ jsxs("table", { className: "docs-table", children: [
        /* @__PURE__ */ jsx("thead", { children: /* @__PURE__ */ jsxs("tr", { children: [
          /* @__PURE__ */ jsx("th", { children: "Cookie" }),
          /* @__PURE__ */ jsx("th", { children: "Properties" })
        ] }) }),
        /* @__PURE__ */ jsxs("tbody", { children: [
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "alpha_router_session" }) }),
            /* @__PURE__ */ jsxs("td", { children: [
              "HttpOnly, ",
              /* @__PURE__ */ jsx("code", { children: "path=/api" }),
              ", SameSite=Lax \u2014 carries the JWT"
            ] })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "alpha_router_csrf" }) }),
            /* @__PURE__ */ jsxs("td", { children: [
              "Readable, ",
              /* @__PURE__ */ jsx("code", { children: "path=/" }),
              " \u2014 double-submit token; SPA sends ",
              /* @__PURE__ */ jsx("code", { children: "X-CSRF-Token" }),
              " on unsafe methods"
            ] })
          ] })
        ] })
      ] }),
      /* @__PURE__ */ jsxs("p", { children: [
        "CSRF is enforced for unsafe methods under ",
        /* @__PURE__ */ jsx("code", { children: "/api/" }),
        " when a session cookie is present. Login, 2FA, and SSO exchange paths keep Origin checks with defined exemptions; SAML ACS is fully exempt (IdP form POST). The",
        " ",
        /* @__PURE__ */ jsx("code", { children: "/v1" }),
        " gateway is outside CSRF (API-key auth only)."
      ] }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Allowed Origins include ",
        /* @__PURE__ */ jsx("code", { children: "FRONTEND_URL" }),
        ", loopback ",
        /* @__PURE__ */ jsx("code", { children: ":8080" }),
        ", and HTTP Origins on RFC1918 addresses (single-box LAN). ",
        /* @__PURE__ */ jsx("code", { children: "Secure" }),
        " cookies are set in production, with a carve-out for same-origin HTTP on private LAN installs."
      ] }),
      /* @__PURE__ */ jsxs(Warn, { children: [
        "Legacy browser Bearer JWT auth (",
        /* @__PURE__ */ jsx("code", { children: "ALLOW_LEGACY_BEARER_AUTH" }),
        ") is off by default. Enabling it bypasses the CSRF cookie path for API calls that send only ",
        /* @__PURE__ */ jsx("code", { children: "Authorization" }),
        " \u2014 keep it disabled in production."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Inactive users" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Disabled accounts can still authenticate for read-only access to their own chat history and media, but cannot send new messages or create spend. Soft-deleted accounts (",
        /* @__PURE__ */ jsx("code", { children: "deleted_at" }),
        " set) cannot authenticate."
      ] })
    ] })
  },
  {
    id: "rbac-model",
    title: "RBAC model",
    group: "Security",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "RBAC model" }),
      /* @__PURE__ */ jsx("p", { children: "Permissions are role slugs assigned per user (many roles supported). Admin menus are defined in eight categories matching the sidebar. Write access is least-privilege: if any of a user\u2019s roles for a menu is read-only, writes are denied." }),
      /* @__PURE__ */ jsx("h3", { children: "Primary assignable roles" }),
      /* @__PURE__ */ jsxs("table", { className: "docs-table", children: [
        /* @__PURE__ */ jsx("thead", { children: /* @__PURE__ */ jsxs("tr", { children: [
          /* @__PURE__ */ jsx("th", { children: "Role" }),
          /* @__PURE__ */ jsx("th", { children: "Access" })
        ] }) }),
        /* @__PURE__ */ jsxs("tbody", { children: [
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("strong", { children: "User" }) }),
            /* @__PURE__ */ jsxs("td", { children: [
              /* @__PURE__ */ jsx("code", { children: "/app" }),
              " only (chat, media, activity, manual)"
            ] })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("strong", { children: "Super Admin" }) }),
            /* @__PURE__ */ jsx("td", { children: "Full admin panel and destructive operations" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("strong", { children: "API Key Admin" }) }),
            /* @__PURE__ */ jsx("td", { children: "API Keys menu (full admin for that menu)" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsxs("td", { children: [
              /* @__PURE__ */ jsx("strong", { children: "Dashboard (read-only)" }),
              " / ",
              /* @__PURE__ */ jsx("strong", { children: "Reports Admin" })
            ] }),
            /* @__PURE__ */ jsx("td", { children: "Scoped access re-enabled for those menus" })
          ] })
        ] })
      ] }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Most other historical per-menu roles were removed from the assignable catalog; Super Admin covers those menus. Assign roles from ",
        /* @__PURE__ */ jsx("strong", { children: "Roles" }),
        " (bulk assign) or inline on the ",
        /* @__PURE__ */ jsx("strong", { children: "Users" }),
        " table."
      ] }),
      /* @__PURE__ */ jsx(Note, { children: "End-user menus (chat, media, user manual) are always writable for active accounts \u2014 they are not gated by admin RBAC write locks." })
    ] })
  },
  {
    id: "secrets-encryption",
    title: "Secrets &amp; encryption",
    group: "Security",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Secrets & encryption" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Provider API keys, SMTP passwords, LDAP/OIDC client secrets, and TOTP secrets are stored with Fernet encryption. The only encryption key is derived from ",
        /* @__PURE__ */ jsx("code", { children: "DATA_ENCRYPTION_KEY" }),
        " (PBKDF2). Plaintext, malformed ciphertext, and ciphertext from another key are rejected instead of being forwarded upstream."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Sandbox trust boundary" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Code interpreter workloads are sent to ",
        /* @__PURE__ */ jsx("code", { children: "alpha-router-sandbox-broker" }),
        ", which authenticates with a long Bearer token (",
        /* @__PURE__ */ jsx("code", { children: "SANDBOX_BROKER_TOKEN" }),
        " / ",
        /* @__PURE__ */ jsx("code", { children: "CODE_SANDBOX_BROKER_TOKEN" }),
        ", \u226532 characters) and starts disposable containers from ",
        /* @__PURE__ */ jsx("code", { children: "alpha-router-sandbox:latest" }),
        " with",
        " ",
        /* @__PURE__ */ jsx("code", { children: "--network none" }),
        ", read-only root, dropped capabilities, and resource limits. The broker\u2019s Docker socket mount remains the residual host trust boundary \u2014 keep the broker on an internal network only and never publish port ",
        /* @__PURE__ */ jsx("code", { children: "8081" }),
        ". Spreadsheet uploads are converted to CSV text before they reach the sandbox. Generated PDF/CSV/JSON/text artifacts are bounded and validated twice, then stored in the requesting user's Media library; no host volume is mounted into the sandbox. Each execution has a Job ID and an explicit cancel path, so Stop terminates the disposable container and releases its capacity slot."
      ] }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Workspace and artifact names may use any script (Persian, Arabic, Cyrillic, CJK), so a generated file such as",
        " ",
        /* @__PURE__ */ jsx("code", { children: "\u06AF\u0632\u0627\u0631\u0634-\u0645\u062F\u06CC\u0631\u06CC\u062A\u06CC.pdf" }),
        " is stored and downloadable under its own name. The name policy rejects only deceptive or non-local components: path separators, ",
        /* @__PURE__ */ jsx("code", { children: "." }),
        "/",
        /* @__PURE__ */ jsx("code", { children: ".." }),
        ", control characters, BiDi and zero-width formatting characters that hide the real extension, a leading dot or dash, and names over 128 characters or 255 UTF-8 bytes. The extension allowlist plus per-artifact content validation remain the controls that decide what may leave the sandbox."
      ] })
    ] })
  },
  {
    id: "hardening",
    title: "Production hardening",
    group: "Security",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Production hardening checklist" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          "Set ",
          /* @__PURE__ */ jsx("code", { children: "ENVIRONMENT=production" }),
          " and keep ",
          /* @__PURE__ */ jsx("code", { children: "PRODUCTION_GUARD_MODE=hard-fail" }),
          " until every flagged item is fixed."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Replace all placeholder secrets; set a dedicated ",
          /* @__PURE__ */ jsx("code", { children: "DATA_ENCRYPTION_KEY" }),
          "."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Require Redis authentication; wire ",
          /* @__PURE__ */ jsx("code", { children: "REDIS_PASSWORD" }),
          " (or an authenticated URL)."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Set ",
          /* @__PURE__ */ jsx("code", { children: "CODE_SANDBOX_BROKER_URL" }),
          ", a \u226532-character ",
          /* @__PURE__ */ jsx("code", { children: "SANDBOX_BROKER_TOKEN" }),
          ", and (for local API runs) matching ",
          /* @__PURE__ */ jsx("code", { children: "CODE_SANDBOX_BROKER_TOKEN" }),
          ". Verify the sandbox initializer exits with code zero, the broker becomes healthy, and keep ",
          /* @__PURE__ */ jsx("code", { children: "ALLOW_INSECURE_CODE_SUBPROCESS=false" }),
          "."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Lock OpenAPI docs to Super Admin (",
          /* @__PURE__ */ jsx("code", { children: "OPENAPI_ADMIN_ONLY=true" }),
          ")."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Use HTTPS for public ",
          /* @__PURE__ */ jsx("code", { children: "FRONTEND_URL" }),
          " / ",
          /* @__PURE__ */ jsx("code", { children: "API_PUBLIC_URL" }),
          "; enable HSTS when the public surface is TLS-terminated. Prefer ",
          /* @__PURE__ */ jsx("strong", { children: "Security \u2192 Security Settings" }),
          " for in-product certificates, then bind HTTP to loopback with ",
          /* @__PURE__ */ jsx("code", { children: "ALPHAROUTER_HTTP_BIND=127.0.0.1" }),
          "."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Keep all dangerous opt-in flags ",
          /* @__PURE__ */ jsx("code", { children: "false" }),
          " (see table below). Startup logs a warning if any are enabled."
        ] }),
        /* @__PURE__ */ jsx("li", { children: "Rotate the gateway master key away from any default; treat it as a full-power service credential." }),
        /* @__PURE__ */ jsx("li", { children: "Never publish sandbox-broker ports to the host or public network." })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Dangerous opt-in flags" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "These escape hatches default to ",
        /* @__PURE__ */ jsx("code", { children: "false" }),
        ". Do not enable them on shared or internet-facing hosts. Prefer the safer alternative in the last column."
      ] }),
      /* @__PURE__ */ jsxs("table", { className: "docs-table", children: [
        /* @__PURE__ */ jsx("thead", { children: /* @__PURE__ */ jsxs("tr", { children: [
          /* @__PURE__ */ jsx("th", { children: "Flag" }),
          /* @__PURE__ */ jsx("th", { children: "If enabled" }),
          /* @__PURE__ */ jsx("th", { children: "When (if ever)" }),
          /* @__PURE__ */ jsx("th", { children: "Safer alternative" })
        ] }) }),
        /* @__PURE__ */ jsxs("tbody", { children: [
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "ALLOW_LEGACY_BEARER_AUTH" }) }),
            /* @__PURE__ */ jsxs("td", { children: [
              "Browser JWT in ",
              /* @__PURE__ */ jsx("code", { children: "Authorization" }),
              " bypasses cookie + CSRF"
            ] }),
            /* @__PURE__ */ jsx("td", { children: "Never in production; rejected by production guard" }),
            /* @__PURE__ */ jsxs("td", { children: [
              "Session cookies for browsers; ",
              /* @__PURE__ */ jsx("code", { children: "/v1" }),
              " API keys for machines"
            ] })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "ALLOW_SSRF_PRIVATE_RANGES" }) }),
            /* @__PURE__ */ jsxs("td", { children: [
              /* @__PURE__ */ jsx("code", { children: "ssrf_guard" }),
              " allows private/loopback/metadata fetches"
            ] }),
            /* @__PURE__ */ jsx("td", { children: "Isolated internal lab only, with a written exception" }),
            /* @__PURE__ */ jsx("td", { children: "Upload SAML Metadata XML; expose internal docs via a controlled proxy" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "ALLOW_INSECURE_CODE_SUBPROCESS" }) }),
            /* @__PURE__ */ jsx("td", { children: "Code interpreter can run on the API host (development only)" }),
            /* @__PURE__ */ jsx("td", { children: "Local single-developer lab without Docker broker; never production" }),
            /* @__PURE__ */ jsxs("td", { children: [
              "Keep ",
              /* @__PURE__ */ jsx("code", { children: "CODE_SANDBOX_BROKER_URL" }),
              " + ",
              /* @__PURE__ */ jsx("code", { children: "SANDBOX_BROKER_TOKEN" })
            ] })
          ] })
        ] })
      ] }),
      /* @__PURE__ */ jsxs(Warn, { children: [
        "Copying ",
        /* @__PURE__ */ jsx("code", { children: "true" }),
        " for these flags from an old lab ",
        /* @__PURE__ */ jsx("code", { children: ".env" }),
        " into a shared server is a common misconfiguration. Leave them ",
        /* @__PURE__ */ jsx("code", { children: "false" }),
        " unless you deliberately accept the risk."
      ] }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Browser hardening: CSP starts in Report-Only mode; enforced CSP is opt-in via",
        " ",
        /* @__PURE__ */ jsx("code", { children: "CONTENT_SECURITY_POLICY" }),
        ". Review reports before enforcing."
      ] })
    ] })
  },
  {
    id: "security-settings-https",
    title: "HTTPS certificates",
    group: "Security",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "HTTPS certificates" }),
      /* @__PURE__ */ jsxs("p", { children: [
        /* @__PURE__ */ jsx("strong", { children: "Security \u2192 Security Settings" }),
        " stores a certificate and private key, then writes desired TLS state onto a shared volume. The ",
        /* @__PURE__ */ jsx("code", { children: "alpha-router-edge" }),
        " container (nginx, host network) watches that volume, runs ",
        /* @__PURE__ */ jsx("code", { children: "nginx -t" }),
        ", and reloads without restarting the application."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Upload PEM (certificate + key, optional chain) or PKCS#12. Private keys are encrypted at rest and never returned by the API." }),
        /* @__PURE__ */ jsx("li", { children: "Activate on port 443 or any free port that is not reserved by Alpharouter services." }),
        /* @__PURE__ */ jsxs("li", { children: [
          "On activate (and when Storage transfer limits change), the edge nginx config uses a",
          " ",
          /* @__PURE__ */ jsx("code", { children: "client_max_body_size" }),
          " derived from Storage max upload / chat total so large chat attachments are not rejected at the TLS edge before they reach the app."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Keep HTTP on 8080 during cutover, confirm ",
          /* @__PURE__ */ jsx("code", { children: "https://host:port/health" }),
          ", then set ",
          /* @__PURE__ */ jsx("code", { children: "ALPHAROUTER_HTTP_BIND=127.0.0.1" }),
          "."
        ] }),
        /* @__PURE__ */ jsx("li", { children: "Revert to HTTP from the same page if the listener does not come up." }),
        /* @__PURE__ */ jsx("li", { children: "The page shows an expiry warning when the active certificate is near the end of its validity (and an error banner after expiry). Replace the cert before clients start failing TLS." })
      ] }),
      /* @__PURE__ */ jsxs(Warn, { children: [
        "If HTTP stays published on ",
        /* @__PURE__ */ jsx("code", { children: "0.0.0.0:8080" }),
        " after HTTPS is on, clients can skip the edge proxy. Bind loopback after you confirm TLS."
      ] })
    ] })
  },
  {
    id: "security-settings-ip",
    title: "Admin IP restrictions",
    group: "Security",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Admin IP restrictions" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "The allowlist applies to ",
        /* @__PURE__ */ jsx("code", { children: "/admin" }),
        " and ",
        /* @__PURE__ */ jsx("code", { children: "/api/admin/*" }),
        " only. Login and end-user routes stay reachable so operators can recover."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "off" }),
          " \u2014 no restriction."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "monitor" }),
          " \u2014 log and increment ",
          /* @__PURE__ */ jsx("code", { children: "admin_ip_denied" }),
          " without blocking."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "enforce" }),
          " \u2014 deny unmatched clients. The API refuses to enable this unless the current browser IP is already listed."
        ] })
      ] }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Break-glass inside the app container:",
        " ",
        /* @__PURE__ */ jsx("code", { children: "python -m app.security_breakglass --disable-admin-ip-restriction" }),
        ". The env kill-switch is",
        " ",
        /* @__PURE__ */ jsx("code", { children: "ADMIN_IP_RESTRICTION_DISABLED=true" }),
        "."
      ] }),
      /* @__PURE__ */ jsxs(Note, { children: [
        /* @__PURE__ */ jsx("code", { children: "X-Forwarded-For" }),
        " is trusted only from ",
        /* @__PURE__ */ jsx("code", { children: "TRUSTED_PROXY_CIDRS" }),
        " (default loopback, which is the host-network edge)."
      ] })
    ] })
  },
  // ── Overview ──────────────────────────────────────────────────────────────
  {
    id: "admin-menu",
    title: "Admin menu map",
    group: "Overview",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Admin menu map" }),
      /* @__PURE__ */ jsx("p", { children: "The admin sidebar groups match RBAC categories. Items you cannot access are hidden. A read-only role can open menus but cannot save destructive changes (writes show as locked)." }),
      /* @__PURE__ */ jsxs("table", { className: "docs-table", children: [
        /* @__PURE__ */ jsx("thead", { children: /* @__PURE__ */ jsxs("tr", { children: [
          /* @__PURE__ */ jsx("th", { children: "Group" }),
          /* @__PURE__ */ jsx("th", { children: "Menus" })
        ] }) }),
        /* @__PURE__ */ jsxs("tbody", { children: [
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "User panel" }),
            /* @__PURE__ */ jsxs("td", { children: [
              "Shortcuts into ",
              /* @__PURE__ */ jsx("code", { children: "/app" }),
              " (Chat, Media, Activity, User Manual)"
            ] })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Overview" }),
            /* @__PURE__ */ jsx("td", { children: "Dashboard, Operations, Database" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Agents & Knowledge" }),
            /* @__PURE__ */ jsx("td", { children: "Overview, Agent Studio, Knowledge Bases, Tool Registry, Evaluations, Approvals, Audit" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Models & API" }),
            /* @__PURE__ */ jsx("td", { children: "Connections, Models, API Keys" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "People & access" }),
            /* @__PURE__ */ jsx("td", { children: "Roles, Users, Deleted Users, Groups, Plans, Authentication" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Security" }),
            /* @__PURE__ */ jsx("td", { children: "Security Settings (HTTPS certificates and admin IP allowlist)" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Integrations" }),
            /* @__PURE__ */ jsx("td", { children: "SMTP Server" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Data & reports" }),
            /* @__PURE__ */ jsx("td", { children: "Storage Management, Retention Policy, Memory, Reports, Projects, API Logs" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Developer" }),
            /* @__PURE__ */ jsx("td", { children: "Admin Guide, User Manual" })
          ] })
        ] })
      ] })
    ] })
  },
  {
    id: "admin-dashboard",
    title: "Dashboard",
    group: "Overview",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Dashboard" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin" }),
        ". Service-wide ",
        /* @__PURE__ */ jsx("strong", { children: "Activity" }),
        " for administrators \u2014 spend, requests, tokens, heatmaps, trends, and exploration tools. The same tabbed Activity UI is reused wherever usage is scoped (see ",
        /* @__PURE__ */ jsx("a", { href: "#admin-activity-scopes", children: "Activity scopes" }),
        ")."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Toolbar" }),
          " \u2014 period, group-by (model / app / user), timezone, filters (model, user, app, status, API key), CSV/PDF export."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Overview" }),
          " \u2014 KPIs with sparklines, top users/apps, usage and token charts, request heatmap."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Trends" }),
          " \u2014 models, users, API keys, and apps over time."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Explore" }),
          " \u2014 custom metric, grouping, rollup, ranking, chart type, and table; PDF download."
        ] })
      ] }),
      /* @__PURE__ */ jsxs(Note, { children: [
        "Personal usage for any signed-in user (including admins) is under ",
        /* @__PURE__ */ jsx("strong", { children: "Activity" }),
        " in the user panel (",
        /* @__PURE__ */ jsx("code", { children: "/app/my-activity" }),
        " or ",
        /* @__PURE__ */ jsx("code", { children: "/admin/my-activity" }),
        "). That view hides organization-wide dimensions such as \u201Ctop users\u201D and cannot filter by user."
      ] })
    ] })
  },
  {
    id: "admin-activity-scopes",
    title: "Activity scopes",
    group: "Overview",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Activity scopes" }),
      /* @__PURE__ */ jsx("p", { children: "Alpharouter uses one shared Activity experience (Overview \xB7 Trends \xB7 Explore) everywhere usage is analyzed. Each scope fixes the dataset and hides filters that would be meaningless (for example an API-key page does not offer an \u201CAPI key\u201D filter)." }),
      /* @__PURE__ */ jsxs("table", { className: "docs-table", children: [
        /* @__PURE__ */ jsx("thead", { children: /* @__PURE__ */ jsxs("tr", { children: [
          /* @__PURE__ */ jsx("th", { children: "Scope" }),
          /* @__PURE__ */ jsx("th", { children: "Path" }),
          /* @__PURE__ */ jsx("th", { children: "What it shows" })
        ] }) }),
        /* @__PURE__ */ jsxs("tbody", { children: [
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Service (Dashboard)" }),
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "/admin" }) }),
            /* @__PURE__ */ jsx("td", { children: "All organization traffic; full filters and Group-by" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "My Activity" }),
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "/admin/my-activity" }) }),
            /* @__PURE__ */ jsx("td", { children: "Signed-in user only; no user filter or user trends" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "User" }),
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "/admin/users/<id>/activity" }) }),
            /* @__PURE__ */ jsx("td", { children: "One user; no user filter" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Gateway API key" }),
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "/admin/api-keys/<id>/activity" }) }),
            /* @__PURE__ */ jsx("td", { children: "One gateway key; no API-key filter or API-key trends" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Connection" }),
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "/admin/connections/<id>/activity" }) }),
            /* @__PURE__ */ jsx("td", { children: "Models on that connection; Explore hides provider grouping" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Group" }),
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "/admin/groups/<id>/activity" }) }),
            /* @__PURE__ */ jsx("td", { children: "Members of the group; standard user/model/app filters" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Project" }),
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "/app/projects/<id>/activity" }) }),
            /* @__PURE__ */ jsxs("td", { children: [
              "One project's spend (Primary Owner, Owner, or Reports admin). Admin list:",
              " ",
              /* @__PURE__ */ jsx("code", { children: "/admin/project-usage" })
            ] })
          ] })
        ] })
      ] }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Gateway API key and User rows also link to scoped ",
        /* @__PURE__ */ jsx("strong", { children: "Logs" }),
        " (",
        /* @__PURE__ */ jsx("code", { children: "/admin/api-keys/<id>/logs" }),
        ") \u2014 the same API Logs table with the key pre-selected. User-scoped logs use query parameters on ",
        /* @__PURE__ */ jsx("code", { children: "/admin/logs" }),
        "."
      ] }),
      /* @__PURE__ */ jsxs(Note, { children: [
        /* @__PURE__ */ jsx("strong", { children: "Agent Audit" }),
        " (",
        /* @__PURE__ */ jsx("code", { children: "/admin/agent-activity" }),
        ") is separate: runtime guardrail and retrieval metadata, not billing analytics."
      ] })
    ] })
  },
  {
    id: "admin-operations",
    title: "Operations",
    group: "Overview",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Operations" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/operations" }),
        " (alias ",
        /* @__PURE__ */ jsx("code", { children: "/admin/debug" }),
        "). Infrastructure and API health \u2014 not billing analytics."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          "Time range selector and ",
          /* @__PURE__ */ jsx("strong", { children: "Check Now" }),
          " (records a metrics snapshot; the page also refreshes on an hourly cadence)."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Infrastructure" }),
          " \u2014 host CPU/memory, database size."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "API traffic" }),
          " \u2014 errors, latency, throughput."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Model experience" }),
          " \u2014 slow requests, P95, slowest models table (links into API Logs)."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Code Interpreter capacity" }),
          " \u2014 active/available turn leases, global and per-user ceilings, broker job counts, and editable operational limits. The environment ceiling remains a hard upper bound; rejection and cancellation counters are exposed by observability."
        ] })
      ] }),
      /* @__PURE__ */ jsxs(Note, { children: [
        "Code Interpreter requests above the configured ceiling are rejected before provider billing with",
        " ",
        /* @__PURE__ */ jsx("code", { children: "HTTP 429" }),
        " and ",
        /* @__PURE__ */ jsx("code", { children: "Retry-After" }),
        ". Observability counters are also available via",
        " ",
        /* @__PURE__ */ jsx("code", { children: "GET /api/admin/operations/observability" }),
        "."
      ] })
    ] })
  },
  {
    id: "admin-database",
    title: "Database",
    group: "Overview",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Database" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/database" }),
        ". Read-only monitor: connection status, engine, host CPU/RAM, DB size, ping, Alpharouter process RSS/CPU, and table row counts. Use ",
        /* @__PURE__ */ jsx("strong", { children: "Refresh" }),
        " to reload."
      ] })
    ] })
  },
  // ── Agents & Knowledge ────────────────────────────────────────────────────
  {
    id: "agents-knowledge-overview",
    title: "Agents & Knowledge overview",
    group: "Agents & Knowledge",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Agents & Knowledge overview" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/agents" }),
        ". This area governs specialist behavior, immutable configuration versions, authorized Knowledge releases, Tool contracts, evaluation gates, and runtime evidence."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Overview" }),
          " \u2014 KPIs and last-24-hour runtime health. The Knowledge number counts live documents only (",
          /* @__PURE__ */ jsx("code", { children: "draft" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: "active" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: "superseded" }),
          "), not revoked or deleted rows. Runtime tiles for Turns, Guardrail blocked, and Failed open ",
          /* @__PURE__ */ jsx("strong", { children: "Audit" }),
          " with matching Runtime filters; Success rate is a derived percentage and is not a link. Below the quick-start cards,",
          /* @__PURE__ */ jsx("strong", { children: "Agent spend" }),
          " sums chat-turn cost for the same 24 hours (not Knowledge ingest). Top Agents open that Agent\u2019s Activity dashboard."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Agent Studio" }),
          " \u2014 create or clone a draft, edit the operator policy form, bind Knowledge, submit for review, publish, and roll back. The Agent \u22EE menu includes the same ",
          /* @__PURE__ */ jsx("strong", { children: "Activity" }),
          "usage dashboard as Users and Connections, scoped to that Agent\u2019s chat turns."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Knowledge Bases" }),
          " \u2014 upload and review documents, publish indexed releases, configure connectors, and retry durable jobs. Removing a file from Documents is a ",
          /* @__PURE__ */ jsx("em", { children: "revoke" }),
          ", not a hard delete."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Tool Registry" }),
          " \u2014 versioned schemas, side-effect classification, approvals, and execution limits."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Evaluations" }),
          " \u2014 versioned FA/EN golden datasets, deterministic scorecards, and publish-gate readiness."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Approvals" }),
          " \u2014 maker-checker queues for Agent versions, Knowledge bindings, document versions (including project Resource uploads), and tools. Each card shows the submitter's name (display name or username), not a user id."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Audit" }),
          " \u2014 append-only lifecycle evidence, legal holds, retention, and metadata-only runtime outcomes (blocked/failed turns). This is not the usage/spend Activity page."
        ] })
      ] }),
      /* @__PURE__ */ jsx(Note, { children: "New Agents are configuration work in Agent Studio: create the Agent and its draft version, curate a Knowledge Base and evaluation set, complete approvals, then publish. No application code change is required." })
    ] })
  },
  {
    id: "agent-studio",
    title: "Agent Studio",
    group: "Agents & Knowledge",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Agent Studio" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/agents/studio" }),
        ". Published versions are immutable. Edit a ",
        /* @__PURE__ */ jsx("strong", { children: "draft" }),
        ", or use ",
        /* @__PURE__ */ jsx("strong", { children: "Clone to draft" }),
        " on a published version, then publish the new version when review is complete."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Policy form" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "The primary editor is an operator form: primary model, routing keywords (chip list), example questions, English/Persian disclaimers, and retrieval toggles (enabled, require evidence, citations required). Raw policy JSON stays under collapsed ",
        /* @__PURE__ */ jsx("strong", { children: "Advanced policy JSON" }),
        ". Do not use the form to weaken fail-closed citation or guardrail hooks; those remain platform policy."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Knowledge bindings" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          "On a draft, ",
          /* @__PURE__ */ jsx("strong", { children: "+ Add knowledge" }),
          " opens a search-and-select modal. Already-bound Knowledge Bases are hidden. Binding still requires Knowledge (and, for sensitive KBs, domain) approval unless Super Admin break-glass auto-approves."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Draft chips include \xD7. Confirming sets the binding to ",
          /* @__PURE__ */ jsx("code", { children: "revoked" }),
          " and writes audit; the row is not hard-deleted (unique constraint on version + Knowledge Base). Adding the same KB later reactivates that row."
        ] }),
        /* @__PURE__ */ jsx("li", { children: "Published versions are read-only. Clone to draft, then add or remove bindings on the new draft. Clone copies live bindings and skips revoked/suspended ones." })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Activity (usage)" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "The Agent \u22EE menu ",
        /* @__PURE__ */ jsx("strong", { children: "Activity" }),
        " item opens the same spend/requests/tokens dashboard used for Users, Connections, API Keys, and Groups, filtered to this Agent\u2019s chat turns. Path:",
        " ",
        /* @__PURE__ */ jsx("code", { children: "/admin/agents/<agent-id>/activity" }),
        ". Filters that still apply: user, model, API key, app, and success/fail. Group-by is omitted because the page is already scoped to one Agent."
      ] }),
      /* @__PURE__ */ jsxs(Note, { children: [
        "Agent Activity counts chat-turn cost linked through ",
        /* @__PURE__ */ jsx("code", { children: "agent_runs" }),
        ". It does not include Knowledge embedding or index-build jobs. For blocked-turn reasons, use ",
        /* @__PURE__ */ jsx("strong", { children: "Audit" }),
        ", not Activity."
      ] })
    ] })
  },
  {
    id: "knowledge-release-workflow",
    title: "Knowledge release workflow",
    group: "Agents & Knowledge",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Knowledge release workflow" }),
      /* @__PURE__ */ jsxs("ol", { children: [
        /* @__PURE__ */ jsx("li", { children: "Set the Knowledge Base owner, sensitivity, retention, and explicit ACL. Deny always wins." }),
        /* @__PURE__ */ jsx("li", { children: "Upload an authoritative revision or configure a connector. Source bytes enter encrypted quarantine." }),
        /* @__PURE__ */ jsx("li", { children: "Wait for malware, format, parser, OCR (when required), and prompt-injection checks. Failed jobs are visible and retriable; unsafe content remains unavailable." }),
        /* @__PURE__ */ jsx("li", { children: "A reviewer other than the uploader approves the immutable document version. Blocked injection findings need an explicit recorded override." }),
        /* @__PURE__ */ jsx("li", { children: "Create a release from reviewed versions. A different publisher submits the release for dense/sparse indexing." }),
        /* @__PURE__ */ jsx("li", { children: "The worker builds and validates a blue/green Qdrant index, switches the alias atomically, and only then marks the release published." })
      ] }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Removing a PDF from Documents is ",
        /* @__PURE__ */ jsx("strong", { children: "revoke" }),
        ": the document leaves retrieval immediately, but the row remains for audit and retention. After the configured days, ",
        /* @__PURE__ */ jsx("strong", { children: "Run cleanup" }),
        " purges stored files and vectors and marks the document ",
        /* @__PURE__ */ jsx("code", { children: "deleted" }),
        " (hidden from the Documents list). The Overview Knowledge KPI ignores both ",
        /* @__PURE__ */ jsx("code", { children: "revoked" }),
        " and ",
        /* @__PURE__ */ jsx("code", { children: "deleted" }),
        " so it matches live corpus size."
      ] }),
      /* @__PURE__ */ jsxs(Note, { children: [
        "Project ",
        /* @__PURE__ */ jsx("strong", { children: "Resources" }),
        " uploads use the same scan/extract/review path, stored on a private internal Knowledge Base per project. Approving the document version (Published) is what project members wait for. Ordinary project chat may then inject short PostgreSQL excerpts; it does ",
        /* @__PURE__ */ jsx("em", { children: "not" }),
        " query the Qdrant release index. Bind that Knowledge Base to an Agent and publish a release only when specialist retrieval should use it."
      ] }),
      /* @__PURE__ */ jsx(Warn, { children: "PostgreSQL is the source of truth and Qdrant is rebuildable derived state. Never mark a release or index active manually to work around a failed job. Fix the dependency, retry the durable job, and preserve its audit trail." })
    ] })
  },
  {
    id: "agent-evaluation-workflow",
    title: "Evaluation and publish gates",
    group: "Agents & Knowledge",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Evaluation and publish gates" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/agent-evaluations" }),
        ". Publish-gate datasets must include Persian and English cases covering routing, retrieval, citation, abstention, ACL, and prompt injection. Active datasets are immutable; create a new dataset version to change expectations."
      ] }),
      /* @__PURE__ */ jsxs("ol", { children: [
        /* @__PURE__ */ jsx("li", { children: "Import or replace cases while the dataset is a draft and review every expected document-version ID." }),
        /* @__PURE__ */ jsx("li", { children: "Activate the curated dataset to freeze its snapshot." }),
        /* @__PURE__ */ jsx("li", { children: "Run the exact Agent version and upload observations for every enabled case." }),
        /* @__PURE__ */ jsx("li", { children: "Confirm retrieval recall@10, routing accuracy, abstention, citation integrity, injection resistance, case pass rate, and zero ACL leaks meet the configured thresholds." }),
        /* @__PURE__ */ jsx("li", { children: "Complete independent human review when required. A passing run applies only to that immutable snapshot and Agent-version fingerprint." })
      ] }),
      /* @__PURE__ */ jsx(Note, { children: "Publishing or rolling back an Agent version fails closed when any active publish-gate dataset lacks a passing, current evaluation." })
    ] })
  },
  {
    id: "agent-operations",
    title: "Agent operations & incidents",
    group: "Agents & Knowledge",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Agent operations & incidents" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/agent-activity" }),
        " (",
        /* @__PURE__ */ jsx("strong", { children: "Audit" }),
        " in the sidebar). Runtime health on Overview deep-links here with ",
        /* @__PURE__ */ jsx("code", { children: "?source=runtime&since_hours=24" }),
        " and, for blocked or failed tiles,",
        " ",
        /* @__PURE__ */ jsx("code", { children: "status=blocked" }),
        " or ",
        /* @__PURE__ */ jsx("code", { children: "status=failed" }),
        ". Events are metadata-only: Agent name, reason code (for example ",
        /* @__PURE__ */ jsx("code", { children: "citation_validation_failed" }),
        "), retrieval outcome, and guardrail evidence. Prompts and provider output are not stored."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          "Scrape ",
          /* @__PURE__ */ jsx("code", { children: "/metrics" }),
          " with its production Bearer token. Alert on failed Agent runs, retrieval failure, queue backlog/dead letters, ACL denials, and latency/error-budget burn."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Correlate JSON logs with ",
          /* @__PURE__ */ jsx("code", { children: "x-request-id" }),
          ", trace ID, and span ID. Prompts, retrieved text, secrets, and credentials are intentionally absent from telemetry."
        ] }),
        /* @__PURE__ */ jsx("li", { children: "When citation integrity fails closed, the user sees a localized safe message (English or Persian) instead of the uncited model output. Do not relax fail-closed citation rules to make the KPI look healthier; fix retrieval, the draft prompt, or the Knowledge binding." }),
        /* @__PURE__ */ jsx("li", { children: "For bad knowledge, revoke the document, verify it leaves the active release/index, and rerun citation/ACL evaluations. Apply a legal hold before retention when evidence must be preserved." }),
        /* @__PURE__ */ jsxs("li", { children: [
          "For a bad Agent version, stop new publication, roll back only to a version that passes all current active gates, and verify UI plus ",
          /* @__PURE__ */ jsx("code", { children: "/v1/chat/completions" }),
          "."
        ] }),
        /* @__PURE__ */ jsx("li", { children: "Restore PostgreSQL, SeaweedFS, Redis durability as applicable, then rebuild Qdrant indexes from authoritative releases. Validate aliases and point counts before reopening traffic." })
      ] })
    ] })
  },
  // ── Models & API ──────────────────────────────────────────────────────────
  {
    id: "admin-connections",
    title: "Connections",
    group: "Models & API",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Connections" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/connections" }),
        ". Each connection stores a provider type, encrypted API key, optional base URL, and sync schedule."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Create / edit" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          "Name, provider (for example ",
          /* @__PURE__ */ jsx("code", { children: "openrouter" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: "openai" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: "custom" }),
          ")"
        ] }),
        /* @__PURE__ */ jsx("li", { children: "Base URL (optional; provider defaults apply when empty)" }),
        /* @__PURE__ */ jsx("li", { children: "API key (required on create; leave blank on edit to keep the existing key)" }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Sync interval in hours (",
          /* @__PURE__ */ jsx("code", { children: "0" }),
          " = manual sync only)"
        ] })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Actions" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Sync now" }),
          " \u2014 fetch models/pricing from the provider (UI \u201Cflash\u201D briefly disables catalog rows during refresh)."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Enable / Disable" }),
          " \u2014 toggles the connection and its models."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Activity" }),
          " (",
          /* @__PURE__ */ jsx("code", { children: "/admin/connections/<id>/activity" }),
          ") / changelog \u2014 usage for models on this connection and audit of connection changes."
        ] })
      ] }),
      /* @__PURE__ */ jsxs(Warn, { children: [
        "Creating a connection does not sync automatically \u2014 run ",
        /* @__PURE__ */ jsx("strong", { children: "Sync now" }),
        " before enabling models for users."
      ] })
    ] })
  },
  {
    id: "admin-models",
    title: "Models",
    group: "Models & API",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Models" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/models" }),
        ". Catalog entries synced from Connections. Input/output cost per 1K tokens is displayed read-only from the provider."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Search and kind filters (chat, image, \u2026)." }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "New" }),
          " \u2014 dropdown of ",
          /* @__PURE__ */ jsx("code", { children: "1d" }),
          " / ",
          /* @__PURE__ */ jsx("code", { children: "3d" }),
          " / ",
          /* @__PURE__ */ jsx("code", { children: "7d" }),
          " /",
          " ",
          /* @__PURE__ */ jsx("code", { children: "14d" }),
          " / ",
          /* @__PURE__ */ jsx("code", { children: "30d" }),
          " shows models first listed in Alpha Router in that window. Existing catalog rows without a first-seen time stay hidden from this filter."
        ] }),
        /* @__PURE__ */ jsx("li", { children: "Browse (tiles) or table view; per-model enable toggle." }),
        /* @__PURE__ */ jsx("li", { children: "Bulk edit: turn ON, OFF, or delete selected models." }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Set Default" }),
          " \u2014 select one public, enabled, text-capable model. New chats use it only when the user has not chosen a personal default. Existing user defaults are never overwritten."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Access" }),
          " \u2014 Public (all users) or Private (assigned users and/or groups only). Super admins always see private models. Gateway keys inherit the owner's catalog access; they cannot widen access beyond the owner through key settings."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Code Interpreter" }),
          " column \u2014 measured compatibility per model, with probe history and manual pinning."
        ] })
      ] }),
      /* @__PURE__ */ jsxs(Note, { children: [
        "Only enabled models on active connections appear in the chat model picker and ",
        /* @__PURE__ */ jsx("code", { children: "/v1/models" }),
        "."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Code Interpreter compatibility" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Not every text model can complete the Code Interpreter flow: some never emit a ",
        /* @__PURE__ */ jsx("code", { children: "```python" }),
        " block, and some providers reject the tool-calling schema (for example with ",
        /* @__PURE__ */ jsx("code", { children: "MALFORMED_FUNCTION_CALL" }),
        "). Alpharouter therefore ",
        /* @__PURE__ */ jsx("em", { children: "measures" }),
        " compatibility per Connection + model instead of hardcoding vendor names, so newly released models are handled without a code change."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Unknown" }),
          " \u2014 never measured. The model stays selectable so new releases are not lost."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Verified" }),
          " \u2014 a probe or a real chat turn completed the whole flow (Python block \u2192 sandbox execution \u2192 artifact \u2192 follow-up answer)."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Quarantined" }),
          " \u2014 repeated or hard runtime failures. Hidden from the picker and rejected by the API until the quarantine expires and the next probe runs."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Blocked" }),
          " \u2014 a probe proved the flow fails. Re-probed automatically about once a day."
        ] })
      ] }),
      /* @__PURE__ */ jsx("p", { children: "A scheduled job probes a small batch of due models every 30 minutes (claimed with row locks so multiple workers cannot pay for the same probe twice). Probe cost is recorded as a normal system usage operation." }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Evidence is weighted by what it actually proves. Transient provider problems (rate limits, timeouts, auth errors) and unclassified upstream errors never hide a model on their own \u2014 they lower the health score and schedule an earlier re-probe, and a model that already passed keeps its verified status. Only repeated unclassified failures escalate. Models the provider cannot serve interactively at all (batch-only ids, retired ids, no routable provider) are blocked with reason ",
        /* @__PURE__ */ jsx("code", { children: "model_unavailable" }),
        " and re-checked weekly instead of daily."
      ] }),
      /* @__PURE__ */ jsx("p", { children: "For OpenRouter Auto Router, Alpharouter derives per-request routing constraints from this registry: verified models become the allowed pool and blocked models are excluded. The Auto Router entry itself is never hidden. Because the router reports its alias while streaming, the concretely selected model is resolved from the provider afterwards, so evidence is credited to the model that actually ran the flow rather than to the alias." }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Open the Code Interpreter cell to review evidence, run a probe on demand, or pin",
        " ",
        /* @__PURE__ */ jsx("strong", { children: "Force allow" }),
        " / ",
        /* @__PURE__ */ jsx("strong", { children: "Force block" }),
        ". Pinning overrides all automatic measurement until you switch back to ",
        /* @__PURE__ */ jsx("strong", { children: "Automatic" }),
        ". Because a pin silently outranks every measurement, each change is recorded in the same evidence list with the administrator who made it."
      ] })
    ] })
  },
  {
    id: "admin-api-keys",
    title: "API Keys",
    group: "Models & API",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "API Keys" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/api-keys" }),
        ". Admin-issued ",
        /* @__PURE__ */ jsx("strong", { children: "gateway keys" }),
        " for OpenAI-compatible clients (Open WebUI, scripts, IDEs). These are separate from ",
        /* @__PURE__ */ jsx("strong", { children: "personal API keys" }),
        " that employees create in Settings \u2192 API Key (one per user, debits that user's monthly budget)."
      ] }),
      /* @__PURE__ */ jsxs("table", { className: "docs-table", children: [
        /* @__PURE__ */ jsx("thead", { children: /* @__PURE__ */ jsxs("tr", { children: [
          /* @__PURE__ */ jsx("th", { children: "Key type" }),
          /* @__PURE__ */ jsx("th", { children: "Created on" }),
          /* @__PURE__ */ jsx("th", { children: "Spend debited from" }),
          /* @__PURE__ */ jsx("th", { children: "Typical use" })
        ] }) }),
        /* @__PURE__ */ jsxs("tbody", { children: [
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Gateway API key" }),
            /* @__PURE__ */ jsx("td", { children: "API Keys" }),
            /* @__PURE__ */ jsx("td", { children: "Key credit limit (period pool)" }),
            /* @__PURE__ */ jsx("td", { children: "Integrations, shared service accounts" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "User API key" }),
            /* @__PURE__ */ jsx("td", { children: "Users" }),
            /* @__PURE__ */ jsx("td", { children: "That user's monthly plan budget" }),
            /* @__PURE__ */ jsx("td", { children: "Personal automation for one employee" })
          ] })
        ] })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Key settings" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Owner" }),
          " (required) \u2014 attribution in logs and Activity; also defines which catalog models the key may use through Public/Private ACL. Owner does ",
          /* @__PURE__ */ jsx("em", { children: "not" }),
          " mean spend is taken from the owner's personal monthly budget."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Name" }),
          " \u2014 label in admin UI and exports."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Credit limit (USD)" }),
          " and ",
          /* @__PURE__ */ jsx("strong", { children: "reset period" }),
          " (daily / weekly / monthly). Empty or 0 = no cap on the key itself."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Expiration" }),
          " \u2014 never, or auto-deactivate after N days."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Allowed connections" }),
          " \u2014 optional multi-select allowlist. When enabled, the key may only call models on those connections. When disabled, every active connection is eligible (subject to other rules below). If a restricted key loses all of its connections (disabled or deleted), it does ",
          /* @__PURE__ */ jsx("em", { children: "not" }),
          " fall back to \u201Call connections\u201D \u2014 it stops working until you edit the key."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Allowed models" }),
          " \u2014 optional multi-select allowlist by catalog model ID. When enabled, the key only sees and may call those models. The picker lists enabled models the owner can access, optionally narrowed by the connection allowlist. An empty selection while restriction is on denies all model traffic. Allowlist never grants models the owner cannot already access."
        ] })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Policy layers (gateway keys)" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "For ",
        /* @__PURE__ */ jsx("code", { children: "/v1/models" }),
        " and all gateway completion paths, a model must pass ",
        /* @__PURE__ */ jsx("strong", { children: "every" }),
        " enabled layer:"
      ] }),
      /* @__PURE__ */ jsxs("ol", { children: [
        /* @__PURE__ */ jsx("li", { children: "Model enabled on an active connection" }),
        /* @__PURE__ */ jsx("li", { children: "Connection allowlist (if restricted)" }),
        /* @__PURE__ */ jsx("li", { children: "Catalog Public/Private ACL evaluated for the key owner" }),
        /* @__PURE__ */ jsx("li", { children: "Model allowlist (if restricted)" }),
        /* @__PURE__ */ jsx("li", { children: "Key active, not expired, and within credit limit" })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Client usage" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "The plaintext key is shown once at creation (and can be emailed to the owner). Clients call",
        " ",
        /* @__PURE__ */ jsx("code", { children: "/v1/*" }),
        " with ",
        /* @__PURE__ */ jsx("code", { children: "Authorization: Bearer <key>" }),
        ". See",
        " ",
        /* @__PURE__ */ jsx("a", { href: "#platform-api", children: "Platform API (/v1)" }),
        "."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Table & row actions" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          "Columns include Connections and Models summaries (",
          /* @__PURE__ */ jsx("strong", { children: "All" }),
          ", ",
          /* @__PURE__ */ jsx("strong", { children: "None" }),
          ", or named entries)."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Edit" }),
          " \u2014 change settings; header shortcuts to Activity and Logs."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Activity" }),
          " \u2014 ",
          /* @__PURE__ */ jsx("code", { children: "/admin/api-keys/<id>/activity" }),
          " (scoped Dashboard)."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Logs" }),
          " \u2014 ",
          /* @__PURE__ */ jsx("code", { children: "/admin/api-keys/<id>/logs" }),
          " (scoped API Logs)."
        ] }),
        /* @__PURE__ */ jsx("li", { children: "Enable / disable, delete, bulk actions, change log on the Activity page footer." })
      ] }),
      /* @__PURE__ */ jsx(Warn, { children: "Restricted keys with an empty connection or model selection are intentionally unusable until an administrator adds at least one entry or turns restriction off." })
    ] })
  },
  // ── People & access ───────────────────────────────────────────────────────
  {
    id: "admin-roles",
    title: "Roles",
    group: "People & access",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Roles" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/roles" }),
        ". Lists the built-in RBAC catalog (name, description, category, read-only flag). You do not create custom role definitions here \u2014 you ",
        /* @__PURE__ */ jsx("strong", { children: "assign" }),
        " existing roles to users (bulk assign from selected roles)."
      ] }),
      /* @__PURE__ */ jsxs("p", { children: [
        "See ",
        /* @__PURE__ */ jsx("a", { href: "#rbac-model", children: "RBAC model" }),
        " for the intended role set."
      ] })
    ] })
  },
  {
    id: "admin-users",
    title: "Users",
    group: "People & access",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Users" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/users" }),
        ". Directory of accounts with filters (status, email, department, job title, role, group, user plan)."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Capabilities" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Create local users (username, password, profile fields, role, optional group/plan)." }),
        /* @__PURE__ */ jsx("li", { children: "Inline edit of profile fields, multi-role assignment, and plan (direct / inherit from group / none)." }),
        /* @__PURE__ */ jsx("li", { children: "Activate / deactivate, reset budget period usage. Personal API keys are self-service (Settings \u2192 API Key); admins do not issue them from this page." }),
        /* @__PURE__ */ jsx("li", { children: "Soft-delete local users (moves to Deleted Users). Directory-synced users follow LDAP/SSO lifecycle rules." }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Per-user Activity (",
          /* @__PURE__ */ jsx("code", { children: "/admin/users/<id>/activity" }),
          ") and User Storage (admin view of that user's media)."
        ] }),
        /* @__PURE__ */ jsx("li", { children: "Super Admin: disable TOTP for a local user from the edit modal." }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Online Users" }),
          " \u2014 status filter for accounts signed in with an open tab right now. A browser tab reports itself every 30s while visible and the marker expires after ",
          /* @__PURE__ */ jsx("code", { children: "PRESENCE_TTL_SECONDS" }),
          " ",
          "(90s by default), so a closed tab drops off within about a minute. While the filter is active the list refreshes every 20s. Presence lives only in Redis; set ",
          /* @__PURE__ */ jsx("code", { children: "PRESENCE_ENABLED=false" }),
          " to turn it off. If Redis is unreachable the filter is ignored and the page says so rather than showing an empty table."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "User Plan" }),
          " \u2014 filters by the effective budget plan shown in the table: a direct user assignment, or a plan inherited from a group or department. ",
          /* @__PURE__ */ jsx("strong", { children: "No Plan" }),
          " includes accounts with an explicit block and those that inherit nothing. Combined with the other filters."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Export to CSV" }),
          " downloads the current filtered set (same query as the table) via",
          " ",
          /* @__PURE__ */ jsx("code", { children: "GET /api/admin/users/export" }),
          ". Columns include profile fields, roles, effective plan, plan source (assigned / group / department / none), budget, and status. The file is UTF-8 with BOM for Excel."
        ] })
      ] }),
      /* @__PURE__ */ jsxs(Note, { children: [
        /* @__PURE__ */ jsx("strong", { children: "Online" }),
        " is not ",
        /* @__PURE__ */ jsx("strong", { children: "Active" }),
        ". Active means the account is enabled; Online means someone is signed in with an open tab right now. Deactivated users can still sign in to browse history but cannot send chat or create new spend, and they never show an online dot."
      ] })
    ] })
  },
  {
    id: "admin-deleted-users",
    title: "Deleted Users",
    group: "People & access",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Deleted Users" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/deleted-users" }),
        ". Soft-deleted accounts that can no longer sign in. You can open historical Activity / media, or permanently delete (single or bulk) with confirmation. Permanent delete removes residual account data according to cleanup services \u2014 use carefully."
      ] })
    ] })
  },
  {
    id: "admin-groups",
    title: "Groups",
    group: "People & access",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Groups" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/groups" }),
        ". Local groups plus directory-synced groups (",
        /* @__PURE__ */ jsx("code", { children: "ldap" }),
        " /",
        " ",
        /* @__PURE__ */ jsx("code", { children: "saml" }),
        " source)."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Create/edit local groups; assign a budget plan to the group." }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Sync LDAP" }),
          " when AD sync is configured."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Show members (opens Users filtered),",
          " ",
          /* @__PURE__ */ jsx("strong", { children: "Activity" }),
          " (",
          /* @__PURE__ */ jsx("code", { children: "/admin/groups/<id>/activity" }),
          "), deactivate all members, delete group."
        ] }),
        /* @__PURE__ */ jsx("li", { children: "Bulk assign plans or deactivate members." })
      ] })
    ] })
  },
  {
    id: "admin-plans",
    title: "Plans",
    group: "People & access",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Plans" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/plans" }),
        ". A plan is a named monthly USD budget. Assign plans to a user, a group, or a department string. Users inherit the resolved monthly limit into their budget cache."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Create/edit: name + monthly budget USD." }),
        /* @__PURE__ */ jsx("li", { children: "Assign plan modal: choose target type and entity." }),
        /* @__PURE__ */ jsx("li", { children: "Show members: who currently resolves to this plan." })
      ] }),
      /* @__PURE__ */ jsxs("p", { children: [
        "See also ",
        /* @__PURE__ */ jsx("a", { href: "#budget-pricing", children: "Budget & pricing" }),
        "."
      ] })
    ] })
  },
  {
    id: "admin-authentication",
    title: "Authentication",
    group: "People & access",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Authentication" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/authentication" }),
        ". Tabs for Active Directory (LDAP), SAML, and OIDC. Details of each protocol are under ",
        /* @__PURE__ */ jsx("a", { href: "#sign-in", children: "Sign-in & identity" }),
        "."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "LDAP" }),
          " \u2014 enable, DC host, service account, Sync OUs, prune option, daily schedule, Test / Sync."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "SAML" }),
          " \u2014 enable, metadata, entity ID, ACS (read-only), attribute mapping, signature options."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "OIDC" }),
          " \u2014 enable, issuer, client credentials, redirect URI (read-only), scopes, claim mapping."
        ] })
      ] }),
      /* @__PURE__ */ jsx(Warn, { children: "Store IdP credentials carefully; they are encrypted at rest. Prefer HTTPS IdP endpoints in production." })
    ] })
  },
  // ── Integrations ──────────────────────────────────────────────────────────
  {
    id: "admin-smtp",
    title: "SMTP Server",
    group: "Integrations",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "SMTP Server" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/smtp" }),
        ". Outbound mail settings used when emailing reports or credentials."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Host, port, username, password, from address, Use TLS" }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Save" }),
          " and ",
          /* @__PURE__ */ jsx("strong", { children: "Test connection" })
        ] })
      ] }),
      /* @__PURE__ */ jsx(Note, { children: "Test uses the values you enter; point it only at trusted SMTP servers." })
    ] })
  },
  // ── Data & reports ────────────────────────────────────────────────────────
  {
    id: "admin-storage-management",
    title: "Storage Management",
    group: "Data & reports",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Storage Management" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/storage-management" }),
        ". Object-storage usage for user and project media."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Total size/files, expired count, breakdown by kind; refresh." }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "DELETE ALL MEDIA" }),
          " \u2014 destructive, multi-step confirm."
        ] }),
        /* @__PURE__ */ jsx("li", { children: "Per-user quota (GB) for each user's personal Media library." }),
        /* @__PURE__ */ jsx("li", { children: "Per-project quota (GB) for each project's Media library (1\u2013100 GB, default 1 GB). Lowering the limit does not delete existing files; projects over quota cannot upload until they free space." }),
        /* @__PURE__ */ jsx("li", { children: "Global transfer limits: max upload (MB), max chat attachments total per message (MB), maximum files per upload, max ZIP download (MB). Chat attachments may include images, video, audio, and documents; per-file size follows max upload and the combined size of one message follows chat total." }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Saving transfer limits publishes a shared request-body ceiling to the TLS volume and, when HTTPS edge is enabled, rewrites ",
          /* @__PURE__ */ jsx("code", { children: "client_max_body_size" }),
          " on ",
          /* @__PURE__ */ jsx("code", { children: "alpha-router-edge" }),
          " to",
          " ",
          /* @__PURE__ */ jsx("code", { children: "max(upload, chat total) + margin" }),
          " (hard cap 2048 MB). The Save API does not wait for nginx reload (edge applies within a few seconds). If HTTPS is off, app limits still apply on port 8080."
        ] }),
        /* @__PURE__ */ jsx("li", { children: "Code Interpreter workspace limits: maximum files per turn and maximum extracted-text size. The product limit can support 100 or more small files, while a higher broker hard ceiling still protects against pathological zero-byte file counts and payload abuse." })
      ] }),
      /* @__PURE__ */ jsxs(Note, { children: [
        "Any reverse proxy in front of Alpha Router (outside ",
        /* @__PURE__ */ jsx("code", { children: "alpha-router-edge" }),
        ") must allow request bodies at least as large as your Storage max upload / chat total settings, and should use long",
        " ",
        /* @__PURE__ */ jsx("code", { children: "proxy_read_timeout" }),
        " / ",
        /* @__PURE__ */ jsx("code", { children: "proxy_send_timeout" }),
        " values for slow image or video generation (often well over a minute). Otherwise clients may see HTML 413/504 errors from that outer gateway even when the app later finishes the job."
      ] })
    ] })
  },
  {
    id: "admin-retention",
    title: "Retention Policy",
    group: "Data & reports",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Retention Policy" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/retention-policy" }),
        ". Scheduled cleanup for media and chat messages (server timezone)."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Media" }),
          " \u2014 retention days, daily cleanup hour/minute, purge expired now."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Chat" }),
          " \u2014 enable policy, retention days, daily schedule, purge expired messages now."
        ] })
      ] }),
      /* @__PURE__ */ jsx(Note, { children: "Users can also schedule personal media cleanup from the Media library; that schedule is separate from the global media retention settings here." })
    ] })
  },
  {
    id: "admin-memory",
    title: "Memory",
    group: "Data & reports",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Automatic user memory" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/memory" }),
        ". Long-term memory for user chat: a background extractor mines durable facts after non-private turns, stores them in PostgreSQL (source of truth), and indexes IDs (never memory text) in Qdrant for semantic recall."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Extraction model" }),
          " \u2014 required. Until you pick an enabled text model, extraction is a no-op (no surprise cost on upgrade). Cost is recorded as a system operation, not against the user budget."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Embedding model" }),
          " \u2014 ",
          /* @__PURE__ */ jsx("code", { children: "provider:external_id" }),
          ". Dimensions are filled from the selected model and stay editable if you need a smaller size. Clearing the model turns off vector search (PostgreSQL recency/lexical only). Changing the model or dimensions requires a rebuild."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Sensitive categories" }),
          " \u2014 allow-list for storing classified facts (health, financial, \u2026). Empty list means sensitive facts are dropped."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Rebuild index" }),
          " \u2014 create a new Qdrant collection, re-embed every memory, swap the alias. Use after changing the embedding model or if Qdrant was wiped."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Retention: per-fact ",
          /* @__PURE__ */ jsx("code", { children: "expires_at" }),
          ", archive unused facts after the configured days, purge already-soft-deleted rows after 30 days (configurable). Users can delete or export their memories."
        ] })
      ] }),
      /* @__PURE__ */ jsx("h2", { children: "Automatic project memory" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "The same pipeline mines the ",
        /* @__PURE__ */ jsx("strong", { children: "Chat" }),
        " tab of projects into shared team memory. Facts belong to the project, not to the member who happened to post, so every member sees them. Rooms (",
        /* @__PURE__ */ jsx("code", { children: "channel_kind=member" }),
        ") and private chats are never mined."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Project memory enabled" }),
          " \u2014 kill switch for the whole organization. Each project also has an",
          " ",
          /* @__PURE__ */ jsx("em", { children: "Automatically learn from project chats" }),
          " switch in its Settings tab (Owners only), on by default."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Personal memory is never used in project chats" }),
          ", in either direction: a project chat does not read the requesting member's personal memory and does not write to it. Only project memory is injected."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Personal categories are hard-dropped" }),
          " in project scope \u2014",
          " ",
          /* @__PURE__ */ jsx("code", { children: "health" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: "financial" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: "personal" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: "family" }),
          ",",
          " ",
          /* @__PURE__ */ jsx("code", { children: "identity" }),
          " are discarded no matter what the sensitive-category allow-list above says, and that cannot be widened from this page."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Retrieval" }),
          " \u2014 owner-authored (manual) facts are always injected as authoritative; learned facts go through the same hybrid Qdrant + PostgreSQL search, tenant-filtered by project."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Cost" }),
          " \u2014 recorded as the system operation ",
          /* @__PURE__ */ jsx("code", { children: "project_memory_extract" }),
          ", never against a member's budget. It shows separately in the KPI row above."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Extraction and embedding models are shared" }),
          " with user memory; ",
          /* @__PURE__ */ jsx("strong", { children: "Rebuild index" }),
          " ",
          "re-embeds user and project facts together. Cross-project memory grants still share manual facts only."
        ] }),
        /* @__PURE__ */ jsx("li", { children: "Owners can delete a single learned fact or all of them from the project Settings tab. A deleted fact is suppressed so the extractor does not re-learn it from the same chats." })
      ] }),
      /* @__PURE__ */ jsx(Note, { children: "Stats include oldest pending extraction job age \u2014 if the Knowledge worker is not running, jobs queue harmlessly and chat is unaffected." })
    ] })
  },
  {
    id: "admin-reports",
    title: "Reports",
    group: "Data & reports",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Reports" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/reports" }),
        ". Catalog of operational and cost reports with preview (table) and download (CSV / Excel / PDF). Parameters depend on the report (dates, user, Agent, plan, department, model, project, thresholds, \u2026). ",
        /* @__PURE__ */ jsx("strong", { children: "Agent usage" }),
        " sums chat-turn spend, turns, and tokens from Agent runs for a date range; the Agent filter is optional (all Agents when empty). Knowledge ingest cost is excluded."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Project reports" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Under the Projects category: ",
        /* @__PURE__ */ jsx("strong", { children: "All projects usage" }),
        " has no project picker (organization-wide). Single-project reports (",
        /* @__PURE__ */ jsx("strong", { children: "usage summary" }),
        ", ",
        /* @__PURE__ */ jsx("strong", { children: "by model" }),
        ", ",
        /* @__PURE__ */ jsx("strong", { children: "by member" }),
        ",",
        " ",
        /* @__PURE__ */ jsx("strong", { children: "media usage" }),
        ") require a project from the catalog dropdown. Cost is attributed from the chat session's project \u2014 clients cannot spoof another project's ",
        /* @__PURE__ */ jsx("code", { children: "project_id" }),
        " on the request."
      ] }),
      /* @__PURE__ */ jsx(Note, { children: "Report generation is interactive from this page. Ensure SMTP is configured if you rely on email delivery elsewhere in your process." })
    ] })
  },
  {
    id: "admin-projects",
    title: "Projects",
    group: "Data & reports",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Projects (admin)" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Employees create and join projects in ",
        /* @__PURE__ */ jsx("code", { children: "/app/projects" }),
        ". Administrators do not manage day-to-day membership here; they report on spend and understand lifecycle. See the User Manual",
        " ",
        /* @__PURE__ */ jsx("a", { href: "/app/manual#user-projects", children: "Projects" }),
        " section for roles and workspace UI."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Lifecycle" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Archive" }),
          " hides a project from Explore and the active My list. Only the Primary Owner can archive or restore."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Delete" }),
          " marks the project ",
          /* @__PURE__ */ jsx("code", { children: "deletion_pending" }),
          ". Members still see it until purge. Only the Primary Owner can delete."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Purge" }),
          " (Primary Owner, on pending deletion) permanently removes rows and object storage. A daily job also purges projects that stay pending past the retention window (",
          /* @__PURE__ */ jsx("code", { children: "PROJECT_DELETION_RETENTION_DAYS" }),
          ", default 30)."
        ] })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Billing and access" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/project-usage" }),
        " (Data & reports \u2192 Projects). Lists organization projects with period spend; ",
        /* @__PURE__ */ jsx("strong", { children: "Activity" }),
        " opens the shared page",
        " ",
        /* @__PURE__ */ jsx("code", { children: "/app/projects/<id>/activity" }),
        " (same Overview / Trends / Explore as User or Group Activity). The Primary Owner and Owners of a project can open the same charts from the workspace ",
        /* @__PURE__ */ jsx("strong", { children: "Activity" }),
        " ",
        "tab. Contributors and Viewers cannot. Request cost is charged from ",
        /* @__PURE__ */ jsx("code", { children: "ChatSession.project_id" }),
        " ",
        "(server-side) for AI chats only. Member rooms (",
        /* @__PURE__ */ jsx("code", { children: "channel_kind=member" }),
        ") cannot call completions or media generation, so they never appear as project spend. A client cannot attach another project's id to a personal chat to steal budget or reports. Deleting a user account reassigns remaining project chat sessions to another Owner (or member) so shared threads are not CASCADE-deleted with the account."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Rooms vs Knowledge" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Rooms are human-only (",
        /* @__PURE__ */ jsx("code", { children: "channel_kind=member" }),
        "). Completions, image/video/speech generation, turn planning, and project memory extraction skip them. ",
        /* @__PURE__ */ jsx("strong", { children: "Send decision to Chat" }),
        " creates an empty AI session and puts the edited brief in the composer only \u2014 it does not send the brief to the model or copy the room transcript. Project resource files still need Knowledge review (same maker-checker as other documents) before they are Published; that is not the Agent release/index workflow. See",
        " ",
        /* @__PURE__ */ jsx("a", { href: "#knowledge-release-workflow", children: "Knowledge release workflow" }),
        "."
      ] }),
      /* @__PURE__ */ jsx(Warn, { children: "Purge is irreversible. Confirm the project is no longer needed before running Purge now." })
    ] })
  },
  {
    id: "admin-logs",
    title: "API Logs",
    group: "Data & reports",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "API Logs" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/admin/logs" }),
        ". Request-level billing/telemetry rows: time, user or API key, model, provider, app, tokens, cache hit, cost, duration, success/failure."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          "Filters: user, gateway API key (",
          /* @__PURE__ */ jsx("code", { children: "api_key_id" }),
          "), model, status, prompt cache, date range."
        ] }),
        /* @__PURE__ */ jsx("li", { children: "The table stays inside the page: narrower widths hide secondary columns (Provider, App, cache, duration, then tokens) and ellipsize long user/model names. Full values remain on hover; click a row for Cost details." }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Open a gateway key from ",
          /* @__PURE__ */ jsx("strong", { children: "API Keys \u2192 Logs" }),
          " or",
          " ",
          /* @__PURE__ */ jsx("code", { children: "/admin/api-keys/<id>/logs" }),
          " \u2014 same table scoped to that key (username filter and Clear All hidden; banner shows key name)."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "The badge next to Cost identifies its quality: ",
          /* @__PURE__ */ jsx("strong", { children: "Provider" }),
          ", ",
          /* @__PURE__ */ jsx("strong", { children: "Reconciled" }),
          ",",
          " ",
          /* @__PURE__ */ jsx("strong", { children: "Catalog" }),
          ", ",
          /* @__PURE__ */ jsx("strong", { children: "Estimated" }),
          ", or ",
          /* @__PURE__ */ jsx("strong", { children: "Unpriced" }),
          ". Hover it to compare the provider and calculated amounts."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Click a row to open ",
          /* @__PURE__ */ jsx("strong", { children: "Cost details" }),
          ": user or API key, operation totals, each upstream attempt (tokens, sources, provider IDs), and line items from",
          " ",
          /* @__PURE__ */ jsx("code", { children: "GET /api/admin/logs/<id>/cost-details" }),
          ". Pre-ledger rows show only the legacy summary."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Export" }),
          " downloads the current filtered set (including date range) as CSV via",
          " ",
          /* @__PURE__ */ jsx("code", { children: "GET /api/admin/logs/export" }),
          ". Inside Cost details, ",
          /* @__PURE__ */ jsx("strong", { children: "Export" }),
          " downloads that one request plus its ledger rows via ",
          /* @__PURE__ */ jsx("code", { children: "GET /api/admin/logs/<id>/export" }),
          "."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Clear All Logs" }),
          " \u2014 write-gated, multi-step confirm."
        ] })
      ] }),
      /* @__PURE__ */ jsx(Note, { children: "Clearing request logs does not erase the cost ledger. Accounting entries are retained so budget totals and reconciliation adjustments remain auditable." }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Deep links from Operations (for example filtered by model) are supported via query parameters. Export and cost-details respect the active filters, including ",
        /* @__PURE__ */ jsx("code", { children: "api_key_id" }),
        " when scoped to a gateway key."
      ] })
    ] })
  },
  // ── End users ─────────────────────────────────────────────────────────────
  {
    id: "user-panel",
    title: "User panel",
    group: "End users",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "User panel" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Employees use ",
        /* @__PURE__ */ jsx("code", { children: "/app" }),
        ": Chat, Projects, Media, Activity, and the User Manual. Admins with panel access can open the same Chat/Media experiences from the admin sidebar shortcuts, plus the full admin menus."
      ] }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Document every end-user capability in the ",
        /* @__PURE__ */ jsx("strong", { children: "User Manual" }),
        " \u2014 do not duplicate the full chat guide here. Link: ",
        /* @__PURE__ */ jsx("code", { children: "/app/manual" }),
        "."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Chat with enabled models, tools, voice, images, private mode, export." }),
        /* @__PURE__ */ jsx("li", { children: "Projects: shared workspaces, rooms vs chats, membership, resources, and project media." }),
        /* @__PURE__ */ jsx("li", { children: "Media library with quota and optional personal cleanup schedule." }),
        /* @__PURE__ */ jsx("li", { children: "Personal Activity with CSV/PDF export." }),
        /* @__PURE__ */ jsx("li", { children: "Settings: theme, font, voice language, chat import/export, password/2FA." })
      ] })
    ] })
  },
  // ── Platform API & Billing ────────────────────────────────────────────────
  {
    id: "platform-api",
    title: "Platform API (/v1)",
    group: "Platform API",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Platform API (/v1)" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Streaming-first OpenAI-style gateway for external tools (IDEs, scripts, Open WebUI, automation). No CSRF \u2014 authenticate with a Bearer key only. Chat completions require ",
        /* @__PURE__ */ jsx("code", { children: "stream=true" }),
        "; non-stream chat is rejected."
      ] }),
      /* @__PURE__ */ jsxs("table", { className: "docs-table", children: [
        /* @__PURE__ */ jsx("thead", { children: /* @__PURE__ */ jsxs("tr", { children: [
          /* @__PURE__ */ jsx("th", { children: "Endpoint" }),
          /* @__PURE__ */ jsx("th", { children: "Notes" })
        ] }) }),
        /* @__PURE__ */ jsxs("tbody", { children: [
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "GET /v1/models" }) }),
            /* @__PURE__ */ jsx("td", { children: "Enabled catalog models after connection allowlist, owner ACL, and model allowlist (gateway keys)" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "POST /v1/chat/completions" }) }),
            /* @__PURE__ */ jsx("td", { children: "Streaming SSE (stream required)" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("code", { children: "POST /v1/embeddings" }) }),
            /* @__PURE__ */ jsx("td", { children: "Embeddings proxy" })
          ] })
        ] })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Authentication modes" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Alpharouter gateway API key" }),
          " \u2014 debits the key's period credit pool (not the owner's personal budget). Optional connection and model allowlists further restrict which providers and catalog entries appear. Owner controls Private-model ACL inheritance."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "User API key" }),
          " \u2014 debits that user\u2019s monthly budget; user must be active."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Gateway master key" }),
          " \u2014 maps to a fixed ",
          /* @__PURE__ */ jsx("code", { children: "gateway-service" }),
          " account (no",
          " ",
          /* @__PURE__ */ jsx("code", { children: "body.user" }),
          " impersonation). Treat as a high-privilege secret; assign that account a budget plan or requests receive 402."
        ] })
      ] }),
      /* @__PURE__ */ jsx(Code, { children: `curl -sS "$ALPHA_ROUTER_BASE/v1/models" \\
  -H "Authorization: Bearer $ALPHA_ROUTER_API_KEY"` }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Point OpenAI-compatible clients at your Alpharouter base URL (for example",
        " ",
        /* @__PURE__ */ jsx("code", { children: "https://alpha-router.example.com/v1" }),
        ") and use an Alpharouter-issued key as the API key."
      ] })
    ] })
  },
  {
    id: "budget-pricing",
    title: "Budget &amp; pricing",
    group: "Billing",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Budget & pricing" }),
      /* @__PURE__ */ jsx("h3", { children: "Pricing" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Model prices come from provider sync (normalized to USD per 1K tokens where possible). Alpharouter does not apply a markup in the catalog. Billing prefers a provider-reported request charge, then provider catalog/configured contract pricing, and finally a LiteLLM estimate. A request that cannot be priced is marked",
        " ",
        /* @__PURE__ */ jsx("strong", { children: "Unpriced" }),
        "; missing cost data is never presented as a confirmed zero."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Monthly user budgets" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Resolved from plan assignment (user \u2192 group \u2192 department). Before a paid request, Alpharouter places a",
        " ",
        /* @__PURE__ */ jsx("strong", { children: "reservation" }),
        " (hold) against ",
        /* @__PURE__ */ jsx("code", { children: "budget_reserved_usd" }),
        ". After completion it",
        " ",
        /* @__PURE__ */ jsx("strong", { children: "settles" }),
        " the actual cost into ",
        /* @__PURE__ */ jsx("code", { children: "budget_used_usd" }),
        " and releases the hold. Stale holds expire via a background sweeper."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "What counts" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Every chat/embedding/image provider attempt, including retry, fallback, tool loop, and code loop iterations" }),
        /* @__PURE__ */ jsx("li", { children: "Automatic title generation, prompt enhancement/translation, voice refinement, and transcription" }),
        /* @__PURE__ */ jsx("li", { children: "Web search/fetch requests; metered units such as request, credit, second, character, or image are supported" }),
        /* @__PURE__ */ jsxs("li", { children: [
          "User API key traffic on ",
          /* @__PURE__ */ jsx("code", { children: "/v1" }),
          " and gateway key traffic against the key\u2019s credit limit"
        ] })
      ] }),
      /* @__PURE__ */ jsx(Note, { children: "Provider errors can still be billable. Failed attempts are retained as events; when the provider exposes no charge, the event remains Unpriced instead of silently assuming it was free." }),
      /* @__PURE__ */ jsx("h3", { children: "Resets" }),
      /* @__PURE__ */ jsx("p", { children: "Monthly user budgets reset on a schedule (first of month). Gateway key credits reset according to each key\u2019s daily/weekly/monthly setting. Admins can force a per-user budget reset from the Users page." })
    ] })
  },
  {
    id: "cost-accounting",
    title: "Cost accounting & reconciliation",
    group: "Billing",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Cost accounting & reconciliation" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Alpharouter uses a provider-agnostic usage ledger. A user action is a ",
        /* @__PURE__ */ jsx("code", { children: "UsageOperation" }),
        "; every real upstream attempt is a ",
        /* @__PURE__ */ jsx("code", { children: "UsageEvent" }),
        "; normalized quantities and unit prices are",
        " ",
        /* @__PURE__ */ jsx("code", { children: "CostLineItem" }),
        " records; and the amount applied to a user budget or gateway key is an immutable",
        " ",
        /* @__PURE__ */ jsx("code", { children: "LedgerEntry" }),
        ". Provider corrections create adjustment entries instead of rewriting history."
      ] }),
      /* @__PURE__ */ jsx("p", { children: "Ledger entries themselves are immutable. Reconciliation may append an adjustment and update the event/request summary fields so the latest authoritative total is visible in API Logs. Original line items remain as they were calculated at capture time." }),
      /* @__PURE__ */ jsx("h3", { children: "Cost-source precedence" }),
      /* @__PURE__ */ jsxs("ol", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Provider / Reconciled" }),
          " \u2014 a per-request charge returned by the provider or fetched later from its usage API."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Catalog / Configured" }),
          " \u2014 the provider model catalog or an explicit contract rate for metered services."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Estimated" }),
          " \u2014 LiteLLM model pricing when neither source above is available."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Unpriced" }),
          " \u2014 usage is retained but no confirmed amount is added to the displayed total."
        ] })
      ] }),
      /* @__PURE__ */ jsx("p", { children: "LiteLLM remains the transport, usage normalizer, token counter, and final estimation fallback. It is not the accounting ledger and its estimates are not labelled as provider-confirmed charges." }),
      /* @__PURE__ */ jsx("h3", { children: "Configured rates for credit/request-based providers" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "For services such as web search, audio, or external tools that do not return USD cost, create a versioned rate through ",
        /* @__PURE__ */ jsx("code", { children: "POST /api/admin/cost-accounting/pricing" }),
        ". Supported units include",
        " ",
        /* @__PURE__ */ jsx("code", { children: "request" }),
        ", ",
        /* @__PURE__ */ jsx("code", { children: "credit" }),
        ", ",
        /* @__PURE__ */ jsx("code", { children: "second" }),
        ", ",
        /* @__PURE__ */ jsx("code", { children: "minute" }),
        ",",
        " ",
        /* @__PURE__ */ jsx("code", { children: "character" }),
        ", and ",
        /* @__PURE__ */ jsx("code", { children: "image" }),
        ". New rates expire the previous active rate; past events keep their original ",
        /* @__PURE__ */ jsx("code", { children: "PricingSnapshot" }),
        "."
      ] }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Built-in web search emits ",
        /* @__PURE__ */ jsx("code", { children: "provider_type=duckduckgo" }),
        " and ",
        /* @__PURE__ */ jsx("code", { children: "service_type=web_search" }),
        "; direct URL fetch emits ",
        /* @__PURE__ */ jsx("code", { children: "provider_type=direct_http" }),
        " and ",
        /* @__PURE__ */ jsx("code", { children: "service_type=web_fetch" }),
        ". Both use the ",
        /* @__PURE__ */ jsx("code", { children: "request" }),
        " unit unless the provider response exposes a more specific metered unit."
      ] }),
      /* @__PURE__ */ jsx(Code, { children: `curl -X POST "$ALPHA_ROUTER_BASE/api/admin/cost-accounting/pricing" \\
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
  }'` }),
      /* @__PURE__ */ jsx("h3", { children: "Reconciliation" }),
      /* @__PURE__ */ jsx("p", { children: "Registered provider adapters periodically fetch final request charges and post signed ledger adjustments. Built-in adapters:" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "OpenRouter" }),
          " \u2014 ",
          /* @__PURE__ */ jsx("code", { children: "GET /generation?id=\u2026" }),
          " returns the per-request",
          " ",
          /* @__PURE__ */ jsx("code", { children: "total_cost" }),
          "."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "OpenAI" }),
          " \u2014 for Responses IDs (",
          /* @__PURE__ */ jsx("code", { children: "resp_*" }),
          "), Alpharouter retrieves",
          " ",
          /* @__PURE__ */ jsx("code", { children: "/v1/responses/<id>" }),
          ". If the payload includes a USD charge it is used; otherwise the provider's authoritative token usage is re-quoted against the local model catalog. Chat Completions IDs (",
          /* @__PURE__ */ jsx("code", { children: "chatcmpl-*" }),
          ") cannot be retrieved from OpenAI, so they stay unmatched until you post a manual reconciliation. OpenAI's organization Costs API is aggregate-only and is not used for per-event matching."
        ] })
      ] }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Configure automatic runs with ",
        /* @__PURE__ */ jsx("code", { children: "COST_RECONCILIATION_ENABLED" }),
        ",",
        " ",
        /* @__PURE__ */ jsx("code", { children: "COST_RECONCILIATION_INTERVAL_MINUTES" }),
        ", and ",
        /* @__PURE__ */ jsx("code", { children: "COST_RECONCILIATION_BATCH_SIZE" }),
        ". An admin can also trigger one connection with ",
        /* @__PURE__ */ jsx("code", { children: "POST /api/admin/cost-accounting/reconcile/provider" }),
        "."
      ] }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Providers without an automatic adapter can submit authoritative event costs to",
        " ",
        /* @__PURE__ */ jsx("code", { children: "POST /api/admin/cost-accounting/reconcile" }),
        ". Each item contains a usage-event ID and the actual USD charge. The operation, request log, user/key counter, and reconciliation run are updated in one transaction."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Audit and diagnostics" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("code", { children: "GET /api/admin/cost-accounting/summary" }),
          " \u2014 ledger totals by source/confidence, unpriced count, legacy pre-ledger spend, ledger start timestamp, and recent reconciliation runs."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("code", { children: "GET /api/admin/logs/<id>/cost-details" }),
          " \u2014 attempts, tokens, provider IDs, line items, and pricing sources for one request."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("code", { children: "GET /api/admin/cost-accounting/pricing" }),
          " \u2014 configured-rate history and effective windows."
        ] })
      ] }),
      /* @__PURE__ */ jsx(Warn, { children: "No library can guarantee exact USD cost when a provider supplies neither a request charge, a billable usage unit, nor invoice/usage reconciliation data. Treat Unpriced events as an operational alert and add a provider adapter or configured contract rate." })
    ] })
  },
  {
    id: "schedulers",
    title: "Background jobs",
    group: "Billing",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Background jobs" }),
      /* @__PURE__ */ jsx("p", { children: "APScheduler jobs inside the Alpharouter process include (among others):" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Model sync due-check (interval)" }),
        /* @__PURE__ */ jsx("li", { children: "Monthly budget reset" }),
        /* @__PURE__ */ jsx("li", { children: "Budget reservation expiry" }),
        /* @__PURE__ */ jsx("li", { children: "Provider cost reconciliation for registered adapters" }),
        /* @__PURE__ */ jsx("li", { children: "Media and chat retention cleanup (cron from Retention Policy)" }),
        /* @__PURE__ */ jsx("li", { children: "Per-user media cleanup schedules" }),
        /* @__PURE__ */ jsx("li", { children: "System metrics snapshots" }),
        /* @__PURE__ */ jsx("li", { children: "Chat session stats reconcile" }),
        /* @__PURE__ */ jsx("li", { children: "Code Interpreter compatibility probes for due models (interval, small claimed batches)" }),
        /* @__PURE__ */ jsx("li", { children: "Auth directory sync schedules (when configured)" })
      ] })
    ] })
  },
  // ── Legal ─────────────────────────────────────────────────────────────────
  {
    id: "copyright",
    title: "Copyright",
    group: "Legal",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Copyright" }),
      /* @__PURE__ */ jsx("p", { children: "Copyright \xA9 2026 Majid Arasskhani." }),
      /* @__PURE__ */ jsxs("p", { children: [
        "The ",
        PRODUCT_NAME_MARKED,
        " source code is licensed under the MIT License. Use, modification, and redistribution are permitted under that license. The name and logos are not included; see",
        " ",
        /* @__PURE__ */ jsx("a", { href: "#trademarks", children: "Trademarks" }),
        "."
      ] }),
      /* @__PURE__ */ jsx("p", { children: "Contact: Majid.Arasskhani@gmail.com" })
    ] })
  },
  {
    id: "trademarks",
    title: "Trademarks",
    group: "Legal",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Trademarks" }),
      /* @__PURE__ */ jsxs("p", { children: [
        PRODUCT_NAME_MARKED,
        ", Alpha Router, AlphaRouter, and the product logos are trademarks of",
        " ",
        TRADEMARK_OWNER,
        "."
      ] }),
      /* @__PURE__ */ jsx("p", { children: "The MIT License covers the source code only. It does not grant permission to use these marks for a fork, a competing product, or any use that implies an official relationship." })
    ] })
  }
];
export {
  docSections
};
