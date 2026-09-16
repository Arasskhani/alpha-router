/**
 * @vitest-environment happy-dom
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { attachDragScroll } from "./dragScroll";

let el: HTMLElement;
let detach: () => void;

/** happy-dom has no layout, so the scrollable geometry is declared. */
function makeScrollable(scrollWidth = 1000, clientWidth = 400) {
  Object.defineProperty(el, "scrollWidth", { value: scrollWidth, configurable: true });
  Object.defineProperty(el, "clientWidth", { value: clientWidth, configurable: true });
}

function pointer(type: string, x: number, y = 0, init: Partial<PointerEvent> = {}) {
  const e = new Event(type, { bubbles: true, cancelable: true }) as PointerEvent;
  Object.assign(e, { pointerId: 1, pointerType: "mouse", button: 0, clientX: x, clientY: y, ...init });
  return e;
}

beforeEach(() => {
  el = document.createElement("div");
  el.scrollLeft = 0;
  el.setPointerCapture = vi.fn();
  el.releasePointerCapture = vi.fn();
  document.body.appendChild(el);
  makeScrollable();
  detach = attachDragScroll(el);
});

afterEach(() => {
  detach();
  el.remove();
});

function drag(from: number, to: number, y = 0) {
  el.dispatchEvent(pointer("pointerdown", from, y));
  el.dispatchEvent(pointer("pointermove", to, y));
  el.dispatchEvent(pointer("pointerup", to, y));
}

describe("attachDragScroll", () => {
  it("pulls the container the other way, like grabbing the page", () => {
    el.dispatchEvent(pointer("pointerdown", 300));
    el.dispatchEvent(pointer("pointermove", 200));
    expect(el.scrollLeft).toBe(100);
  });

  it("ignores a movement too small to be deliberate", () => {
    el.dispatchEvent(pointer("pointerdown", 300));
    el.dispatchEvent(pointer("pointermove", 297));
    expect(el.scrollLeft).toBe(0);
  });

  it("leaves a mostly-vertical drag alone, so text stays selectable", () => {
    el.dispatchEvent(pointer("pointerdown", 300, 100));
    el.dispatchEvent(pointer("pointermove", 292, 160));
    expect(el.scrollLeft).toBe(0);
  });

  it("does nothing when there is nothing to scroll", () => {
    makeScrollable(400, 400);
    el.dispatchEvent(pointer("pointerdown", 300));
    el.dispatchEvent(pointer("pointermove", 200));
    expect(el.scrollLeft).toBe(0);
  });

  it("does not start from a control inside the table", () => {
    const btn = document.createElement("button");
    el.appendChild(btn);
    const down = pointer("pointerdown", 300);
    Object.defineProperty(down, "target", { value: btn });
    el.dispatchEvent(down);
    el.dispatchEvent(pointer("pointermove", 200));
    expect(el.scrollLeft).toBe(0);
  });

  it("ignores touch, which pans natively already", () => {
    el.dispatchEvent(pointer("pointerdown", 300, 0, { pointerType: "touch" }));
    el.dispatchEvent(pointer("pointermove", 200, 0, { pointerType: "touch" }));
    expect(el.scrollLeft).toBe(0);
  });

  it("swallows the click a real drag produces, so no row opens", () => {
    const onClick = vi.fn();
    const row = document.createElement("div");
    row.addEventListener("click", onClick);
    el.appendChild(row);

    drag(300, 200);
    row.dispatchEvent(new Event("click", { bubbles: true, cancelable: true }));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("swallows only that one click", () => {
    const onClick = vi.fn();
    const row = document.createElement("div");
    row.addEventListener("click", onClick);
    el.appendChild(row);

    drag(300, 200);
    row.dispatchEvent(new Event("click", { bubbles: true, cancelable: true }));
    row.dispatchEvent(new Event("click", { bubbles: true, cancelable: true }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("a press without a drag still opens the row", () => {
    const onClick = vi.fn();
    const row = document.createElement("div");
    row.addEventListener("click", onClick);
    el.appendChild(row);

    drag(300, 300);
    row.dispatchEvent(new Event("click", { bubbles: true, cancelable: true }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("marks the container while dragging, and clears it afterwards", () => {
    el.dispatchEvent(pointer("pointerdown", 300));
    el.dispatchEvent(pointer("pointermove", 200));
    expect(el.classList.contains("is-drag-scrolling")).toBe(true);
    el.dispatchEvent(pointer("pointerup", 200));
    expect(el.classList.contains("is-drag-scrolling")).toBe(false);
  });

  it("a cancelled pointer does not leave the container stuck", () => {
    el.dispatchEvent(pointer("pointerdown", 300));
    el.dispatchEvent(pointer("pointermove", 200));
    el.dispatchEvent(pointer("pointercancel", 200));
    expect(el.classList.contains("is-drag-scrolling")).toBe(false);
  });

  it("stops listening once detached", () => {
    detach();
    el.dispatchEvent(pointer("pointerdown", 300));
    el.dispatchEvent(pointer("pointermove", 200));
    expect(el.scrollLeft).toBe(0);
  });
});
