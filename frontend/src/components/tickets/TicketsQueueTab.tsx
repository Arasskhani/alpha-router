import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { useSearchParams } from "react-router-dom";

import AssignMenu, { useDismiss } from "./AssignMenu";
import DeleteTicketsDialog, { type DeleteTarget } from "./DeleteTicketsDialog";
import { PriorityBadge, StatusBadge } from "./TicketBadges";
import TicketDetailPanel from "./TicketDetailPanel";
import { useConfirm } from "../../context/ConfirmContext";
import { useDebounced } from "../../hooks/useDebounced";
import { useMediaQuery } from "../../hooks/useMediaQuery";
import {
  PRIORITIES,
  PRIORITY_LABELS,
  STAFF_VIEW_LABELS,
  TICKETS_BASE,
  announceTicketsChanged,
  statusLabel,
  ticketsRequest,
  type Assignee,
  type StaffCounts,
  type StaffMeta,
  type StaffTicketDetail,
  type StaffTicketList,
  type StaffTicketSummary,
  type StaffView,
  type TicketSettings,
  type TicketStatus,
} from "../../lib/tickets";
import {
  deleteFilterFromQueue,
  downloadCsv,
  queueQuery,
  readQueueFilters,
  relativeTime,
  type ImageLimits,
} from "../../lib/ticketsAdmin";

type Props = {
  meta: StaffMeta | null;
  settings: TicketSettings | null;
  canWrite: boolean;
  isSuperAdmin: boolean;
};

