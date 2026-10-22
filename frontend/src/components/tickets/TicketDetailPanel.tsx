import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";

import AssignMenu, { useDismiss } from "./AssignMenu";
import { TicketAvatar } from "./TicketBadges";
import { useConfirm } from "../../context/ConfirmContext";
import {
  PRIORITIES,
  PRIORITY_LABELS,
  STATUSES,
  TICKETS_BASE,
  TicketsApiError,
  formatBytes,
  statusLabel,
  ticketNumber,
  ticketsRequest,
  type Assignee,
  type Priority,
  type StaffTicketDetail,
  type TicketMessage,
  type TicketStatus,
} from "../../lib/tickets";
import {
  firstName,
  imageLargestSide,
  imageProblem,
  imageTypesLabel,
  messageTime,
  type ImageLimits,
} from "../../lib/ticketsAdmin";
import { deleteOneTicket } from "./DeleteTicketsDialog";

type Props = {
  ticket: StaffTicketDetail;
  assignees: Assignee[];
  categories: string[];
  limits: ImageLimits;
  autoCloseDays: number;
  emailsAssignee: boolean;
  canWrite: boolean;
  isSuperAdmin: boolean;
  /** The server's new copy after any change. */
  onUpdated: (ticket: StaffTicketDetail) => void;
  onDeleted: () => void;
  onBack?: () => void;
};

type Pending = { id: number; file: File; url: string };

const IMAGE_MIME: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg,.jpg,.jpeg",
  webp: "image/webp",
  gif: "image/gif",
};

let pendingId = 0;

function errorText(err: unknown): string {
  if (err instanceof TicketsApiError) {
    if (err.code === "image_rejected" && typeof err.data.file === "string") return `${err.data.file}: ${err.message}`;
    if (err.status === 413) return "An image is larger than the limit. Choose a smaller one.";
  }
  return err instanceof Error ? err.message : String(err);
}

function contextLine(ticket: StaffTicketDetail) {
  const ctx = ticket.context;
  if (!ctx) return null;
  const parts = [ctx.app_version ? `App ${ctx.app_version}` : "", ctx.browser ?? ""].filter(Boolean);
  if (!parts.length && !ctx.page) return null;
  return (
    <span className="tickets-ctx__tech">
      {parts.join(" · ")}
      {ctx.page ? (
        <>
          {parts.length ? " · " : ""}
          <code dir="ltr">{ctx.page}</code>
        </>
      ) : null}
    </span>
  );
}

