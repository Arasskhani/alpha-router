/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

import OperationsMetricCard from "./OperationsMetricCard";

async function headline(total: number, unit: string) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => {
    root.render(
      <OperationsMetricCard
        title="Card"
        total={total}
        unit={unit}
        segments={[]}
        chartRows={[]}
      />,
    );
  });
  const text = host.querySelector(".activity-metric-card__total")?.textContent;
  act(() => root.unmount());
  host.remove();
  return text;
}

describe("OperationsMetricCard's headline", () => {
  it("puts a symbol against the number and a word after a space", async () => {
    expect(await headline(16.25, "ms")).toBe("16.3ms");
    expect(await headline(19.3, "%")).toBe("19.3%");
    // It read "0peak turns".
    expect(await headline(0, "peak turns")).toBe("0 peak turns");
  });
});
