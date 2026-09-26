import { describe, expect, it, vi } from "vitest";

import { click, drag, hover, modifiersMask, moveAlong, pathBetween, scrollBy, type Send } from "./input";

function recorder() {
  const calls: Array<{ method: string; params: Record<string, unknown> }> = [];
  const send: Send = vi.fn(async (method, params = {}) => {
    calls.push({ method, params });
    return undefined;
  });
  return { send, calls };
}

const types = (calls: Array<{ method: string; params: Record<string, unknown> }>, method: string) =>
  calls.filter((c) => c.method === method).map((c) => c.params.type);

describe("modifiersMask", () => {
  it("is CDP's bitmask and treats cmd/command as meta", () => {
    expect(modifiersMask([])).toBe(0);
    expect(modifiersMask(["alt"])).toBe(1);
    expect(modifiersMask(["ctrl"])).toBe(2);
    expect(modifiersMask(["shift", "ctrl"])).toBe(10);
    expect(modifiersMask(["cmd"])).toBe(4);
    expect(modifiersMask(["Command"])).toBe(4);
    expect(modifiersMask(["nonsense"])).toBe(0);
  });
});

describe("pathBetween", () => {
  it("includes both endpoints and the requested number of segments", () => {
    const path = pathBetween({ x: 0, y: 0 }, { x: 10, y: 20 }, 2);
    expect(path).toEqual([{ x: 0, y: 0 }, { x: 5, y: 10 }, { x: 10, y: 20 }]);
  });
});

describe("click", () => {
  it("moves, presses and releases at the point", async () => {
    const { send, calls } = recorder();
    await click(send, { x: 40, y: 50 });
    expect(types(calls, "Input.dispatchMouseEvent")).toEqual(["mouseMoved", "mousePressed", "mouseReleased"]);
    const pressed = calls.find((c) => c.params.type === "mousePressed")!.params;
    expect(pressed).toMatchObject({ x: 40, y: 50, button: "left", buttons: 1, clickCount: 1 });
    expect(calls.find((c) => c.params.type === "mouseReleased")!.params.buttons).toBe(0);
  });

  it("carries the button, click count and modifiers", async () => {
    const { send, calls } = recorder();
    await click(send, { x: 1, y: 2 }, { button: "right", clickCount: 2, modifiers: ["shift"] });
    const pressed = calls.find((c) => c.params.type === "mousePressed")!.params;
    expect(pressed).toMatchObject({ button: "right", buttons: 2, clickCount: 2, modifiers: 8 });
  });

  it("moves along an approach path when given one", async () => {
    const { send, calls } = recorder();
    await click(send, { x: 100, y: 0 }, { approach: { x: 0, y: 0 } });
    expect(types(calls, "Input.dispatchMouseEvent").filter((t) => t === "mouseMoved").length).toBeGreaterThan(1);
  });
});

describe("hover and scroll", () => {
  it("hover is a single move with no buttons", async () => {
    const { send, calls } = recorder();
    await hover(send, { x: 5, y: 6 });
    expect(calls).toHaveLength(1);
    expect(calls[0].params).toMatchObject({ type: "mouseMoved", x: 5, y: 6, buttons: 0 });
  });

  it("scroll is a wheel event with the deltas", async () => {
    const { send, calls } = recorder();
    await scrollBy(send, { x: 5, y: 6 }, { y: 300 });
    expect(calls[0].params).toMatchObject({ type: "mouseWheel", deltaX: 0, deltaY: 300 });
  });
});

describe("moveAlong", () => {
  it("emits one move per point", async () => {
    const { send, calls } = recorder();
    await moveAlong(send, [{ x: 0, y: 0 }, { x: 1, y: 1 }, { x: 2, y: 2 }]);
    expect(calls.map((c) => c.params.type)).toEqual(["mouseMoved", "mouseMoved", "mouseMoved"]);
  });
});

describe("drag", () => {
  it("intercepts the native drag and replays it as drag events at the target", async () => {
    const { send, calls } = recorder();
    const data = { items: [{ mimeType: "text/plain", data: "payload" }] };
    let handed = false;
    const take = async () => {
      if (handed) return null;
      handed = true;
      return data;
    };
    const result = await drag(send, { x: 0, y: 0 }, { x: 100, y: 0 }, take);
    expect(result.intercepted).toBe(true);
    // Interception on, then off in the finally.
    const intercept = calls.filter((c) => c.method === "Input.setInterceptDrags").map((c) => c.params.enabled);
    expect(intercept).toEqual([true, false]);
    const dragEvents = calls.filter((c) => c.method === "Input.dispatchDragEvent").map((c) => c.params.type);
    expect(dragEvents).toEqual(["dragEnter", "dragOver", "drop"]);
    for (const c of calls.filter((c) => c.method === "Input.dispatchDragEvent")) expect(c.params.data).toBe(data);
    expect(calls.some((c) => c.params.type === "mouseReleased")).toBe(true);
  });

  it("still presses, moves and releases when no native drag is intercepted", async () => {
    const { send, calls } = recorder();
    const result = await drag(send, { x: 0, y: 0 }, { x: 50, y: 0 }, async () => null);
    expect(result.intercepted).toBe(false);
    expect(calls.some((c) => c.method === "Input.dispatchDragEvent")).toBe(false);
    expect(calls.filter((c) => c.method === "Input.setInterceptDrags").map((c) => c.params.enabled)).toEqual([true, false]);
    expect(calls.some((c) => c.params.type === "mouseReleased")).toBe(true);
  });
});
