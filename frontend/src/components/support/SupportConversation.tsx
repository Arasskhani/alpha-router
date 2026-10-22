import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import AdminPage from "../AdminPage";
import Modal from "../Modal";
import { useReadOnly } from "../../context/ReadOnlyContext";
import { formatLocalDateTime } from "../../lib/dateTime";
import {
  SUPPORT_BASE,
  TicketsApiError,
  announceTicketsChanged,
  ticketNumber,
  ticketsRequest,
  type Attachment,
  type SupportStatus,
  type TicketMessage,
  type UserTicketDetail,
} from "../../lib/tickets";
import { BODY_MAX, acceptAttribute } from "./NewTicketModal";
import { Avatar, CategoryTag, ImageThumbs, PriorityBadge, StatusBadge } from "./SupportBits";
import {
  dayLabel,
  daysUntil,
  imageTypesLabel,
  isTicketsDisabled,
  messageTime,
  openedTime,
  plural,
  supportErrorText,
} from "./supportFormat";
import { useImagePicks } from "./useImagePicks";

type Props = {
  ticketId: number;
  status: SupportStatus;
  onDisabled: () => void;
};

/** Only the API's own attachment address is shown; anything else falls back to it. */
function attachmentSrc(a: Attachment): string {
  return a.url && a.url.startsWith(`${SUPPORT_BASE}/attachments/`) ? a.url : `${SUPPORT_BASE}/attachments/${a.id}`;
}

