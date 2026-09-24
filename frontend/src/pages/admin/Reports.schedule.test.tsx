/**
 * @vitest-environment happy-dom
 *
 * The Reports page emails a report on a schedule: the report and filters on
 * the page go into the schedule (its dates do not: the schedule's period
 * decides them), and the scheduled reports are listed under the catalog.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const readOnly = vi.hoisted(() => ({ value: false }));

vi.mock("../../api", () => ({
  api: vi.fn(),
  authFetch: vi.fn(),
  formatApiError: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => readOnly.value }));
vi.mock("../../hooks/useMediaQuery", () => ({
  PHONE_QUERY: "(max-width: 768px)",
  usePhoneLayout: () => false,
  useMediaQuery: () => false,
}));

import { api } from "../../api";
import Reports from "./Reports";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const CATALOG = {
  categories: { budget: "Budget & cost" },
  reports: [
    {
      id: "top_users_by_spend",
      category: "budget",
      title: "Top users by spend",
      description: "Who spent the most.",
      needs_date: true,
      params: ["top_n"],
    },
  ],
  default_dates: { start_date: "2026-08-25", end_date: "2026-09-24" },
  schedule_periods: [
    { value: "previous_7_days", label: "The 7 days before" },
    { value: "previous_month", label: "The calendar month before" },
  ],
  schedule_timezone: "Asia/Tehran",
};

const OPTIONS = {
  plans: [],
  groups: [],
  departments: [],
  offices: [],
  apps: [],
  providers: [],
  models: [],
  alpha_router_api_keys: [],
  agents: [],
  projects: [],
  auth_providers: [],
  group_by_options: [],
};

const SAVED = {
  id: 4,
  report_type: "top_users_by_spend",
  report_title: "Top users by spend",
  needs_date: true,
  cron_expression: "0 8 * * 1",
  period: "previous_7_days",
  recipients: "cfo@example.com",
  parameters: { top_n: 5 },
  format: "pdf",
  is_active: true,
  owner: null,
  next_run_at: "2026-09-28T04:30:00Z",
  next_run_local: "2026-09-28 08:00",
  last_run_at: null,
  last_run_local: null,
  last_status: null,
  last_error: null,
};

let host: HTMLDivElement;
let root: Root;
let listed: unknown[];

beforeEach(() => {
  readOnly.value = false;
  listed = [];
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === "/api/admin/reports/catalog") return CATALOG;
    if (path === "/api/admin/reports/options") return OPTIONS;
    if (path === "/api/admin/reports/schedules" && !init?.method) return listed;
    if (path === "/api/admin/reports/schedules" && init?.method === "POST") {
      listed = [SAVED];
      return { ok: true, schedule: SAVED };
    }
    throw new Error(`unexpected ${init?.method ?? "GET"} ${path}`);
  });
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

async function render() {
  await act(async () => {
    root.render(<Reports />);
  });
}

const button = (label: string) =>
  [...document.querySelectorAll("button")].find((b) => (b.textContent || "").trim() === label) as
    | HTMLButtonElement
    | undefined;

function setValue(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), "value")?.set;
  return act(async () => {
    setter?.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function chooseReport() {
  await act(async () => {
    [...host.querySelectorAll<HTMLButtonElement>(".reports-catalog__item")][0].click();
  });
}

describe("scheduling from the Reports page", () => {
  it("schedules the chosen report with its filters and lists it", async () => {
    await render();
    expect(host.textContent).toContain("No reports are scheduled.");
    await chooseReport();
    await setValue(document.getElementById("reports-top-n") as HTMLInputElement, "5");
    await act(async () => button("Schedule by email…")!.click());

    const dialog = document.querySelector('[role="dialog"]')!;
    expect(dialog.textContent).toContain("Top users by spend");
    await setValue(document.getElementById("report-schedule-recipients") as HTMLTextAreaElement, "cfo@example.com");
    await act(async () => button("Schedule")!.click());

    const post = vi.mocked(api).mock.calls.find(([, init]) => init?.method === "POST")!;
    const body = JSON.parse(String(post[1]?.body));
    expect(body.report_type).toBe("top_users_by_spend");
    const parameters = JSON.parse(body.parameters_json);
    expect(parameters.top_n).toBe(5);
    expect(parameters).not.toHaveProperty("start_date");
    expect(parameters).not.toHaveProperty("end_date");
    expect(parameters).not.toHaveProperty("format");

    expect(document.querySelector('[role="dialog"]')).toBeNull();
    const row = host.querySelector(".reports-schedules tbody tr");
    expect(row?.textContent).toContain("Every Monday at 08:00");
    expect(row?.textContent).toContain("Next: 2026-09-28 08:00");
  });

  it("offers no scheduling to a read-only role", async () => {
    readOnly.value = true;
    await render();
    await chooseReport();
    expect(button("Schedule by email…")!.disabled).toBe(true);
  });
});
