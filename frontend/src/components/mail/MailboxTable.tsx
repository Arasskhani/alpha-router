import { FormEvent, useState } from "react";
import { useConfirm } from "../../context/ConfirmContext";
import { useTableCards } from "../../hooks/useTableCards";
import {
  mailApi,
  type MailCapabilities,
  type MailConnection,
  type Mailbox,
  type MailboxSource,
} from "../../lib/exchangeMail";
import { STALE_CODES, mailErrorCode, mailErrorText, type MailErrorContext } from "./mailFormat";
import MailSwitch from "./MailSwitch";

const SOURCE_LABELS: Record<MailboxSource, string> = {
  own: "Your account",
  autodiscover: "Autodiscover",
  manual: "Added by you",
};

type Props = {
  connection: MailConnection;
  capabilities: MailCapabilities;
  readOnly: boolean;
  onChanged: (connection: MailConnection) => void;
  onStale: () => void;
};

/** "Found 2 new mailboxes." after Find again, from the lists before and after. */
function rediscoverNotice(before: Mailbox[], after: Mailbox[]): string {
  const had = new Set(before.map((m) => m.smtp));
  const has = new Set(after.map((m) => m.smtp));
  const added = after.filter((m) => !had.has(m.smtp)).length;
  const removed = before.filter((m) => !has.has(m.smtp)).length;
  const parts = [
    added === 0 ? "No new mailboxes found." : added === 1 ? "Found 1 new mailbox." : `Found ${added} new mailboxes.`,
  ];
  if (removed === 1) parts.push("1 mailbox is no longer shared with you and was removed.");
  else if (removed > 1) parts.push(`${removed} mailboxes are no longer shared with you and were removed.`);
  return parts.join(" ");
}

/**
 * The connection's mailboxes: the person's own and the Full Access ones, each
 * with "Use in chat" and "Notify", plus Add a mailbox and Find again when the
 * administrator allows them.
 */
