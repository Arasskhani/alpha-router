import type { ReactNode } from "react";

type IconProps = { className?: string };

function IconExternalClients({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" aria-hidden>
      <rect x="4" y="6" width="24" height="16" rx="2" stroke="currentColor" strokeWidth="1.6" />
      <path d="M8 22v3M24 22v3M11 25h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M10 12h8M10 16h12" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

function IconBrowser({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" aria-hidden>
      <rect x="4" y="6" width="24" height="20" rx="2.5" stroke="currentColor" strokeWidth="1.6" />
      <path d="M4 11h24" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="8" cy="8.5" r="1" fill="currentColor" />
      <circle cx="11.5" cy="8.5" r="1" fill="currentColor" />
      <rect x="8" y="15" width="16" height="2" rx="1" fill="currentColor" opacity="0.55" />
      <rect x="8" y="19" width="10" height="2" rx="1" fill="currentColor" opacity="0.35" />
    </svg>
  );
}

function IconFastAPI({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" aria-hidden>
      <circle cx="16" cy="16" r="11" stroke="currentColor" strokeWidth="1.6" />
      <path
        d="M11 19l5-10 2.5 5 2.5-2.5L21 19"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconReact({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" aria-hidden>
      <circle cx="16" cy="16" r="2.2" fill="currentColor" />
      <ellipse cx="16" cy="16" rx="11" ry="4.2" stroke="currentColor" strokeWidth="1.4" />
      <ellipse cx="16" cy="16" rx="11" ry="4.2" stroke="currentColor" strokeWidth="1.4" transform="rotate(60 16 16)" />
      <ellipse cx="16" cy="16" rx="11" ry="4.2" stroke="currentColor" strokeWidth="1.4" transform="rotate(120 16 16)" />
    </svg>
  );
}

function IconPostgres({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" aria-hidden>
      <path
        d="M10 8c4-1 8-1 12 0v14c-4 2-8 2-12 0V8z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M10 12h12M10 16h12M10 20h12" stroke="currentColor" strokeWidth="1.2" opacity="0.45" />
      <circle cx="22" cy="10" r="2" stroke="currentColor" strokeWidth="1.4" />
      <path d="M22 8v4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}

function IconObjectStorage({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" aria-hidden>
      <path
        d="M6 12h20l-2 14H8L6 12z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M6 12l3-6h14l3 6" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M12 18h8M12 22h8" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" opacity="0.5" />
    </svg>
  );
}

function IconRedis({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" aria-hidden>
      <path d="M6 10l10-4 10 4-10 4-10-4z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M6 16l10 4 10-4" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M6 22l10 4 10-4" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M16 14v12" stroke="currentColor" strokeWidth="1.2" opacity="0.35" />
    </svg>
  );
}

function IconLiteLLM({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" aria-hidden>
      <circle cx="16" cy="16" r="3" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="8" cy="10" r="2" stroke="currentColor" strokeWidth="1.4" />
      <circle cx="24" cy="10" r="2" stroke="currentColor" strokeWidth="1.4" />
      <circle cx="8" cy="22" r="2" stroke="currentColor" strokeWidth="1.4" />
      <circle cx="24" cy="22" r="2" stroke="currentColor" strokeWidth="1.4" />
      <path d="M10 11l4 3M22 11l-4 3M10 21l4-3M22 21l-4-3" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}

function IconQdrant({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" aria-hidden>
      <circle cx="10" cy="12" r="2.2" stroke="currentColor" strokeWidth="1.4" />
      <circle cx="22" cy="10" r="2.2" stroke="currentColor" strokeWidth="1.4" />
      <circle cx="16" cy="21" r="2.2" stroke="currentColor" strokeWidth="1.4" />
      <circle cx="24" cy="20" r="1.6" stroke="currentColor" strokeWidth="1.3" />
      <path d="M12 13l8-2M12 13.5l3.5 6M22 12l-4 8M22.5 12l1 6.5" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}

function IconClamav({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" aria-hidden>
      <path
        d="M16 5l10 4v8c0 6-4.2 10.2-10 12-5.8-1.8-10-6-10-12V9l10-4z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M11 16.5l3.2 3.2L21 13" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function IconWorker({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" aria-hidden>
      <rect x="5" y="8" width="10" height="7" rx="1.4" stroke="currentColor" strokeWidth="1.5" />
      <rect x="17" y="17" width="10" height="7" rx="1.4" stroke="currentColor" strokeWidth="1.5" />
      <path d="M10 15v3.5h7" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M22 17V13.5H15" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" opacity="0.55" />
    </svg>
  );
}

function IconProviders({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" aria-hidden>
      <rect x="5" y="8" width="22" height="16" rx="2" stroke="currentColor" strokeWidth="1.6" />
      <path d="M5 13h22" stroke="currentColor" strokeWidth="1.4" />
      <circle cx="10" cy="19" r="2" stroke="currentColor" strokeWidth="1.3" />
      <circle cx="16" cy="19" r="2" stroke="currentColor" strokeWidth="1.3" />
      <circle cx="22" cy="19" r="2" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  );
}

function FlowArrow() {
  return (
    <div className="docs-arch-flow" aria-hidden>
      <span className="docs-arch-flow-line" />
      <span className="docs-arch-flow-head">▼</span>
    </div>
  );
}

type ComponentCardProps = {
  icon?: ReactNode;
  title: string;
  subtitle?: string;
  children: ReactNode;
  variant?: "default" | "core" | "providers";
  iconCentered?: boolean;
};

function ComponentCard({
  icon,
  title,
  subtitle,
  children,
  variant = "default",
  iconCentered = false,
}: ComponentCardProps) {
  const headClass = [
    "docs-arch-component-head",
    iconCentered ? "docs-arch-component-head--center" : "",
    !icon ? "docs-arch-component-head--text-only" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <article className={`docs-arch-component docs-arch-component--${variant}`}>
      <header className={headClass}>
        {icon ? (
          <div className={`docs-arch-icon-wrap${iconCentered ? " docs-arch-icon-wrap--sm" : ""}`}>{icon}</div>
        ) : null}
        <div className="docs-arch-component-titles">
          <strong>{title}</strong>
          {subtitle ? <span className="docs-arch-muted">{subtitle}</span> : null}
        </div>
      </header>
      <div className="docs-arch-component-body">{children}</div>
    </article>
  );
}

/** Visual architecture map for Admin Guide (monochrome, theme-aware). */
export default function AdminArchitectureDiagram() {
  return (
    <figure className="docs-arch" aria-label="Alpharouter platform architecture">
      <figcaption className="docs-arch-title">Platform architecture</figcaption>

      <div className="docs-arch-board">
        <section className="docs-arch-zone">
          <h4 className="docs-arch-zone-label">Clients</h4>
          <div className="docs-arch-zone-grid docs-arch-zone-grid--2">
            <ComponentCard
              icon={<IconExternalClients className="docs-arch-icon" />}
              title="External integrations"
              subtitle="HTTPS · Authorization: Bearer Alpharouter key"
            >
              <ul className="docs-arch-route-list">
                <li>
                  <code>GET /v1/models</code>
                </li>
                <li>
                  <code>POST /v1/chat/completions</code>
                  <span className="docs-arch-muted"> · stream · optional Agent</span>
                </li>
                <li>
                  <code>POST /v1/embeddings</code>
                </li>
              </ul>
            </ComponentCard>
            <ComponentCard
              icon={<IconBrowser className="docs-arch-icon" />}
              title="Alpharouter web UI"
              subtitle="HTTPS · session cookie after /api/auth/login"
            >
              <ul className="docs-arch-route-list">
                <li>
                  <code>POST /api/chat/completions</code>
                  <span className="docs-arch-muted"> · persist during SSE · Agents</span>
                </li>
                <li>
                  <code>/api/user/chats/*</code>
                  <span className="docs-arch-muted"> · sessions, messages, folders</span>
                </li>
                <li>
                  <code>POST /api/images/generate</code>
                </li>
                <li>
                  <code>/api/admin/agents/*</code>
                  <span className="docs-arch-muted"> · Studio, Knowledge, Audit</span>
                </li>
              </ul>
            </ComponentCard>
          </div>
        </section>

        <FlowArrow />

        <section className="docs-arch-zone">
          <h4 className="docs-arch-zone-label">Application</h4>
          <ComponentCard
            variant="core"
            title="Alpharouter application"
            subtitle="FastAPI backend + React SPA"
          >
            <div className="docs-arch-stack" aria-label="Stack">
              <span title="FastAPI">
                <IconFastAPI className="docs-arch-icon docs-arch-icon--tiny" />
                FastAPI
              </span>
              <span title="React">
                <IconReact className="docs-arch-icon docs-arch-icon--tiny" />
                React
              </span>
            </div>
            <ul className="docs-arch-core-list">
              <li>Auth &amp; RBAC · budget reserve / settle</li>
              <li>
                Shared <code>stream_chat</code> pipeline → LiteLLM
              </li>
              <li>
                Agent runtime: routing, Qdrant retrieval, citations, fail-closed guardrails
              </li>
              <li>
                <code>ChatCompletionPersister</code> — server-owned writes during in-app SSE
              </li>
              <li>Request logging · model catalog · Connections · Agent/Knowledge audit</li>
              <li>Chat rows in PostgreSQL · blobs in SeaweedFS · code via sandbox-broker</li>
            </ul>
          </ComponentCard>
        </section>

        <FlowArrow />

        <section className="docs-arch-zone">
          <h4 className="docs-arch-zone-label">Data &amp; infrastructure</h4>
          <div className="docs-arch-zone-grid docs-arch-zone-grid--4">
            <ComponentCard
              iconCentered
              icon={<IconPostgres className="docs-arch-icon" />}
              title="PostgreSQL + PgBouncer"
              subtitle="Primary data store"
            >
              <p>
                Users, Connections, catalog, chat rows, budgets, Agent versions, Knowledge metadata, reservations,
                request logs. App uses transaction pooling via PgBouncer.
              </p>
            </ComponentCard>
            <ComponentCard
              iconCentered
              icon={<IconObjectStorage className="docs-arch-icon" />}
              title="SeaweedFS / S3"
              subtitle="Object storage"
            >
              <p>
                S3 API for media and Knowledge source bytes (quarantine then governed objects). Served only through
                authenticated Alpharouter APIs.
              </p>
            </ComponentCard>
            <ComponentCard
              iconCentered
              icon={<IconRedis className="docs-arch-icon" />}
              title="Redis"
              subtitle="Cache &amp; state"
            >
              <p>
                Rate limits, SSO/2FA pending state, LiteLLM cache, Knowledge job streams; in-memory fallback when Redis
                is down.
              </p>
            </ComponentCard>
            <ComponentCard
              iconCentered
              icon={<IconLiteLLM className="docs-arch-icon" />}
              title="LiteLLM + sandbox"
              subtitle="LLM router · code broker"
            >
              <p>
                LiteLLM calls upstream providers from Connections. Code interpreter runs via internal sandbox-broker
                (no public port).
              </p>
            </ComponentCard>
          </div>
        </section>

        <FlowArrow />

        <section className="docs-arch-zone">
          <h4 className="docs-arch-zone-label">Agents &amp; Knowledge plane</h4>
          <div className="docs-arch-zone-grid docs-arch-zone-grid--3">
            <ComponentCard
              iconCentered
              icon={<IconQdrant className="docs-arch-icon" />}
              title="Qdrant"
              subtitle="Derived vector index"
            >
              <p>
                Dense/sparse collections for published Knowledge releases. PostgreSQL remains source of truth; indexes
                are rebuildable.
              </p>
            </ComponentCard>
            <ComponentCard
              iconCentered
              icon={<IconClamav className="docs-arch-icon" />}
              title="ClamAV"
              subtitle="Malware scan"
            >
              <p>
                Knowledge uploads are scanned in quarantine before parse/index. Unsafe bytes never enter retrieval.
              </p>
            </ComponentCard>
            <ComponentCard
              iconCentered
              icon={<IconWorker className="docs-arch-icon" />}
              title="Knowledge scheduler + worker"
              subtitle="Same app image"
            >
              <p>
                Scheduler enqueues ingest/retention jobs on Redis. Worker parses, scans, embeds, and writes Qdrant,
                then switches the alias after validation.
              </p>
            </ComponentCard>
          </div>
        </section>

        <FlowArrow />

        <section className="docs-arch-zone">
          <h4 className="docs-arch-zone-label">Upstream</h4>
          <ComponentCard
            variant="providers"
            icon={<IconProviders className="docs-arch-icon" />}
            title="Upstream provider APIs"
            subtitle="OpenRouter · OpenAI · Anthropic · Google · …"
          >
            <p>Provider credentials are stored only in the Connections table; keys never leave PostgreSQL.</p>
          </ComponentCard>
        </section>
      </div>
    </figure>
  );
}
