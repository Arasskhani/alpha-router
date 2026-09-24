/**
 * @vitest-environment happy-dom
 *
 * The scheduled reports list: what each schedule sends, when it runs next,
 * how its last run went and why not, and Send now, Pause, Resume and Delete.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from "vitest";

vi.mock("../../api", () => ({
  api: vi.fn(),
  formatApiError: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => false }));
vi.mock("../../hooks/useMediaQuery", () => ({
  PHONE_QUERY: "(max-width: 768px)",
  usePhoneLayout: () => false,
  useMediaQuery: () => false,
}));

import { api } from "../../api";
import type { ScheduledReport } from "../../lib/reportSchedules";
import ScheduledReports from "./ScheduledReports";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const PERIODS = [
  { value: "previous_7_days", label: "The 7 days before" },
  { value: "previous_month", label: "The calendar month before" },
];

function schedule(values: Partial<ScheduledReport> = {}): ScheduledReport {
  return {
    id: 1,
    report_type: "org_cost_summary",
    report_title: "Organization cost summary",
    needs_date: true,
    cron_expression: "0 8 * * 1",
    period: "previous_month",
    recipients: "a@example.com,b@example.com",
    parameters: {},
    format: "pdf",
    is_active: true,
    owner: null,
    next_run_at: "2026-09-28T04:30:00Z",
    next_run_local: "2026-09-28 08:00",
    last_run_at: null,
    last_run_local: null,
    last_status: null,
    last_error: null,
    ...values,
  };
}

let host: HTMLDivElement;
let root: Root;
let onReload: Mock<() => Promise<void>>;

beforeEach(() => {
  vi.mocked(api).mockReset();
  onReload = vi.fn<() => Promise<void>>(async () => {});
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  document.body.innerHTML = "";
});

async function render(schedules: ScheduledReport[]) {
  await act(async () => {
    root.render(<ScheduledReports schedules={schedules} periods={PERIODS} timezone="Asia/Tehran" onReload={onReload} />);
  });
}

const rows = () => [...host.querySelectorAll("tbody tr")];
const cells = (row: Element) => [...row.querySelectorAll("td")].map((td) => td.textContent ?? "");

async function act_on(row: Element, label: string) {
  await act(async () => {
    row.querySelector<HTMLButtonElement>(".row-actions-trigger")!.click();
  });
  const item = [...document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find(
    (b) => (b.textContent || "").trim() === label,
  );
  if (!item) throw new Error(`no ${label} action`);
  await act(async () => {
    item.click();
  });
}

describe("ScheduledReports", () => {
  it("says there are none", async () => {
    await render([]);
    expect(host.textContent).toContain("No reports are scheduled.");
    expect(host.textContent).toContain("on the server's clock (Asia/Tehran)");
    expect(host.querySelector("table")).toBeNull();
  });

  it("describes each schedule", async () => {
    await render([
      schedule(),
      schedule({
        id: 2,
        report_title: "Users without budget",
        needs_date: false,
        cron_expression: "*/30 * * * *",
        format: "csv",
        recipients: "owner@example.com",
        parameters: { department: "Sales", top_n: 10 },
        owner: "sara",
        is_active: false,
        last_status: "partial",
        last_run_local: "2026-09-21 08:00",
        last_error: "gone@example.com: refused",
      }),
    ]);
    const [first, second] = rows().map(cells);
    expect(first[0]).toBe("Organization cost summaryThe calendar month before · PDF");
    expect(first[1]).toBe("Every Monday at 08:00Next: 2026-09-28 08:00");
    expect(first[2]).toBe("a@example.com, b@example.com");
    expect(first[3]).toBe("Not run yet");

    expect(second[0]).toBe("Users without budgetSnapshot · CSVDepartment: SalesSet up by sara");
    expect(second[1]).toBe("Cron: */30 * * * *Paused");
    expect(second[3]).toBe("Partly sent2026-09-21 08:00gone@example.com: refused");
    expect(rows()[1].querySelector(".status-badge--partial")).not.toBeNull();
  });

  it("sends now and says how it went", async () => {
    vi.mocked(api).mockResolvedValue({ status: "sent", sent: ["a@example.com", "b@example.com"], not_sent: {}, error: null });
    await render([schedule()]);
    await act_on(rows()[0], "Send now");
    expect(api).toHaveBeenCalledWith("/api/admin/reports/schedules/1/send", { method: "POST" });
    expect(host.querySelector('[role="status"]')?.textContent).toBe("Sent Organization cost summary to 2 recipients.");
    expect(onReload).toHaveBeenCalledTimes(1);
  });

  it("says a report is being sent, and offers no second Send now meanwhile", async () => {
    let finish: (value: unknown) => void = () => {};
    vi.mocked(api).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    await render([schedule()]);
    await act_on(rows()[0], "Send now");
    expect(host.querySelector('[role="status"]')?.textContent).toBe("Sending Organization cost summary…");
    await act(async () => {
      rows()[0].querySelector<HTMLButtonElement>(".row-actions-trigger")!.click();
    });
    const labels = [...document.querySelectorAll('[role="menuitem"]')].map((b) => b.textContent);
    expect(labels).toEqual(["Pause", "Delete"]);
    await act(async () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });

    await act(async () => {
      finish({ status: "sent", sent: ["a@example.com", "b@example.com"], not_sent: {}, error: null });
    });
    expect(host.querySelector('[role="status"]')?.textContent).toBe("Sent Organization cost summary to 2 recipients.");
    expect(api).toHaveBeenCalledTimes(1);
    await act_on(rows()[0], "Send now");
    expect(api).toHaveBeenCalledTimes(2);
  });

  it("says who a partly sent report did not reach", async () => {
    vi.mocked(api).mockResolvedValue({
      status: "partial",
      sent: ["a@example.com"],
      not_sent: { "b@example.com": "refused" },
      error: "b@example.com: refused",
    });
    await render([schedule()]);
    await act_on(rows()[0], "Send now");
    expect(host.querySelector('[role="alert"]')?.textContent).toBe(
      "Sent Organization cost summary to 1 of 2 recipients. b@example.com: refused",
    );
  });

  it("says why a report was not sent", async () => {
    vi.mocked(api).mockResolvedValue({
      status: "failed",
      sent: [],
      not_sent: { "a@example.com": "SMTP is not configured." },
      error: "SMTP is not configured. Not sent to a@example.com.",
    });
    await render([schedule()]);
    await act_on(rows()[0], "Send now");
    expect(host.querySelector('[role="alert"]')?.textContent).toBe(
      "Organization cost summary was not sent. SMTP is not configured. Not sent to a@example.com.",
    );
  });

  it("pauses and resumes", async () => {
    vi.mocked(api).mockResolvedValue({ ok: true });
    await render([schedule(), schedule({ id: 2, is_active: false })]);
    await act_on(rows()[0], "Pause");
    await act_on(rows()[1], "Resume");
    expect(vi.mocked(api).mock.calls).toEqual([
      ["/api/admin/reports/schedules/1", { method: "PATCH", body: JSON.stringify({ is_active: false }) }],
      ["/api/admin/reports/schedules/2", { method: "PATCH", body: JSON.stringify({ is_active: true }) }],
    ]);
    expect(onReload).toHaveBeenCalledTimes(2);
  });

  it("shows a refused change", async () => {
    vi.mocked(api).mockRejectedValue(new Error("This schedule cannot run: never"));
    await render([schedule({ is_active: false })]);
    await act_on(rows()[0], "Resume");
    expect(host.querySelector('[role="alert"]')?.textContent).toBe("This schedule cannot run: never");
  });

  it("deletes only once confirmed", async () => {
    vi.mocked(api).mockResolvedValue({ ok: true });
    await render([schedule()]);
    await act_on(rows()[0], "Delete");
    const dialog = document.querySelector('[role="alertdialog"]')!;
    expect(dialog.textContent).toContain(
      "Organization cost summary will no longer be emailed to a@example.com, b@example.com.",
    );
    const keep = [...dialog.querySelectorAll("button")].find((b) => b.textContent === "Keep")!;
    await act(async () => keep.click());
    expect(api).not.toHaveBeenCalled();

    await act_on(rows()[0], "Delete");
    const confirm = [...document.querySelectorAll('[role="alertdialog"] button')].find(
      (b) => b.textContent === "Delete",
    ) as HTMLButtonElement;
    await act(async () => confirm.click());
    expect(api).toHaveBeenCalledWith("/api/admin/reports/schedules/1", { method: "DELETE" });
    expect(onReload).toHaveBeenCalledTimes(1);
  });
});
