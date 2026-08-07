import { FormEvent, useEffect, useRef, useState } from "react";
import { api, authFetch, formatApiError } from "../../api";

type ConnectorView = {
  provider_id: string;
  label: string;
  auth_type: "oauth" | "api_key" | "none";
  mcp_url: string;
  docs_url: string | null;
  scopes_required: string[];
  category: string[];
  subtitle: string | null;
  connected: boolean;
  connected_at: string | null;
  expires_at: string | null;
  scopes_granted: string | null;
};

type ConnectorsResponse = { connectors: ConnectorView[] };

const PROVIDER_INITIALS: Record<string, string> = {
  gmail: "Gm",
  google_drive: "Dr",
  google_calendar: "Ca",
  github: "Gh",
  notion: "No",
  figma: "Fi",
  huggingface: "HF",
  context7: "C7",
  instagram: "Ig",
  linkedin: "In",
  twitter: "Tw",
};

function initialsFor(providerId: string): string {
  return PROVIDER_INITIALS[providerId] ?? providerId.slice(0, 2).toUpperCase();
}

export default function ConnectorsPanel() {
  const [connectors, setConnectors] = useState<ConnectorView[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  // Credentials modal state (per provider being configured).
  const [editingProvider, setEditingProvider] = useState<string | null>(null);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [credSaving, setCredSaving] = useState(false);

  // API-key modal state (for api_key auth_type providers).
  const [apiKeyProvider, setApiKeyProvider] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [apiKeySaving, setApiKeySaving] = useState(false);

  // Per-row action menu (vertical ellipsis).
  const [openMenuFor, setOpenMenuFor] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  async function refresh() {
    try {
      const data = await api<ConnectorsResponse>("/api/user/connectors");
      setConnectors(data.connectors);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await refresh();
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Close the row action menu on outside click.
  useEffect(() => {
    if (!openMenuFor) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpenMenuFor(null);
      }
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [openMenuFor]);

  // Detect OAuth callback result in URL (?connectors=connected|error).
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const status = params.get("connectors");
    const provider = params.get("provider");
    const reason = params.get("reason");
    if (status === "connected") {
      setMessage(`${provider ? `${provider} connected successfully.` : "Connector connected."}`);
      void refresh();
      window.history.replaceState({}, "", window.location.pathname);
    } else if (status === "error") {
      setError(`Connection failed${reason ? `: ${reason}` : "."}`);
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  function openCredentials(providerId: string) {
    setEditingProvider(providerId);
    setClientId("");
    setClientSecret("");
    setError("");
    setMessage("");
    setOpenMenuFor(null);
  }

  function openApiKey(providerId: string) {
    setApiKeyProvider(providerId);
    setApiKey("");
    setError("");
    setMessage("");
    setOpenMenuFor(null);
  }

  async function saveCredentials(e: FormEvent) {
    e.preventDefault();
    if (!editingProvider) return;
    setCredSaving(true);
    setError("");
    setMessage("");
    try {
      await api(`/api/user/connectors/${editingProvider}/credentials`, {
        method: "POST",
        body: JSON.stringify({ client_id: clientId, client_secret: clientSecret }),
      });
      setEditingProvider(null);
      setClientId("");
      setClientSecret("");
      setMessage("Credentials saved. Click Connect to authorize.");
      await refresh();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setCredSaving(false);
    }
  }

  async function saveApiKey(e: FormEvent) {
    e.preventDefault();
    if (!apiKeyProvider) return;
    setApiKeySaving(true);
    setError("");
    setMessage("");
    try {
      await api(`/api/user/connectors/${apiKeyProvider}/connect-api-key`, {
        method: "POST",
        body: JSON.stringify({ api_key: apiKey }),
      });
      const name = apiKeyProvider;
      setApiKeyProvider(null);
      setApiKey("");
      setMessage(`${name} connected.`);
      await refresh();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setApiKeySaving(false);
    }
  }

  async function beginConnect(providerId: string) {
    setError("");
    setMessage("");
    setOpenMenuFor(null);
    try {
      const res = await authFetch(`/api/user/connectors/${providerId}/begin`);
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `Failed to start connection (${res.status})`);
      }
      const data = (await res.json()) as { auth_url: string };
      window.location.assign(data.auth_url);
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  async function connectNoAuth(providerId: string) {
    setError("");
    setMessage("");
    setOpenMenuFor(null);
    try {
      await api(`/api/user/connectors/${providerId}/connect`, { method: "POST" });
      setMessage(`${providerId} connected.`);
      await refresh();
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  async function disconnect(providerId: string) {
    setError("");
    setMessage("");
    setOpenMenuFor(null);
    if (!window.confirm(`Disconnect ${providerId}? Alpharouter will lose access to this service.`)) return;
    try {
      await api(`/api/user/connectors/${providerId}`, { method: "DELETE" });
      setMessage(`${providerId} disconnected.`);
      await refresh();
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  function primaryAction(c: ConnectorView): { label: string; run: () => void } | null {
    if (c.connected) return { label: "Disconnect", run: () => void disconnect(c.provider_id) };
    if (c.auth_type === "oauth") return { label: "Connect", run: () => void beginConnect(c.provider_id) };
    if (c.auth_type === "api_key") return { label: "Connect with API key", run: () => openApiKey(c.provider_id) };
    if (c.auth_type === "none") return { label: "Connect", run: () => void connectNoAuth(c.provider_id) };
    return null;
  }

  if (loading) return <p className="muted">Loading connectors…</p>;
  if (!connectors) return <p className="settings-error">{error || "Unable to load connectors."}</p>;

  return (
    <div className="settings-section">
      <h2>Connectors</h2>
      <p className="settings-section-desc">
        Link your accounts via official MCP servers. You supply OAuth credentials or an API key; secrets are encrypted at rest.
      </p>

      <div className="connectors-list" role="table" aria-label="Available connectors">
        <div className="connectors-list__head" role="row">
          <span className="connectors-list__col connectors-list__col--name" role="columnheader">Name</span>
          <span className="connectors-list__col connectors-list__col--type" role="columnheader">Type</span>
          <span className="connectors-list__col connectors-list__col--category" role="columnheader">Category</span>
          <span className="connectors-list__col connectors-list__col--menu" role="columnheader" aria-hidden="true" />
        </div>

        {connectors.map((c) => {
          const action = primaryAction(c);
          return (
            <div className="connectors-list__row" role="row" key={c.provider_id}>
              <span className="connectors-list__col connectors-list__col--name" role="cell">
                <span className="connectors-list__logo" aria-hidden="true">{initialsFor(c.provider_id)}</span>
                <span className="connectors-list__name-text">
                  <span className="connectors-list__name">{c.label}</span>
                  {c.subtitle && <span className="connectors-list__subtitle">{c.subtitle}</span>}
                  {c.connected && (
                    <span className="connectors-list__badge" title="Connected">●</span>
                  )}
                </span>
              </span>
              <span className="connectors-list__col connectors-list__col--type" role="cell">Web</span>
              <span className="connectors-list__col connectors-list__col--category" role="cell">
                {c.category.join(", ")}
              </span>
              <span className="connectors-list__col connectors-list__col--menu" role="cell">
                <div className="connectors-list__menu-wrap">
                  <button
                    type="button"
                    className="connectors-list__menu-btn"
                    aria-label={`Actions for ${c.label}`}
                    aria-haspopup="menu"
                    aria-expanded={openMenuFor === c.provider_id}
                    onClick={() => setOpenMenuFor(openMenuFor === c.provider_id ? null : c.provider_id)}
                  >
                    ⋮
                  </button>
                  {openMenuFor === c.provider_id && (
                    <div className="connectors-list__menu" role="menu" ref={menuRef}>
                      {action && (
                        <button type="button" role="menuitem" className="connectors-list__menu-item" onClick={action.run}>
                          {action.label}
                        </button>
                      )}
                      {c.auth_type === "oauth" && !c.connected && (
                        <button
                          type="button"
                          role="menuitem"
                          className="connectors-list__menu-item"
                          onClick={() => openCredentials(c.provider_id)}
                        >
                          Set credentials
                        </button>
                      )}
                      {c.docs_url && (
                        <a
                          className="connectors-list__menu-item"
                          role="menuitem"
                          href={c.docs_url}
                          target="_blank"
                          rel="noreferrer noopener"
                        >
                          Docs ↗
                        </a>
                      )}
                    </div>
                  )}
                </div>
              </span>
            </div>
          );
        })}
      </div>

      {editingProvider && (
        <div className="connector-cred-modal" role="dialog" aria-label="OAuth credentials">
          <form className="connector-cred-form" onSubmit={saveCredentials}>
            <h3>OAuth Client Credentials</h3>
            <p className="settings-hint">
              Create an OAuth Client ID in your provider's developer console
              (e.g. Google Cloud → APIs &amp; Services → Credentials).
              Use <code>{window.location.origin}/api/user/connectors/oauth/callback</code> as the authorized redirect URI.
            </p>
            <label className="settings-field">
              <span className="settings-label">Client ID</span>
              <input
                type="text"
                className="settings-input"
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                required
                autoComplete="off"
              />
            </label>
            <label className="settings-field">
              <span className="settings-label">Client Secret</span>
              <input
                type="password"
                className="settings-input"
                value={clientSecret}
                onChange={(e) => setClientSecret(e.target.value)}
                required
                autoComplete="off"
              />
            </label>
            <div className="settings-actions">
              <button type="submit" className="btn btn-sm" disabled={credSaving}>
                {credSaving ? "Saving…" : "Save credentials"}
              </button>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                onClick={() => setEditingProvider(null)}
                disabled={credSaving}
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {apiKeyProvider && (
        <div className="connector-cred-modal" role="dialog" aria-label="API key">
          <form className="connector-cred-form" onSubmit={saveApiKey}>
            <h3>API Key</h3>
            <p className="settings-hint">
              Paste the API key from this provider's developer console. It is encrypted at rest and never shown again.
            </p>
            <label className="settings-field">
              <span className="settings-label">API Key</span>
              <input
                type="password"
                className="settings-input"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                required
                autoComplete="off"
              />
            </label>
            <div className="settings-actions">
              <button type="submit" className="btn btn-sm" disabled={apiKeySaving}>
                {apiKeySaving ? "Connecting…" : "Connect"}
              </button>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                onClick={() => setApiKeyProvider(null)}
                disabled={apiKeySaving}
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {error && <p className="settings-error">{error}</p>}
      {message && <p className="settings-success">{message}</p>}
    </div>
  );
}
