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

function IconMinIO({ className }: IconProps) {
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
    <figure className="docs-arch" aria-label="Alpha Router platform architecture">
      <figcaption className="docs-arch-title">Platform architecture</figcaption>

      <div className="docs-arch-board">
        <section className="docs-arch-zone">
          <h4 className="docs-arch-zone-label">Clients</h4>
          <div className="docs-arch-zone-grid docs-arch-zone-grid--2">
            <ComponentCard
              icon={<IconExternalClients className="docs-arch-icon" />}
              title="External integrations"
              subtitle="HTTPS · Authorization: Bearer Alpha Router key"
            >
              <ul className="docs-arch-route-list">
                <li>
                  <code>GET /v1/models</code>
                </li>
                <li>
                  <code>POST /v1/chat/completions (stream)</code>
                </li>
              </ul>
            </ComponentCard>
            <ComponentCard
              icon={<IconBrowser className="docs-arch-icon" />}
              title="Alpha Router web UI"
              subtitle="HTTPS · JWT after /api/auth/login"
            >
              <ul className="docs-arch-route-list">
                <li>
                  <code>POST /api/chat/completions</code>
                  <span className="docs-arch-muted"> · persist during SSE</span>
                </li>
                <li>
                  <code>/api/user/chats/*</code>
                  <span className="docs-arch-muted"> · sessions, messages, folders</span>
                </li>
                <li>
                  <code>POST /api/images/generate</code>
                </li>
                <li>
                  <code>/api/admin/*</code>
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
            title="Alpha Router application"
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
              <li>Auth &amp; RBAC · monthly budget engine</li>
              <li>
                Shared <code>stream_chat</code> pipeline → LiteLLM
              </li>
              <li>
                <code>ChatCompletionPersister</code> — server-owned writes during in-app SSE
              </li>
              <li>Request logging · model catalog · Connections</li>
              <li>Normalized chat rows in PostgreSQL · media blobs in MinIO (hash dedup)</li>
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
              title="PostgreSQL"
              subtitle="Production metadata"
            >
              <p>
                <code>chat_sessions</code>, <code>chat_messages</code>, <code>chat_folders</code>,{" "}
                <code>user_chat_prefs</code>, <code>media_assets</code>, logs, Connections.
              </p>
            </ComponentCard>
            <ComponentCard
              iconCentered
              icon={<IconMinIO className="docs-arch-icon" />}
              title="MinIO / S3"
              subtitle="Object storage"
            >
              <p>Media blobs at cdn/u/username/hash.ext — served via authenticated API only.</p>
            </ComponentCard>
            <ComponentCard
              iconCentered
              icon={<IconRedis className="docs-arch-icon" />}
              title="Redis"
              subtitle="Optional"
            >
              <p>LiteLLM prompt cache in production; in-memory fallback when unavailable.</p>
            </ComponentCard>
            <ComponentCard
              iconCentered
              icon={<IconLiteLLM className="docs-arch-icon" />}
              title="LiteLLM"
              subtitle="LLM router"
            >
              <p>Calls provider APIs using keys &amp; base URLs from Connections (DB).</p>
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
