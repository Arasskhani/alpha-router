import { FormEvent, useState } from "react";

import { api, formatApiError } from "../../api";
import { useAdminWriteLock } from "../../lib/adminWriteLock";
import {
  cronFor,
  MAX_SCHEDULE_RECIPIENTS,
  parseRecipients,
  SCHEDULE_FORMATS,
  type ScheduledReport,
  type ScheduleFrequency,
  type SchedulePeriod,
  WEEKDAY_NAMES,
} from "../../lib/reportSchedules";
import Modal from "../Modal";

const DEFAULT_PERIOD = "previous_7_days";
const MONTH_DAYS = Array.from({ length: 28 }, (_, i) => i + 1);

type Props = {
  open: boolean;
  report: { id: string; title: string; needs_date: boolean };
  /** The report's parameters as chosen on the page. */
  parameters: Record<string, unknown>;
  periods: SchedulePeriod[];
  /** The server's timezone: cron expressions and times are its clock. */
  timezone: string;
  onClose: () => void;
  onScheduled: (schedule: ScheduledReport) => void;
};

/**
 * Email a report on a schedule: when, which days it covers, in what format, to
 * whom. The report's filters are the ones chosen on the page.
 */
export default function ScheduleReportDialog({
  open,
  report,
  parameters,
  periods,
  timezone,
  onClose,
  onScheduled,
}: Props) {
  const { readOnly, writeLockProps } = useAdminWriteLock();
  const [frequency, setFrequency] = useState<ScheduleFrequency>("weekly");
  const [time, setTime] = useState("08:00");
  const [weekday, setWeekday] = useState(1);
  const [monthDay, setMonthDay] = useState(1);
  const [cron, setCron] = useState("");
  const [period, setPeriod] = useState(DEFAULT_PERIOD);
  const [format, setFormat] = useState("pdf");
  const [recipients, setRecipients] = useState("");
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);

  // The next opening starts from what was chosen, without the last error.
  function close() {
    setErr("");
    onClose();
  }

  const knownPeriod = periods.some((p) => p.value === period) ? period : (periods[0]?.value ?? DEFAULT_PERIOD);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const addresses = parseRecipients(recipients);
    if (addresses.length === 0) {
      setErr("Add at least one recipient.");
      return;
    }
    if (addresses.length > MAX_SCHEDULE_RECIPIENTS) {
      setErr(`At most ${MAX_SCHEDULE_RECIPIENTS} recipients.`);
      return;
    }
    const expression = cronFor({ frequency, time, weekday, monthDay, cron });
    if (!expression) {
      setErr(frequency === "custom" ? "Type a cron expression." : "Choose a time.");
      return;
    }
    setSaving(true);
    setErr("");
    try {
      const data = await api<{ schedule: ScheduledReport }>("/api/admin/reports/schedules", {
        method: "POST",
        body: JSON.stringify({
          report_type: report.id,
          cron_expression: expression,
          recipients: addresses.join(", "),
          parameters_json: Object.keys(parameters).length ? JSON.stringify(parameters) : null,
          format,
          period: knownPeriod,
        }),
      });
      onScheduled(data.schedule);
      close();
    } catch (ex) {
      setErr(formatApiError(ex));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} title="Schedule by email" onClose={close}>
      <form onSubmit={submit} className="report-schedule-form">
        <p className="muted-text" style={{ marginTop: 0 }}>
          Emails <strong>{report.title}</strong> as an attachment, with the filters chosen on the page. Each recipient gets
          their own email.
        </p>

        <label htmlFor="report-schedule-frequency">Send</label>
        <select
          id="report-schedule-frequency"
          className="input-block"
          value={frequency}
          onChange={(e) => setFrequency(e.target.value as ScheduleFrequency)}
        >
          <option value="daily">Every day</option>
          <option value="weekly">Every week</option>
          <option value="monthly">Every month</option>
          <option value="custom">Custom (cron expression)</option>
        </select>

        {frequency === "weekly" ? (
          <>
            <label htmlFor="report-schedule-weekday">On</label>
            <select
              id="report-schedule-weekday"
              className="input-block"
              value={weekday}
              onChange={(e) => setWeekday(Number(e.target.value))}
            >
              {WEEKDAY_NAMES.map((name, index) => (
                <option key={name} value={index}>
                  {name}
                </option>
              ))}
            </select>
          </>
        ) : null}

        {frequency === "monthly" ? (
          <>
            <label htmlFor="report-schedule-month-day">On day</label>
            <select
              id="report-schedule-month-day"
              className="input-block"
              value={monthDay}
              onChange={(e) => setMonthDay(Number(e.target.value))}
            >
              {MONTH_DAYS.map((day) => (
                <option key={day} value={day}>
                  {day}
                </option>
              ))}
            </select>
          </>
        ) : null}

        {frequency === "custom" ? (
          <>
            <label htmlFor="report-schedule-cron">Cron expression</label>
            <input
              id="report-schedule-cron"
              className="input-block"
              value={cron}
              onChange={(e) => setCron(e.target.value)}
              placeholder="0 8 * * 1-5"
              aria-describedby="report-schedule-cron-hint report-schedule-timezone"
              spellCheck={false}
              autoComplete="off"
            />
            <p id="report-schedule-cron-hint" className="muted-text report-schedule-form__hint">
              Five fields: minute, hour, day of the month, month, day of the week (0 and 7 are Sunday).
            </p>
          </>
        ) : (
          <>
            <label htmlFor="report-schedule-time">At</label>
            <input
              id="report-schedule-time"
              type="time"
              className="input-block"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              aria-describedby="report-schedule-timezone"
            />
          </>
        )}
        <p id="report-schedule-timezone" className="muted-text report-schedule-form__hint">
          Times are the server&apos;s clock ({timezone}).
        </p>

        {report.needs_date ? (
          <>
            <label htmlFor="report-schedule-period">Covering</label>
            <select
              id="report-schedule-period"
              className="input-block"
              value={knownPeriod}
              onChange={(e) => setPeriod(e.target.value)}
            >
              {periods.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </>
        ) : (
          <p className="muted-text report-schedule-form__hint">
            A snapshot report: each email shows the data as it is when it is sent.
          </p>
        )}

        <label htmlFor="report-schedule-format">Format</label>
        <select id="report-schedule-format" className="input-block" value={format} onChange={(e) => setFormat(e.target.value)}>
          {SCHEDULE_FORMATS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>

        <label htmlFor="report-schedule-recipients">Recipients</label>
        <textarea
          id="report-schedule-recipients"
          className="input-block"
          rows={3}
          value={recipients}
          onChange={(e) => setRecipients(e.target.value)}
          placeholder="name@example.com"
          aria-describedby="report-schedule-recipients-hint"
          spellCheck={false}
        />
        <p id="report-schedule-recipients-hint" className="muted-text report-schedule-form__hint">
          Up to {MAX_SCHEDULE_RECIPIENTS} addresses, separated by commas or new lines.
        </p>

        {err && (
          <p className="alert alert-error" role="alert">
            {err}
          </p>
        )}
        <div className="dialog-actions">
          <button type="submit" className="btn" disabled={saving || readOnly} title={writeLockProps.title}>
            {saving ? "Scheduling…" : "Schedule"}
          </button>
          <button type="button" className="btn btn-ghost dialog-actions-cancel" onClick={close}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
}
