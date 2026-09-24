/**
 * Scheduled reports on the Reports page: a cron expression from a plain choice
 * (every day, every week, every month), and a plain description of one.
 *
 * Cron is read the standard way by the server: day-of-week 0 and 7 are
 * Sunday, and times are the server's clock.
 */

export type SchedulePeriod = { value: string; label: string };

/** A schedule as `GET /api/admin/reports/schedules` lists it. */
export type ScheduledReport = {
  id: number;
  report_type: string;
  report_title: string;
  needs_date: boolean;
  cron_expression: string;
  period: string;
  recipients: string;
  parameters: Record<string, unknown>;
  format: string;
  is_active: boolean;
  owner: string | null;
  next_run_at: string | null;
  next_run_local: string | null;
  last_run_at: string | null;
  last_run_local: string | null;
  last_status: string | null;
  last_error: string | null;
};

export type ScheduleFrequency = "daily" | "weekly" | "monthly" | "custom";

export type ScheduleWhen = {
  frequency: ScheduleFrequency;
  /** "HH:MM" on the server's clock. */
  time: string;
  /** 0 is Sunday, 6 Saturday. */
  weekday: number;
  /** 1 to 28: every month has those. */
  monthDay: number;
  /** A five-field cron expression, for "custom". */
  cron: string;
};

export const WEEKDAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

export const SCHEDULE_FORMATS = [
  { value: "pdf", label: "PDF" },
  { value: "xlsx", label: "Excel" },
  { value: "csv", label: "CSV" },
] as const;

/** What the server allows on one schedule. */
export const MAX_SCHEDULE_RECIPIENTS = 20;

function hourAndMinute(time: string): [number, number] | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(time.trim());
  if (!m) return null;
  const hour = Number(m[1]);
  const minute = Number(m[2]);
  return hour <= 23 && minute <= 59 ? [hour, minute] : null;
}

/** The cron expression for a choice, or null when the time is missing or not a time. */
export function cronFor(when: ScheduleWhen): string | null {
  if (when.frequency === "custom") return when.cron.trim().split(/\s+/).join(" ") || null;
  const parsed = hourAndMinute(when.time);
  if (!parsed) return null;
  const [hour, minute] = parsed;
  if (when.frequency === "daily") return `${minute} ${hour} * * *`;
  if (when.frequency === "weekly") return `${minute} ${hour} * * ${when.weekday}`;
  return `${minute} ${hour} ${when.monthDay} * *`;
}

const clock = (hour: number, minute: number) => `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;

/** "Every Monday at 08:00" for the expressions the page makes; the expression itself for any other. */
export function describeCron(cron: string): string {
  const fields = cron.trim().split(/\s+/);
  const custom = `Cron: ${fields.join(" ")}`;
  if (fields.length !== 5 || !/^\d{1,2}$/.test(fields[0]) || !/^\d{1,2}$/.test(fields[1])) return custom;
  const minute = Number(fields[0]);
  const hour = Number(fields[1]);
  if (minute > 59 || hour > 23) return custom;
  const at = `at ${clock(hour, minute)}`;
  const [, , day, month, weekday] = fields;
  if (month !== "*") return custom;
  if (day === "*" && weekday === "*") return `Every day ${at}`;
  if (day === "*" && /^[0-7]$/.test(weekday)) return `Every ${WEEKDAY_NAMES[Number(weekday) % 7]} ${at}`;
  if (day === "*" && weekday === "1-5") return `Every weekday, Monday to Friday, ${at}`;
  if (weekday === "*" && /^\d{1,2}$/.test(day) && Number(day) >= 1 && Number(day) <= 31) {
    return `On day ${Number(day)} of every month ${at}`;
  }
  return custom;
}

/** Addresses typed into one box, separated by commas, semicolons, spaces or lines. */
export function parseRecipients(text: string): string[] {
  return text
    .split(/[\s,;]+/)
    .map((address) => address.trim())
    .filter(Boolean);
}

const DECIDED_BY_THE_SCHEDULE = new Set(["report_type", "format", "start_date", "end_date"]);

/** A report request's parameters without what a schedule decides itself. */
export function scheduleParameters(body: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(body).filter(([key]) => !DECIDED_BY_THE_SCHEDULE.has(key)));
}

const FILTER_LABELS: [key: string, label: string][] = [
  ["department", "Department"],
  ["office", "Office"],
  ["app", "App"],
  ["model_id", "Model"],
  ["provider", "Provider"],
  ["auth_provider", "Sign-in"],
  ["user_id", "User #"],
  ["plan_id", "Plan #"],
  ["group_id", "Group #"],
  ["alpha_router_api_key_id", "API key #"],
  ["agent_id", "Agent "],
  ["project_id", "Project "],
];

/** The filters a schedule narrows its report by, in a line; empty when none. */
export function describeFilters(parameters: Record<string, unknown>): string {
  return FILTER_LABELS.flatMap(([key, label]) => {
    const value = parameters[key];
    if (value === null || value === undefined || value === "") return [];
    return [label.endsWith("#") || label.endsWith(" ") ? `${label}${String(value)}` : `${label}: ${String(value)}`];
  }).join(" · ");
}

/** The label and badge style for the outcome of a schedule's last run. */
export function lastRunBadge(status: string | null): { label: string; className: string } {
  switch (status) {
    case "sent":
      return { label: "Sent", className: "status-badge status-badge--active" };
    case "partial":
      return { label: "Partly sent", className: "status-badge status-badge--partial" };
    case "failed":
      return { label: "Failed", className: "status-badge status-badge--failed" };
    case "running":
      return { label: "Running", className: "status-badge status-badge--processing" };
    default:
      return { label: "Not run yet", className: "status-badge status-badge--neutral" };
  }
}
