import { useState } from "react";

import { api, formatApiError } from "../../api";
import { useTableCards } from "../../hooks/useTableCards";
import {
  describeCron,
  describeFilters,
  lastRunBadge,
  SCHEDULE_FORMATS,
  type ScheduledReport,
  type SchedulePeriod,
} from "../../lib/reportSchedules";
import ConfirmModal from "../ConfirmModal";
import RowActionsMenu from "../RowActionsMenu";

type SendResult = {
  status: string;
  sent: string[];
  not_sent: Record<string, string>;
  error: string | null;
};

type Props = {
  schedules: ScheduledReport[];
  periods: SchedulePeriod[];
  /** The server's timezone: cron expressions and times are its clock. */
  timezone: string;
  /** Fetch the list again after a change. */
  onReload: () => Promise<void>;
};

type Notice = { tone: "status" | "alert"; text: string };

function sendNotice(schedule: ScheduledReport, result: SendResult): Notice {
  const total = result.sent.length + Object.keys(result.not_sent).length;
  if (result.status === "sent") {
    return { tone: "status", text: `Sent ${schedule.report_title} to ${total === 1 ? "1 recipient" : `${total} recipients`}.` };
  }
  if (result.status === "partial") {
    return {
      tone: "alert",
      text: `Sent ${schedule.report_title} to ${result.sent.length} of ${total} recipients. ${result.error ?? ""}`.trim(),
    };
  }
  return { tone: "alert", text: `${schedule.report_title} was not sent. ${result.error ?? ""}`.trim() };
}

/**
 * The reports that are emailed on a schedule: when each goes out next, how the
 * last run went, and Send now, Pause or Resume, and Delete.
 */
export default function ScheduledReports({ schedules, periods, timezone, onReload }: Props) {
  const tableRef = useTableCards<HTMLTableElement>();
  const [notice, setNotice] = useState<Notice | null>(null);
  const [deleting, setDeleting] = useState<ScheduledReport | null>(null);

  const periodLabel = (value: string) => periods.find((p) => p.value === value)?.label ?? value;
  const formatLabel = (value: string) => SCHEDULE_FORMATS.find((f) => f.value === value)?.label ?? value.toUpperCase();

  async function sendNow(schedule: ScheduledReport) {
    setNotice(null);
    try {
      const result = await api<SendResult>(`/api/admin/reports/schedules/${schedule.id}/send`, { method: "POST" });
      setNotice(sendNotice(schedule, result));
    } catch (ex) {
      setNotice({ tone: "alert", text: formatApiError(ex) });
    }
    await onReload();
  }

  async function setActive(schedule: ScheduledReport, active: boolean) {
    setNotice(null);
    try {
      await api(`/api/admin/reports/schedules/${schedule.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: active }),
      });
    } catch (ex) {
      setNotice({ tone: "alert", text: formatApiError(ex) });
    }
    await onReload();
  }

  async function confirmDelete() {
    const schedule = deleting;
    setDeleting(null);
    if (!schedule) return;
    setNotice(null);
    try {
      await api(`/api/admin/reports/schedules/${schedule.id}`, { method: "DELETE" });
    } catch (ex) {
      setNotice({ tone: "alert", text: formatApiError(ex) });
    }
    await onReload();
  }

  return (
    <section className="card reports-schedules" aria-labelledby="reports-schedules-title">
      <h3 id="reports-schedules-title" className="reports-schedules__title">
        Scheduled reports
      </h3>
      <p className="muted-text reports-schedules__intro">
        Emailed on their schedule, on the server&apos;s clock ({timezone}). To add one, choose a report and use Schedule by
        email.
      </p>
      {notice ? (
        notice.tone === "alert" ? (
          <p className="alert alert-error" role="alert">
            {notice.text}
          </p>
        ) : (
          <p className="alert alert-success" role="status">
            {notice.text}
          </p>
        )
      ) : null}
      {schedules.length === 0 ? (
        <p className="muted-text">No reports are scheduled.</p>
      ) : (
        <div className="table-wrap">
          <table ref={tableRef} className="data-table data-table--cards reports-schedules__table">
            <thead>
              <tr>
                <th>Report</th>
                <th>When</th>
                <th>Recipients</th>
                <th>Last run</th>
                <th className="col-actions">Actions</th>
              </tr>
            </thead>
            <tbody>
              {schedules.map((s) => {
                const badge = lastRunBadge(s.last_status);
                const filters = describeFilters(s.parameters);
                return (
                  <tr key={s.id}>
                    <td>
                      <strong>{s.report_title}</strong>
                      <span className="muted-text reports-schedules__detail">
                        {[s.needs_date ? periodLabel(s.period) : "Snapshot", formatLabel(s.format)].join(" · ")}
                      </span>
                      {filters ? <span className="muted-text reports-schedules__detail">{filters}</span> : null}
                      {s.owner ? <span className="muted-text reports-schedules__detail">Set up by {s.owner}</span> : null}
                    </td>
                    <td>
                      {describeCron(s.cron_expression)}
                      <span className="muted-text reports-schedules__detail">
                        {s.is_active ? (s.next_run_local ? `Next: ${s.next_run_local}` : "Next: not due") : "Paused"}
                      </span>
                    </td>
                    <td className="reports-schedules__recipients">{s.recipients.split(",").join(", ")}</td>
                    <td>
                      <span className={badge.className}>{badge.label}</span>
                      {s.last_run_local ? (
                        <span className="muted-text reports-schedules__detail">{s.last_run_local}</span>
                      ) : null}
                      {s.last_error ? <span className="reports-schedules__error">{s.last_error}</span> : null}
                    </td>
                    <td className="col-actions">
                      <RowActionsMenu
                        label="Actions"
                        onError={(message) => setNotice({ tone: "alert", text: message })}
                        actions={[
                          { label: "Send now", onClick: () => sendNow(s) },
                          s.is_active
                            ? { label: "Pause", onClick: () => setActive(s, false) }
                            : { label: "Resume", onClick: () => setActive(s, true) },
                          { label: "Delete", onClick: () => setDeleting(s), danger: true },
                        ]}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <ConfirmModal
        open={deleting !== null}
        title="Delete this scheduled report?"
        message={
          deleting
            ? `${deleting.report_title} will no longer be emailed to ${deleting.recipients.split(",").join(", ")}.`
            : ""
        }
        confirmLabel="Delete"
        cancelLabel="Keep"
        danger
        onConfirm={() => void confirmDelete()}
        onCancel={() => setDeleting(null)}
      />
    </section>
  );
}
