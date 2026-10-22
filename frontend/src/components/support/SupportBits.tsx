import { PRIORITY_LABELS, formatBytes, statusLabel, type Priority, type TicketStatus } from "../../lib/tickets";
import type { ImagePick, RefusedPick } from "./useImagePicks";
import { initials } from "./supportFormat";

const STATUS_TONE: Record<TicketStatus, string> = {
  open: "open",
  in_progress: "progress",
  waiting: "waiting",
  resolved: "resolved",
  closed: "closed",
};

export function PriorityBadge({ priority }: { priority: Priority }) {
  return (
    <span className={`support-badge support-badge--p-${priority}`}>
      {priority === "urgent" ? <i aria-hidden="true" /> : null}
      {PRIORITY_LABELS[priority] ?? priority}
    </span>
  );
}

export function StatusBadge({ status }: { status: TicketStatus }) {
  return (
    <span className={`support-badge support-badge--status support-badge--s-${STATUS_TONE[status] ?? "closed"}`}>
      <i aria-hidden="true" />
      {statusLabel(status, "user")}
    </span>
  );
}

export function CategoryTag({ category }: { category: string }) {
  return <span className="support-cat">{category}</span>;
}

export function Avatar({ name, tone = "user" }: { name: string; tone?: "user" | "staff" | "auto" }) {
  return (
    <span className={`support-avatar support-avatar--${tone}`} aria-hidden="true">
      {tone === "auto" ? "⚙" : initials(name)}
    </span>
  );
}

/** The kept images (preview, name, size, remove) and the refused ones (name, reason). */
export function ImageThumbs({
  picks,
  refused,
  onRemove,
  onDismiss,
}: {
  picks: ImagePick[];
  refused: RefusedPick[];
  onRemove: (key: string) => void;
  onDismiss: (key: string) => void;
}) {
  if (picks.length === 0 && refused.length === 0) return null;
  return (
    <ul className="support-thumbs" aria-label="Images">
      {picks.map((pick) => (
        <li key={pick.key} className="support-thumb">
          {pick.url ? <img src={pick.url} alt="" /> : <span className="support-thumb__blank" aria-hidden="true" />}
          <span className="support-thumb__meta">
            <span className="support-thumb__name" title={pick.file.name}>
              {pick.file.name}
            </span>
            <span>{formatBytes(pick.file.size)}</span>
          </span>
          <button
            type="button"
            className="support-thumb__remove"
            aria-label={`Remove ${pick.file.name}`}
            onClick={() => onRemove(pick.key)}
          >
            ×
          </button>
        </li>
      ))}
      {refused.map((bad) => (
        <li key={bad.key} className="support-thumb support-thumb--refused">
          <span className="support-thumb__blank" aria-hidden="true">
            ⛔
          </span>
          <span className="support-thumb__meta">
            <span className="support-thumb__name" title={bad.name}>
              {bad.name}
            </span>
            <span>{bad.reason}</span>
          </span>
          <button
            type="button"
            className="support-thumb__remove"
            aria-label={`Dismiss ${bad.name}`}
            onClick={() => onDismiss(bad.key)}
          >
            ×
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Support switched off in Tickets › Settings: a calm page, not an error. */
export function SupportOff() {
  return (
    <div className="support-off" role="status">
      <span className="support-off__icon" aria-hidden="true">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
          <path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4l2 2h9A1.5 1.5 0 0 1 21 9.5v8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z" />
          <path d="M9.5 13.5h5" strokeLinecap="round" />
        </svg>
      </span>
      <h2>Support is turned off by your administrator</h2>
      <p className="muted-text">
        You cannot open or read tickets for now. If something is not working, contact your administrator another way.
      </p>
    </div>
  );
}
