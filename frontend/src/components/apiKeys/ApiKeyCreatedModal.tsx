import { useState } from "react";
import { api } from "../../api";
import Modal from "../Modal";

type Props = {
  open: boolean;
  apiKey: string;
  url: string;
  name?: string;
  ownerUserId: number;
  ownerEmail: string;
  onClose: () => void;
};

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
      className="api-key-created__copy"
      onClick={() => void handleCopy()}
      title={label}
      aria-label={label}
    >
      {copied ? (
        <span className="api-key-created__copy-done">✓</span>
      ) : (
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
          <rect x="9" y="9" width="13" height="13" rx="2" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
      )}
    </button>
  );
}

function SecretRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="api-key-created__block">
      <p className="api-key-created__field-label">{label}</p>
      <div className="api-key-created__row">
        <input readOnly value={value} className="api-key-created__field mono" aria-label={label} />
        <CopyButton value={value} label={`Copy ${label}`} />
      </div>
    </div>
  );
}

export default function ApiKeyCreatedModal({
  open,
  apiKey,
  url,
  name,
  ownerUserId,
  ownerEmail,
  onClose,
}: Props) {
  const [emailBusy, setEmailBusy] = useState(false);
  const [emailMsg, setEmailMsg] = useState("");
  const [emailErr, setEmailErr] = useState("");
  const [copyToMe, setCopyToMe] = useState(false);
  const [emailSent, setEmailSent] = useState(false);

  const canDismissFreely = emailSent;

  async function sendToOwner() {
    setEmailBusy(true);
    setEmailMsg("");
    setEmailErr("");
    try {
      const res = await api<{ ok: boolean; to: string; cc?: string | null }>(
        "/api/admin/api-keys/email-credentials",
        {
          method: "POST",
          body: JSON.stringify({
            owner_user_id: ownerUserId,
            name: name ?? "API key",
            api_key: apiKey,
            url,
            copy_to_admin: copyToMe,
          }),
        },
      );
      setEmailMsg(res.cc ? `Sent to ${res.to} (copy to ${res.cc})` : `Sent to ${res.to}`);
      setEmailSent(true);
    } catch (ex) {
      setEmailErr(String(ex));
    } finally {
      setEmailBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      title=""
      onClose={onClose}
      compactHeader
      closeOnBackdrop={canDismissFreely}
      closeOnEscape={canDismissFreely}
    >
      <div className="api-key-created">
        {name ? <p className="api-key-created__name muted-text">{name}</p> : null}
        <SecretRow label="Your new key:" value={apiKey} />
        <SecretRow label="Base URL (OpenAI-compatible):" value={url} />
        <div className="api-key-created__email">
          <div className="api-key-created__email-actions">
            <button
              type="button"
              className="btn btn-ghost api-key-created__email-btn"
              disabled={emailBusy || !ownerEmail}
              onClick={() => void sendToOwner()}
              title={ownerEmail ? `Send credentials to ${ownerEmail}` : "Owner has no email"}
            >
              {emailBusy ? "Sending…" : "Email to owner"}
            </button>
            <label className="api-key-created__email-copy">
              <input
                type="checkbox"
                checked={copyToMe}
                disabled={emailBusy}
                onChange={(e) => setCopyToMe(e.target.checked)}
              />
              Send me a copy
            </label>
          </div>
          {ownerEmail ? (
            <span className="muted-text api-key-created__email-hint">{ownerEmail}</span>
          ) : (
            <span className="muted-text api-key-created__email-hint">No owner email on file</span>
          )}
        </div>
        {emailMsg && <p className="alert alert-success api-key-created__email-status">{emailMsg}</p>}
        {emailErr && <p className="alert alert-error api-key-created__email-status">{emailErr}</p>}
        <p className="api-key-created__warn">
          Please copy it now and write it down somewhere safe.{" "}
          <strong>You will not be able to see it again.</strong>
        </p>
        <p className="api-key-created__footer muted-text">
          You can use it with OpenAI-compatible apps (Open WebUI, Kilo Code, scripts), or{" "}
          <a href="/admin/docs#platform-api" target="_blank" rel="noopener noreferrer">
            read the setup guide in Docs
          </a>{" "}
          (opens in a new tab).
        </p>
      </div>
    </Modal>
  );
}
