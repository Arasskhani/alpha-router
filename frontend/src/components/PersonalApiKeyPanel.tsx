import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, formatApiError } from "../api";
import { useConfirm } from "../context/ConfirmContext";
import Modal from "./Modal";

type PersonalKey = {
  id: number;
  name: string;
  prefix: string;
  url: string;
  is_active: boolean;
  created_at: string | null;
  last_used_at: string | null;
};

type Budget = {
  monthly_budget_usd: number;
  used_usd: number;
  reserved_usd?: number;
  remaining_usd: number | null;
};

type CreatedKey = {
  id: number;
  name: string;
  api_key: string;
  prefix: string;
  url: string;
};

function formatWhen(iso: string | null) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      return true;
    } catch {
      return false;
    }
  }
}

function CopyIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <rect x="9" y="9" width="13" height="13" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  );
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    const ok = await copyText(value);
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    }
  }

  return (
    <button
      type="button"
      className="btn btn-sm btn-ghost personal-api-key-field__copy"
      onClick={() => void handleCopy()}
      title={label}
      aria-label={label}
    >
      {copied ? "✓" : <CopyIcon />}
    </button>
  );
}

function SecretField({
  label,
  value,
  showCopy = true,
}: {
  label: string;
  value: string;
  showCopy?: boolean;
}) {
  return (
    <label className="settings-field personal-api-key-field">
      <span className="settings-label">{label}</span>
      <div className="personal-api-key-field__row">
        <input
          readOnly
          value={value}
          className="settings-row__control mono personal-api-key-field__input"
          aria-label={label}
        />
        {showCopy ? <CopyButton value={value} label={`Copy ${label}`} /> : null}
      </div>
    </label>
  );
}

export default function PersonalApiKeyPanel() {
  const { confirm } = useConfirm();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [keys, setKeys] = useState<PersonalKey[]>([]);
  const [budget, setBudget] = useState<Budget | null>(null);
  const [name, setName] = useState("Personal API Key");
  const [created, setCreated] = useState<CreatedKey | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [keyRows, budgetRow] = await Promise.all([
        api<PersonalKey[]>("/api/user/api-keys/list"),
        api<Budget>("/api/user/budget"),
      ]);
      setKeys(keyRows);
      setBudget(budgetRow);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const row = await api<CreatedKey>("/api/user/api-keys", {
        method: "POST",
        body: JSON.stringify({ name: name.trim() || "Personal API Key" }),
      });
      setCreated(row);
      setMessage("Copy your API key now. It will not be shown again.");
      await load();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setSaving(false);
    }
  }

  async function onRevoke(key: PersonalKey) {
    const ok = await confirm({
      title: "Revoke personal API key?",
      message: `Permanently delete "${key.name}"? External tools using this key will stop working immediately.`,
      confirmLabel: "Revoke",
      danger: true,
    });
    if (!ok) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      await api(`/api/user/api-keys/${key.id}`, { method: "DELETE" });
      setMessage("API key revoked.");
      setCreated(null);
      await load();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setSaving(false);
    }
  }

  const activeKey = keys[0] ?? null;
  const hasBudget = (budget?.monthly_budget_usd ?? 0) > 0;

  if (loading) return <p className="muted">Loading API key settings…</p>;

  return (
    <div className="settings-section personal-api-key-panel">
      <h2>Personal API Key</h2>
      <p className="settings-section-desc">
        Use one personal key with OpenAI-compatible clients (scripts, IDEs, Kilo Code). Usage debits your
        monthly budget — the same pool as Chat.
      </p>

      {budget && (
        <div className="docs-callout docs-callout-info personal-api-key-panel__budget">
          Monthly budget:{" "}
          <strong>${budget.used_usd.toFixed(2)}</strong> used
          {(budget.reserved_usd ?? 0) > 0 ? (
            <>
              {" "}
              · <strong>${(budget.reserved_usd ?? 0).toFixed(2)}</strong> reserved
            </>
          ) : null}
          {budget.remaining_usd != null ? (
            <>
              {" "}
              · <strong>${budget.remaining_usd.toFixed(2)}</strong> remaining
            </>
          ) : (
            <> · no plan assigned</>
          )}
        </div>
      )}

      {error && <p className="settings-error" role="alert">{error}</p>}
      {message && <p className="settings-success">{message}</p>}

      {activeKey ? (
        <div className="settings-list">
          <div className="settings-row-block settings-row-block--open">
            <div className="settings-row">
              <div className="settings-row__meta">
                <span className="settings-row__title">{activeKey.name}</span>
                <span className="settings-row__hint mono">{activeKey.prefix}…</span>
                <span className="settings-row__hint">
                  Created {formatWhen(activeKey.created_at)}
                  {activeKey.last_used_at ? <> · Last used {formatWhen(activeKey.last_used_at)}</> : null}
                </span>
              </div>
              <div className="settings-row__trail">
                <button
                  type="button"
                  className="settings-row__action settings-row__action--danger"
                  disabled={saving}
                  onClick={() => void onRevoke(activeKey)}
                >
                  Revoke
                </button>
              </div>
            </div>
            <div className="settings-row__detail">
              <SecretField label="Base URL" value={activeKey.url} showCopy={false} />
            </div>
          </div>
        </div>
      ) : (
        <div className="settings-list">
          <div className="settings-row-block">
            <form className="settings-inline-form personal-api-key-create" onSubmit={onCreate}>
              <label className="settings-field">
                <span className="settings-label">Key name</span>
                <input
                  className="settings-row__control"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  maxLength={128}
                  disabled={!hasBudget || saving}
                />
              </label>
              {!hasBudget && (
                <p className="settings-hint">
                  Ask an administrator to assign a monthly budget plan before creating a key.
                </p>
              )}
              <button type="submit" className="btn btn-sm btn-primary" disabled={!hasBudget || saving}>
                {saving ? "Creating…" : "Create API key"}
              </button>
            </form>
          </div>
        </div>
      )}

      <Modal
        open={!!created}
        title="Your personal API key"
        onClose={() => setCreated(null)}
        panelClassName="modal-panel--settings"
        bodyClassName="personal-api-key-created-body"
      >
        {created && (
          <div className="personal-api-key-created">
            <p className="settings-hint">Copy this key now. You will not be able to view it again.</p>
            <SecretField label="API key" value={created.api_key} />
            <SecretField label="Base URL" value={created.url} />
            <p className="settings-hint mono personal-api-key-created__curl">
              curl {created.url}/models -H &quot;Authorization: Bearer {created.api_key.slice(0, 12)}…&quot;
            </p>
            <div className="settings-actions">
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => setCreated(null)}>
                Done
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
