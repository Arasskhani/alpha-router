/**
 * @vitest-environment happy-dom
 *
 * Schedule by email: the choice of when becomes a standard cron expression,
 * the page's filters go with it without the page's dates, and mistakes are
 * caught before anything is sent.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from "vitest";

const readOnly = vi.hoisted(() => ({ value: false }));

vi.mock("../../api", () => ({
  api: vi.fn(),
  formatApiError: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => readOnly.value }));

import { api } from "../../api";
import type { ScheduledReport } from "../../lib/reportSchedules";
import ScheduleReportDialog from "./ScheduleReportDialog";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const PERIODS = [
  { value: "previous_day", label: "The day before" },
  { value: "previous_7_days", label: "The 7 days before" },
  { value: "previous_30_days", label: "The 30 days before" },
  { value: "previous_month", label: "The calendar month before" },
];
const DATED = { id: "top_users_by_spend", title: "Top users by spend", needs_date: true };
const SNAPSHOT = { id: "users_without_budget", title: "Users without budget", needs_date: false };

let host: HTMLDivElement;
let root: Root;
let onClose: Mock<() => void>;
let onScheduled: Mock<(schedule: ScheduledReport) => void>;

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue({ schedule: { id: 7 } });
  readOnly.value = false;
  onClose = vi.fn<() => void>();
  onScheduled = vi.fn<(schedule: ScheduledReport) => void>();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  document.body.innerHTML = "";
  document.body.style.overflow = "";
});

async function render(report = DATED, parameters: Record<string, unknown> = { top_n: 5, department: "Sales" }) {
  await act(async () => {
    root.render(
      <ScheduleReportDialog
        open
        report={report}
        parameters={parameters}
        periods={PERIODS}
        timezone="Asia/Tehran"
        onClose={onClose}
        onScheduled={onScheduled}
      />,
    );
  });
}

const field = <T extends HTMLElement>(id: string) => document.getElementById(id) as T | null;
const button = (label: string) =>
  [...document.querySelectorAll("button")].find((b) => (b.textContent || "").trim() === label) as
    | HTMLButtonElement
    | undefined;

function setValue(el: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement, value: string) {
  const proto = Object.getPrototypeOf(el);
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  return act(async () => {
    setter?.call(el, value);
    el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
  });
}

async function submit() {
  await act(async () => {
    button("Schedule")!.click();
  });
}

function sentBody() {
  const [path, init] = vi.mocked(api).mock.calls[0];
  expect(path).toBe("/api/admin/reports/schedules");
  expect(init?.method).toBe("POST");
  return JSON.parse(String(init?.body));
}

describe("ScheduleReportDialog", () => {
  it("schedules a weekly report with the page's filters", async () => {
    await render();
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("Top users by spend");
    expect(document.body.textContent).toContain("Times are the server's clock (Asia/Tehran).");
    await setValue(field<HTMLSelectElement>("report-schedule-weekday")!, "1");
    await setValue(field<HTMLInputElement>("report-schedule-time")!, "08:30");
    await setValue(field<HTMLSelectElement>("report-schedule-period")!, "previous_month");
    await setValue(field<HTMLSelectElement>("report-schedule-format")!, "xlsx");
    await setValue(field<HTMLTextAreaElement>("report-schedule-recipients")!, "a@example.com\nb@example.com, ");
    await submit();

    expect(sentBody()).toEqual({
      report_type: "top_users_by_spend",
      cron_expression: "30 8 * * 1",
      recipients: "a@example.com, b@example.com",
      parameters_json: JSON.stringify({ top_n: 5, department: "Sales" }),
      format: "xlsx",
      period: "previous_month",
    });
    expect(onScheduled).toHaveBeenCalledWith({ id: 7 });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("starts from every Monday at 08:00, the 7 days before, as a PDF", async () => {
    await render(DATED, {});
    await setValue(field<HTMLTextAreaElement>("report-schedule-recipients")!, "a@example.com");
    await submit();
    expect(sentBody()).toMatchObject({
      cron_expression: "0 8 * * 1",
      period: "previous_7_days",
      format: "pdf",
      parameters_json: null,
    });
  });

  it("makes daily, monthly and custom expressions", async () => {
    await render();
    await setValue(field<HTMLTextAreaElement>("report-schedule-recipients")!, "a@example.com");
    const frequency = field<HTMLSelectElement>("report-schedule-frequency")!;

    await setValue(frequency, "daily");
    expect(field("report-schedule-weekday")).toBeNull();
    await setValue(field<HTMLInputElement>("report-schedule-time")!, "06:15");
    await submit();

    await setValue(frequency, "monthly");
    await setValue(field<HTMLSelectElement>("report-schedule-month-day")!, "28");
    await submit();

    await setValue(frequency, "custom");
    expect(field("report-schedule-time")).toBeNull();
    await setValue(field<HTMLInputElement>("report-schedule-cron")!, " 0 7  * * 1-5");
    await submit();

    const crons = vi.mocked(api).mock.calls.map(([, init]) => JSON.parse(String(init?.body)).cron_expression);
    expect(crons).toEqual(["15 6 * * *", "15 6 28 * *", "0 7 * * 1-5"]);
  });

  it("offers no period for a snapshot report", async () => {
    await render(SNAPSHOT, {});
    expect(field("report-schedule-period")).toBeNull();
    expect(document.body.textContent).toContain("A snapshot report");
  });

  it("asks for a recipient, and for no more than twenty", async () => {
    await render();
    await submit();
    expect(document.querySelector('[role="alert"]')?.textContent).toBe("Add at least one recipient.");

    const many = Array.from({ length: 21 }, (_, i) => `p${i}@example.com`).join(", ");
    await setValue(field<HTMLTextAreaElement>("report-schedule-recipients")!, many);
    await submit();
    expect(document.querySelector('[role="alert"]')?.textContent).toBe("At most 20 recipients.");
    expect(api).not.toHaveBeenCalled();
  });

  it("asks for a time, or an expression", async () => {
    await render();
    await setValue(field<HTMLTextAreaElement>("report-schedule-recipients")!, "a@example.com");
    await setValue(field<HTMLInputElement>("report-schedule-time")!, "");
    await submit();
    expect(document.querySelector('[role="alert"]')?.textContent).toBe("Choose a time.");
    await setValue(field<HTMLSelectElement>("report-schedule-frequency")!, "custom");
    await submit();
    expect(document.querySelector('[role="alert"]')?.textContent).toBe("Type a cron expression.");
    expect(api).not.toHaveBeenCalled();
  });

  it("shows what the server refused, and stays open", async () => {
    vi.mocked(api).mockRejectedValue(new Error("Invalid cron_expression: 'x' is not a day of the week"));
    await render();
    await setValue(field<HTMLTextAreaElement>("report-schedule-recipients")!, "a@example.com");
    await submit();
    expect(document.querySelector('[role="alert"]')?.textContent).toContain("Invalid cron_expression");
    expect(onClose).not.toHaveBeenCalled();
    expect(onScheduled).not.toHaveBeenCalled();
  });

  it("cannot schedule for a read-only role", async () => {
    readOnly.value = true;
    await render();
    expect(button("Schedule")!.disabled).toBe(true);
  });

  it("closes on Cancel", async () => {
    await render();
    await act(async () => {
      button("Cancel")!.click();
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
