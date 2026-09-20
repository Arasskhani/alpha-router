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

const DEFAULT_KEY_NAME = "Personal API Key";

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

function CopyButton({
  value,
  label,
  onCopied,
}: {
  value: string;
  label: string;
  onCopied?: () => void;
}) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    const ok = await copyText(value);
    if (ok) {
      setCopied(true);
      onCopied?.();
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
  onCopied,
}: {
  label: string;
  value: string;
  showCopy?: boolean;
  onCopied?: () => void;
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
        {showCopy ? <CopyButton value={value} label={`Copy ${label}`} onCopied={onCopied} /> : null}
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
  const [name, setName] = useState(DEFAULT_KEY_NAME);
  const [created, setCreated] = useState<CreatedKey | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  // Kept apart from the panel's error: a failed create has to be readable in
  // the dialog the person is looking at, not behind it.
  const [createError, setCreateError] = useState("");
  // The secret leaves this dialog once. Until it has been copied, closing is
  // the wrong default, so the exit is held back rather than merely warned about.
  const [keyCopied, setKeyCopied] = useState(false);

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

  function openCreateDialog() {
    setName(DEFAULT_KEY_NAME);
    setCreateError("");
    setMessage("");
    setKeyCopied(false);
    setCreateOpen(true);
  }

  /** Close the dialog in either of its two steps, and forget both. */
  function closeCreateDialog() {
    setCreateOpen(false);
    setCreated(null);
    setCreateError("");
    setName(DEFAULT_KEY_NAME);
    setKeyCopied(false);
  }

  /**
   * Leaving the secret step without copying loses the key for good, so that
   * exit asks first. Every other way out of the dialog closes as usual.
   */
  async function requestClose() {
    if (created && !keyCopied) {
      const ok = await confirm({
        title: "Close without copying the key?",
        message:
          "This key is shown once. Close now and it cannot be recovered - you would have to revoke it and update every tool that uses it.",
        confirmLabel: "Close anyway",
        cancelLabel: "Keep it open",
        danger: true,
      });
      if (!ok) return;
    }
    closeCreateDialog();
  }

  async function copyKey(value: string) {
    if (await copyText(value)) setKeyCopied(true);
  }

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setCreateError("");
    setMessage("");
    try {
      const row = await api<CreatedKey>("/api/user/api-keys", {
        method: "POST",
        body: JSON.stringify({ name: name.trim() || DEFAULT_KEY_NAME }),
      });
      // The same dialog now shows the key: naming it and copying it are two
      // steps of one act, and the secret is shown exactly once.
      setCreated(row);
      setMessage("Copy your API key now. It will not be shown again.");
      await load();
    } catch (err) {
      setCreateError(formatApiError(err));
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
      closeCreateDialog();
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
            <div className="personal-api-key-create">
              {!hasBudget && (
                <p className="settings-hint">
                  Ask an administrator to assign a monthly budget plan before creating a key.
                </p>
              )}
              <button
                type="button"
                className="btn btn-sm btn-primary"
                disabled={!hasBudget || saving}
                onClick={openCreateDialog}
              >
                Create API key
              </button>
            </div>
          </div>
        </div>
      )}

      <Modal
        open={createOpen}
        title={created ? "Your personal API key" : "Create personal API key"}
        onClose={() => void requestClose()}
        panelClassName="modal-panel--settings modal-panel--fit"
        bodyClassName="personal-api-key-created-body"
        // Once the secret is on screen it exists nowhere else; a stray click on
        // the backdrop should not be how somebody loses it.
        closeOnBackdrop={!created}
      >
        {created ? (
          <div className="personal-api-key-created">
            <p className="alert alert-warning personal-api-key-created__warning" role="alert">
              <strong>This key is shown once.</strong> Copy it into your password manager now — closing this
              window is the last you will see of it. To get another you have to revoke this one and update
              every tool that uses it.
            </p>
            <SecretField label="API key" value={created.api_key} onCopied={() => setKeyCopied(true)} />
            <SecretField label="Base URL" value={created.url} showCopy={false} />
            <p className="settings-hint mono personal-api-key-created__curl">
              curl {created.url}/models -H &quot;Authorization: Bearer {created.api_key.slice(0, 12)}…&quot;
            </p>
            {/* Copy is the primary action here, not Done. The old hierarchy had
                the exit as the big button and the copy as a 14px icon, which is
                how a key that is shown once gets lost. */}
            <div className="settings-actions">
              <button
                type="button"
                className="btn btn-sm btn-primary"
                onClick={() => void copyKey(created.api_key)}
              >
                {keyCopied ? "Copied ✓" : "Copy key"}
              </button>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                onClick={() => void requestClose()}
                disabled={!keyCopied}
                title={keyCopied ? undefined : "Copy the key first — it cannot be shown again."}
              >
                Done
              </button>
            </div>
          </div>
        ) : (
          <form className="personal-api-key-created" onSubmit={onCreate}>
            <p className="settings-hint">
              Name it for where you will use it — a laptop, a script, an IDE — so you know what you are revoking
              later. The key itself is shown <strong>once</strong>, right after it is created, so have somewhere
              to put it.
            </p>
            <label className="settings-field personal-api-key-field">
              <span className="settings-label">Key name</span>
              <input
                className="settings-row__control"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={128}
                disabled={saving}
              />
            </label>
            {createError && (
              <p className="settings-error" role="alert">
                {createError}
              </p>
            )}
            <div className="settings-actions">
              <button type="button" className="btn btn-sm btn-ghost" onClick={closeCreateDialog} disabled={saving}>
                Cancel
              </button>
              {/* Not "Create API key" again: the button that opened this
                  dialog is still behind it, and two identical labels on screen
                  read as one control that moved. */}
              <button type="submit" className="btn btn-sm btn-primary" disabled={saving}>
                {saving ? "Creating…" : "Create key"}
              </button>
            </div>
          </form>
        )}
      </Modal>
    </div>
  );
}
