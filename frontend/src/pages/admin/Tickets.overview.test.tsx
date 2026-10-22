/**
 * @vitest-environment happy-dom
 *
 * Admin › Tickets: the tabs follow the address, and the Overview reads its
 * numbers, colours the KPI cards by better or worse, and keeps its filters in
 * the address and in the request.
 */
import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", () => ({ authFetch: vi.fn(), api: vi.fn(), formatApiError: (e: unknown) => String(e) }));
vi.mock("../../context/ConfirmContext", () => ({
  useConfirm: () => ({ confirm: async () => true, prompt: async () => null }),
}));
const readOnly = vi.hoisted(() => ({ value: false }));
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => readOnly.value }));

import { authFetch } from "../../api";
import { fakeTicketsApi, OVERVIEW, type Call } from "../../components/tickets/testFixtures";
import Tickets from "./Tickets";

let host: HTMLDivElement;
let root: Root;
let calls: Call[];
const where = { path: "" };

function Probe() {
  const loc = useLocation();
  useEffect(() => {
    where.path = `${loc.pathname}${loc.search}`;
  }, [loc]);
  return null;
}

beforeEach(() => {
  readOnly.value = false;
  calls = [];
  vi.mocked(authFetch).mockReset();
  vi.mocked(authFetch).mockImplementation(fakeTicketsApi(calls) as typeof authFetch);
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function render(path: string) {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[path]}>
        <Probe />
        <Routes>
          <Route path="/admin/tickets" element={<Tickets />} />
          <Route path="/admin/tickets/list" element={<Tickets />} />
          <Route path="/admin/tickets/settings" element={<Tickets />} />
        </Routes>
      </MemoryRouter>,
    );
  });
  await act(async () => undefined);
  await act(async () => undefined);
}

