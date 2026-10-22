import { useCallback, useEffect, useState } from "react";

import Modal from "../Modal";
import type { useConfirm } from "../../context/ConfirmContext";
import {
  DELETE_ALL_PHRASE,
  PRIORITIES,
  PRIORITY_LABELS,
  STATUSES,
  TICKETS_BASE,
  TicketsApiError,
  announceTicketsChanged,
  formatBytes,
  statusLabel,
  ticketNumber,
  ticketsRequest,
  type DeleteFilter,
  type DeletePreview,
  type TicketStatus,
} from "../../lib/tickets";
import { cleanDeleteFilter, deleteFilterExportQuery, downloadCsv } from "../../lib/ticketsAdmin";

type Confirmer = ReturnType<typeof useConfirm>;

export type DeleteTarget =
  /** `fromQueue`: opened from the queue, whose search and quick view do not carry over. */
  | { kind: "filter"; filter: DeleteFilter; fromQueue?: boolean }
  /** `numbers` are the ticket numbers people know (#1042), in the order of `ids`. */
  | { kind: "ids"; ids: number[]; numbers: number[] };

type Options = { categories: string[]; departments: string[]; assignees: { id: number; name: string }[] };

type Props = {
  target: DeleteTarget | null;
  options: Options;
  onClose: () => void;
  onDeleted: (deleted: number) => void;
};

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function formatDay(value: string): string {
  const d = new Date(`${value}T00:00:00`);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/** "Closed, Resolved", "any", one line per filter that is set. */
function filterRows(filter: DeleteFilter, options: Options): [string, string][] {
  const statuses = filter.statuses?.length ? filter.statuses : (["resolved", "closed"] as TicketStatus[]);
  const rows: [string, string][] = [
    ["Status", [...statuses].sort().map((s) => statusLabel(s, "staff")).join(", ")],
    ["Last activity", filter.before ? `before ${formatDay(filter.before)}` : "any time"],
  ];
  const rest: [string, string][] = [];
  if (filter.priority) rest.push(["Priority", PRIORITY_LABELS[filter.priority] ?? filter.priority]);
  if (filter.category) rest.push(["Category", filter.category]);
  if (filter.department) rest.push(["Department", filter.department]);
  if (filter.assignee) {
    rest.push([
      "Assignee",
      filter.assignee === "none"
        ? "Unassigned"
        : (options.assignees.find((a) => String(a.id) === filter.assignee)?.name ?? `#${filter.assignee}`),
    ]);
  }
  return rest.length ? [...rows, ...rest] : [...rows, ["Priority · Category · Assignee", "any"]];
}

/**
 * Delete the selected tickets, or every ticket a filter matches: the filter,
 * what goes (tickets, messages, images and their size), a CSV first, and the
 * typed phrase the server checks again with a fresh count.
 */
export default function DeleteTicketsDialog({ target, options, onClose, onDeleted }: Props) {
  const [filter, setFilter] = useState<DeleteFilter>({});
  const [stage, setStage] = useState<"edit" | "confirm">("edit");
  const [preview, setPreview] = useState<DeletePreview | null>(null);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [changed, setChanged] = useState("");

  const scope = useCallback(
    (f: DeleteFilter) => (target?.kind === "ids" ? { ids: target.ids } : { filter: cleanDeleteFilter(f) }),
    [target],
  );

  const runPreview = useCallback(
    async (f: DeleteFilter) => {
      setBusy(true);
      setError("");
      try {
        const next = await ticketsRequest<DeletePreview>(`${TICKETS_BASE}/delete-preview`, {
          method: "POST",
          body: JSON.stringify(scope(f)),
        });
        setPreview(next);
        setTyped("");
        setStage("confirm");
        return next;
      } catch (err) {
        setError(errorText(err));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [scope],
  );

  useEffect(() => {
    if (!target) return;
    /* eslint-disable react-hooks/set-state-in-effect -- a new dialog starts from what it was opened with */
    setPreview(null);
    setTyped("");
    setError("");
    setChanged("");
    if (target.kind === "filter") {
      setFilter(cleanDeleteFilter(target.filter));
      setStage("edit");
    } else {
      setStage("confirm");
      void runPreview({});
    }
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [target, runPreview]);

  async function remove() {
    if (!preview) return;
    setBusy(true);
    setError("");
    try {
      const done = await ticketsRequest<{ deleted: number }>(`${TICKETS_BASE}/delete`, {
        method: "POST",
        body: JSON.stringify({ ...scope(filter), token: preview.token, phrase: typed }),
      });
      announceTicketsChanged();
      onDeleted(done.deleted ?? preview.count);
    } catch (err) {
      if (err instanceof TicketsApiError && (err.code === "count_changed" || err.code === "token_invalid")) {
        const before = preview.count;
        const next = await runPreview(filter);
        const now = typeof err.data.count === "number" ? err.data.count : next?.count;
        setChanged(
          err.code === "count_changed"
            ? `Nothing was deleted: the tickets changed while you were deciding. There are now ${now ?? "a different number of"} tickets (it was ${before}). Check the numbers and type the new phrase.`
            : "Nothing was deleted: the confirmation expired. Check the numbers and type the phrase again.",
        );
      } else {
        setError(errorText(err));
      }
      setBusy(false);
    }
  }

  async function exportFirst() {
    try {
      await downloadCsv(`${TICKETS_BASE}/export.csv?${deleteFilterExportQuery(cleanDeleteFilter(filter))}`, "tickets.csv");
    } catch (err) {
      setError(errorText(err));
    }
  }

  if (!target) return null;
  const isFilter = target.kind === "filter";
  const statuses = filter.statuses ?? [];
  const title = isFilter
    ? "Delete tickets matching this filter"
    : target.ids.length === 1
      ? "Delete the selected ticket"
      : `Delete ${target.ids.length} selected tickets`;

  return (
    <Modal open title={title} onClose={onClose} panelClassName="tickets-modal">
      <div className="tickets-form">
        {error ? (
          <p className="alert alert-error" role="alert">
            {error}
          </p>
        ) : null}
        {isFilter && stage === "edit" ? (
          <form
            className="tickets-form"
            onSubmit={(e) => {
              e.preventDefault();
              void runPreview(filter);
            }}
          >
            {target.fromQueue ? (
              <p className="tickets-hint" data-testid="tickets-delete-scope">
                The search and the quick view are not part of this filter: it counts every ticket with these
                statuses and fields, not only the ones the queue shows.
              </p>
            ) : null}
            <fieldset className="tickets-delete-statuses">
              <legend>Status</legend>
              {STATUSES.map((s) => (
                <label key={s} className="tickets-check">
                  <input
                    type="checkbox"
                    checked={statuses.includes(s)}
                    onChange={(e) =>
                      setFilter({
                        ...filter,
                        statuses: e.target.checked ? [...statuses, s] : statuses.filter((x) => x !== s),
                      })
                    }
                  />
                  <span>{statusLabel(s, "staff")}</span>
                </label>
              ))}
            </fieldset>
            <div className="tickets-row2">
              <label className="tickets-field-stack">
                <span>Last activity before</span>
                <input
                  type="date"
                  className="input-block"
                  value={filter.before ?? ""}
                  onChange={(e) => setFilter({ ...filter, before: e.target.value })}
                />
              </label>
              <label className="tickets-field-stack">
                <span>Priority</span>
                <select
                  className="input-block"
                  value={filter.priority ?? ""}
                  onChange={(e) => setFilter({ ...filter, priority: e.target.value as DeleteFilter["priority"] })}
                >
                  <option value="">Any priority</option>
                  {PRIORITIES.map((p) => (
                    <option key={p} value={p}>
                      {PRIORITY_LABELS[p]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="tickets-field-stack">
                <span>Category</span>
                <select
                  className="input-block"
                  value={filter.category ?? ""}
                  onChange={(e) => setFilter({ ...filter, category: e.target.value })}
                >
                  <option value="">Any category</option>
                  {options.categories.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </label>
              <label className="tickets-field-stack">
                <span>Department</span>
                <select
                  className="input-block"
                  value={filter.department ?? ""}
                  onChange={(e) => setFilter({ ...filter, department: e.target.value })}
                >
                  <option value="">Any department</option>
                  {options.departments.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
              </label>
              <label className="tickets-field-stack">
                <span>Assignee</span>
                <select
                  className="input-block"
                  value={filter.assignee ?? ""}
                  onChange={(e) => setFilter({ ...filter, assignee: e.target.value })}
                >
                  <option value="">Anyone</option>
                  <option value="none">Unassigned</option>
                  {options.assignees.map((a) => (
                    <option key={a.id} value={String(a.id)}>
                      {a.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {statuses.some((s) => s !== "resolved" && s !== "closed") ? (
              <p className="tickets-warn-line">This filter names active tickets: people may still be waiting on them.</p>
            ) : null}
            <p className="tickets-hint">With no status chosen, Resolved and Closed tickets are counted.</p>
            <div className="tickets-actions">
              <button type="button" className="btn btn-ghost" onClick={onClose}>
                Cancel
              </button>
              <button type="submit" className="btn" disabled={busy}>
                {busy ? "Counting…" : "Count the tickets"}
              </button>
            </div>
          </form>
        ) : null}

        {stage === "confirm" ? (
          preview ? (
            <>
              <div className="tickets-filter-summary">
                {isFilter ? (
                  filterRows(cleanDeleteFilter(filter), options).map(([label, value]) => (
                    <div key={label}>
                      <span className="muted-text">{label}</span>
                      <b>{value}</b>
                    </div>
                  ))
                ) : (
                  <div>
                    <span className="muted-text">Selected</span>
                    <b>
                      {target.numbers.length > 6
                        ? `${target.numbers.length} tickets`
                        : target.numbers.map((n) => ticketNumber(n)).join(", ")}
                    </b>
                  </div>
                )}
              </div>
              {changed ? (
                <p className="alert alert-warning" role="alert">
                  {changed}
                </p>
              ) : null}
              <div className="tickets-impact" data-testid="tickets-delete-impact">
                <b>
                  {preview.count} {preview.count === 1 ? "ticket" : "tickets"}
                </b>{" "}
                · {preview.messages} {preview.messages === 1 ? "message" : "messages"} · {preview.images}{" "}
                {preview.images === 1 ? "image" : "images"} ({formatBytes(preview.image_bytes)}) will be deleted for good.
              </div>
              <ul className="tickets-warn">
                <li>The people who sent them will no longer see them.</li>
                <li>Ticket reports for past periods will count fewer tickets. Nothing can be restored.</li>
                {preview.includes_active ? (
                  <li className="tickets-warn__strong">
                    This includes Open, In progress or Waiting tickets: people are still waiting on them.
                  </li>
                ) : (
                  <li>Open, In progress and Waiting tickets are not in this {isFilter ? "filter" : "selection"}.</li>
                )}
              </ul>
              {isFilter && preview.count > 0 ? (
                <p className="tickets-export-first">
                  <button type="button" className="tickets-linkbtn tickets-linkbtn--plain" onClick={() => void exportFirst()}>
                    Export these {preview.count} tickets as CSV first
                  </button>
                </p>
              ) : null}
              {preview.count > 0 ? (
                <label className="tickets-field-stack">
                  <span className="tickets-label-strong">
                    Type <code>{preview.phrase}</code> to confirm
                  </span>
                  <input
                    className="input-block"
                    value={typed}
                    onChange={(e) => setTyped(e.target.value)}
                    autoComplete="off"
                    spellCheck={false}
                    aria-label={`Type ${preview.phrase} to confirm`}
                  />
                </label>
              ) : (
                <p className="muted-text">No ticket matches: there is nothing to delete.</p>
              )}
              <p className="tickets-hint">
                The server counts again before deleting: if the {isFilter ? "filter" : "selection"} now matches a different
                number, nothing is deleted and you are asked again. Recorded in Admin Logs.
              </p>
              <div className="tickets-actions">
                {isFilter ? (
                  <button type="button" className="btn btn-ghost" onClick={() => setStage("edit")} disabled={busy}>
                    Back
                  </button>
                ) : null}
                <button type="button" className="btn btn-ghost" onClick={onClose}>
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn btn-danger"
                  disabled={busy || preview.count === 0 || typed !== preview.phrase}
                  onClick={() => void remove()}
                >
                  {busy ? "Deleting…" : `Delete ${preview.count} ${preview.count === 1 ? "ticket" : "tickets"}`}
                </button>
              </div>
            </>
          ) : (
            <p className="muted-text">{busy ? "Counting the tickets…" : "Could not count the tickets."}</p>
          )
        ) : null}
      </div>
    </Modal>
  );
}

/** One ticket, after a confirmation. Resolves to true when it is gone. */
export async function deleteOneTicket(
  confirmer: Confirmer,
  ticket: { id: number; number: number; title: string },
): Promise<boolean> {
  const ok = await confirmer.confirm({
    title: `Delete ticket ${ticketNumber(ticket.number)}?`,
    message: `“${ticket.title}”, its messages and its images are deleted for good. The person who sent it will no longer see it. Recorded in Admin Logs.`,
    confirmLabel: "Delete ticket",
    danger: true,
  });
  if (ok !== true) return false;
  await ticketsRequest(`${TICKETS_BASE}/${ticket.id}`, { method: "DELETE" });
  announceTicketsChanged();
  return true;
}

/**
 * Every ticket: two dialogs, then the typed phrase the server checks again
 * (the pattern of API Logs and Storage). Resolves to the number deleted, or
 * null when the administrator stopped.
 */
export async function deleteAllTickets(confirmer: Confirmer): Promise<number | null> {
  const first = await confirmer.confirm({
    title: "Delete all tickets?",
    message:
      "This deletes every ticket, open or closed, with every message and image. People lose their conversations with support. This cannot be undone.",
    confirmLabel: "Continue",
    danger: true,
  });
  if (first !== true) return null;
  const second = await confirmer.confirm({
    title: "Delete every ticket and its history?",
    message:
      "Ticket reports and the Overview will start again from zero. CSV files exported earlier are not affected. Recorded in Admin Logs before anything is deleted.",
    confirmLabel: "Yes, delete all",
    danger: true,
  });
  if (second !== true) return null;
  const typed = await confirmer.prompt({
    title: "Final confirmation",
    message: "You are about to delete ALL tickets. Only continue if you want an empty ticket list.",
    promptLabel: `Type "${DELETE_ALL_PHRASE}" to confirm`,
    promptExactMatch: DELETE_ALL_PHRASE,
    confirmLabel: "Delete all tickets now",
    danger: true,
  });
  if (typed !== DELETE_ALL_PHRASE) return null;
  const done = await ticketsRequest<{ deleted: number }>(`${TICKETS_BASE}/delete-all`, {
    method: "POST",
    body: JSON.stringify({ phrase: typed }),
  });
  announceTicketsChanged();
  return done.deleted ?? 0;
}
