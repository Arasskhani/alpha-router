import { FormEvent, useId, useRef, useState } from "react";
import { mailApi, type MailConnection } from "../../lib/exchangeMail";
import { STALE_CODES, mailErrorCode, mailErrorText } from "./mailFormat";

type Props = {
  /** The login Exchange is asked with: the person's own AD account, shown and never editable. */
  login: string;
  mode: "connect" | "update";
  disabled: boolean;
  onConnected: (connection: MailConnection) => void;
  /** The server's answer means the page's picture is out of date (a refused password, say). */
  onStale: () => void;
  onCancel?: () => void;
};

/**
 * Connect, or give the password again. The password is cleared after every
 * try, right or wrong: it is not kept on the page longer than needed.
 */
export default function MailPasswordForm({ login, mode, disabled, onConnected, onStale, onCancel }: Props) {
  const id = useId();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const passwordRef = useRef<HTMLInputElement>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!password || busy || disabled) return;
    setBusy(true);
    setError("");
    try {
      const connection = await mailApi.connect(password);
      setPassword("");
      onConnected(connection);
    } catch (err) {
      setPassword("");
      setError(mailErrorText(err, "connect"));
      if (STALE_CODES.has(mailErrorCode(err) ?? "")) onStale();
      passwordRef.current?.focus();
    } finally {
      setBusy(false);
    }
  }

  const label = mode === "connect" ? "Connect" : "Save password";
  return (
    <form className="mail-password" onSubmit={submit} aria-label={mode === "connect" ? "Connect your mailbox" : "Update password"}>
      <div className="smtp-field-row mail-password__row">
        <div className="smtp-field">
          <label htmlFor={`${id}-login`}>User name</label>
          <input id={`${id}-login`} value={login} readOnly aria-readonly="true" className="mail-password__login" />
        </div>
        <div className="smtp-field">
          <label htmlFor={`${id}-password`}>Password</label>
          <input
            ref={passwordRef}
            id={`${id}-password`}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            // The person's own directory password, the one they sign in with.
            autoComplete="current-password"
            disabled={disabled}
            maxLength={256}
            aria-describedby={`${id}-note`}
          />
        </div>
      </div>
      <p id={`${id}-note`} className="smtp-hint">
        Your password is stored encrypted and used only to reach your mailbox. If you change your AD password, enter
        the new one here.
      </p>
      {error ? (
        <p className="alert alert-error mail-alert" role="alert">
          {error}
        </p>
      ) : null}
      <div className="mail-password__actions">
        <button type="submit" className="btn" disabled={disabled || busy || !password}>
          {busy ? (mode === "connect" ? "Connecting…" : "Saving…") : label}
        </button>
        {onCancel ? (
          <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
        ) : null}
      </div>
    </form>
  );
}
