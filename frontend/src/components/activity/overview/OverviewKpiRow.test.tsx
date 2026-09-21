/**
 * @vitest-environment happy-dom
 *
 * The Memory card is the only one on this row for money the person did not
 * ask to spend, and the only one whose figure does not move their budget bar.
 * Without the note under it, the row says "you spent this" about something
 * nothing else on the page will confirm.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("recharts", () => ({
  Line: () => null,
  LineChart: ({ children }: { children?: unknown }) => <div>{children as never}</div>,
  ResponsiveContainer: ({ children }: { children?: unknown }) => <div>{children as never}</div>,
  YAxis: () => null,
}));

import type { OverviewKpi } from "../types";
import OverviewKpiRow from "./OverviewKpiRow";

const kpi = (value: number): OverviewKpi => ({ value, change_pct: 4.2, sparkline: [1, 2, 3] });

const KPIS = {
  spend: kpi(18.42),
  requests: kpi(1204),
  tokens: kpi(3_800_000),
  cache_hit_rate: kpi(41.2),
  blended_per_1m: kpi(4.85),
  memory_spend: kpi(0.42),
};

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

function render(kpis = KPIS) {
  act(() => root.render(<OverviewKpiRow kpis={kpis} />));
}

function cards() {
  return [...host.querySelectorAll(".overview-kpi-card")];
}

describe("the activity KPI row", () => {
  it("gives memory a card beside the others, not a style of its own", () => {
    render();
    const titles = cards().map((c) => c.querySelector(".overview-kpi-card__title")?.textContent);
    expect(titles).toEqual(["Total spend", "Requests", "Token volume", "Cache hit rate", "Blended $/1M", "Memory"]);
    const memory = cards().at(-1);
    expect(memory?.className).toBe(cards()[0].className);
  });

  it("says the memory figure is not charged, and says it only there", () => {
    render();
    const notes = cards().map((c) => c.querySelector(".overview-kpi-card__note")?.textContent ?? null);
    expect(notes).toEqual([null, null, null, null, null, "Not charged to your plan"]);
  });

  it("formats it as money", () => {
    render();
    expect(cards().at(-1)?.querySelector(".overview-kpi-card__value")?.textContent).toBe("$0.42");
  });

  it("still renders when memory never ran", () => {
    render({ ...KPIS, memory_spend: { value: 0, change_pct: null, sparkline: [] } });
    const memory = cards().at(-1);
    expect(memory?.querySelector(".overview-kpi-card__value")?.textContent).toBe("$0.00");
    expect(memory?.querySelector(".overview-kpi-card__change")?.textContent).toContain("—");
  });
});