const tab = (name: string) => [...host.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((b) => b.textContent === name)!;
const card = (title: string) =>
  [...host.querySelectorAll<HTMLElement>(".overview-kpi-card")].find((c) => c.querySelector(".overview-kpi-card__title")?.textContent === title)!;

describe("the Tickets tabs", () => {
  it("opens on the Overview and follows the address", async () => {
    await render("/admin/tickets");
    expect(tab("Overview").getAttribute("aria-selected")).toBe("true");
    await act(async () => tab("Tickets").click());
    expect(where.path).toBe("/admin/tickets/list");
    expect(tab("Tickets").getAttribute("aria-selected")).toBe("true");
    await act(async () => tab("Settings").click());
    expect(where.path).toBe("/admin/tickets/settings");
  });
});

describe("the Overview", () => {
  it("shows the numbers, coloured by better or worse rather than up or down", async () => {
    await render("/admin/tickets");
    expect(host.querySelector(".activity-subtitle")!.textContent).toBe(
      "Ticket flow and support workload · Past 1 Week · Local time",
    );
    expect(card("Tickets opened").dataset.tone).toBe("flat");
    expect(card("Resolved").dataset.tone).toBe("good");
    expect(card("Open now").dataset.tone).toBe("good");
    expect(card("Open now").textContent).toContain("↓ 11.1%");
    expect(card("Open now").textContent).toContain("5 wait for a first answer");
    expect(card("Median first reply").dataset.tone).toBe("good");
    expect(card("Median first reply").textContent).toContain("1h 20m");
    expect(card("Median resolution").dataset.tone).toBe("bad");
    expect(card("Median resolution").textContent).toContain("21 h");
    expect(card("Auto-closed").dataset.tone).toBe("flat");
    expect(card("Auto-closed").textContent).toContain("15% of closed tickets");
  });

  it("lists departments, workload with Unassigned last, and first replies", async () => {
    await render("/admin/tickets");
    const lists = [...host.querySelectorAll(".overview-top-list")];
    expect(lists.map((l) => l.querySelector("h3")!.textContent)).toEqual([
      "Top departments",
      "Workload by assignee",
      "First reply by priority",
    ]);
    expect(lists[0].textContent).toContain("6 still open · 1 Urgent");
    const workload = [...lists[1].querySelectorAll("li")];
    expect(workload.at(-1)!.className).toContain("tickets-ov-unassigned");
    expect(workload.at(-1)!.textContent).toContain("oldest waits 3 h 10 min");
    expect(lists[2].textContent).toContain("18 min");
    expect(host.textContent).toContain("Flow and backlog");
    expect(host.textContent).toContain("3 (7%)");
    expect(host.textContent).toContain("Bug · 38%");
  });

  it("sends a filter and the period with the request and keeps them in the address", async () => {
    await render("/admin/tickets");
    await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="Filters"]')!.click());
    const department = [...host.querySelectorAll<HTMLButtonElement>(".activity-filter-primary__item")].find(
      (b) => b.textContent === "Department",
    )!;
    await act(async () => department.click());
    const finance = [...host.querySelectorAll<HTMLButtonElement>(".activity-filter-flyout__item")].find(
      (b) => b.textContent?.includes("Finance"),
    )!;
    await act(async () => finance.click());
    await act(async () => undefined);
    expect(where.path).toContain("department=Finance");
    const last = calls.filter((c) => c.url.includes("/overview?")).at(-1)!;
    expect(last.url).toContain("department=Finance");
    expect(last.url).toContain("period=week");
    expect(last.url).toContain("timezone=local");
    expect(host.querySelector(".activity-subtitle")!.textContent).toContain("Department: Finance");
  });

  it("opens the queue with the same filter from Explore", async () => {
    await render("/admin/tickets?department=IT&period=month");
    expect(calls.find((c) => c.url.includes("/overview?"))!.url).toContain("period=month");
    const explore = host.querySelectorAll<HTMLButtonElement>(".overview-explore-link")[1];
    await act(async () => explore.click());
    expect(where.path).toBe("/admin/tickets/list?view=active&department=IT");
  });

  it("opens the queue in a view that can hold a Resolved or Closed status", async () => {
    await render("/admin/tickets?status=resolved");
    // Workload's Explore asks for the active view: Resolved tickets are never in it.
    const explore = host.querySelectorAll<HTMLButtonElement>(".overview-explore-link")[1];
    await act(async () => explore.click());
    expect(where.path).toBe("/admin/tickets/list?view=all&status=resolved");
  });

  it("keeps the active view for an active status", async () => {
    await render("/admin/tickets?status=waiting");
    const explore = host.querySelectorAll<HTMLButtonElement>(".overview-explore-link")[1];
    await act(async () => explore.click());
    expect(where.path).toBe("/admin/tickets/list?view=active&status=waiting");
  });

  it("links to the tickets that need staff, and says nothing when none do", async () => {
    await render("/admin/tickets");
    const link = host.querySelector<HTMLAnchorElement>('[data-testid="tickets-needs-staff"]')!;
    expect(link.textContent).toBe("5 need staff — open the queue");
    expect(link.getAttribute("href")).toBe("/admin/tickets/list?view=needs_staff");

    act(() => root.unmount());
    root = createRoot(host);
    vi.mocked(authFetch).mockImplementation(
      fakeTicketsApi(calls, (url) =>
        url.endsWith("/counts") ? { needs_staff: 0, needs_staff_urgent: 0, mine: 0, unassigned: 0, active: 3, closed: 9 } : undefined,
      ) as typeof authFetch,
    );
    await render("/admin/tickets");
    expect(host.querySelector('[data-testid="tickets-needs-staff"]')).toBeNull();
  });

  it("closes the filter and export menus with Escape and gives the focus back", async () => {
    await render("/admin/tickets");
    const filters = host.querySelector<HTMLButtonElement>('[aria-label="Filters"]')!;
    await act(async () => filters.click());
    expect(host.querySelector('[aria-label="Ticket filters"]')).not.toBeNull();
    host.querySelector<HTMLInputElement>('[aria-label="Search filter categories"]')!.focus();
    await act(async () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(host.querySelector('[aria-label="Ticket filters"]')).toBeNull();
    expect(document.activeElement).toBe(filters);

    const exportBtn = host.querySelector<HTMLButtonElement>('[aria-label="Export"]')!;
    await act(async () => exportBtn.click());
    expect(host.querySelector(".activity-menu-panel")).not.toBeNull();
    await act(async () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(host.querySelector(".activity-menu-panel")).toBeNull();
  });

  it("says so when the period has no tickets", async () => {
    const empty = {
      ...OVERVIEW,
      kpis: {
        ...OVERVIEW.kpis,
        opened: { value: 0, change_pct: null, sparkline: [] },
        resolved: { value: 0, change_pct: null, sparkline: [] },
        open_now: { value: 0, change_pct: null, sparkline: [], unanswered: 0 },
      },
      ended: { ...OVERVIEW.ended, total: 0 },
    };
    vi.mocked(authFetch).mockImplementation(
      fakeTicketsApi(calls, (url) => (url.includes("/overview?") ? empty : undefined)) as typeof authFetch,
    );
    await render("/admin/tickets");
    expect(host.textContent).toContain("No tickets in this period");
    expect(host.textContent).not.toContain("Flow and backlog");
  });
});
