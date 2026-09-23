/**
 * The usage heatmap's week columns and their month labels.
 */
import { describe, expect, it } from "vitest";

import { heatmapWeeks } from "./ActivityHeatmap";
import type { HeatmapDay } from "./types";

function year(from: string, to: string): HeatmapDay[] {
  const days: HeatmapDay[] = [];
  for (
    let d = new Date(`${from}T12:00:00Z`);
    d <= new Date(`${to}T12:00:00Z`);
    d.setUTCDate(d.getUTCDate() + 1)
  ) {
    days.push({
      date: d.toISOString().slice(0, 10),
      requests: 0,
      tokens: 0,
      spend: 0,
      level_requests: 0,
      level_tokens: 0,
      level_spend: 0,
    });
  }
  return days;
}

describe("heatmapWeeks", () => {
  it("never labels two weeks in a row, which drew the labels over each other", () => {
    // Starts on a Wednesday late in September: that week holds 4 September days,
    // and October begins in the very next week.
    const weeks = heatmapWeeks(year("2025-09-24", "2026-09-23"), "utc");
    const labelled = weeks
      .map((w, i) => (w.month ? i : -1))
      .filter((i) => i >= 0);
    for (let n = 1; n < labelled.length; n += 1) {
      expect(
        labelled[n] - labelled[n - 1],
        `${weeks[labelled[n - 1]].month} → ${weeks[labelled[n]].month}`,
      ).toBeGreaterThanOrEqual(2);
    }
    // The lone September week goes unlabelled; October onwards keep theirs.
    expect(weeks[0].month).toBeUndefined();
    expect(
      weeks
        .map((w) => w.month)
        .filter(Boolean)
        .slice(0, 3),
    ).toEqual(["Oct", "Nov", "Dec"]);
  });

  it("keeps every column: one per week, Sunday first", () => {
    const weeks = heatmapWeeks(year("2025-09-24", "2026-09-23"), "utc");
    expect(weeks.every((w) => w.cells.length === 7)).toBe(true);
    expect(weeks[0].cells.slice(0, 3)).toEqual([null, null, null]);
    expect(weeks[0].cells[3]?.date).toBe("2025-09-24");
  });
});
