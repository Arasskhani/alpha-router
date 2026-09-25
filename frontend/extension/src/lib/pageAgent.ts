/**
 * The side panel's line to the agent's hands in a page (content.js).
 *
 * Each call injects content.js into the tab - only now, and only there - and
 * runs one action. The tab may have moved to another site since the rules
 * judged the page, so the call checks the page's origin inside the page,
 * where no navigation can come between the check and the action. What comes
 * back is built from the page, so it is checked and cut to size before the
 * panel uses it: nothing in it is taken on trust.
 */

import type { ElementInfo } from "../content/agent";
import type { PageMethod } from "../content/runtime";

export type { ElementInfo } from "../content/agent";
export type { PageMethod } from "../content/runtime";

type PageFailure = { ok: false; error: string; message: string };
type PageOk = { ok: true } & Record<string, unknown>;
export type PageResult = PageOk | PageFailure;

const ERRORS = new Set([
  "stale_ref",
  "not_visible",
  "disabled",
  "covered",
  "not_typable",
  "sensitive_field",
  "read_only",
  "not_select",
  "no_option",
  "no_form",
  "invalid_form",
  "bad_key",
  "bad_request",
  "not_found",
  "failed",
  // Set on this side, never by the page.
  "moved",
  "no_access",
]);

const MAX_MESSAGE = 500;
const MAX_OUTLINE = 30_000;
const MAX_TEXT = 30_000;
const MAX_ELEMENTS = 300;

function str(value: unknown, limit: number): string | undefined {
  return typeof value === "string" ? value.slice(0, limit) : undefined;
}

function failure(error: string, message: string): PageFailure {
  return { ok: false, error, message };
}

const REF = /^e\d{1,9}$/;

/** One element as content.js described it, with every field checked; null when it is not one. */
export function cleanElement(raw: unknown): ElementInfo | null {
  if (!raw || typeof raw !== "object") return null;
  const v = raw as Record<string, unknown>;
  const ref = str(v.ref, 12);
  const role = str(v.role, 32);
  const tag = str(v.tag, 32);
  if (!ref || !REF.test(ref) || !role || !tag) return null;
  const info: ElementInfo = { ref, role, name: str(v.name, 120) ?? "", tag };
  const text = str(v.text, 120);
  if (text) info.text = text;
  const type = str(v.type, 32);
  if (type) info.type = type;
  const value = str(v.value, 120);
  if (value !== undefined) info.value = value;
  if (typeof v.checked === "boolean") info.checked = v.checked;
  if (v.disabled === true) info.disabled = true;
  if (v.sensitive === true) {
    info.sensitive = true;
    delete info.value;
  }
  const href = str(v.href, 4096);
  if (href) info.href = href;
  if (v.submits === true) info.submits = true;
  const formAction = str(v.formAction, 4096);
  if (formAction) info.formAction = formAction;
  if (Array.isArray(v.formButton)) {
    const said = v.formButton.slice(0, 2).map((label) => str(label, 120) ?? "").filter(Boolean);
    if (said.length) info.formButton = said;
  }
  if (Array.isArray(v.options)) {
    info.options = v.options.slice(0, 20).map((option) => str(option, 80) ?? "");
  }
  return info;
}

/** What content.js answered, checked for its method: anything out of shape is a failure. */
export function cleanPageResult(method: PageMethod, raw: unknown): PageResult {
  if (!raw || typeof raw !== "object") return failure("failed", "The page did not answer. Reload it and try again.");
  const v = raw as Record<string, unknown>;
  if (v.ok !== true) {
    const error = typeof v.error === "string" && ERRORS.has(v.error) ? v.error : "failed";
    return failure(error, str(v.message, MAX_MESSAGE) || "The action failed.");
  }
  switch (method) {
    case "read_page": {
      const outline = str(v.outline, MAX_OUTLINE);
      if (outline === undefined || !Array.isArray(v.elements)) return failure("failed", "The page could not be read.");
      const elements = v.elements.slice(0, MAX_ELEMENTS).map(cleanElement).filter((e): e is ElementInfo => e !== null);
      return { ok: true, url: str(v.url, 4096) ?? "", title: str(v.title, 300) ?? "", outline, elements, truncated: v.truncated === true };
    }
    case "get_page_text": {
      const text = str(v.text, MAX_TEXT);
      if (text === undefined) return failure("failed", "The page could not be read.");
      return { ok: true, url: str(v.url, 4096) ?? "", title: str(v.title, 300) ?? "", text, truncated: v.truncated === true };
    }
    case "find": {
      if (!Array.isArray(v.matches)) return failure("failed", "The page could not be searched.");
      const matches = v.matches.slice(0, 20).flatMap((m) => {
        if (!m || typeof m !== "object") return [];
        const match = m as Record<string, unknown>;
        const ref = str(match.ref, 12);
        if (!ref || !REF.test(ref)) return [];
        return [{ ref, role: str(match.role, 32) ?? "", name: str(match.name, 120) ?? "", snippet: str(match.snippet, 300) }];
      });
      return { ok: true, matches };
    }
    case "describe": {
      const element = cleanElement(v.element);
      return element ? { ok: true, element } : failure("failed", "The element could not be read.");
    }
    case "describe_focus": {
      // Nothing focused is an answer too: the page itself has the keyboard.
      if (v.element === undefined || v.element === null) return { ok: true };
      const element = cleanElement(v.element);
      return element ? { ok: true, element } : failure("failed", "The focused element could not be read.");
    }
    default:
      return { ok: true, note: str(v.note, MAX_MESSAGE) };
  }
}

type AgentScope = { __alpharouter?: { agent?: (method: unknown, args: unknown) => unknown } };

/**
 * Where a call goes: the tab, and the page in it the rules judged - its host
 * and its origin, as `readablePage` names them.
 */
export type PageTarget = { tabId: number; host: string; origin: string };

/** The agent's banner, put up (again) on the page before the action: which run, and what it says. */
export type OverlayRequest = { run: string; label: string };

/**
 * Run one agent action in the tab `target.tabId`, only while it shows a page
 * of `target.origin`, with the run's banner shown first when `overlay` is
 * given. Never throws: every outcome is a PageResult.
 */
export async function callPage(
  target: PageTarget,
  method: PageMethod,
  args: Record<string, unknown> = {},
  overlay: OverlayRequest | null = null,
): Promise<PageResult> {
  const { tabId, host, origin } = target;
  let results: Array<{ result?: unknown }>;
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
    results = await chrome.scripting.executeScript({
      target: { tabId },
      // Serialized into the page: it may use nothing from this module. The
      // origin, not the host: another port or scheme of a host is another site.
      func: (expected: string, name: string, input: Record<string, unknown>, banner: OverlayRequest | null) => {
        if (location.origin !== expected) return { ok: false, error: "moved", message: `The tab left ${expected}.` };
        const agent = (globalThis as AgentScope).__alpharouter?.agent;
        if (!agent) return { ok: false, error: "failed", message: "The page's helper is missing." };
        if (banner) agent("show_overlay", banner);
        return agent(name, input);
      },
      args: [origin, method, args, overlay],
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "";
    if (/permission|cannot access|cannot be scripted/i.test(message)) {
      return failure("no_access", `Alpharouter does not have access to ${host}.`);
    }
    if (/no tab with id|tab was closed/i.test(message)) return failure("moved", "The tab was closed.");
    return failure("failed", "The page could not be reached. Reload it and try again.");
  }
  return cleanPageResult(method, results?.[0]?.result);
}
