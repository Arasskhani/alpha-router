/**
 * @vitest-environment happy-dom
 *
 * On a phone the heatmap's weeks scroll sideways (styles.css); the chart
 * starts at the latest week.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import ActivityHeatmap from "./ActivityHeatmap";
import type { ActivityInsights } from "./types";

const stats = { streak_days: 0, avg_day: 0, avg_week: 0, total: 0 };
const insights = {
  streak_days: 0,
  change_pct: { prompts: null, tokens: null, spend: null },
  period_footer_label: "",
  period_prompts: 0,
  heatmap: {
    days: ["2026-09-01", "2026-09-02"].map((date) => ({
      date,
      requests: 1,
      tokens: 1,
      spend: 0,
      level_requests: 1,
      level_tokens: 1,
      level_spend: 0,
    })),
  },
  usage_stats: { requests: stats, tokens: stats, spend: stats },
} as unknown as ActivityInsights;

const scrollWidth = Object.getOwnPropertyDescriptor(
  Element.prototype,
  "scrollWidth",
);

afterEach(() => {
  if (scrollWidth)
    Object.defineProperty(Element.prototype, "scrollWidth", scrollWidth);
});

describe("ActivityHeatmap", () => {
  it("scrolls its weeks to the latest one", async () => {
    Object.defineProperty(Element.prototype, "scrollWidth", {
      configurable: true,
      get: () => 742,
    });
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => {
      root.render(
        <ActivityHeatmap
          insights={insights}
          metric="requests"
          timezone="utc"
          onMetricChange={() => {}}
        />,
      );
    });
    expect(
      host.querySelector<HTMLElement>(".activity-heatmap__chart-row")
        ?.scrollLeft,
    ).toBe(742);
    act(() => root.unmount());
    host.remove();
  });
});
