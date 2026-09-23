/**
 * @vitest-environment happy-dom
 */
import { describe, expect, it } from "vitest";

import { scrollIntoStrip } from "./scrollIntoStrip";

function box(left: number, right: number): HTMLElement {
  const el = document.createElement("div");
  el.getBoundingClientRect = () => ({ left, right, top: 0, bottom: 10, width: right - left, height: 10, x: left, y: 0, toJSON: () => ({}) });
  return el;
}

describe("scrollIntoStrip", () => {
  it("leaves the strip alone when the item is in view", () => {
    const strip = box(0, 300);
    strip.scrollLeft = 40;
    scrollIntoStrip(strip, box(50, 120));
    expect(strip.scrollLeft).toBe(40);
  });

  it("scrolls forward by the part that sticks out on the right", () => {
    const strip = box(0, 300);
    strip.scrollLeft = 0;
    scrollIntoStrip(strip, box(260, 340));
    expect(strip.scrollLeft).toBe(40);
  });

  it("scrolls back by the part that sticks out on the left", () => {
    const strip = box(0, 300);
    strip.scrollLeft = 100;
    scrollIntoStrip(strip, box(-30, 50));
    expect(strip.scrollLeft).toBe(70);
  });

  it("does nothing without a strip or an item", () => {
    expect(() => scrollIntoStrip(null, box(0, 1))).not.toThrow();
    expect(() => scrollIntoStrip(box(0, 1), undefined)).not.toThrow();
  });
});
