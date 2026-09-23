/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const layout = vi.hoisted(() => ({ phone: false }));
vi.mock("../hooks/useMediaQuery", () => ({
  PHONE_QUERY: "(max-width: 768px)",
  usePhoneLayout: () => layout.phone,
  useMediaQuery: () => false,
}));

import FilterPanel, { countActiveFilters } from "./FilterPanel";

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  layout.phone = false;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const render = (activeCount: number) =>
  act(async () => {
    root.render(
      <FilterPanel activeCount={activeCount}>
        <div className="filters">
          <input aria-label="User" defaultValue="" />
        </div>
      </FilterPanel>,
    );
  });
const toggle = () => host.querySelector<HTMLButtonElement>(".filter-panel-toggle");
const panel = () => host.querySelector<HTMLElement>(".filter-panel");

describe("FilterPanel", () => {
  it("shows the filters and no button on a desktop", async () => {
    await render(2);
    expect(toggle()).toBeNull();
    // The wrapper is there (display: contents in styles.css), never hidden.
    expect(panel()?.hidden).toBe(false);
    expect(panel()?.firstElementChild?.className).toBe("filters");
  });

  it("keeps the same fields, and what was typed, when the width crosses the breakpoint", async () => {
    await render(0);
    const input = host.querySelector<HTMLInputElement>('[aria-label="User"]')!;
    input.value = "sara";
    layout.phone = true;
    await render(0);
    expect(toggle()).not.toBeNull();
    expect(host.querySelector('[aria-label="User"]')).toBe(input);
    layout.phone = false;
    await render(0);
    expect(toggle()).toBeNull();
    expect(host.querySelector('[aria-label="User"]')).toBe(input);
    expect(input.value).toBe("sara");
  });

  it("folds the filters behind a button on a phone, and keeps them mounted", async () => {
    layout.phone = true;
    await render(0);
    expect(toggle()?.getAttribute("aria-expanded")).toBe("false");
    expect(toggle()?.getAttribute("aria-controls")).toBe(panel()?.id);
    expect(toggle()?.textContent).toBe("Filters");
    expect(panel()?.hidden).toBe(true);
    // Still in the page: a typed value survives folding.
    const input = host.querySelector<HTMLInputElement>('[aria-label="User"]')!;
    input.value = "sara";
    await act(async () => toggle()!.click());
    expect(panel()?.hidden).toBe(false);
    expect(toggle()?.getAttribute("aria-expanded")).toBe("true");
    expect(toggle()?.textContent).toBe("Hide filters");
    await act(async () => toggle()!.click());
    expect(panel()?.hidden).toBe(true);
    expect(host.querySelector<HTMLInputElement>('[aria-label="User"]')?.value).toBe("sara");
  });

  it("opens by itself and shows the count when filters are set", async () => {
    layout.phone = true;
    await render(3);
    expect(panel()?.hidden).toBe(false);
    const count = host.querySelector(".filter-panel-toggle__count");
    expect(count?.textContent).toBe("3");
    expect(count?.getAttribute("aria-label")).toBe("3 active");
  });

  it("counts filters that have a value", () => {
    expect(countActiveFilters(["", "  ", null, undefined, "a", " b ", false, true])).toBe(3);
  });
});
