import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { formatLocalDateTime } from "../../lib/dateTime";
import { announceMailChanged, mailApi, safeOwaUrl, type ActionItem } from "../../lib/exchangeMail";
import { agoText } from "../support/supportFormat";
import { askAlpharouter } from "./askAlpharouter";
import { STALE_CODES, mailErrorCode, mailErrorText, senderLabel, subjectLabel } from "./mailFormat";

type Props = {
  items: ActionItem[] | null;
  loadError: string;
  /** The person's own address: other mailboxes are named on their items. */
  ownMailbox: string;
  notifyEnabled: boolean;
  readOnly: boolean;
  onRetry: () => void;
  /** An item was closed here (Done, Dismiss): take it off the list. */
  onClosed: (id: number) => void;
  onStale: () => void;
};

/** "Waiting for your action": the emails the check picked out, with Ask Alpharouter, Open in Outlook, Done, Dismiss. */
export default function MailActionList({
  items,
  loadError,
  ownMailbox,
  notifyEnabled,
  readOnly,
  onRetry,
  onClosed,
  onStale,
}: Props) {
  const navigate = useNavigate();
  const location = useLocation();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  async function act(key: string, call: () => Promise<unknown>, closes?: number) {
    setBusy(key);
    setError("");
    try {
      await call();
      if (closes !== undefined) {
        onClosed(closes);
        announceMailChanged();
      }
    } catch (err) {
      setError(mailErrorText(err, "action"));
      if (STALE_CODES.has(mailErrorCode(err) ?? "")) onStale();
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="card mail-card mail-actions" id="mail-actions" aria-labelledby="mail-actions-title">
      <div className="mail-section-head">
        <h2 id="mail-actions-title">Waiting for your action</h2>
        {items && items.length > 0 ? <span className="mail-count">{items.length}</span> : null}
      </div>

      {loadError ? (
        <div className="alert alert-error support-alert" role="alert">
          <span>{loadError}</span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onRetry}>
            Try again
          </button>
        </div>
      ) : null}
      {error ? (
        <p className="alert alert-error mail-alert" role="alert">
          {error}
        </p>
      ) : null}

      {!items && !loadError ? <p className="muted-text">Loading…</p> : null}

      {items && items.length === 0 ? (
        <p className="support-empty">
          {notifyEnabled
            ? "Nothing is waiting for you."
            : "Turn on “Tell me about emails that need my action” above to see emails that need you here."}
        </p>
      ) : null}

      {items && items.length > 0 ? (
        <ul className="mail-action-list" aria-label="Emails waiting for your action">
          {items.map((item) => {
            const owa = safeOwaUrl(item.owa_url);
            const other = item.mailbox && item.mailbox.toLowerCase() !== ownMailbox.toLowerCase();
            const when = item.received_at || item.created_at;
            // The same buttons repeat on every row: a screen reader hears which email each one is for.
            const subject = subjectLabel(item.subject);
            return (
              <li key={item.id} className="mail-action">
                <div className="mail-action__main">
                  <span className="mail-action__subject" dir="auto">
                    {subject}
                    {item.importance === "High" ? <span className="mail-important">Important</span> : null}
                  </span>
                  <span className="mail-action__meta">
                    <span dir="auto">{senderLabel(item)}</span>
                    {when ? <span title={formatLocalDateTime(when)}>{agoText(when)}</span> : null}
                    {other ? (
                      <span className="support-cat mail-action__mailbox" title={item.mailbox}>
                        {item.mailbox}
                      </span>
                    ) : null}
                  </span>
                  {item.reason ? (
                    <span className="mail-action__reason" dir="auto">
                      {item.reason}
                    </span>
                  ) : null}
                </div>
                <div className="mail-action__buttons">
                  <button
                    type="button"
                    className="btn btn-sm"
                    aria-label={`Ask Alpharouter: ${subject}`}
                    disabled={readOnly || busy !== null}
                    onClick={() =>
                      void act(`ask:${item.id}`, () => askAlpharouter(item.id, navigate, location.pathname))
                    }
                  >
                    {busy === `ask:${item.id}` ? "Opening…" : "Ask Alpharouter"}
                  </button>
                  {owa ? (
                    <a
                      className="btn btn-ghost btn-sm btn-readonly-ok"
                      href={owa}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={`Open in Outlook: ${subject}`}
                    >
                      Open in Outlook
                    </a>
                  ) : null}
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    aria-label={`Done: ${subject}`}
                    disabled={readOnly || busy !== null}
                    onClick={() => void act(`done:${item.id}`, () => mailApi.doneAction(item.id), item.id)}
                  >
                    Done
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    aria-label={`Dismiss: ${subject}`}
                    disabled={readOnly || busy !== null}
                    onClick={() => void act(`dismiss:${item.id}`, () => mailApi.dismissAction(item.id), item.id)}
                  >
                    Dismiss
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
