import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";

import Modal from "./Modal";
import { useConfirm } from "../context/ConfirmContext";
import { PRODUCT_NAME } from "../lib/brand";
import { formatLocalDateTime } from "../lib/dateTime";
import { EXCHANGE_BLOCKED_TEXT } from "./mail/mailFormat";
import {
  MailApiError,
  isLiveDraft,
  mailApi,
  safeOwaUrl,
  type MailAddress,
  type MailDraft,
  type MailDraftCard,
  type DraftStatus,
  type MailDraftLive,
} from "../lib/exchangeMail";

export const CONFLICT_NOTICE = "The draft changed in Outlook; check it again";
export const SEND_OFF_NOTICE = `Sending from ${PRODUCT_NAME} is turned off by your administrator. Open the draft in Outlook to send it.`;
export const SENDING_ELSEWHERE_NOTICE = "This draft is already being sent from another window. Check again in a moment.";

type Notice = { tone: "info" | "warning"; text: string };

/** Why the draft cannot be shown, and what the person can do about it. */
type Problem = { message: string; connections: boolean; retry: boolean };

type Props = {
  card: MailDraftCard;
  /** Every state of the draft the dialog learns from the server (read, sent, discarded, failed). Keep it stable. */
  onDraft: (draft: MailDraft | MailDraftLive) => void;
  onClose: () => void;
};

/** Codes that mean the mailbox itself is out of reach: the draft is not the problem. */
const MAILBOX_CODES = new Set(["needs_password", "exchange_auth", "connection_error", "not_connected", "not_eligible"]);

function serverText(err: unknown, fallback: string): string {
  return err instanceof MailApiError && err.serverMessage ? err.message : fallback;
}

function problemFor(err: unknown): Problem {
  if (err instanceof MailApiError) {
    if (err.code === "needs_password" || err.code === "exchange_auth") {
      return {
        message: "Exchange no longer accepts the saved password. Enter your current password in Connections, then try again.",
        connections: true,
        retry: false,
      };
    }
    if (err.code === "connection_error") {
      // Stopped because the saved password opened another mailbox: typing the own password in Connections
      // restarts it. No retry here.
      return {
        message: "The connection to your mailbox stopped. Enter your password again in Connections to reconnect, then try again.",
        connections: true,
        retry: false,
      };
    }
    if (err.code === "exchange_blocked") {
      return { message: EXCHANGE_BLOCKED_TEXT, connections: false, retry: true };
    }
    if (err.code === "not_connected") {
      return { message: "Your mailbox is not connected. Connect it in Connections first.", connections: true, retry: false };
    }
    if (err.code === "not_eligible") {
      return { message: serverText(err, "Your account cannot use a mailbox here."), connections: false, retry: false };
    }
    if (err.status === 404 && !err.code?.startsWith("exchange_")) {
      return { message: "This draft was not found.", connections: false, retry: false };
    }
  }
  return {
    message: serverText(err, "The draft could not be read from your mailbox. Try again in a moment."),
    connections: false,
    retry: true,
  };
}

function addressList(list: MailAddress[]): string {
  return list.map((a) => (a.name.trim() && a.name.trim() !== a.email ? `${a.name.trim()} <${a.email}>` : a.email)).join(", ");
}

/** What happened to a draft that is no longer in Drafts (or could not be sent). */
function StatusNote({ draft }: { draft: MailDraft }) {
  if (draft.status === "sent") {
    return (
      <p className="alert alert-success" role="status">
        Sent{draft.sent_at ? ` ${formatLocalDateTime(draft.sent_at)}` : ""}. A copy is in Sent Items.
      </p>
    );
  }
  if (draft.status === "discarded") {
    return (
      <p className="alert alert-info" role="status">
        {draft.error || "This draft was discarded."}
      </p>
    );
  }
  if (draft.status === "failed") {
    return (
      <p className="alert alert-error" role="alert">
        The email was not sent{draft.error ? `: ${draft.error}` : "."}
      </p>
    );
  }
  if (draft.status === "sending") {
    return (
      <p className="alert alert-info" role="status">
        This email is being sent right now.
      </p>
    );
  }
  return null;
}