export default function MailboxTable({ connection, capabilities, readOnly, onChanged, onStale }: Props) {
  const tableRef = useTableCards<HTMLTableElement>();
  const { confirm } = useConfirm();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [address, setAddress] = useState("");

  const mailboxes = connection.mailboxes;
  // The administrator's limit counts the Full Access mailboxes only, not the person's own.
  const fullAccess = mailboxes.filter((m) => m.kind === "full_access").length;
  const canAdd = capabilities.full_access && capabilities.manual_mailboxes;
  const notifyColumn = capabilities.notifications;
  const locked = readOnly || busy !== null;

  async function run(
    key: string,
    context: MailErrorContext,
    call: () => Promise<MailConnection>,
    done?: (next: MailConnection) => string,
  ): Promise<boolean> {
    setBusy(key);
    setError("");
    setNotice("");
    try {
      const next = await call();
      onChanged(next);
      if (done) setNotice(done(next));
      return true;
    } catch (err) {
      setError(mailErrorText(err, context, capabilities.max_mailboxes));
      if (STALE_CODES.has(mailErrorCode(err) ?? "")) onStale();
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function remove(mailbox: Mailbox) {
    const ok = await confirm({
      title: "Remove mailbox",
      message:
        mailbox.source === "autodiscover"
          ? `Remove ${mailbox.smtp}? The chat stops using it. Find again adds it back while you have Full Access.`
          : `Remove ${mailbox.smtp}? The chat stops using it. You can add it again later.`,
      emphasize: mailbox.smtp,
      confirmLabel: "Remove",
      danger: true,
    });
    if (ok !== true) return;
    await run(`remove:${mailbox.id}`, "mailbox", () => mailApi.removeMailbox(mailbox.id), () => `${mailbox.smtp} was removed.`);
  }

  async function add(e: FormEvent) {
    e.preventDefault();
    const smtp = address.trim();
    if (!smtp || locked) return;
    const ok = await run("add", "mailbox", () => mailApi.addMailbox(smtp), () => `${smtp} was added.`);
    if (ok) setAddress("");
  }

  return (
    <div className="mail-mailboxes">
      <div className="mail-section-head">
        <h3>Mailboxes</h3>
        {capabilities.full_access ? (
          <span className="muted-text" data-testid="mail-full-access-count">
            {fullAccess} of {capabilities.max_mailboxes} Full Access
          </span>
        ) : null}
      </div>
      <p className="smtp-hint mail-section-hint">
        {capabilities.full_access
          ? `Your own mailbox, and up to ${capabilities.max_mailboxes} ${capabilities.max_mailboxes === 1 ? "mailbox" : "mailboxes"} you have Full Access to. The chat uses the ones turned on.`
          : "Your own mailbox. Your administrator has not allowed other mailboxes."}
      </p>

      <table ref={tableRef} className="data-table data-table--cards mail-mailbox-table">
        <thead>
          <tr>
            <th>Mailbox</th>
            <th>Type</th>
            <th>Source</th>
            <th>Use in chat</th>
            {notifyColumn ? <th>Notify</th> : null}
            {/* No text: on a phone the header becomes each card's label, and the button says it already. */}
            <th aria-label="Remove" />
          </tr>
        </thead>
        <tbody>
          {mailboxes.map((mailbox) => {
            const own = mailbox.kind === "own";
            return (
              <tr key={mailbox.id}>
                <td>
                  <span className="mail-mailbox__smtp">{mailbox.smtp}</span>
                  {mailbox.display_name ? (
                    <span className="mail-mailbox__name" dir="auto">
                      {mailbox.display_name}
                    </span>
                  ) : null}
                  {mailbox.last_error ? <span className="mail-mailbox__error">{mailbox.last_error}</span> : null}
                </td>
                <td>{own ? "Own" : "Full access"}</td>
                <td>{SOURCE_LABELS[mailbox.source] ?? mailbox.source}</td>
                <td>
                  {own ? (
                    <span className="muted-text">Always</span>
                  ) : (
                    <MailSwitch
                      on={mailbox.enabled}
                      label={`Use ${mailbox.smtp} in chat`}
                      disabled={locked}
                      onChange={(enabled) =>
                        void run(`enabled:${mailbox.id}`, "mailbox", () => mailApi.updateMailbox(mailbox.id, { enabled }))
                      }
                    />
                  )}
                </td>
                {notifyColumn ? (
                  <td>
                    <MailSwitch
                      on={mailbox.notify}
                      label={`Notify about emails in ${mailbox.smtp}`}
                      disabled={locked}
                      onChange={(notify) =>
                        void run(`notify:${mailbox.id}`, "mailbox", () => mailApi.updateMailbox(mailbox.id, { notify }))
                      }
                    />
                  </td>
                ) : null}
                <td>
                  {own ? null : (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      aria-label={`Remove ${mailbox.smtp}`}
                      disabled={locked}
                      onClick={() => void remove(mailbox)}
                    >
                      Remove
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {error ? (
        <p className="alert alert-error mail-alert" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="alert alert-success mail-alert" role="status">
          {notice}
        </p>
      ) : null}

      {canAdd || capabilities.full_access ? (
        <div className="mail-mailbox-tools">
          {canAdd ? (
            <form className="mail-add" onSubmit={add} aria-label="Add a mailbox">
              <label htmlFor="mail-add-address">Add a mailbox</label>
              <div className="mail-add__row">
                <input
                  id="mail-add-address"
                  type="text"
                  inputMode="email"
                  className="input-block"
                  value={address}
                  onChange={(e) => setAddress(e.target.value)}
                  placeholder="shared@company.com"
                  autoComplete="off"
                  spellCheck={false}
                  disabled={readOnly}
                  aria-describedby="mail-add-hint"
                />
                <button type="submit" className="btn" disabled={locked || !address.trim()}>
                  {busy === "add" ? "Checking…" : "Add"}
                </button>
              </div>
              <p id="mail-add-hint" className="smtp-hint">
                A shared or other mailbox you have Full Access to. Alpharouter checks that it can open it first.
              </p>
            </form>
          ) : null}
          {capabilities.full_access ? (
            <div className="mail-find">
              <button
                type="button"
                className="btn btn-ghost"
                disabled={locked}
                onClick={() =>
                  void run("find", "mailbox", () => mailApi.rediscover(), (next) =>
                    rediscoverNotice(mailboxes, next.mailboxes),
                  )
                }
              >
                {busy === "find" ? "Looking…" : "Find again"}
              </button>
              <span className="smtp-hint">Looks again for the mailboxes Exchange gives you Full Access to.</span>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
