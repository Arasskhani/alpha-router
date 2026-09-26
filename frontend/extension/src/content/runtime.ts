/**
 * One call from the side panel's agent, run in the page: which action, with
 * which arguments. Every answer is an object with `ok`; nothing here throws
 * back into the page or the panel.
 */

import {
  click,
  describe,
  describeAt,
  describeFocus,
  find,
  pageText,
  pressKey,
  scroll,
  selectOption,
  snapshot,
  submitForm,
  typeText,
  waitFor,
  type Result,
  type Visibility,
} from "./agent";
import { hideOverlay, runStopped, showOverlay, type StopSender } from "./overlay";
import { hideTarget, hideVisuals, moveCursor, pulseClick, setHighlightState, showTarget, showVisuals, type ClickKind, type HighlightState } from "./visuals";

/** What the panel can ask of the page. */
export type PageMethod =
  | "read_page"
  | "get_page_text"
  | "find"
  | "describe"
  | "describe_at"
  | "describe_focus"
  | "click"
  | "type_text"
  | "select_option"
  | "submit_form"
  | "press_key"
  | "scroll"
  | "wait_for"
  | "show_overlay"
  | "hide_overlay"
  | "visuals_show"
  | "visuals_hide"
  | "visuals_state"
  | "visuals_cursor"
  | "visuals_target";

const HIGHLIGHT_STATES = new Set<HighlightState>(["working", "waiting", "paused", "error"]);
const CLICK_KINDS = new Set<ClickKind>(["left", "right", "double", "triple"]);

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

const RUN_ID = /^[A-Za-z0-9_-]{1,64}$/;

/** What changes the page: refused for a run the user stopped from this page's banner. */
const ACTS = new Set(["click", "type_text", "select_option", "submit_form", "press_key"]);

function count(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export async function runAgentCall(
  doc: Document,
  method: unknown,
  rawArgs: unknown,
  isVisible: Visibility,
  send: StopSender,
  run?: unknown,
): Promise<Result> {
  const args = rawArgs && typeof rawArgs === "object" ? (rawArgs as Record<string, unknown>) : {};
  if (typeof method === "string" && ACTS.has(method) && runStopped(run)) {
    return { ok: false, error: "stopped", message: "The user stopped the agent on this page." };
  }
  try {
    switch (method) {
      case "read_page":
        return { ok: true, ...snapshot(doc, { maxChars: count(args.max_chars), isVisible }) };
      case "get_page_text":
        return { ok: true, ...pageText(doc, { maxChars: count(args.max_chars), isVisible }) };
      case "find":
        return find(doc, args.query, isVisible);
      case "describe":
        return describe(args.ref, isVisible, args.activates === true, args.choose);
      case "describe_at":
        return describeAt(doc, args.x, args.y, isVisible, args.activates === true);
      case "describe_focus":
        return describeFocus(doc, isVisible);
      case "click":
        return click(args.ref, isVisible);
      case "type_text":
        return typeText(args.ref, args.text, args.clear, isVisible);
      case "select_option":
        return selectOption(args.ref, args.value, isVisible);
      case "submit_form":
        return submitForm(args.ref, isVisible);
      case "press_key":
        return pressKey(doc, args.key);
      case "scroll":
        return scroll(doc, args.direction, args.ref, isVisible);
      case "wait_for":
        return await waitFor(doc, args.text, args.seconds);
      case "show_overlay": {
        const run = typeof args.run === "string" && RUN_ID.test(args.run) ? args.run : null;
        if (!run) return { ok: false, error: "bad_request", message: "The overlay needs the run's id." };
        const label = typeof args.label === "string" ? args.label.slice(0, 120) : "Alpharouter is working on this page";
        showOverlay(doc, run, label, send);
        return { ok: true };
      }
      case "hide_overlay":
        hideOverlay(doc, typeof args.run === "string" ? args.run : undefined);
        return { ok: true };
      case "visuals_show":
        showVisuals(doc);
        return { ok: true };
      case "visuals_hide":
        hideVisuals(doc);
        return { ok: true };
      case "visuals_state": {
        const state = args.state as HighlightState;
        if (!HIGHLIGHT_STATES.has(state)) return { ok: false, error: "bad_request", message: "Unknown highlight state." };
        setHighlightState(doc, state);
        return { ok: true };
      }
      case "visuals_cursor": {
        const x = num(args.x);
        const y = num(args.y);
        if (x === null || y === null) return { ok: false, error: "bad_request", message: "The cursor needs x and y." };
        moveCursor(doc, { x, y });
        const kind = args.click as ClickKind | undefined;
        if (kind !== undefined && CLICK_KINDS.has(kind)) pulseClick(doc, { x, y }, kind);
        return { ok: true };
      }
      case "visuals_target": {
        const rect = args.rect as Record<string, unknown> | null | undefined;
        if (!rect) {
          hideTarget(doc);
          return { ok: true };
        }
        const x = num(rect.x);
        const y = num(rect.y);
        const width = num(rect.width);
        const height = num(rect.height);
        if (x === null || y === null || width === null || height === null) return { ok: false, error: "bad_request", message: "The target needs a rect." };
        showTarget(doc, { x, y, width, height });
        return { ok: true };
      }
      default:
        return { ok: false, error: "bad_request", message: "The page does not know that action." };
    }
  } catch (err) {
    const message = err instanceof Error && err.message ? err.message.slice(0, 200) : "The action failed.";
    return { ok: false, error: "failed", message };
  }
}
