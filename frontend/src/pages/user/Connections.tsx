import { useCallback, useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { bootstrapSession } from "../../api";
import AdminPage from "../../components/AdminPage";
import { IconMail } from "../../components/icons/navIcons";
import MailActionList from "../../components/mail/MailActionList";
import MailboxTable from "../../components/mail/MailboxTable";
import MailPasswordForm from "../../components/mail/MailPasswordForm";
import MailSwitch from "../../components/mail/MailSwitch";
import { STALE_CODES, mailErrorCode, mailErrorText } from "../../components/mail/mailFormat";
import { agoText } from "../../components/support/supportFormat";
import { useConfirm } from "../../context/ConfirmContext";
import { useReadOnly } from "../../context/ReadOnlyContext";
import { formatLocalDateTime } from "../../lib/dateTime";
import {
  CONNECTION_STATUS_LABELS,
  MAIL_CHANGED_EVENT,
  announceMailChanged,
  mailApi,
  type ActionItem,
  type MailCapabilities,
  type MailConnection,
  type MailStatus,
} from "../../lib/exchangeMail";

/** The connection changed in a way the session's switches follow (the sign by the chat box). */
function refreshSession() {
  void bootstrapSession(true).catch(() => undefined);
}

/** What connecting allows, from what the administrator turned on. */
function CapabilityList({ capabilities }: { capabilities: MailCapabilities }) {
  const things = ["Read and search your email", "Summarise emails and threads"];
  if (capabilities.drafts) things.push("Draft new emails, replies and forwards");
  if (capabilities.free_time) things.push("Find a free time to meet");
  if (capabilities.notifications) things.push("Tell you about emails that need your action");
  return (
    <>
      <p>Connect your Exchange mailbox to use it in the chat. Alpharouter can:</p>
      <ul className="mail-capabilities">
        {things.map((thing) => (
          <li key={thing}>{thing}</li>
        ))}
      </ul>
      <p className="mail-promise">
        Nothing is sent without you. You review each draft and press Send yourself.
      </p>
    </>
  );
}

/**
 * Connections: the person's own Exchange mailbox (/app/connections, and
 * /admin/my-connections in the admin panel). /status comes first: it says
 * whether this account may connect and, once connected, carries the mailboxes
 * and what the administrator allows.
 */
export default function Connections() {
  const readOnly = useReadOnly();
  const location = useLocation();
  const { confirm } = useConfirm();
  const [status, setStatus] = useState<MailStatus | null>(null);
  const [loadError, setLoadError] = useState("");
  const [tick, setTick] = useState(0);
  const [items, setItems] = useState<ActionItem[] | null>(null);
  const [itemsError, setItemsError] = useState("");
  const [itemsTick, setItemsTick] = useState(0);
  const [updating, setUpdating] = useState(false);
  const [busy, setBusy] = useState<"notify" | "disconnect" | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const reload = useCallback(() => setTick((n) => n + 1), []);
  const reloadItems = useCallback(() => setItemsTick((n) => n + 1), []);
  const stale = useCallback(() => {
    reload();
    refreshSession();
  }, [reload]);

  useEffect(() => {
    let cancelled = false;
    mailApi
      .status()
      .then((s) => {
        if (cancelled) return;
        setStatus(s);
        setLoadError("");
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(mailErrorText(err));
      });
    return () => {
      cancelled = true;
    };
  }, [tick]);

  const connection = status?.eligible ? status.connection : null;
  const listsActions = Boolean(connection && status?.capabilities.notifications);

  useEffect(() => {
    if (!listsActions) return undefined;
    let cancelled = false;
    mailApi
      .actionItems("open")
      .then((list) => {
        if (cancelled) return;
        setItems(list.items);
        setItemsError("");
      })
      .catch((err: unknown) => {
        if (!cancelled) setItemsError(mailErrorText(err));
      });
    return () => {
      cancelled = true;
    };
  }, [listsActions, itemsTick]);

  // A toast's Dismiss (or another tab) changed the list.
  useEffect(() => {
    window.addEventListener(MAIL_CHANGED_EVENT, reloadItems);
    return () => window.removeEventListener(MAIL_CHANGED_EVENT, reloadItems);
  }, [reloadItems]);

  // "N more emails need your action" links here with #mail-actions.
  const wantsActions = location.hash === "#mail-actions";
  const itemsShown = items !== null;
  useEffect(() => {
    if (wantsActions && itemsShown) document.getElementById("mail-actions")?.scrollIntoView?.({ block: "start" });
  }, [wantsActions, itemsShown]);

  function applyConnection(next: MailConnection | null) {
    setStatus((s) => (s ? { ...s, connection: next } : s));
    announceMailChanged();
  }

  async function setNotify(on: boolean) {
    setBusy("notify");
    setError("");
    setNotice("");
    try {
      applyConnection(await mailApi.setNotify(on));
    } catch (err) {
      setError(mailErrorText(err));
      if (STALE_CODES.has(mailErrorCode(err) ?? "")) stale();
    } finally {
      setBusy(null);
    }
  }

  async function disconnect() {
    const ok = await confirm({
      title: "Disconnect mailbox",
      message:
        "Disconnect your Exchange mailbox? Alpharouter forgets your password and your mailbox list. The chat can no longer use your mail. Your emails stay in Exchange.",
      confirmLabel: "Disconnect",
      danger: true,
    });
    if (ok !== true) return;
    setBusy("disconnect");
    setError("");
    setNotice("");
    try {
      await mailApi.disconnect();
      setUpdating(false);
      setItems(null);
      applyConnection(null);
      refreshSession();
      setNotice("Your mailbox is disconnected.");
    } catch (err) {
      setError(mailErrorText(err));
    } finally {
      setBusy(null);
    }
  }

  function connected(next: MailConnection, wasUpdate: boolean) {
    setUpdating(false);
    setError("");
    setNotice(wasUpdate ? "Password saved. Your mailbox is connected." : "Your mailbox is connected.");
    applyConnection(next);
    refreshSession();
    reloadItems();
  }

  if (!status) {
    return (
      <AdminPage title="Connections">
        {loadError ? (
          <div className="alert alert-error support-alert" role="alert">
            <span>{loadError}</span>
            <button type="button" className="btn btn-ghost btn-sm" onClick={reload}>
              Try again
            </button>
          </div>
        ) : (
          <p className="muted-text">Loading…</p>
        )}
      </AdminPage>
    );
  }

  const caps = status.capabilities;
  const showUpdate = connection !== null && (updating || connection.status === "needs_password");
  const checked = connection?.last_checked_at || connection?.last_ok_at || null;

  return (
    <AdminPage title="Connections">
      <p className="support-intro">Services Alpharouter can use for you in the chat.</p>

      <section className="card mail-card" aria-labelledby="mail-card-title">
        <div className="mail-card__head">
          <span className="mail-card__icon" aria-hidden="true">
            <IconMail />
          </span>
          <h2 id="mail-card-title">Exchange mailbox</h2>
          {connection ? (
            <span className={`support-badge support-badge--status mail-status mail-status--${connection.status}`}>
              <i aria-hidden="true" />
              {CONNECTION_STATUS_LABELS[connection.status] ?? connection.status}
            </span>
          ) : null}
        </div>

        {!status.eligible ? (
          <p className="mail-ineligible" role="status">
            {status.message || "Your account cannot connect a mailbox."}
          </p>
        ) : !connection ? (
          <div className="mail-connect">
            <CapabilityList capabilities={caps} />
            {notice ? (
              <p className="alert alert-success mail-alert" role="status">
                {notice}
              </p>
            ) : null}
            <MailPasswordForm
              login={status.login}
              mode="connect"
              disabled={readOnly}
              onConnected={(next) => connected(next, false)}
              onStale={stale}
            />
          </div>
        ) : (
          <div className="mail-connected">
            <div className="mail-identity">
              <span className="mail-identity__smtp">{connection.primary_smtp}</span>
              {connection.display_name ? (
                <span className="mail-identity__name" dir="auto">
                  {connection.display_name}
                </span>
              ) : null}
              <span className="mail-identity__meta">
                <span>Signed in as {connection.login}</span>
                {checked ? (
                  <span title={formatLocalDateTime(checked)}>Last checked {agoText(checked)}</span>
                ) : null}
              </span>
            </div>

            {connection.status === "needs_password" ? (
              <p className="alert alert-warning mail-alert" role="status">
                Exchange did not accept your saved password. Enter your current password to use your mailbox again.
              </p>
            ) : null}
            {connection.status === "error" ? (
              <p className="alert alert-error mail-alert" role="status">
                {connection.last_error || "The last check of your mailbox failed."}
              </p>
            ) : null}
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

            {showUpdate ? (
              <MailPasswordForm
                login={connection.login}
                mode="update"
                disabled={readOnly}
                onConnected={(next) => connected(next, true)}
                onStale={stale}
                onCancel={connection.status === "needs_password" ? undefined : () => setUpdating(false)}
              />
            ) : null}

            <div className="mail-card__actions">
              {!showUpdate ? (
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={readOnly || busy !== null}
                  onClick={() => {
                    setNotice("");
                    setUpdating(true);
                  }}
                >
                  Update password
                </button>
              ) : null}
              <button
                type="button"
                className="btn btn-ghost mail-danger-ghost"
                disabled={readOnly || busy !== null}
                onClick={() => void disconnect()}
              >
                {busy === "disconnect" ? "Disconnecting…" : "Disconnect"}
              </button>
            </div>

            {caps.notifications ? (
              <div className="mail-setting">
                <span className="mail-setting__text">
                  <span className="mail-setting__label" id="mail-notify-label">
                    Tell me about emails that need my action
                  </span>
                  <span className="smtp-hint">
                    Alpharouter checks your Inbox every few minutes and shows a note in the app.
                  </span>
                </span>
                <MailSwitch
                  on={connection.notify_enabled}
                  label="Tell me about emails that need my action"
                  disabled={readOnly || busy !== null}
                  onChange={(on) => void setNotify(on)}
                />
              </div>
            ) : null}

            <MailboxTable
              connection={connection}
              capabilities={caps}
              readOnly={readOnly}
              onChanged={applyConnection}
              onStale={stale}
            />
          </div>
        )}
      </section>

      {connection && caps.notifications ? (
        <MailActionList
          items={items}
          loadError={itemsError}
          ownMailbox={connection.primary_smtp}
          notifyEnabled={connection.notify_enabled}
          readOnly={readOnly}
          onRetry={reloadItems}
          onClosed={(id) => setItems((list) => (list ? list.filter((item) => item.id !== id) : list))}
          onStale={stale}
        />
      ) : null}
    </AdminPage>
  );
}