const QUICK_VIEWS: StaffView[] = ["needs_staff", "mine", "unassigned", "active", "closed"];
const PAGE_SIZE = 50;
const PHONE = "(max-width: 900px)";
const DEFAULT_LIMITS: ImageLimits = { image_types: ["png", "jpg", "webp", "gif"], max_image_mb: 5, max_images: 5, max_side_px: 4096 };

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** "Majid A." for the row; the panel shows the whole name. */
function shortName(name: string): string {
  const parts = name.trim().split(/\s+/);
  return parts.length > 1 ? `${parts[0]} ${parts[parts.length - 1][0]}.` : name;
}

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`;
}

/**
 * The queue staff work: quick views with their counts, search and filters,
 * the list with "Assign to me" on unassigned rows, bulk actions, and the
 * ticket beside it (`?ticket=<id>`), full width on a phone.
 */
export default function TicketsQueueTab({ meta, settings, canWrite, isSuperAdmin }: Props) {
  const confirmer = useConfirm();
  const [params, setParams] = useSearchParams();
  const filters = readQueueFilters(params);
  const page = Math.max(1, Number(params.get("page")) || 1);
  const ticketId = Number(params.get("ticket")) || null;
  const isPhone = useMediaQuery(PHONE);

  const [qDraft, setQDraft] = useState(filters.q);
  const debouncedQ = useDebounced(qDraft, 300);
  const [version, setVersion] = useState(0);
  const [list, setList] = useState<{ key: string; data: StaffTicketList } | null>(null);
  const [counts, setCounts] = useState<StaffCounts | null>(null);
  const [assignees, setAssignees] = useState<Assignee[]>(meta?.assignees ?? []);
  const [detail, setDetail] = useState<StaffTicketDetail | null>(null);
  const [detailError, setDetailError] = useState("");
  const [selection, setSelection] = useState<{ key: string; ids: Set<number> }>({ key: "", ids: new Set() });
  const [bulkAssignOpen, setBulkAssignOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const bulkRef = useRef<HTMLDivElement>(null);
  const closeBulk = useCallback(() => setBulkAssignOpen(false), [setBulkAssignOpen]);
  useDismiss(bulkRef, bulkAssignOpen, closeBulk);

  const listKey = queueQuery(filters, { page, page_size: PAGE_SIZE });
  const selected = selection.key === listKey ? selection.ids : new Set<number>();

  const patch = useCallback(
    (next: Record<string, string>, keepPage = false) => {
      setParams(
        (current) => {
          const out = new URLSearchParams(current);
          for (const [key, value] of Object.entries(next)) {
            if (value) out.set(key, value);
            else out.delete(key);
          }
          if (!keepPage) out.delete("page");
          return out;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  // The search box writes to the address a moment after typing stops.
  useEffect(() => {
    if (debouncedQ.trim() !== filters.q) patch({ q: debouncedQ.trim() });
  }, [debouncedQ, filters.q, patch]);

  useEffect(() => {
    let cancelled = false;
    ticketsRequest<StaffTicketList>(`${TICKETS_BASE}?${listKey}`)
      .then((data) => {
        if (cancelled) return;
        setList({ key: listKey, data });
        setError("");
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errorText(err));
      });
    return () => {
      cancelled = true;
    };
  }, [listKey, version]);

  useEffect(() => {
    let cancelled = false;
    ticketsRequest<StaffCounts>(`${TICKETS_BASE}/counts`)
      .then((next) => !cancelled && setCounts(next))
      .catch(() => undefined);
    ticketsRequest<Assignee[]>(`${TICKETS_BASE}/assignees`)
      .then((next) => !cancelled && setAssignees(next))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [version]);

  useEffect(() => {
    if (!ticketId) return;
    let cancelled = false;
    ticketsRequest<StaffTicketDetail>(`${TICKETS_BASE}/${ticketId}`)
      .then((next) => {
        if (cancelled) return;
        setDetail(next);
        setDetailError("");
      })
      .catch((err: unknown) => {
        if (!cancelled) setDetailError(errorText(err));
      });
    return () => {
      cancelled = true;
    };
  }, [ticketId]);

  /** Something changed: the list, the counts, the badges and the people's open counts follow. */
  const changed = useCallback(() => {
    announceTicketsChanged();
    setVersion((v) => v + 1);
  }, [setVersion]);

  function setSelected(ids: Set<number>) {
    setSelection({ key: listKey, ids });
  }

  function toggle(id: number) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  }

  async function assignToMe(e: MouseEvent, row: StaffTicketSummary) {
    e.stopPropagation();
    try {
      const next = await ticketsRequest<StaffTicketDetail>(`${TICKETS_BASE}/${row.id}/assign-to-me`, { method: "POST" });
      if (detail?.id === row.id) setDetail(next);
      setNotice(`#${row.number} is yours now.`);
      changed();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function bulk(action: "assign_to_me" | "assign" | "close", person?: Assignee) {
    setBulkAssignOpen(false);
    const ids = [...selected];
    if (!ids.length) return;
    if (action === "close") {
      const ok = await confirmer.confirm({
        title: `Close ${plural(ids.length, "ticket", "tickets")}?`,
        message: `The people who sent them see them as Closed. They can still reopen them by replying within ${settings?.reopen_days ?? meta?.settings.reopen_days ?? 14} days.`,
        confirmLabel: "Close",
      });
      if (ok !== true) return;
    }
    try {
      const body: Record<string, unknown> = { ids, action };
      if (action === "assign" && person) body.assignee_id = person.id;
      const done = await ticketsRequest<{ updated: number }>(`${TICKETS_BASE}/bulk`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      const n = done.updated ?? ids.length;
      setNotice(
        action === "close"
          ? `${plural(n, "ticket", "tickets")} closed.`
          : action === "assign_to_me"
            ? `${plural(n, "ticket", "tickets")} assigned to you.`
            : `${plural(n, "ticket", "tickets")} assigned to ${person?.name}.${settings?.email_assignee === false ? "" : " They get one email listing them."}`,
      );
      setSelected(new Set());
      changed();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function exportCsv() {
    try {
      await downloadCsv(`${TICKETS_BASE}/export.csv?${queueQuery(filters)}`, "tickets.csv");
    } catch (err) {
      setError(errorText(err));
    }
  }

  const data = list?.data ?? null;
  const loading = !list || list.key !== listKey;
  const items = data?.items ?? [];
  const allChecked = items.length > 0 && items.every((t) => selected.has(t.id));
  const totalPages = data ? Math.max(1, Math.ceil(data.total / (data.page_size || PAGE_SIZE))) : 1;
  const limits: ImageLimits = settings ?? DEFAULT_LIMITS;
  const categories = meta?.categories ?? settings?.categories ?? [];
  const departments = meta?.departments ?? [];
  const assigneeName = (id: string) =>
    id === "none" ? "Unassigned" : (assignees.find((a) => String(a.id) === id)?.name ?? `#${id}`);
  const shownDetail = detail && detail.id === ticketId ? detail : null;

  const views = useMemo(() => (filters.view === "all" ? [...QUICK_VIEWS, "all" as StaffView] : QUICK_VIEWS), [filters.view]);

  const panel = ticketId ? (
    shownDetail ? (
      <TicketDetailPanel
        key={shownDetail.id}
        ticket={shownDetail}
        assignees={assignees}
        categories={categories}
        limits={limits}
        autoCloseDays={settings?.auto_close_days ?? meta?.settings.auto_close_days ?? 7}
        emailsAssignee={settings?.email_assignee ?? true}
        canWrite={canWrite}
        isSuperAdmin={isSuperAdmin}
        onUpdated={(next) => {
          setDetail(next);
          changed();
        }}
        onDeleted={() => {
          setDetail(null);
          setNotice("The ticket was deleted.");
          patch({ ticket: "" }, true);
          changed();
        }}
        onBack={isPhone ? () => patch({ ticket: "" }, true) : undefined}
      />
    ) : (
      <section className="tickets-panel tickets-detail tickets-detail--empty">
        {isPhone ? (
          <button type="button" className="btn btn-ghost tickets-back" onClick={() => patch({ ticket: "" }, true)}>
            ← All tickets
          </button>
        ) : null}
        <p className={detailError ? "alert alert-error" : "muted-text"}>{detailError || "Loading the ticket…"}</p>
      </section>
    )
  ) : (
    <section className="tickets-panel tickets-detail tickets-detail--empty">
      <p className="muted-text">Choose a ticket to read it here.</p>
    </section>
  );

  if (isPhone && ticketId) return <div className="tickets-queue tickets-queue--phone-detail">{panel}</div>;

  return (
    <div className="tickets-queue">
      <div className="tickets-toolbar">
        <div className="tickets-seg" role="group" aria-label="Quick views">
          {views.map((view) => {
            // Closed has no count, as on the mockup: it only grows, and nobody works it down.
            const count = view === "all" || view === "closed" ? null : counts?.[view as keyof StaffCounts];
            return (
              <button
                key={view}
                type="button"
                className={filters.view === view ? "is-on" : undefined}
                aria-pressed={filters.view === view}
                onClick={() => patch({ view: view === "active" ? "" : view })}
              >
                {STAFF_VIEW_LABELS[view]}
                {count != null ? ` · ${count}` : ""}
                {view === "needs_staff" && (counts?.needs_staff_urgent ?? 0) > 0 ? (
                  <span className="tickets-seg__urgent" title={`${counts?.needs_staff_urgent} Urgent`} aria-hidden />
                ) : null}
              </button>
            );
          })}
        </div>
        <input
          type="search"
          className="input-block tickets-search"
          placeholder="Search title, text, user or #number"
          aria-label="Search tickets"
          value={qDraft}
          onChange={(e) => setQDraft(e.target.value)}
        />
        <select
          className="input-block"
          aria-label="Priority"
          value={filters.priority}
          onChange={(e) => patch({ priority: e.target.value })}
        >
          <option value="">Priority</option>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {PRIORITY_LABELS[p]}
            </option>
          ))}
        </select>
        <select
          className="input-block"
          aria-label="Category"
          value={filters.category}
          onChange={(e) => patch({ category: e.target.value })}
        >
          <option value="">Category</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select
          className="input-block"
          aria-label="Department"
          value={filters.department}
          onChange={(e) => patch({ department: e.target.value })}
        >
          <option value="">Department</option>
          {departments.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        {filters.assignee ? (
          <span className="tickets-chip">
            Assignee: {assigneeName(filters.assignee)}
            <button type="button" className="tickets-chip__x" aria-label="Clear the assignee filter" onClick={() => patch({ assignee: "" })}>
              ✕
            </button>
          </span>
        ) : null}
        {filters.status ? (
          <span className="tickets-chip">
            Status: {statusLabel(filters.status as TicketStatus, "staff")}
            <button type="button" className="tickets-chip__x" aria-label="Clear the status filter" onClick={() => patch({ status: "" })}>
              ✕
            </button>
          </span>
        ) : null}
        <div className="tickets-toolbar__end">
          <button type="button" className="btn btn-ghost btn-readonly-ok" onClick={() => void exportCsv()}>
            Export CSV
          </button>
          {isSuperAdmin ? (
            <button
              type="button"
              className="btn btn-ghost tickets-danger-ghost"
              onClick={() => setDeleteTarget({ kind: "filter", filter: deleteFilterFromQueue(filters) })}
            >
              Delete by filter…
            </button>
          ) : null}
        </div>
      </div>

      {error ? (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="alert alert-success tickets-notice" role="status">
          {notice}
          <button type="button" className="tickets-chip__x" aria-label="Dismiss" onClick={() => setNotice("")}>
            ✕
          </button>
        </p>
      ) : null}

      {canWrite && selected.size > 0 ? (
        <div className="tickets-bulkbar" role="region" aria-label="Selected tickets">
          <b>{selected.size} selected</b>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => void bulk("assign_to_me")}>
            Assign to me
          </button>
          <div className="tickets-bulkbar__assign" ref={bulkRef}>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              aria-haspopup="dialog"
              aria-expanded={bulkAssignOpen}
              onClick={() => setBulkAssignOpen((v) => !v)}
            >
              Assign… ▾
            </button>
            {bulkAssignOpen ? (
              <AssignMenu
                assignees={assignees}
                currentId={null}
                emailsAssignee={settings?.email_assignee ?? true}
                canUnassign={false}
                bulk
                onPick={(person) => (person?.is_me ? void bulk("assign_to_me") : person ? void bulk("assign", person) : undefined)}
              />
            ) : null}
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => void bulk("close")}>
            Close
          </button>
          {isSuperAdmin ? (
            <button
              type="button"
              className="btn btn-ghost btn-sm tickets-danger-ghost"
              onClick={() => setDeleteTarget({ kind: "ids", ids: [...selected] })}
            >
              Delete…
            </button>
          ) : null}
          <span className="muted-text tickets-bulkbar__note">
            Assigning someone else sends them one email for all selected tickets; Assign to me sends nothing.
          </span>
        </div>
      ) : null}

      <div className={`tickets-split${isPhone ? " tickets-split--phone" : ""}`}>
        <div className={`tickets-panel tickets-list${loading && list ? " is-loading" : ""}`}>
          <table className="tickets-table tickets-queue-table">
            <thead>
              <tr>
                {canWrite ? (
                  <th className="tickets-cb">
                    <input
                      type="checkbox"
                      aria-label="Select every ticket on this page"
                      checked={allChecked}
                      onChange={() => setSelected(allChecked ? new Set() : new Set(items.map((t) => t.id)))}
                    />
                  </th>
                ) : null}
                <th className="tickets-col-num">#</th>
                <th>Ticket</th>
                <th className="tickets-col-wide">Priority</th>
                <th className="tickets-col-wide">Status</th>
                <th className="tickets-col-wide">Updated</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr
                  key={row.id}
                  className={`${row.needs_staff ? "is-unread" : ""}${row.id === ticketId ? " is-selected" : ""}`.trim() || undefined}
                  aria-selected={row.id === ticketId}
                  onClick={() => patch({ ticket: String(row.id) }, true)}
                >
                  {canWrite ? (
                    <td className="tickets-cb" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label={`Select #${row.number}`}
                        checked={selected.has(row.id)}
                        onChange={() => toggle(row.id)}
                      />
                    </td>
                  ) : null}
                  <td className="tickets-num tickets-col-num">{row.number}</td>
                  <td>
                    <button
                      type="button"
                      className="tickets-row-title"
                      dir="auto"
                      onClick={(e) => {
                        e.stopPropagation();
                        patch({ ticket: String(row.id) }, true);
                      }}
                    >
                      {row.title}
                      {row.needs_staff ? <span className="tickets-unread-dot" title="Needs staff" aria-label="Needs staff" /> : null}
                    </button>
                    <div className="tickets-row-sub">
                      {row.reporter.name}
                      {row.reporter.department ? ` · ${row.reporter.department}` : ""} · {row.category} ·{" "}
                      {row.assignee ? (
                        <span className="tickets-to">→ {shortName(row.assignee.name)}</span>
                      ) : (
                        <>
                          <span className="tickets-unassigned">unassigned</span>
                          {canWrite ? (
                            <button
                              type="button"
                              className="tickets-linkbtn tickets-linkbtn--row"
                              onClick={(e) => void assignToMe(e, row)}
                            >
                              Assign to me
                            </button>
                          ) : null}
                        </>
                      )}
                    </div>
                    <div className="tickets-row-badges">
                      <PriorityBadge priority={row.priority} />
                      <StatusBadge status={row.status} />
                      <span className="muted-text">{relativeTime(row.updated_at)}</span>
                    </div>
                  </td>
                  <td className="tickets-col-wide">
                    <PriorityBadge priority={row.priority} />
                  </td>
                  <td className="tickets-col-wide">
                    <StatusBadge status={row.status} />
                  </td>
                  <td className="tickets-col-wide muted-text">{relativeTime(row.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!data ? (
            <p className="tickets-list__empty muted-text">{error ? "" : "Loading tickets…"}</p>
          ) : items.length === 0 ? (
            <p className="tickets-list__empty muted-text">
              {filters.view === "needs_staff" ? "Nothing waits for staff. " : ""}No ticket matches.
            </p>
          ) : null}
          {data && data.total > data.page_size ? (
            <nav className="tickets-pager" aria-label="Pages">
              <span className="muted-text">
                {(data.page - 1) * data.page_size + 1}–{Math.min(data.page * data.page_size, data.total)} of {data.total}
              </span>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={page <= 1}
                onClick={() => patch({ page: String(page - 1) }, true)}
              >
                ‹ Previous
              </button>
              <span>
                Page {page} of {totalPages}
              </span>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={page >= totalPages}
                onClick={() => patch({ page: String(page + 1) }, true)}
              >
                Next ›
              </button>
            </nav>
          ) : null}
        </div>
        {isPhone ? null : panel}
      </div>

      <DeleteTicketsDialog
        target={deleteTarget}
        options={{ categories, departments, assignees }}
        onClose={() => setDeleteTarget(null)}
        onDeleted={(deleted) => {
          setDeleteTarget(null);
          setSelected(new Set());
          setNotice(`${plural(deleted, "ticket was", "tickets were")} deleted.`);
          if (ticketId) patch({ ticket: "" }, true);
          changed();
        }}
      />
    </div>
  );
}
