/**
 * Mouse gestures as CDP `Input.*` command sequences.
 *
 * Each gesture takes a `send(method, params)` - the debugger session's own
 * command sender - so the sequences are testable without a browser, and the
 * shapes are the ones the Phase 0 spike proved in Chromium: a move, then a
 * press and release for a click; a wheel event for a scroll; and, for a native
 * HTML5 drag, `Input.setInterceptDrags` plus the data from the intercepted
 * drag replayed as `Input.dispatchDragEvent` at the target.
 */

import type { Point } from "./coords";

export type Send = (method: string, params?: Record<string, unknown>) => Promise<unknown>;
export type MouseButton = "left" | "right" | "middle";

/** CDP's modifier bitmask: Alt 1, Ctrl 2, Meta 4, Shift 8. cmd/command are meta. */
const MODIFIER_BITS: Record<string, number> = {
  alt: 1,
  ctrl: 2,
  control: 2,
  meta: 4,
  cmd: 4,
  command: 4,
  shift: 8,
};

export function modifiersMask(modifiers: readonly string[] = []): number {
  let mask = 0;
  for (const raw of modifiers) mask |= MODIFIER_BITS[raw.trim().toLowerCase()] ?? 0;
  return mask;
}

function buttonsBit(button: MouseButton): number {
  return button === "right" ? 2 : button === "middle" ? 4 : 1;
}

/** Points along a straight path from `from` to `to`, `steps` segments, endpoints included. */
export function pathBetween(from: Point, to: Point, steps = 10): Point[] {
  const n = Math.max(1, Math.round(steps));
  const out: Point[] = [];
  for (let i = 0; i <= n; i++) out.push({ x: from.x + ((to.x - from.x) * i) / n, y: from.y + ((to.y - from.y) * i) / n });
  return out;
}

/** Move the pointer along a path, so real hover states fire as they would for a person. */
export async function moveAlong(send: Send, path: Point[], modifiers: readonly string[] = []): Promise<void> {
  const mask = modifiersMask(modifiers);
  for (const p of path) await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: p.x, y: p.y, buttons: 0, modifiers: mask });
}

export async function hover(send: Send, point: Point, modifiers: readonly string[] = []): Promise<void> {
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: point.x, y: point.y, buttons: 0, modifiers: modifiersMask(modifiers) });
}

export async function click(
  send: Send,
  point: Point,
  options: { button?: MouseButton; clickCount?: number; modifiers?: readonly string[]; approach?: Point } = {},
): Promise<void> {
  const button = options.button ?? "left";
  const clickCount = options.clickCount ?? 1;
  const mask = modifiersMask(options.modifiers);
  if (options.approach) await moveAlong(send, pathBetween(options.approach, point), options.modifiers);
  else await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: point.x, y: point.y, buttons: 0, modifiers: mask });
  const buttons = buttonsBit(button);
  const base = { x: point.x, y: point.y, button, buttons, clickCount, modifiers: mask };
  await send("Input.dispatchMouseEvent", { type: "mousePressed", ...base });
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", ...base, buttons: 0 });
}

export async function scrollBy(
  send: Send,
  point: Point,
  delta: { x?: number; y?: number },
  modifiers: readonly string[] = [],
): Promise<void> {
  await send("Input.dispatchMouseEvent", {
    type: "mouseWheel",
    x: point.x,
    y: point.y,
    deltaX: delta.x ?? 0,
    deltaY: delta.y ?? 0,
    modifiers: modifiersMask(modifiers),
  });
}

export type DragData = Record<string, unknown>;

/**
 * A native HTML5 drag from `from` to `to`.
 *
 * Chrome starts a native drag when the pointer moves past a threshold while a
 * button is held; with interception on it hands the drag data to the debugger
 * instead of the OS. `takeDragData` returns that captured data (the session
 * buffers the `Input.dragIntercepted` event). With the data in hand we play the
 * drag out as dragEnter/dragOver/drop at the target. Returns whether a drag was
 * actually intercepted; a page that used pointer-based dragging (no native drag)
 * still got the moves and the release, so it works either way.
 */
export async function drag(
  send: Send,
  from: Point,
  to: Point,
  takeDragData: () => Promise<DragData | null>,
): Promise<{ intercepted: boolean }> {
  await send("Input.setInterceptDrags", { enabled: true });
  try {
    await send("Input.dispatchMouseEvent", { type: "mousePressed", x: from.x, y: from.y, button: "left", buttons: 1, clickCount: 1 });
    let data: DragData | null = null;
    const path = pathBetween(from, to, 8);
    for (const p of path.slice(1)) {
      await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: p.x, y: p.y, button: "left", buttons: 1 });
      data = await takeDragData();
      if (data) break;
    }
    if (data) {
      for (const type of ["dragEnter", "dragOver", "drop"]) await send("Input.dispatchDragEvent", { type, x: to.x, y: to.y, data });
    }
    await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: to.x, y: to.y, button: "left", buttons: 0, clickCount: 1 });
    return { intercepted: Boolean(data) };
  } finally {
    await send("Input.setInterceptDrags", { enabled: false });
  }
}
