import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import AdminPage from "../AdminPage";
import { useReadOnly } from "../../context/ReadOnlyContext";
import { formatLocalDateTime } from "../../lib/dateTime";
import {
  ACTIVE_STATUSES,
  SUPPORT_BASE,
  announceTicketsChanged,
  ticketNumber,
  ticketsRequest,
  type SupportStatus,
  type UserState,
  type UserTicketList,
  type UserTicketSummary,
} from "../../lib/tickets";
import NewTicketModal from "./NewTicketModal";
import { CategoryTag, PriorityBadge, StatusBadge } from "./SupportBits";
import { agoText, daysUntil, isTicketsDisabled, plural, supportErrorText } from "./supportFormat";

const FILTERS: { key: UserState; label: string }[] = [
  { key: "open", label: "Open" },
  { key: "resolved", label: "Resolved" },
  { key: "all", label: "All" },
];

const SEARCH_DELAY_MS = 250;

type Props = {
  status: SupportStatus;
  onDisabled: () => void;
  onStatusStale: () => void;
};

function metaLine(ticket: UserTicketSummary): string {
  if (ACTIVE_STATUSES.includes(ticket.status)) {
    const parts = [`Updated ${agoText(ticket.updated_at)}`, plural(ticket.message_count, "message")];
    if (ticket.image_count > 0) parts.push(plural(ticket.image_count, "image"));
    return parts.join(" · ");
  }
  const verb = ticket.status === "resolved" ? "Resolved" : "Closed";
  const left = daysUntil(ticket.reopen_until);
  const reopen = left && left > 0 ? `can be reopened for ${plural(left, "day")}` : "can no longer be reopened";
  return `${verb} ${agoText(ticket.updated_at)} · ${reopen}`;
}

function TicketRow({ ticket }: { ticket: UserTicketSummary }) {
  return (
    <li>
      <Link
        to={`/app/support/${ticket.id}`}
        className={`support-item${ticket.user_unread ? " support-item--unread" : ""}`}
      >
        <span className="support-item__title">
          <span className="support-num">{ticketNumber(ticket.number)}</span>
          <span className="support-item__text" dir="auto">
            {ticket.title}
          </span>
          {ticket.user_unread ? <span className="support-new">New reply</span> : null}
        </span>
        <span className="support-item__side">
          <PriorityBadge priority={ticket.priority} />
          <StatusBadge status={ticket.status} />
        </span>
        <span className="support-item__meta" title={`Updated ${formatLocalDateTime(ticket.updated_at)}`}>
          <CategoryTag category={ticket.category} />
          <span>{metaLine(ticket)}</span>
        </span>
      </Link>
    </li>
  );
}

/** /app/support: the person's tickets, Open · Resolved · All, a search, and + New ticket. */
export default function SupportList({ status, onDisabled, onStatusStale }: Props) {
  const readOnly = useReadOnly();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState<UserState>("open");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [data, setData] = useState<UserTicketList | null>(null);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  // "Open a new ticket" from a conversation that can no longer be reopened lands here with ?new=1.
  const modalOpen = params.get("new") === "1" && !readOnly;

  const setModalOpen = (open: boolean) => {
    const next = new URLSearchParams(params);
    if (open) next.set("new", "1");
    else next.delete("new");
    setParams(next, { replace: true });
  };

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(query.trim()), SEARCH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    let cancelled = false;
    const qs = new URLSearchParams({ state: filter });
    if (search) qs.set("q", search);
    ticketsRequest<UserTicketList>(`${SUPPORT_BASE}/tickets?${qs.toString()}`)
      .then((list) => {
        if (cancelled) return;
        setData(list);
        setError("");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (isTicketsDisabled(err)) onDisabled();
        else setError(supportErrorText(err));
      });
    return () => {
      cancelled = true;
    };
  }, [filter, search, tick, onDisabled]);

  const counts = data?.counts;
  const items = data?.items ?? [];

  return (
    <AdminPage
      title="Support"
      actions={
        readOnly ? null : (
          <button type="button" className="btn" onClick={() => setModalOpen(true)}>
            + New ticket
          </button>
        )
      }
    >
      <p className="support-intro">
        Report a problem or a bug to your administrators. Their answers show here, and Support shows a count when one
        arrives.
      </p>
      <div className="support-toolbar">
        <div className="support-seg" role="group" aria-label="Show">
          {FILTERS.map((f) => {
            const n = f.key === "all" ? null : counts?.[f.key];
            return (
              <button
                key={f.key}
                type="button"
                className={`support-seg__btn${filter === f.key ? " is-on" : ""}`}
                aria-pressed={filter === f.key}
                onClick={() => setFilter(f.key)}
              >
                {f.label}
                {n != null ? ` · ${n}` : ""}
              </button>
            );
          })}
        </div>
        <input
          type="search"
          className="input-block support-search"
          placeholder="Search my tickets"
          aria-label="Search my tickets"
          value={query}
          dir="auto"
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {error ? (
        <div className="alert alert-error support-alert" role="alert">
          <span>{error}</span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setTick((n) => n + 1)}>
            Try again
          </button>
        </div>
      ) : null}

      {!data && !error ? <p className="muted-text">Loading…</p> : null}

      {data && items.length === 0 ? (
        <div className="support-empty">
          {search ? (
            <p>No tickets match “{search}”.</p>
          ) : filter === "open" ? (
            <p>
              No open tickets.{" "}
              {readOnly ? null : "If something does not work as it should, use New ticket to tell your administrators."}
            </p>
          ) : filter === "resolved" ? (
            <p>No resolved or closed tickets yet.</p>
          ) : (
            <p>You have not opened a ticket yet.</p>
          )}
        </div>
      ) : null}

      {items.length > 0 ? (
        <ul className="support-list" aria-label="My tickets">
          {items.map((t) => (
            <TicketRow key={t.id} ticket={t} />
          ))}
        </ul>
      ) : null}

      {modalOpen ? (
        <NewTicketModal
          status={status}
          onClose={() => setModalOpen(false)}
          onDisabled={onDisabled}
          onStale={onStatusStale}
          onCreated={(ticket) => {
            announceTicketsChanged();
            navigate(`/app/support/${ticket.id}`, { replace: false });
          }}
        />
      ) : null}
    </AdminPage>
  );
}
