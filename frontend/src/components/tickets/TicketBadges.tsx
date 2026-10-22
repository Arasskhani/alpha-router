import { PRIORITY_LABELS, statusLabel, type Priority, type TicketStatus } from "../../lib/tickets";
import { initials } from "../../lib/ticketsAdmin";

/** Low · Normal · High · Urgent (Urgent with a dot). */
export function PriorityBadge({ priority }: { priority: Priority }) {
  return (
    <span className={`tickets-badge tickets-p-${priority}`}>
      {priority === "urgent" ? <i aria-hidden /> : null}
      {PRIORITY_LABELS[priority] ?? priority}
    </span>
  );
}

/** Open · In progress · Waiting for user · Resolved · Closed, in the staff wording. */
export function StatusBadge({ status }: { status: TicketStatus }) {
  return (
    <span className={`tickets-badge tickets-s-${status}`}>
      <i aria-hidden />
      {statusLabel(status, "staff")}
    </span>
  );
}

/** A round initials badge; staff are lilac, reporters teal. */
export function TicketAvatar({ name, staff, small }: { name: string; staff?: boolean; small?: boolean }) {
  return (
    <span
      className={`tickets-avatar${staff ? " tickets-avatar--staff" : ""}${small ? " tickets-avatar--xs" : ""}`}
      aria-hidden
    >
      {initials(name)}
    </span>
  );
}