/**
 * Review & send: the draft as it is now in the person's mailbox (read again
 * from Exchange, never from the card), sent only when they press Send. The
 * send carries the change key read here, so a draft edited in Outlook since is
 * read again rather than sent unseen.
 */
export default function MailReviewDialog({ card, onDraft, onClose }: Props) {
  const { confirm } = useConfirm();
  const [draft, setDraft] = useState<MailDraft | MailDraftLive | null>(null);
  // Each read of the draft is a request; a notice can ride along to explain why it was read again,
  // and `after` is the state a refused send or discard found the draft in.
  const [request, setRequest] = useState<{ n: number; notice: Notice | null; after: DraftStatus | null }>({
    n: 0,
    notice: null,
    after: null,
  });
  const [loaded, setLoaded] = useState(-1);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState<"send" | "discard" | null>(null);
  const [owaUrl, setOwaUrl] = useState<string | null>(null);
  const loading = loaded !== request.n;

  useEffect(() => {
    let cancelled = false;
    mailApi
      .draft(card.id)
      .then((next) => {
        if (cancelled) return;
        setDraft(next);
        setProblem(null);
        setNotice(request.notice);
        // The draft moved on (sent, failed, gone): its own status says what happened, once.
        if (request.after && next.status !== request.after) setActionError("");
        if (isLiveDraft(next)) setOwaUrl(safeOwaUrl(next.owa_url));
        onDraft(next);
      })
      .catch((err: unknown) => {
        if (!cancelled) setProblem(problemFor(err));
      })
      .finally(() => {
        if (!cancelled) setLoaded(request.n);
      });
    return () => {
      cancelled = true;
    };
  }, [card.id, request, onDraft]);

  const readAgain = (withNotice: Notice | null, after: DraftStatus | null = null) =>
    setRequest((r) => ({ n: r.n + 1, notice: withNotice, after }));

  const finished = (next: MailDraft) => {
    setDraft(next);
    onDraft(next);
  };

  /** A refused send or discard: answer each code the API gives, else read the draft again to show where it stands. */
  const refused = (err: unknown, current: MailDraft | MailDraftLive) => {
    const code = err instanceof MailApiError ? err.code : null;
    if (code === "exchange_conflict") {
      readAgain({ tone: "info", text: CONFLICT_NOTICE });
      return;
    }
    if (code === "send_off") {
      if (isLiveDraft(current)) setDraft({ ...current, can_send: false });
      setNotice({ tone: "warning", text: SEND_OFF_NOTICE });
      return;
    }
    if (code && MAILBOX_CODES.has(code)) {
      setProblem(problemFor(err));
      return;
    }
    if (code === "send_in_progress") {
      // Another window claimed it: show where it stands now, with why.
      readAgain({ tone: "info", text: SENDING_ELSEWHERE_NOTICE });
      return;
    }
    if (code === "exchange_blocked") {
      // About the login, not this draft: reading it again would be refused the same way.
      setActionError(EXCHANGE_BLOCKED_TEXT);
      return;
    }
    if (err instanceof MailApiError && err.status === 429) {
      setActionError(serverText(err, "Too many emails for now. Wait a while, then try again."));
      return;
    }
    setActionError(serverText(err, "That did not work. Try again in a moment."));
    // A failed send is kept on the draft (status "failed"), and "not_a_draft" means it moved on
    // meanwhile: either way, show the draft as it is now. A discard refused for a failed draft
    // leaves it failed, and the error stays shown under it.
    readAgain(null, current.status);
  };

  const send = async () => {
    if (!draft || !isLiveDraft(draft) || !draft.can_send || busy) return;
    setBusy("send");
    setActionError("");
    setNotice(null);
    try {
      finished(await mailApi.sendDraft(draft.id, draft.change_key));
    } catch (err) {
      refused(err, draft);
    } finally {
      setBusy(null);
    }
  };

  const discard = async () => {
    if (!draft || busy) return;
    const ok = await confirm({
      title: "Discard this draft?",
      message: "It will be deleted from Drafts in your mailbox. This cannot be undone here.",
      confirmLabel: "Discard",
      cancelLabel: "Keep",
      danger: true,
    });
    if (ok !== true) return;
    setBusy("discard");
    setActionError("");
    setNotice(null);
    try {
      finished(await mailApi.discardDraft(draft.id));
    } catch (err) {
      refused(err, draft);
    } finally {
      setBusy(null);
    }
  };

  const close = () => {
    if (!busy) onClose();
  };

  const live = draft && isLiveDraft(draft) ? draft : null;
  const canDiscard = !!draft && (draft.status === "draft" || draft.status === "failed");
  const text = live ? live.body_text : (draft?.body_preview ?? "");
  const sendTitle = live && !live.can_send ? SEND_OFF_NOTICE : undefined;

  return createPortal(
    <Modal
      open
      title="Review & send"
      onClose={close}
      closeOnBackdrop={!busy}
      closeOnEscape={!busy}
      panelClassName="mail-review"
    >
      {problem ? (
        <div className="mail-review__problem">
          <p className="alert alert-error" role="alert">
            {problem.message}
          </p>
          {problem.connections ? (
            <p>
              <Link to="/app/connections" onClick={onClose}>
                Open Connections
              </Link>
            </p>
          ) : null}
        </div>
      ) : draft ? (
        <>
          {notice ? (
            <p className={`alert alert-${notice.tone}`} role="status">
              {notice.text}
            </p>
          ) : null}
          <StatusNote draft={draft} />
          <dl className="mail-review__fields">
            <dt>From</dt>
            <dd>{draft.mailbox}</dd>
            <dt>To</dt>
            <dd dir="auto">{addressList(draft.to) || "—"}</dd>
            {draft.cc.length ? (
              <>
                <dt>Cc</dt>
                <dd dir="auto">{addressList(draft.cc)}</dd>
              </>
            ) : null}
            <dt>Subject</dt>
            <dd dir="auto">{draft.subject || "(no subject)"}</dd>
          </dl>
          {text ? (
            // A long email scrolls here; focusable so a keyboard can scroll it too.
            // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a scrolling region must be reachable by keyboard
            <div className="mail-review__text" dir="auto" tabIndex={0} role="region" aria-label="Email text">
              {text}
            </div>
          ) : null}
          {live && !live.can_send && notice?.text !== SEND_OFF_NOTICE ? (
            <p className="muted-text mail-review__note">{SEND_OFF_NOTICE}</p>
          ) : null}
          {actionError ? (
            <p className="alert alert-error" role="alert">
              {actionError}
            </p>
          ) : null}
        </>
      ) : loading ? (
        <p className="muted-text" role="status">
          Reading the draft from your mailbox…
        </p>
      ) : null}
      <div className="dialog-actions mail-review__actions">
        {live && !problem ? (
          <button
            type="button"
            className="btn"
            onClick={() => void send()}
            disabled={!live.can_send || !!busy || loading}
            title={sendTitle}
          >
            {busy === "send" ? "Sending…" : "Send"}
          </button>
        ) : null}
        {canDiscard && !problem ? (
          <button
            type="button"
            className="btn btn-ghost mail-review__discard"
            onClick={() => void discard()}
            disabled={!!busy || loading}
          >
            {busy === "discard" ? "Discarding…" : "Discard"}
          </button>
        ) : null}
        {owaUrl && canDiscard && !problem ? (
          <a className="btn btn-ghost" href={owaUrl} target="_blank" rel="noopener noreferrer">
            Open in Outlook
          </a>
        ) : null}
        {problem?.retry ? (
          <button type="button" className="btn btn-ghost" onClick={() => readAgain(null)} disabled={loading}>
            {loading ? "Trying…" : "Try again"}
          </button>
        ) : null}
        <button type="button" className="btn btn-ghost dialog-actions-cancel" onClick={close} disabled={!!busy}>
          Close
        </button>
      </div>
    </Modal>,
    document.body,
  );
}