function Message({ message }: { message: TicketMessage }) {
  const when = messageTime(message.created_at);
  if (message.kind === "event") {
    return (
      <div className="tickets-event" role="note">
        <span dir="auto">
          {message.body}
          {when ? ` · ${when}` : ""}
        </span>
      </div>
    );
  }
  const staff = message.kind === "staff" || message.kind === "note";
  const auto = message.kind === "auto";
  const who = auto ? "Support team" : (message.author?.name ?? message.author_label);
  const images = message.attachments.filter((a) => a.url.startsWith("/api/"));
  return (
    <div
      className={`tickets-msg tickets-msg--${message.kind}`}
      data-kind={message.kind}
    >
      {auto ? (
        <span className="tickets-avatar tickets-avatar--auto" aria-hidden>
          ⚙
        </span>
      ) : (
        <TicketAvatar name={who} staff={staff} />
      )}
      <div className="tickets-msg__body">
        <div className="tickets-msg__who">
          <b>{who}</b>
          <span>{auto ? "Automatic reply" : message.author_label}</span>
          {when ? <span>· {when}</span> : null}
        </div>
        {message.kind === "note" ? <div className="tickets-note-tag">Internal note · not visible to the user</div> : null}
        <div className="tickets-msg__text" dir="auto">
          {message.body}
        </div>
        {images.length ? (
          <div className="tickets-msg__imgs">
            {images.map((a) => (
              <a key={a.id} href={a.url} target="_blank" rel="noreferrer" title={`${a.display_name} · ${formatBytes(a.bytes)}`}>
                <img src={a.url} alt={a.display_name} loading="lazy" />
              </a>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/**
 * One ticket beside the queue: who sent it and from where, its status,
 * priority, category and assignee, the thread with internal notes and system
 * lines, and the composer (a reply to the person or an internal note).
 */
export default function TicketDetailPanel({
  ticket,
  assignees,
  categories,
  limits,
  autoCloseDays,
  emailsAssignee,
  canWrite,
  isSuperAdmin,
  onUpdated,
  onDeleted,
  onBack,
}: Props) {
  const confirmer = useConfirm();
  const writable = canWrite && ticket.can_write;
  const [mode, setMode] = useState<"reply" | "note">("reply");
  const [body, setBody] = useState("");
  const [status, setStatus] = useState<"" | TicketStatus>("");
  const [pending, setPending] = useState<Pending[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [assignOpen, setAssignOpen] = useState(false);
  const assignRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const pendingRef = useRef<Pending[]>([]);
  const closeAssign = useCallback(() => setAssignOpen(false), []);
  useDismiss(assignRef, assignOpen, closeAssign);

  useEffect(() => {
    pendingRef.current = pending;
  }, [pending]);
  useEffect(() => () => pendingRef.current.forEach((p) => URL.revokeObjectURL(p.url)), []);

  const me = assignees.find((a) => a.is_me) ?? null;
  const reporterFirst = firstName(ticket.reporter.name);

  async function run<T>(request: () => Promise<T>): Promise<T | null> {
    setBusy(true);
    setError("");
    try {
      return await request();
    } catch (err) {
      setError(errorText(err));
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function patch(change: Partial<{ status: TicketStatus; priority: Priority; category: string }>) {
    const next = await run(() =>
      ticketsRequest<StaffTicketDetail>(`${TICKETS_BASE}/${ticket.id}`, { method: "PATCH", body: JSON.stringify(change) }),
    );
    if (next) onUpdated(next);
  }

  async function assign(person: Assignee | null) {
    setAssignOpen(false);
    const next = await run(() =>
      person?.is_me
        ? ticketsRequest<StaffTicketDetail>(`${TICKETS_BASE}/${ticket.id}/assign-to-me`, { method: "POST" })
        : ticketsRequest<StaffTicketDetail>(`${TICKETS_BASE}/${ticket.id}/assign`, {
            method: "POST",
            body: JSON.stringify({ assignee_id: person ? person.id : null }),
          }),
    );
    if (next) onUpdated(next);
  }

  async function addFiles(e: ChangeEvent<HTMLInputElement>) {
    const files = [...(e.target.files ?? [])];
    e.target.value = "";
    const problems: string[] = [];
    const accepted: Pending[] = [];
    for (const file of files) {
      if (pending.length + accepted.length >= limits.max_images) {
        problems.push(`${file.name}: at most ${limits.max_images} images per message`);
        continue;
      }
      const problem = imageProblem(file, limits);
      if (problem) {
        problems.push(`${file.name}: ${problem}`);
        continue;
      }
      const side = await imageLargestSide(file);
      if (side != null && side > limits.max_side_px) {
        problems.push(`${file.name}: larger than ${limits.max_side_px} px on its longest side`);
        continue;
      }
      pendingId += 1;
      accepted.push({ id: pendingId, file, url: URL.createObjectURL(file) });
    }
    if (accepted.length) setPending((list) => [...list, ...accepted]);
    setError(problems.join(" · "));
  }

  function removePending(id: number) {
    setPending((list) => {
      const gone = list.find((p) => p.id === id);
      if (gone) URL.revokeObjectURL(gone.url);
      return list.filter((p) => p.id !== id);
    });
  }

  async function send() {
    const text = body.trim();
    if (!text) {
      setError(mode === "note" ? "Write the note first." : "Write the reply first.");
      return;
    }
    const form = new FormData();
    form.append("body", text);
    form.append("internal", mode === "note" ? "true" : "false");
    if (mode === "reply" && status) form.append("status", status);
    for (const p of pending) form.append("images", p.file, p.file.name);
    const next = await run(() =>
      ticketsRequest<StaffTicketDetail>(`${TICKETS_BASE}/${ticket.id}/messages`, { method: "POST", body: form }),
    );
    if (!next) return;
    pending.forEach((p) => URL.revokeObjectURL(p.url));
    setPending([]);
    setBody("");
    setStatus("");
    onUpdated(next);
  }

  async function remove() {
    try {
      if (await deleteOneTicket(confirmer, ticket)) onDeleted();
    } catch (err) {
      setError(errorText(err));
    }
  }

  const categoryOptions = categories.includes(ticket.category) ? categories : [...categories, ticket.category];
  const assignedToMe = Boolean(ticket.assignee && me && ticket.assignee.id === me.id);
  const accept = limits.image_types.map((t) => IMAGE_MIME[t] ?? "").filter(Boolean).join(",");

  return (
    <section className="tickets-panel tickets-detail" aria-label={`Ticket ${ticketNumber(ticket.number)}`}>
      {onBack ? (
        <button type="button" className="btn btn-ghost tickets-back" onClick={onBack}>
          ← All tickets
        </button>
      ) : null}
      <header className="tickets-detail__head">
        <h2>
          <span className="tickets-num">{ticketNumber(ticket.number)}</span>{" "}
          <span dir="auto">{ticket.title}</span>
        </h2>
        {isSuperAdmin && ticket.can_delete ? (
          <button type="button" className="btn btn-ghost btn-sm tickets-danger-ghost" onClick={() => void remove()}>
            Delete…
          </button>
        ) : null}
      </header>
      <div className="tickets-ctx">
        <TicketAvatar name={ticket.reporter.name} />
        <span>
          <b>{ticket.reporter.name}</b> · {ticket.reporter.username}
          {ticket.reporter.department ? ` · ${ticket.reporter.department}` : ""}
          {ticket.reporter.email ? (
            <span className="tickets-ctx__email" dir="ltr">
              {" "}
              · {ticket.reporter.email}
            </span>
          ) : null}
        </span>
        {contextLine(ticket)}
      </div>

      <div className="tickets-panel__controls">
        <label>
          Status
          <select
            className="input-block"
            value={ticket.status}
            disabled={!writable || busy}
            onChange={(e) => void patch({ status: e.target.value as TicketStatus })}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {statusLabel(s, "staff")}
              </option>
            ))}
          </select>
        </label>
        <label>
          Priority
          <select
            className="input-block"
            value={ticket.priority}
            disabled={!writable || busy}
            onChange={(e) => void patch({ priority: e.target.value as Priority })}
          >
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {PRIORITY_LABELS[p]}
              </option>
            ))}
          </select>
        </label>
        <label>
          Category
          <select
            className="input-block"
            value={ticket.category}
            disabled={!writable || busy}
            onChange={(e) => void patch({ category: e.target.value })}
          >
            {categoryOptions.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <div className="tickets-assignee" ref={assignRef}>
          <div className="tickets-assignee__label">
            <span id={`tickets-assignee-${ticket.id}`}>Assignee</span>
            {writable && me && !assignedToMe ? (
              <button type="button" className="tickets-linkbtn" disabled={busy} onClick={() => void assign(me)}>
                Assign to me
              </button>
            ) : null}
          </div>
          <button
            type="button"
            className={`input-block tickets-assignee__btn${assignOpen ? " is-open" : ""}`}
            aria-labelledby={`tickets-assignee-${ticket.id}`}
            aria-haspopup="dialog"
            aria-expanded={assignOpen}
            disabled={!writable || busy}
            onClick={() => setAssignOpen((v) => !v)}
          >
            {ticket.assignee ? (
              <>
                <TicketAvatar name={ticket.assignee.name} staff small />
                <span className="tickets-assignee__name">{ticket.assignee.name}</span>
                {assignedToMe ? <span className="muted-text">(you)</span> : null}
              </>
            ) : (
              <span className="muted-text">Unassigned</span>
            )}
            <span className="tickets-caret" aria-hidden>
              ▾
            </span>
          </button>
          {assignOpen ? (
            <AssignMenu
              assignees={assignees}
              currentId={ticket.assignee?.id ?? null}
              emailsAssignee={emailsAssignee}
              canUnassign={Boolean(ticket.assignee)}
              onPick={(person) => void assign(person)}
            />
          ) : null}
        </div>
      </div>

      <div className="tickets-thread">
        {ticket.messages.map((m) => (
          <Message key={m.id} message={m} />
        ))}
      </div>

      {error ? (
        <p className="alert alert-error tickets-detail__error" role="alert">
          {error}
        </p>
      ) : null}

      {writable ? (
        <div className={`tickets-composer${mode === "note" ? " tickets-composer--note" : ""}`}>
          <textarea
            dir="auto"
            aria-label={mode === "note" ? "Internal note" : `Reply to ${reporterFirst}`}
            placeholder={mode === "note" ? "Internal note — only administrators see it" : `Reply to ${reporterFirst}…`}
            value={body}
            maxLength={5000}
            onChange={(e) => setBody(e.target.value)}
          />
          {pending.length ? (
            <div className="tickets-composer__thumbs">
              {pending.map((p) => (
                <div key={p.id} className="tickets-thumb">
                  <img src={p.url} alt="" />
                  <span title={p.file.name}>{formatBytes(p.file.size)}</span>
                  <button type="button" aria-label={`Remove ${p.file.name}`} onClick={() => removePending(p.id)}>
                    ✕
                  </button>
                </div>
              ))}
            </div>
          ) : null}
          <div className="tickets-composer__bar">
            <div className="tickets-composer__left">
              <span className="tickets-mode" role="group" aria-label="Send as">
                <button
                  type="button"
                  className={mode === "reply" ? "is-on" : undefined}
                  aria-pressed={mode === "reply"}
                  onClick={() => setMode("reply")}
                >
                  Reply to user
                </button>
                <button
                  type="button"
                  className={mode === "note" ? "is-on-note" : undefined}
                  aria-pressed={mode === "note"}
                  onClick={() => setMode("note")}
                >
                  Internal note
                </button>
              </span>
              <button
                type="button"
                className="btn btn-ghost btn-sm tickets-attach"
                aria-label="Add images"
                title={`${imageTypesLabel(limits.image_types)} · up to ${limits.max_image_mb} MB · ${limits.max_images} per message`}
                disabled={pending.length >= limits.max_images}
                onClick={() => fileRef.current?.click()}
              >
                📎
              </button>
              <input ref={fileRef} type="file" className="tickets-file-input" hidden multiple accept={accept} onChange={(e) => void addFiles(e)} />
              {mode === "reply" ? (
                <select
                  className="input-block tickets-composer__status"
                  aria-label="Status after the reply"
                  value={status}
                  onChange={(e) => setStatus(e.target.value as "" | TicketStatus)}
                >
                  <option value="">Status: automatic</option>
                  <option value="waiting">Then: Waiting for user</option>
                  <option value="in_progress">Then: In progress</option>
                  <option value="resolved">Then: Resolved</option>
                  <option value="closed">Then: Closed</option>
                </select>
              ) : null}
            </div>
            <button type="button" className="btn" disabled={busy || !body.trim()} onClick={() => void send()}>
              {busy ? "Sending…" : mode === "note" ? "Add note" : "Send reply"}
            </button>
          </div>
        </div>
      ) : null}
      <p className="tickets-hint tickets-detail__foot">
        {writable
          ? `Internal notes are never shown or emailed to the user. A reply moves an Open ticket to In progress; a ticket waiting for the user closes after ${autoCloseDays} days without an answer.`
          : "You can read this ticket. Replies and changes need the Support role or Super Admin."}
      </p>
    </section>
  );
}