function Message({ message, onOpenImage }: { message: TicketMessage; onOpenImage: (a: Attachment) => void }) {
  const when = messageTime(message.created_at);
  const fullWhen = formatLocalDateTime(message.created_at);
  if (message.kind === "event") {
    return (
      <li className="support-event">
        <span>
          <span dir="auto">{message.body}</span>
          <span title={fullWhen}> · {when}</span>
        </span>
      </li>
    );
  }
  const tone = message.kind === "auto" ? "auto" : message.kind === "user" ? "user" : "staff";
  const name =
    message.kind === "auto"
      ? message.author?.name || "Support team"
      : message.author?.name || message.author_label || (message.kind === "user" ? "You" : "Support");
  const label = message.author_label && message.author_label !== name ? message.author_label : "";
  return (
    <li className={`support-msg support-msg--${tone}`}>
      <Avatar name={name} tone={tone} />
      <div className="support-msg__body">
        <div className="support-msg__who">
          <b>{name}</b>
          {label ? <span>{label}</span> : null}
          <span title={fullWhen}>· {when}</span>
        </div>
        <div className="support-msg__text" dir="auto">
          {message.body}
        </div>
        {message.attachments.length > 0 ? (
          <div className="support-msg__imgs">
            {message.attachments.map((a) => (
              <button
                key={a.id}
                type="button"
                className="support-msg__img"
                onClick={() => onOpenImage(a)}
                aria-label={`Open ${a.display_name || "image"} full size`}
              >
                <img src={attachmentSrc(a)} alt={a.display_name || ""} loading="lazy" />
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </li>
  );
}

/** Why there is no composer, or what a reply will do now. */
function ReplyNotice({ ticket, readOnly }: { ticket: UserTicketDetail; readOnly: boolean }) {
  if (readOnly) {
    return (
      <p className="support-notice" role="status">
        Your account is inactive: you can read this ticket, but not reply to it.
      </p>
    );
  }
  const done = ticket.status === "resolved" || ticket.status === "closed";
  if (!ticket.can_reply) {
    return (
      <p className="support-notice" role="status">
        {done ? "This ticket is closed and can no longer be reopened. " : "Replies are closed on this ticket. "}
        <Link to="/app/support?new=1">Open a new ticket</Link> if you still need help.
      </p>
    );
  }
  if (done) {
    const until = ticket.reopen_until ? dayLabel(ticket.reopen_until) : "";
    return (
      <p className="support-notice support-notice--info" role="status">
        {ticket.status === "resolved" ? "This ticket is resolved." : "This ticket is closed."}{" "}
        {until ? `If the problem comes back, reply before ${until} to reopen it.` : "A reply reopens it."}
      </p>
    );
  }
  return null;
}

/** /app/support/:id: the ticket's thread, the auto-close notice and the reply box. */
export default function SupportConversation({ ticketId, status, onDisabled }: Props) {
  const readOnly = useReadOnly();
  const ids = useId();
  const { limits } = status;
  const [ticket, setTicket] = useState<UserTicketDetail | null>(null);
  const [loadError, setLoadError] = useState<{ text: string; notFound: boolean } | null>(null);
  const [tick, setTick] = useState(0);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState<"" | "reply" | "resolve">("");
  const [actionError, setActionError] = useState("");
  const [viewer, setViewer] = useState<Attachment | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const images = useImagePicks(limits);

  useEffect(() => {
    let cancelled = false;
    ticketsRequest<UserTicketDetail>(`${SUPPORT_BASE}/tickets/${ticketId}`)
      .then((detail) => {
        if (cancelled) return;
        setTicket(detail);
        setLoadError(null);
        // Opening it clears its "New reply": the menu count follows.
        announceTicketsChanged();
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (isTicketsDisabled(err)) {
          onDisabled();
          return;
        }
        const notFound = err instanceof TicketsApiError && err.status === 404;
        setLoadError({ text: notFound ? "This ticket was not found." : supportErrorText(err), notFound });
      });
    return () => {
      cancelled = true;
    };
  }, [ticketId, tick, onDisabled]);

  const failed = (err: unknown) => {
    if (isTicketsDisabled(err)) {
      onDisabled();
      return;
    }
    if (err instanceof TicketsApiError &&
      (err.code === "image_rejected" || err.code === "image_too_large") &&
      typeof err.data.file === "string") {
      images.refuse(err.data.file, "refused");
    }
    // The ticket moved on meanwhile (the reopen window passed): show it as it is now.
    if (err instanceof TicketsApiError && err.code === "reopen_window_passed") setTick((n) => n + 1);
    setActionError(supportErrorText(err, limits));
  };

  const sendReply = async (event: FormEvent) => {
    event.preventDefault();
    if (!body.trim() || busy) return;
    setBusy("reply");
    setActionError("");
    const form = new FormData();
    form.append("body", body.trim());
    for (const pick of images.picks) form.append("images", pick.file, pick.file.name);
    try {
      const detail = await ticketsRequest<UserTicketDetail>(`${SUPPORT_BASE}/tickets/${ticketId}/messages`, {
        method: "POST",
        body: form,
      });
      setTicket(detail);
      setBody("");
      images.clear();
      announceTicketsChanged();
    } catch (err) {
      failed(err);
    } finally {
      setBusy("");
    }
  };

  const resolve = async () => {
    if (busy) return;
    setBusy("resolve");
    setActionError("");
    try {
      const detail = await ticketsRequest<UserTicketDetail>(`${SUPPORT_BASE}/tickets/${ticketId}/resolve`, {
        method: "POST",
      });
      setTicket(detail);
      announceTicketsChanged();
    } catch (err) {
      failed(err);
    } finally {
      setBusy("");
    }
  };

  const back = (
    <Link to="/app/support" className="btn btn-ghost btn-readonly-ok support-back">
      ← My tickets
    </Link>
  );

  if (loadError && !ticket) {
    return (
      <AdminPage title="Support" actions={back}>
        <div className={loadError.notFound ? "support-empty" : "alert alert-error support-alert"} role="alert">
          <span>{loadError.text}</span>
          {loadError.notFound ? null : (
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setTick((n) => n + 1)}>
              Try again
            </button>
          )}
        </div>
      </AdminPage>
    );
  }

  if (!ticket) {
    return (
      <AdminPage title="Support" actions={back}>
        <p className="muted-text">Loading…</p>
      </AdminPage>
    );
  }

  const closesIn = ticket.status === "waiting" ? daysUntil(ticket.auto_close_at) : null;
  const canCompose = ticket.can_reply && !readOnly;
  const placeholder =
    ticket.status === "waiting"
      ? "Write a reply… (a reply sets the ticket back to Open)"
      : ticket.status === "resolved" || ticket.status === "closed"
        ? "Write a reply… (a reply reopens the ticket)"
        : "Write a reply…";
  const messages = ticket.messages.filter((m) => !m.internal && m.kind !== "note");

  return (
    <AdminPage title="Support" actions={back}>
      <div className="support-head">
        <h2>
          <span className="support-num">{ticketNumber(ticket.number)}</span>{" "}
          <span dir="auto">{ticket.title}</span>
        </h2>
        <StatusBadge status={ticket.status} />
        <PriorityBadge priority={ticket.priority} />
        <CategoryTag category={ticket.category} />
        <span className="support-head__when" title={formatLocalDateTime(ticket.created_at)}>
          Opened {openedTime(ticket.created_at)}
        </span>
      </div>

      <ol className="support-thread" aria-label="Conversation">
        {messages.map((m) => (
          <Message key={m.id} message={m} onOpenImage={setViewer} />
        ))}
      </ol>

      {closesIn != null && ticket.auto_close_at ? (
        <p className="support-autoclose" role="status">
          <span aria-hidden="true">⏳</span> This ticket closes automatically on{" "}
          <b>{dayLabel(ticket.auto_close_at)}</b> ({closesIn === 0 ? "today" : plural(closesIn, "day")}) if there is no
          reply. You can reopen it for {plural(status.reopen_days, "day")} after that.
        </p>
      ) : null}

      <ReplyNotice ticket={ticket} readOnly={readOnly} />

      {actionError ? (
        <p className="alert alert-error support-alert" role="alert">
          {actionError}
        </p>
      ) : null}

      {canCompose ? (
        <form className="support-composer" onSubmit={(e) => void sendReply(e)}>
          <label htmlFor={`${ids}-reply`} className="sr-only">
            Reply
          </label>
          <textarea
            id={`${ids}-reply`}
            value={body}
            maxLength={BODY_MAX}
            dir="auto"
            placeholder={placeholder}
            onChange={(e) => setBody(e.target.value)}
            onPaste={(e) => {
              const files = Array.from(e.clipboardData?.files ?? []);
              if (files.length > 0) {
                e.preventDefault();
                images.add(files);
              }
            }}
          />
          {images.picks.length > 0 || images.refused.length > 0 ? (
            <div className="support-composer__images">
              <ImageThumbs
                picks={images.picks}
                refused={images.refused}
                onRemove={images.remove}
                onDismiss={images.dismiss}
              />
            </div>
          ) : null}
          <div className="support-composer__bar">
            <div className="support-composer__left">
              <button type="button" className="btn btn-ghost" onClick={() => fileRef.current?.click()}>
                <span aria-hidden="true">📎</span> Add image
              </button>
              <span>
                {imageTypesLabel(limits.image_types)} · {limits.max_image_mb} MB
              </span>
              <input
                ref={fileRef}
                type="file"
                className="sr-only"
                tabIndex={-1}
                aria-hidden="true"
                accept={acceptAttribute(limits.image_types)}
                multiple
                data-testid="support-reply-files"
                onChange={(e) => {
                  images.add(e.target.files);
                  e.target.value = "";
                }}
              />
            </div>
            <div className="support-composer__right">
              {ticket.can_resolve ? (
                <button type="button" className="btn btn-ghost" disabled={busy !== ""} onClick={() => void resolve()}>
                  {busy === "resolve" ? "Saving…" : "It works — mark resolved"}
                </button>
              ) : null}
              <button type="submit" className="btn" disabled={!body.trim() || busy !== ""}>
                {busy === "reply" ? "Sending…" : "Send reply"}
              </button>
            </div>
          </div>
        </form>
      ) : null}

      {viewer ? (
        <Modal
          open
          title={viewer.display_name || "Image"}
          onClose={() => setViewer(null)}
          panelClassName="support-viewer"
        >
          <img className="support-viewer__img" src={attachmentSrc(viewer)} alt={viewer.display_name || ""} />
          <p className="support-viewer__links">
            <a href={attachmentSrc(viewer)} target="_blank" rel="noopener noreferrer">
              Open in a new tab
            </a>
          </p>
        </Modal>
      ) : null}
    </AdminPage>
  );
}
