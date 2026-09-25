/**
 * One call from the side panel's agent, run in the page: which action, with
 * which arguments. Every answer is an object with `ok`; nothing here throws
 * back into the page or the panel.
 */

import {
  click,
  describe,
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
import { hideOverlay, showOverlay, type StopSender } from "./overlay";

/** What the panel can ask of the page. */
export type PageMethod =
  | "read_page"
  | "get_page_text"
  | "find"
  | "describe"
  | "describe_focus"
  | "click"
  | "type_text"
  | "select_option"
  | "submit_form"
  | "press_key"
  | "scroll"
  | "wait_for"
  | "show_overlay"
  | "hide_overlay";

const RUN_ID = /^[A-Za-z0-9_-]{1,64}$/;

function count(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export async function runAgentCall(
  doc: Document,
  method: unknown,
  rawArgs: unknown,
  isVisible: Visibility,
  send: StopSender,
): Promise<Result> {
  const args = rawArgs && typeof rawArgs === "object" ? (rawArgs as Record<string, unknown>) : {};
  try {
    switch (method) {
      case "read_page":
        return { ok: true, ...snapshot(doc, { maxChars: count(args.max_chars), isVisible }) };
      case "get_page_text":
        return { ok: true, ...pageText(doc, { maxChars: count(args.max_chars), isVisible }) };
      case "find":
        return find(doc, args.query, isVisible);
      case "describe":
        return describe(args.ref, isVisible, args.activates === true);
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
      default:
        return { ok: false, error: "bad_request", message: "The page does not know that action." };
    }
  } catch (err) {
    const message = err instanceof Error && err.message ? err.message.slice(0, 200) : "The action failed.";
    return { ok: false, error: "failed", message };
  }
}
