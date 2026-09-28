/**
 * The browser agent's loop, without the UI.
 *
 * Each step is one model call with the agent's tools (`browser_tools`); the
 * model answers with words, tool calls, or both. The calls run one after the
 * other, each first through the agent's rules (agentPolicy.ts): a read goes
 * ahead, an action waits for the user in Ask mode (or for the review model in
 * Auto mode, which hands anything unsure to the user), a sensitive one always
 * waits for the user, and a blocked one is refused with the reason. Every
 * tool call gets exactly one answer - its result, or why it did not run - so
 * the conversation stays one the model can read.
 *
 * What comes from a page goes back inside <untrusted_page_content_…> tags,
 * with the run's own random suffix; older page content is cut short so a long
 * run stays within the model's reach, and a tool call is never separated from
 * its answer. The run ends when the model calls done, at the step limit,
 * after three failed tool calls in a row (or five refused ones: a refusal is
 * the rules at work, not a failure), or when the user presses Stop. An
 * answer in words alone is not the end: the model is reminded to act, and a
 * second such answer in a row ends the run as "no_action" - not as done.
 */

import { approvalFor, classifyAction, DEFAULT_APPROVALS, type AgentMode, type PolicyContext, type Verdict } from "../lib/agentPolicy";
import { KEY_NAMES_SHOWN, parseKeyCombo } from "../lib/keys";
import { looseName } from "../lib/refs";
import type { CdpDriver } from "../lib/cdpDriver";
import { probeInjection } from "../lib/injection";
import type { ElementInfo, PageMethod, PageResult } from "../lib/pageAgent";
import { readablePage } from "../lib/sites";
import { agentInstructions, CONTROL_TOOL_NAMES, TOOL_NAMES } from "./agentTools";
import type { PauseGate } from "./pauseGate";

export type WorkTab = { id: number; url: string; host: string | null; title: string };

/** The browser as the agent uses it; the panel's own implementation is agentBrowser.ts. */
export type AgentBrowser = {
  /** The tab the agent works in now: the one next to the panel, then whichever tab_open or tab_switch chose. */
  current(): Promise<WorkTab | null>;
  listTabs(): Promise<Array<WorkTab & { active: boolean }>>;
  openTab(url: string): Promise<WorkTab>;
  switchTab(tabId: number): Promise<WorkTab | null>;
  navigate(url: string): Promise<WorkTab>;
  /**
   * One action in the page of the tab the agent works in - only on `judged`,
   * the page the rules judged, when it is given: a tab that has gone to
   * another site since answers "moved".
   */
  page(method: PageMethod, args?: Record<string, unknown>, judged?: WorkTab, signal?: AbortSignal, timeoutMs?: number): Promise<PageResult>;
  /** While `hold` says so (a dialog of the page's waits on the user), a slow page is not given up on. */
  holdWhile?(hold: () => boolean): void;
  /** Whether the browser lets the extension work on the pages of this address's site. */
  hasAccess(url: string): Promise<boolean>;
  /** After an action that may load a page: wait until the tab has settled. */
  settle(): Promise<void>;
};

type ToolCall = { id: string; type: "function"; function: { name: string; arguments: string } };

/** A part of a user message: words, or a screenshot as an inline image. */
type MessagePart = { type: "text"; text: string } | { type: "image_url"; image_url: { url: string } };

export type ApiMessage =
  | { role: "system"; content: string }
  | { role: "user"; content: string | MessagePart[] }
  | { role: "assistant"; content: string | null; tool_calls?: ToolCall[]; reasoning_details?: unknown[] }
  | { role: "tool"; tool_call_id: string; content: string };

export type ModelReply = { text: string; toolCalls: Array<{ id: string; name: string; arguments: string }>; reasoningDetails?: unknown[] };

export type ApprovalRequest = {
  tool: string;
  /** What the action does, in words - what will be typed, where a page is. */
  summary: string;
  verdict: Verdict;
  /** Auto mode: the review model handed this to the user, and why. */
  review?: string;
  /** The site the browser must allow first; the panel asks for it in the Allow click. */
  access?: { pattern: string; host: string };
  /**
   * A plain action in Ask mode: the card may offer to allow such actions on
   * this site for the rest of the run - never an action that always asks.
   */
  offerSite?: string;
};

/** The person's answer to a card: no, yes, or yes and the same for plain actions on this site for the rest of the run. */
export type ApprovalAnswer = boolean | "site";

type ReviewInput = {
  task: string;
  tool: string;
  site: string;
  target?: string;
  arguments: Record<string, unknown>;
  history: string[];
  /** Under full control, a crop of the page around the target, as a data URL; the server shows it to a vision reviewer that may see this site. */
  crop?: string;
};

type StepStatus = "running" | "waiting" | "done" | "denied" | "blocked" | "skipped" | "error" | "stopped";

/** One line of the step log. `kept` is the summary as it may be saved: without what was typed. */
export type StepView = { id: string; tool: string; summary: string; status: StepStatus; detail?: string; kept?: string };

export type AgentEventReport = {
  kind: "agent_step" | "agent_task";
  site?: string;
  action?: string;
  outcome: string;
  detail: Record<string, unknown>;
};

/** The run's driver under full control: input and screenshots (cdpDriver.ts); absent on the dom path. */
export type ControlDriver = Pick<CdpDriver, "screenshot" | "zoom" | "crop" | "click" | "clickAt" | "hover" | "scroll" | "drag" | "type" | "key" | "toCss" | "onDialog" | "handleDialog"> & {
  /** Work in this tab, on this page, from now on (lib/driver.ts TabDrivers); false when Chrome will not attach to it. */
  use?(tabId: number, url?: string): Promise<boolean>;
};

/** What the run is doing, as the page's border and the toolbar badge show it. */
export type RunState = "working" | "waiting" | "paused";

export type AgentDeps = {
  model(messages: ApiMessage[], signal: AbortSignal): Promise<ModelReply>;
  browser: AgentBrowser;
  /** Attached by the caller (chooseDriver) when the run has full control; the caller stops it after the run. */
  driver?: ControlDriver | null;
  /** The person's pause (a take-over, or the panel's button): the loop waits at it at each safe point. */
  pause?: PauseGate;
  /** Each change of what the run is doing, for the toolbar badge. */
  onState?(state: RunState): void;
  approve(request: ApprovalRequest, signal: AbortSignal): Promise<ApprovalAnswer>;
  askUser(question: string, signal: AbortSignal): Promise<string>;
  review(input: ReviewInput, signal: AbortSignal): Promise<{ decision: "allow" | "ask"; reason: string }>;
  report(event: AgentEventReport): void;
  onStep(step: StepView): void;
  /** The model's words, as they come with each step. */
  onText(text: string): void;
};

export type AgentOptions = {
  task: string;
  mode: AgentMode;
  maxSteps: number;
  /** The run's time limit; past it, the run ends before its next step. Absent: no limit. */
  maxMinutes?: number;
  /** How many of the latest screenshots stay in the conversation (SCREENSHOTS_KEPT when absent). */
  screenshotsKept?: number;
  /** Under full control, end each step that changed the page with a fresh screenshot. */
  screenshotAfterAction?: boolean;
  rules: PolicyContext;
  runId: string;
  /** The page-content tag suffix for this run: random, fixed for the run. */
  nonce: string;
  /** The model, as the report names it ("model::7"). */
  modelRef?: string;
};

export type RunOutcome = "done" | "stopped" | "max_steps" | "max_minutes" | "errors" | "failed" | "no_action";

export type RunResult = { outcome: RunOutcome; summary: string; steps: number };

const MAX_ERRORS_IN_A_ROW = 3;
/**
 * Refusals are the rules at work, not the agent failing: they do not count
 * toward the errors above, but a model that keeps asking for what is refused
 * is stopped after this many in a row.
 */
const MAX_REFUSALS_IN_A_ROW = 5;
/** What the model is told after an answer in words alone: the task is not over until it says so with done. */
const NUDGE =
  "You answered without calling a tool, and the task goes on until you call done. Call the next tool now; use ask_user if you need the user, or done with a short summary if the task is complete or cannot be done.";
/** Said for each call of a step after one that did not go through, done included: the model looks at what happened first. */
const SKIP_AFTER_FAILURE =
  "Skipped: an earlier action in this step did not go through. Look at its result, and at the page, before you go on - or before you finish.";
/** The page's border, cursor and take-over window are best-effort: a page that does not answer this fast is not waited for. */
const VISUAL_MS = 2000;
/** The look at the page after an action is best-effort too, and a little longer: it reads the focused element. */
const OBSERVE_MS = 3000;
/** How far the target may have moved between the judgment and the press, in CSS pixels. */
const TARGET_TOLERANCE_PX = 8;
/** This many deletion keys in a row, and the next one asks the user. */
const DELETION_RUN = 8;
/** Older page content is cut to this, so a long run stays within the model's reach. */
const OLD_PAGE_CHARS = 1500;
/** How many of the latest reads of the page (read_page, find, get_page_text) stay whole; the newest outline always does. */
const WHOLE_PAGE_RESULTS = 2;
/** Past this much text the oldest steps are left out, each with its answers. */
const MAX_CONVERSATION_CHARS = 120_000;
const HISTORY_LINES = 10;

/**
 * One message of the conversation, with the page's words it carries kept
 * apart; `read` marks a read of the page - its outline, or its text or a
 * search - which is what grows long and is cut when old. What an action
 * reports from the page is short, and stays whole.
 */
type Entry = { message: ApiMessage; page?: { open: string; body: string; close: string }; read?: "outline" | "text" };

/** The window's view of the page, in CSS pixels, as the page reports it after an action. */
type View = { width: number; height: number; scrollX: number; scrollY: number; pageWidth: number; pageHeight: number };

function abortError(): DOMException {
  return new DOMException("The run was stopped.", "AbortError");
}

function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

function clip(text: string, limit: number): string {
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}

function attribute(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

const TAG = /<(\s*\/?\s*)(untrusted_page_content)/gi;

/** Page content wrapped in tags the page cannot close or imitate. */
function wrapPage(nonce: string, site: string, body: string): Entry["page"] {
  const tag = `untrusted_page_content_${nonce}`;
  return { open: `<${tag} site="${attribute(site)}">`, body: body.replace(TAG, "&lt;$1$2"), close: `</${tag}>` };
}

function pageText(page: NonNullable<Entry["page"]>, whole: boolean): string {
  const body = whole || page.body.length <= OLD_PAGE_CHARS ? page.body : `${page.body.slice(0, OLD_PAGE_CHARS)}\n…(older page content, cut)`;
  return `${page.open}\n${body}\n${page.close}`;
}

/**
 * What the agent is told when the page could not do an action, by the
 * page's error code - in its own words, outside the page tags: the page's
 * message goes inside them, as it may name the page's elements.
 */
const ADVICE: Record<string, string> = {
  stale_ref: "That element is gone from the page: read the page again for fresh references.",
  not_visible: "It is not visible: scroll to it, or look at the page again.",
  disabled: "It is disabled: something else has to come first.",
  covered: "Something covers it: deal with that first, or act elsewhere.",
  not_typable: "It is not a field that takes text.",
  sensitive_field: "The agent never types there: ask the user to fill it in.",
  read_only: "It cannot be changed.",
  not_select: "It is not a menu: click it, then click the option.",
  no_option: "No option matches: the page lists the options it has.",
  no_form: "It is not in a form.",
  invalid_form: "The form is not complete: fill in what is missing first.",
  bad_key: "That is not a key the agent can press.",
  changed: "The element changed since this action was judged: look at the page again.",
  no_focus: "The keyboard is not in that field: look at the page, then click the field again.",
  not_kept: "The page did not keep what was typed: look at the field again, and if it still refuses the text, ask the user.",
  bad_format: "The field takes its value in a set format, which the page's message says: type it again that way.",
  bad_request: "The arguments were not right for this tool.",
  not_found: "Nothing there matches.",
  moved: "The tab is no longer on the page the action was judged on: look at it again.",
  no_access: "The extension may not work on this site.",
  page_busy: "The page did not answer in time: look at it again, or ask the user.",
  paused: "The user took over the page.",
  stopped: "The user stopped the agent on this page.",
};

/** A failure the page reported: the code and what to do, as the agent's words; the page's own message in the tags. */
function notDone(error: string): string {
  return `Not done (${error}). ${ADVICE[error] ?? "The action failed."}`;
}

/** What an image costs the model, counted as if it were this much text. */
const IMAGE_CHARS = 1500;
/** How many of the latest screenshots stay in the conversation; older ones are dropped, with a note. */
export const SCREENSHOTS_KEPT = 3;
const OMITTED_SHOT: MessagePart = { type: "text", text: "(an earlier screenshot, left out to save space)" };

function size(message: ApiMessage): number {
  const calls = message.role === "assistant" ? JSON.stringify(message.tool_calls ?? []).length : 0;
  if (Array.isArray(message.content)) {
    return message.content.reduce((sum, part) => sum + (part.type === "text" ? part.text.length : IMAGE_CHARS), 0);
  }
  return (typeof message.content === "string" ? message.content.length : 0) + calls;
}

function hasImage(message: ApiMessage): boolean {
  return Array.isArray(message.content) && message.content.some((part) => part.type === "image_url");
}

/** A zoom's caption: its image shows a region magnified, and gives no page coordinates. */
const ZOOM_CAPTION = "That region, magnified.";

function isZoom(message: ApiMessage): boolean {
  return Array.isArray(message.content) && message.content.some((part) => part.type === "text" && part.text.startsWith(ZOOM_CAPTION));
}

/**
 * All but the last `kept` screenshots replaced by a note, so a long run stays
 * affordable. The latest full screenshot is always among them - it is the
 * model's only source of coordinates - however many zooms came after it.
 */
function withRecentScreenshots(messages: ApiMessage[], kept: number = SCREENSHOTS_KEPT): ApiMessage[] {
  const shots = messages.flatMap((message, index) => (hasImage(message) ? [index] : []));
  const newest = shots.slice(-Math.max(1, Math.floor(kept)));
  const lastFull = [...shots].reverse().find((index) => !isZoom(messages[index]));
  if (lastFull !== undefined && !newest.includes(lastFull)) newest.splice(0, 1, lastFull);
  const keep = new Set(newest);
  return messages.map((message, index): ApiMessage => {
    if (message.role !== "user" || !Array.isArray(message.content) || keep.has(index) || !hasImage(message)) return message;
    return { role: "user", content: message.content.map((part) => (part.type === "image_url" ? OMITTED_SHOT : part)) };
  });
}

/**
 * The conversation as the model reads it: older page content cut short, only
 * the latest screenshots kept, and - when it is still too long - the oldest
 * steps left out whole, a tool call never without its answer.
 */
/** The model's reasoning goes back with this many of its latest steps. */
const REASONING_KEPT = 2;

export function conversation(entries: Entry[], screenshotsKept: number = SCREENSHOTS_KEPT): ApiMessage[] {
  const reads = entries.flatMap((entry, index) => (entry.page && entry.read ? [index] : []));
  const whole = new Set(reads.slice(-WHOLE_PAGE_RESULTS));
  // The newest outline carries the references the model acts with: it is never cut, however many reads came after it.
  const outline = [...reads].reverse().find((index) => entries[index].read === "outline");
  if (outline !== undefined) whole.add(outline);
  const messages = withRecentScreenshots(
    entries.map((entry, index) =>
      entry.page && entry.message.role === "tool"
        ? { ...entry.message, content: [entry.message.content, pageText(entry.page, !entry.read || whole.has(index))].filter(Boolean).join("\n") }
        : entry.message,
    ),
    screenshotsKept,
  );
  // The model's reasoning goes back with its latest steps only: what a provider checks is the step it goes on from,
  // and the older blocks would only grow every request.
  let assistants = 0;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i];
    if (message.role !== "assistant") continue;
    assistants += 1;
    if (assistants > REASONING_KEPT && message.reasoning_details) {
      const { reasoning_details: _dropped, ...kept } = message;
      messages[i] = kept;
    }
  }
  const [system, task, ...rest] = messages;
  // Steps: an assistant message and the tool answers after it.
  const groups: ApiMessage[][] = [];
  for (const message of rest) {
    if (message.role === "assistant" || !groups.length) groups.push([message]);
    else groups[groups.length - 1].push(message);
  }
  let total = [system, task, ...rest].reduce((sum, message) => sum + size(message), 0);
  let dropped = 0;
  while (groups.length > 1 && total > MAX_CONVERSATION_CHARS) {
    const oldest = groups.shift()!;
    total -= oldest.reduce((sum, message) => sum + size(message), 0);
    dropped += 1;
  }
  const note: ApiMessage[] = dropped
    ? [{ role: "user", content: `(${dropped} earlier step${dropped === 1 ? " was" : "s were"} left out to save space.)` }]
    : [];
  return [system, task, ...note, ...groups.flat()];
}

function args(raw: string): Record<string, unknown> | null {
  try {
    const value = JSON.parse(raw || "{}") as unknown;
    return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function named(element: ElementInfo | undefined, ref: unknown): string {
  if (element?.name) return `"${clip(element.name, 60)}"`;
  return typeof ref === "string" ? `element ${ref}` : "an element";
}

/** Past this, a card's address shows its start and its end, and its length. */
const MAX_SHOWN_ADDRESS = 300;
/** Past this, a card shows the start of the text to be typed, and its length. */
const MAX_SHOWN_TEXT = 2000;

/**
 * An address in full, for the card and the reviewer: the query and the
 * fragment are where data taken from a page would travel, so they are shown,
 * not dropped.
 */
function address(url: unknown): string {
  if (typeof url !== "string" || !readablePage(url)) return "a page";
  const href = new URL(url).href;
  return href.length <= MAX_SHOWN_ADDRESS ? href : `${href.slice(0, 240)}…${href.slice(-40)} (${href.length} characters)`;
}

/** The text to be typed, in full up to a size, then its start and its length. */
function typed(text: string): string {
  return text.length <= MAX_SHOWN_TEXT ? `"${text}"` : `"${text.slice(0, MAX_SHOWN_TEXT)}…" (${text.length} characters in all)`;
}

/**
 * A step's summary as it may be kept after the run: what the person saw,
 * less the text that was typed, which is never stored - only its length.
 */
export function keptSummary(tool: string, a: Record<string, unknown>, summary: string): string | undefined {
  const text = tool === "type_text" || (tool === "computer" && a.action === "type") ? a.text : undefined;
  if (typeof text !== "string" || !text) return undefined;
  const shown = typed(text);
  return summary.includes(shown) ? summary.replace(shown, `${text.length} characters`) : `Type ${text.length} characters`;
}

function whereTo(url: unknown): string {
  const page = typeof url === "string" ? readablePage(url) : null;
  if (!page) return "a page";
  try {
    const parsed = new URL(url as string);
    return `${page.host}${parsed.pathname === "/" ? "" : parsed.pathname}`;
  } catch {
    return page.host;
  }
}

/** The element as the reviewer sees it: its role, its name and the words it shows, and where a link goes. */
function reviewTarget(element: ElementInfo): string {
  const shows = element.text ? ` (it shows "${element.text}")` : "";
  const goes = element.href ? ` - a link to ${readablePage(element.href) ? address(element.href) : "another program"}` : "";
  return clip(`${element.role}: ${element.name || "(no name)"}${shows}${goes}`, 300);
}

/** The tab a tab_switch goes to, as the card names it. */
type SwitchTarget = WorkTab & { readable: boolean };

/** What an action does, in words for the step log and the approval card. */
function describeAction(tool: string, a: Record<string, unknown>, element?: ElementInfo, target?: SwitchTarget): string {
  switch (tool) {
    case "tabs_list":
      return "List the open tabs";
    case "tab_open":
      return `Open ${address(a.url)} in a new tab`;
    case "tab_switch":
      if (!target) return `Switch to tab ${String(a.tab_id)}`;
      if (!target.host) return `Switch to tab ${target.id}, which shows no web page`;
      return target.readable
        ? `Switch to tab ${target.id}: "${clip(target.title || target.host, 80)}" on ${target.host}`
        : `Switch to tab ${target.id} (a tab the agent may not work on)`;
    case "navigate":
      return `Open ${address(a.url)}`;
    case "read_page":
      return "Read the page";
    case "find":
      return `Find "${clip(String(a.query ?? ""), 60)}"`;
    case "get_page_text":
      return "Read the page's text";
    case "click":
      return `Click ${named(element, a.ref)}`;
    case "type_text":
      return `Type ${typed(String(a.text ?? ""))} into ${named(element, a.ref)}${a.clear === true ? ", replacing what is there" : ""}`;
    case "select_option":
      // The option the menu will really take, which the model's words only point at.
      return element?.choice
        ? `Choose "${element.choice}" in ${named(element, a.ref)}`
        : `Choose "${clip(String(a.value ?? ""), 60)}" in ${named(element, a.ref)}${element ? " (no option matches)" : ""}`;
    case "press_key":
      return `Press ${clip(String(a.key ?? "a key"), 20)}${element ? ` in ${named(element, undefined)}` : ""}`;
    case "submit_form":
      return `Send the form${element?.formAction ? ` to ${address(element.formAction)}` : ""}${element?.name ? ` (from ${named(element, a.ref)})` : ""}`;
    case "scroll":
      return a.ref ? `Scroll to ${named(element, a.ref)}` : `Scroll ${typeof a.direction === "string" ? a.direction : "down"}`;
    case "wait_for":
      return typeof a.text === "string" && a.text ? `Wait for "${clip(a.text, 60)}"` : `Wait ${Number(a.seconds) || 2} seconds`;
    case "ask_user":
      return "Ask you a question";
    case "done":
      return "Finish";
    case "update_plan":
      return "Propose a plan";
    default:
      return `Use ${clip(tool, 40)}`;
  }
}

/** A computer action in words, naming what it touches when that is known. */
function describeComputer(a: Record<string, unknown>, element?: ElementInfo, drop?: ElementInfo): string {
  const action = String(a.action ?? "");
  const where = element ? ` ${element.role}${element.name ? ` "${clip(element.name, 80)}"` : ""}` : "";
  const onto = drop ? ` ${drop.role}${drop.name ? ` "${clip(drop.name, 80)}"` : ""}` : "";
  // What is held with a click or a hover, said on the card: shift+click selects a range, ctrl+click adds to one.
  const held = typeof a.modifiers === "string" && a.modifiers.trim() ? ` with ${clip(a.modifiers.trim(), 30)} held` : "";
  const at = (value: unknown) => {
    const p = point(value);
    return p ? ` at (${p.x}, ${p.y})${held}` : held;
  };
  switch (action) {
    case "left_click":
      return `Click${where}${at(a.coordinate)}`;
    case "right_click":
      return `Right-click${where}${at(a.coordinate)}`;
    case "double_click":
      return `Double-click${where}${at(a.coordinate)}`;
    case "triple_click":
      return `Triple-click${where}${at(a.coordinate)}`;
    case "hover":
      return `Hover over${where}${at(a.coordinate)}`;
    case "left_click_drag":
      return `Drag${where}${at(a.start_coordinate)} to${onto}${at(a.coordinate)}`;
    case "scroll":
      return `Scroll ${String(a.scroll_direction ?? "down")}${at(a.coordinate)}`;
    case "type":
      return `Type ${typed(typeof a.text === "string" ? a.text : "")}${element ? ` into${where}` : ""}`;
    case "key":
      return `Press ${clip(String(a.text ?? ""), 40)}${element ? ` in${where}` : ""}`;
    case "wait":
      return `Wait ${Number(a.duration) || 1} s`;
    default:
      return `computer: ${clip(action, 40)}`;
  }
}

const ELEMENT_TOOLS = new Set(["click", "type_text", "select_option", "submit_form"]);
const PAGE_TOOLS = new Set([
  "read_page",
  "find",
  "get_page_text",
  "click",
  "type_text",
  "select_option",
  "submit_form",
  "press_key",
  "scroll",
  "wait_for",
  "screenshot",
  "zoom",
  "computer",
]);
/** Fields whose value is one whole thing, set as a whole rather than typed a part at a time. */
const WHOLE_VALUE_TYPES = new Set(["date", "time", "datetime-local", "month", "week", "color", "range"]);
/** Reference actions that, under full control, use the real mouse and keyboard. */
const BY_HAND = new Set(["click", "type_text", "press_key"]);
/** Ref actions whose result tells what the page is like after them. */
const AFTERMATH = new Set(["click", "type_text", "select_option", "submit_form", "press_key"]);
/** What changes the page, so that a step with one ends with a fresh screenshot (when the administrator wants one). */
const CHANGES = new Set(["click", "type_text", "select_option", "submit_form", "press_key", "scroll", "navigate", "tab_open", "tab_switch"]);
/** Actions after which a page may be loading. */
const MAY_LOAD = new Set(["click", "submit_form", "press_key", "navigate", "tab_open", "tab_switch", "computer"]);
/** A hand-typed field the person took over after it was cleared: what the model is told was done. */
const TOOK_OVER_AFTER_CLEARING = "The user took over this page after the field was cleared, before the text was typed.";
/** The rules' plain actions on the page - no case an administrator relaxed - which "Allow on this site" may cover. */
const PLAIN_REASONS = new Set(["click", "type", "select", "press_key", "same_site", "drag", "tab_switch"]);
/** Tools (as the rules know them) that change nothing: they do not break a run of deletion keys. */
const READ_ONLY = new Set(["tabs_list", "read_page", "find", "get_page_text", "scroll", "wait_for", "screenshot", "zoom", "ask_user"]);

type PointRect = { x: number; y: number; width: number; height: number };

/**
 * Where a form sends, for telling whether it changed: without its query or
 * fragment - a search form with no action sends to the page's own address,
 * which a single-page app rewrites as the person types (?q=…).
 */
function formDestination(action: string | undefined): string {
  if (!action) return "";
  try {
    const url = new URL(action);
    return `${url.origin}${url.pathname}`;
  } catch {
    return action;
  }
}

/** The same target for the rules' purposes: what they judged it by has not changed, whichever DOM node it is now. */
function sameTarget(judged: ElementInfo, now: ElementInfo): boolean {
  return (
    judged.role === now.role &&
    judged.name === now.name &&
    (judged.text ?? "") === (now.text ?? "") &&
    (judged.href ?? "") === (now.href ?? "") &&
    (judged.type ?? "") === (now.type ?? "") &&
    Boolean(judged.submits) === Boolean(now.submits) &&
    formDestination(judged.formAction) === formDestination(now.formAction) &&
    Boolean(judged.sensitive) === Boolean(now.sensitive) &&
    (judged.frame?.host ?? null) === (now.frame?.host ?? null) &&
    Boolean(judged.frame) === Boolean(now.frame) &&
    (judged.hidden ?? "") === (now.hidden ?? "")
  );
}

/**
 * Whether the target sits where it was and is about the same size: within
 * the tolerance, or a tenth of its size for a large one - a wide field that
 * grew a border, a button a pixel taller - so a small shift does not drop a
 * press the rules allowed.
 */
function closeTo(was: PointRect, now: PointRect): boolean {
  const tx = Math.max(TARGET_TOLERANCE_PX, 0.1 * Math.max(was.width, now.width));
  const ty = Math.max(TARGET_TOLERANCE_PX, 0.1 * Math.max(was.height, now.height));
  return Math.abs(was.x - now.x) <= tx && Math.abs(was.y - now.y) <= ty && Math.abs(was.width - now.width) <= tx && Math.abs(was.height - now.height) <= ty;
}

/** What a computer action is, as the rules know actions: the tool it amounts to, and where the element comes from. */
const COMPUTER_ACTIONS: Record<string, { as: string; element: "point" | "start" | "focus" | "none"; kind?: "left" | "right" | "double" | "triple" }> = {
  left_click: { as: "click", element: "point", kind: "left" },
  right_click: { as: "click", element: "point", kind: "right" },
  double_click: { as: "click", element: "point", kind: "double" },
  triple_click: { as: "click", element: "point", kind: "triple" },
  hover: { as: "scroll", element: "point" },
  left_click_drag: { as: "drag", element: "start" },
  scroll: { as: "scroll", element: "none" },
  type: { as: "type_text", element: "focus" },
  key: { as: "press_key", element: "focus" },
  wait: { as: "wait_for", element: "none" },
};

type Answer = {
  content: string;
  page?: Entry["page"];
  /** What the action was, in words, when more is known than the call says (the element's name). */
  summary?: string;
  status: StepStatus;
  detail?: string;
  /** For the report. */
  outcome: string;
  site?: string;
  extra?: Record<string, unknown>;
  finish?: string;
  /** A screenshot to show the model after this step's answers, as an inline image. */
  image?: { url: string; caption: string };
  /** A read of the page, which the conversation cuts short once it is old. */
  read?: Entry["read"];
};

function point(value: unknown): { x: number; y: number } | null {
  if (!Array.isArray(value) || value.length !== 2) return null;
  const [x, y] = value;
  if (typeof x !== "number" || typeof y !== "number" || !Number.isFinite(x) || !Number.isFinite(y)) return null;
  return { x, y };
}

/** A pressed key as Admin Logs names it: a named key alone, by the key table's name ("Space" for the space bar). */
function loggedKey(raw: unknown): { key?: string } {
  const combo = parseKeyCombo(raw);
  if (!combo || combo.ctrl || combo.alt || combo.meta || ([...combo.key].length === 1 && combo.key !== " ")) return {};
  return { key: combo.key === " " ? "Space" : combo.key };
}

/** The agent's note when the tab went to a site the user has not allowed: a host name, never the page's words. */
function elsewhere(host: string): string {
  return `The tab is now on another site, ${host}: the user will be asked before you act there.`;
}

/** An element as a result line names it: its role, its name, and its own words when they differ. */
function hitLine(element: ElementInfo): string {
  return `${element.role}${element.name ? ` "${clip(element.name, 80)}"` : ""}${element.text ? ` (it shows "${clip(element.text, 60)}")` : ""}`;
}

/** The element with the keyboard, as a result line names it: with its reference, and what it holds - never a sensitive field's value. */
function focusLine(element: ElementInfo): string {
  if (element.role === "frame") return `a frame${element.frame?.host ? ` from ${element.frame.host}` : ""}, whose inside this page cannot see`;
  const holds = element.sensitive ? ", a sensitive field (what it holds is not read)" : element.value !== undefined ? `, holding "${clip(element.value, 100)}"` : "";
  return `${hitLine(element)} [${element.ref}]${holds}`;
}

function originPattern(url: string): { pattern: string; host: string } | null {
  const page = readablePage(url);
  return page ? { pattern: page.pattern, host: page.host } : null;
}

export async function runAgent(options: AgentOptions, deps: AgentDeps, signal: AbortSignal): Promise<RunResult> {
  const entries: Entry[] = [
    {
      message: {
        role: "system",
        content: agentInstructions(options.nonce, { fullControl: Boolean(deps.driver), mode: options.mode, screenshotAfterAction: Boolean(options.screenshotAfterAction) }),
      },
    },
    { message: { role: "user", content: options.task } },
  ];
  const history: string[] = [];
  let errorsInARow = 0;
  let refusalsInARow = 0;
  /** Deletion keys pressed one after another, with no other action between: past DELETION_RUN the next one asks. */
  let deletionsInARow = 0;
  /**
   * Set when the last page content read like instructions to the agent: the
   * next action that changes anything asks the user, in every mode, and is
   * cleared once it has. The page may be steering the model.
   */
  let injected: string | null = null;
  /** The page's dialogs being answered now: while one is, the page waits on the user, not stuck. */
  let dialogsOpen = 0;
  // A form sent through the page that opens a confirm waits on the user's card: not a page that stopped answering,
  // whose action would then go through after the model was told it did not - and be tried again.
  deps.browser.holdWhile?.(() => dialogsOpen > 0);
  /** Ask mode: the sites where the person allowed plain actions for the rest of this run, from a card. */
  const siteWide = new Set<string>();
  /** Plan mode: true once the user has approved a plan, after which the plan's sites are worked without asking each action. */
  let planApproved = false;
  /** The model answered in words alone and was reminded to act; a second time in a row ends the run. */
  let nudged = false;
  /** The tool-call ids of this run so far. */
  const callIds = new Set<string>();
  let steps = 0;
  let startSite: string | undefined;
  /**
   * The sites the user has let the agent work on: where the run started, and
   * every other site the user allowed it to go to. A page can take the tab
   * elsewhere by itself - a redirect, a script, a same-site link that
   * bounces - and the agent acts on no such site until the user agrees.
   */
  const allowedSites = new Set<string>();
  const started = Date.now();

  const check = () => {
    if (signal.aborted) throw abortError();
  };

  // Stop takes effect at once, even while the page is busy (a wait, a slow page): see raced().

  async function page(method: PageMethod, a: Record<string, unknown>, judged: WorkTab): Promise<PageResult> {
    check();
    const result = await raced(deps.browser.page(method, a, judged, signal));
    check();
    return result;
  }

  function report(outcome: RunOutcome) {
    deps.report({
      kind: "agent_task",
      site: startSite,
      outcome: outcome === "failed" ? "failed" : outcome,
      detail: {
        task_id: options.runId,
        steps,
        mode: options.mode,
        ...(options.modelRef ? { model: options.modelRef } : {}),
        duration_ms: Math.min(86_400_000, Date.now() - started),
      },
    });
  }

  /** `work`, unless Stop comes first: then the run ends at once, whatever the page or the browser is doing. */
  function raced<T>(work: Promise<T>): Promise<T> {
    // Not a Promise.race with one promise of the Stop: each race would leave a reaction on it, holding its answer (a
    // screenshot, an outline) for the rest of the run. The listener here goes with the answer.
    return new Promise<T>((resolve, reject) => {
      if (signal.aborted) {
        // Nobody waits for `work` any more: its failure, if it comes, is not left unhandled.
        work.catch(() => undefined);
        reject(abortError());
        return;
      }
      const onAbort = () => reject(abortError());
      signal.addEventListener("abort", onAbort, { once: true });
      work.then(
        (value) => {
          signal.removeEventListener("abort", onAbort);
          resolve(value);
        },
        (err: unknown) => {
          signal.removeEventListener("abort", onAbort);
          reject(err);
        },
      );
    });
  }

  /** `work`, or `value` once Stop comes first: for what is best-effort, and must not end the run itself. */
  function orOnStop<T, U>(work: Promise<T>, value: U): Promise<T | U> {
    return raced<T | U>(work).catch((err: unknown) => {
      if (isAbort(err) || signal.aborted) return value;
      throw err;
    });
  }

  /**
   * The page right after an action, as lines of the page's words (for inside
   * the tags): what the point hit, the page it is on now if that changed,
   * where the keyboard is and what that field holds, and what the page
   * announced. Best-effort, and only while the tab is on the site the action
   * was judged on: another site is read only once the user has allowed it.
   */
  async function aftermath(before: WorkTab, after: WorkTab | null, hit?: ElementInfo, scrolledAt?: { x: number; y: number }): Promise<string[]> {
    const lines: string[] = [];
    if (hit) lines.push(`It hit: ${hitLine(hit)}.`);
    if (!after || !after.host || after.host !== before.host) return lines;
    if (after.url !== before.url) lines.push(`The page is now "${clip(after.title, 100) || "(untitled)"}" at ${whereTo(after.url)}.`);
    const seen = await orOnStop(deps.browser.page("observe", scrolledAt ? { at: scrolledAt } : {}, after, signal, OBSERVE_MS).catch(() => null), null);
    if (!seen?.ok) return lines;
    const focus = seen.focus as ElementInfo | undefined;
    if (focus) remember(after.id, [focus]);
    lines.push(focus ? `The keyboard is in: ${focusLine(focus)}.` : "Nothing has the keyboard focus.");
    const said = Array.isArray(seen.said) ? (seen.said as Array<{ kind: string; text: string }>) : [];
    for (const item of said) lines.push(item.kind === "dialog" ? `A dialog shows: "${item.text}"` : `The page announced: "${item.text}"`);
    // After the wheel: what scrolled under the point - a list, or the page - and how much of it is left.
    if (scrolledAt && typeof seen.scrolled === "string") lines.push(`${seen.scrolled.replace(/^./, (c) => c.toUpperCase())}.`);
    return lines;
  }

  /**
   * Where the run starts, for the first message: the tab's title and address
   * and how much of the page the window shows - the page's words, inside the
   * tags. Nothing for a page the agent may not work on.
   */
  async function startingPoint(tab: WorkTab): Promise<string | null> {
    if (!tab.host) return null;
    if (classifyAction({ tool: "read_page", args: {}, page: { url: tab.url, host: tab.host } }, options.rules).class === "blocked") return null;
    const seen = await raced(deps.browser.page("observe", {}, tab, signal, OBSERVE_MS).catch(() => null));
    check();
    const view = seen?.ok ? (seen.view as View | undefined) : undefined;
    const lines = [`"${clip(tab.title, 100) || "(untitled)"}" at ${whereTo(tab.url)}.`];
    if (view) {
      lines.push(`The window shows ${view.width}×${view.height} CSS pixels of a page ${view.pageWidth}×${view.pageHeight}, ${view.scrollY ? `${view.scrollY} pixels down from the top` : "at its top"}.`);
    }
    return `Where you start - the tab next to the side panel:\n${pageText(wrapPage(options.nonce, tab.host, lines.join("\n"))!, true)}`;
  }

  /** Best-effort: the visuals never fail a run, nor hold it up for long, nor outlast a Stop. */
  async function visual(method: PageMethod, a: Record<string, unknown>, tab: WorkTab | null): Promise<void> {
    if (!tab || !deps.driver) return;
    await orOnStop(deps.browser.page(method, a, tab, signal, VISUAL_MS).catch(() => undefined), undefined);
  }

  /** What the run is doing: the page's border (under full control) and the badge. */
  async function state(next: RunState, tab: WorkTab | null): Promise<void> {
    deps.onState?.(next);
    await visual("visuals_state", { state: next }, tab);
  }

  /**
   * A safe point: while the person has the run paused, nothing goes on until
   * they resume - or stop. What was under way (a judgment, an approval) is
   * done again after, since the page may have changed under them.
   */
  async function gate(tab: WorkTab | null): Promise<void> {
    if (!deps.pause?.paused()) return;
    await state("paused", tab);
    await raced(deps.pause.wait());
    check();
    await state("working", tab);
  }

  /** Take a screenshot with the layer veiled, best-effort; the data URL, or undefined on any failure. */
  async function visualCapture(work: () => Promise<{ dataUrl: string }>, tab: WorkTab): Promise<string | undefined> {
    await visual("visuals_veil", { veiled: true }, tab);
    try {
      const shot = await raced(work());
      return shot.dataUrl;
    } catch {
      return undefined;
    } finally {
      await visual("visuals_veil", { veiled: false }, tab);
    }
  }

  /**
   * The step changed the page: a fresh look at it, as an image after the
   * step's answers, so the model sees what its actions did without asking.
   * Only under full control, on a site the user let the agent work on, and
   * where the rules let a screenshot of it go; nothing on any failure.
   */
  async function lookAfter(): Promise<Answer["image"] | undefined> {
    const driver = deps.driver;
    if (!driver) return undefined;
    const tab = await deps.browser.current();
    check();
    if (!tab?.host || !allowedSites.has(tab.host)) return undefined;
    if (classifyAction({ tool: "screenshot", args: {}, page: { url: tab.url, host: tab.host } }, options.rules).class === "blocked") return undefined;
    if (driver.use && !(await raced(driver.use(tab.id, tab.url)))) return undefined;
    check();
    await visual("visuals_veil", { veiled: true }, tab);
    try {
      const shot = await raced(driver.screenshot());
      const size = `${shot.frame.width}×${shot.frame.height}`;
      return { url: shot.dataUrl, caption: `The page after this step (${size}). Coordinates for computer are in this image's pixels.` };
    } catch (err) {
      if (isAbort(err) || signal.aborted) throw err;
      return undefined;
    } finally {
      await visual("visuals_veil", { veiled: false }, tab);
    }
  }

  const invalid = (message: string): Answer => ({ content: message, status: "error", outcome: "error", extra: { error: "invalid_arguments" } });

  /** The person took over the page before this action landed: not a failure of the agent's, and not counted as one. */
  const tookOver = (done?: string): Answer => ({
    content: `Not done: the user took over the page${done ? ` (${done})` : ""}. Once they resume, look at the page again before acting.`,
    status: "skipped",
    detail: "The user took over",
    outcome: "skipped",
    extra: { error: "took_over" },
  });

  /** Watch page-derived text for instruction-like content; the next side-effecting action then asks. */
  function watch(text: string): void {
    if (injected) return;
    const probe = probeInjection(text);
    if (probe.hit) injected = probe.snippet;
  }

  /** One card at a time: a page's dialog that opens while another card waits for the user waits its turn. */
  let cards: Promise<unknown> = Promise.resolve();
  function approve(request: ApprovalRequest): Promise<ApprovalAnswer> {
    const answer = cards.then(() => (signal.aborted ? false : deps.approve(request, signal)));
    cards = answer.catch(() => undefined);
    return answer;
  }

  /**
   * What each reference named when the model was told it, per tab: an
   * element's role and name from an outline, a search or the focus. A page
   * can put something else under a reference - a list that re-rendered, the
   * next page reusing e12 - and then the model would act on what it did not
   * mean. Text and headings are not recorded: a click on words works the
   * control around them, whose role is another.
   */
  const told = new Map<string, { role: string; name: string }>();
  function remember(tabId: number, elements: Array<{ ref?: unknown; role?: unknown; name?: unknown }>): void {
    for (const e of elements) {
      if (typeof e.ref !== "string" || typeof e.role !== "string" || typeof e.name !== "string") continue;
      if (e.role === "text" || e.role === "heading") continue;
      told.set(`${tabId}:${e.ref}`, { role: e.role, name: e.name });
    }
  }

  /** The page's dialogs answered since the last action's result, told to the model with that result. */
  const dialogNotes: string[] = [];

  /**
   * A dialog the page opened (alert, confirm, prompt, or "leave this page?"),
   * answered as it opens: until it is, the page - and the input that opened
   * it - wait. An alert is closed and its message told to the model; a
   * question is the user's to answer, unless the administrator lets the agent
   * accept them - a prompt is then dismissed, as the agent has no answer to
   * type. The page cannot be reached while the dialog is up, so the border
   * stays as it is; the badge shows the wait.
   */
  async function answerDialog(dialog: { type?: string; message?: string }, answer?: (accept: boolean, promptText?: string) => Promise<void>): Promise<void> {
    dialogsOpen += 1;
    try {
      await answerOneDialog(dialog, answer);
    } finally {
      dialogsOpen -= 1;
    }
  }

  async function answerOneDialog(dialog: { type?: string; message?: string }, answer?: (accept: boolean, promptText?: string) => Promise<void>): Promise<void> {
    const driver = deps.driver;
    if (!driver) return;
    // To the tab that asked: the agent may be on another by the time the user answers.
    const respond = answer ?? ((accept: boolean, promptText?: string) => driver.handleDialog(accept, promptText));
    const message = clip(String(dialog.message ?? ""), 300);
    watch(message);
    const shown = message ? ` "${message}"` : "";
    if (dialog.type === "alert") {
      await respond(true).catch(() => undefined);
      dialogNotes.push(`The page showed a message:${shown}`);
      return;
    }
    const kind = dialog.type === "beforeunload" ? "asks whether to leave the page" : dialog.type === "prompt" ? "asks for an answer" : "asks to confirm";
    const asks = (options.rules.approvals ?? DEFAULT_APPROVALS).dialogs;
    let accept: boolean;
    if (signal.aborted) {
      accept = false;
    } else if (asks) {
      deps.onState?.("waiting");
      accept = Boolean(await approve({
        tool: "dialog",
        summary: `The page ${kind}:${shown || " (no message)"} - Allow accepts it, Deny dismisses it`,
        verdict: { class: "sensitive", reason: "dialog", message: `The page ${kind}.` },
      }).catch(() => false));
      deps.onState?.("working");
    } else {
      accept = dialog.type !== "prompt";
    }
    if (accept && dialog.type === "prompt") await respond(true, "").catch(() => undefined);
    else await respond(accept).catch(() => undefined);
    dialogNotes.push(`The page ${kind}:${shown} - it was ${accept ? "accepted" : "dismissed"}${asks && !signal.aborted ? " by the user" : ""}.`);
  }

  /**
   * An action's result with the page's dialogs it opened, which are the
   * page's words: inside the page tags, first - they came up during the
   * action, before what the page was like after it.
   */
  function withDialogs(answer: Answer, site: string): Answer {
    const notes = dialogNotes.splice(0);
    if (!notes.length) return answer;
    if (answer.page) return { ...answer, page: { ...answer.page, body: [...notes, answer.page.body].filter(Boolean).join("\n") } };
    return { ...answer, page: wrapPage(options.nonce, site, notes.join("\n")) };
  }

  /**
   * The agent's own input, inside a window the page knows about: a trusted
   * event outside one is the person's, and pauses the run. A page already
   * paused - the person took over an instant ago - gets nothing (null).
   */
  async function inputWindow<T>(tab: WorkTab, work: () => Promise<T>): Promise<T | null> {
    const opened = await raced(deps.browser.page("takeover_dispatch", { on: true }, tab, signal, VISUAL_MS).catch(() => null));
    if (opened?.ok && opened.paused === true) return null;
    try {
      return await raced(work());
    } finally {
      await visual("takeover_dispatch", { on: false }, tab);
    }
  }

  /**
   * A reference action under full control, with the real mouse and keyboard
   * at the element: the page says where it is (bringing it into view only
   * when needed) and what is there now, which must be what the rules judged;
   * the mouse presses its centre, and typing goes where that click put the
   * keyboard - checked first. Answered as the page's own actions are.
   */
  async function byHand(tool: string, a: Record<string, unknown>, tab: WorkTab, judged: ElementInfo | undefined): Promise<PageResult> {
    const driver = deps.driver!;
    if (tool === "press_key") {
      const key = String(a.key ?? "");
      const pressed = await inputWindow(tab, () => driver.key(key));
      if (pressed === null) return { ok: false, error: "paused", message: "The user took over this page." };
      return pressed ? { ok: true, note: "" } : { ok: false, error: "bad_key", message: `The agent cannot press "${clip(key, 40)}".` };
    }
    const located = await page("locate", { ref: a.ref, activates: tool === "click" }, tab);
    if (!located.ok) return located;
    const now = located.element as ElementInfo | undefined;
    const rect = located.rect as PointRect | undefined;
    if (!now || !rect) return { ok: false, error: "failed", message: "Where the element is could not be read." };
    // Judged twice: what is there now is what the rules judged, or nothing is pressed.
    if (judged && !sameTarget(judged, now)) return { ok: false, error: "changed", message: "The element is not what it was when this action was judged." };
    // A date, a time, a colour: the keyboard fills such a field one part at a time, the page's own way sets it whole.
    if (tool === "type_text" && now.tag === "input" && WHOLE_VALUE_TYPES.has(now.type ?? "")) return await page("type_text", a, tab);
    // Typing into a text area or an editor starts where a person clicks to start: its first line, above a signature or a quote.
    // Its middle may be a signature, or empty space whose click puts the caret at the end of it.
    const multiLine = tool === "type_text" && now.tag !== "input";
    const at = multiLine
      ? { x: rect.x + Math.min(12, rect.width / 2), y: rect.y + Math.min(12, rect.height / 2) }
      : { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
    await visual("visuals_target", { rect }, tab);
    await visual("visuals_cursor", { x: at.x, y: at.y, click: "left" }, tab);
    // Judged again right before the press, as a computer click is: the showing took a moment, and the page may have
    // moved the element (an animation, a late layout) - the press is made only where it still is.
    const again = await page("locate", { ref: a.ref, activates: tool === "click" }, tab);
    if (!again.ok) return again;
    const still = again.element as ElementInfo | undefined;
    const there = again.rect as PointRect | undefined;
    if (!still || !there || !sameTarget(now, still) || !closeTo(rect, there)) {
      return { ok: false, error: "changed", message: "The element moved or changed while the agent was about to press it." };
    }
    const clicked = await inputWindow(tab, () => driver.clickAt(at, { button: "left", clickCount: 1 }));
    if (clicked === null) return { ok: false, error: "paused", message: "The user took over this page." };
    if (tool === "click") return { ok: true, note: "" };
    // The keyboard must be in the field the click was for: text typed anywhere else goes where it should not.
    const focus = await page("describe_focus", {}, tab);
    const into = focus.ok ? (focus.element as ElementInfo | undefined) : undefined;
    if (!into || (into.ref !== now.ref && (into.role !== now.role || into.name !== now.name))) {
      return { ok: false, error: "no_focus", message: into ? `The click left the keyboard in ${into.role} "${clip(into.name, 60)}", not in that field.` : "After the click, nothing has the keyboard." };
    }
    const text = String(a.text ?? "");
    if (a.clear === true) {
      // Select all of it, then delete: the field's own editing, as a person clears it.
      if ((await inputWindow(tab, () => driver.key("ctrl+a"))) === null || (await inputWindow(tab, () => driver.key("Delete"))) === null) {
        return { ok: false, error: "paused", message: "The user took over this page." };
      }
    }
    const typing = now.tag === "input" ? text.replace(/\s*\n\s*/g, " ") : text;
    if ((await inputWindow(tab, () => driver.type(typing))) === null) {
      // What was done before the take-over is said: a field cleared and left empty is not one untouched.
      return { ok: false, error: "paused", message: a.clear === true ? TOOK_OVER_AFTER_CLEARING : "The user took over this page." };
    }
    return { ok: true, note: `Typed ${typing.length} characters${a.clear === true ? ", in place of what was there" : ""}.` };
  }

  /** Full control: screenshots and the real mouse and keyboard, through the run's driver. */
  async function control(tool: string, a: Record<string, unknown>, tab: WorkTab, hit?: ElementInfo): Promise<Answer> {
    const driver = deps.driver;
    if (!driver) return { content: "Full control is not on for this run: use read_page and the reference tools.", status: "error", outcome: "error", extra: { error: "no_control" } };
    const site = tab.host ?? "";
    const race = <T>(work: Promise<T>) => raced(work);
    const dispatch = <T>(work: () => Promise<T>) => inputWindow(tab, work);
    // The layer is veiled for a capture: the model must never see the cursor or the border.
    const capture = async <T>(work: () => Promise<T>): Promise<T> => {
      await visual("visuals_veil", { veiled: true }, tab);
      try {
        return await race(work());
      } finally {
        await visual("visuals_veil", { veiled: false }, tab);
      }
    };
    if (tool === "screenshot") {
      const shot = await capture(() => driver.screenshot());
      check();
      const size = `${shot.frame.width}×${shot.frame.height}`;
      return {
        content: `Screenshot taken (${size} pixels). Coordinates for computer are in these pixels.`,
        status: "done",
        detail: size,
        outcome: "ok",
        image: { url: shot.dataUrl, caption: `The page (${size}). Coordinates for computer are in this image's pixels.` },
      };
    }
    if (tool === "zoom") {
      const r = Array.isArray(a.region) ? a.region.map(Number) : [];
      if (r.length !== 4 || r.some((n) => !Number.isFinite(n)) || r[2] <= r[0] || r[3] <= r[1]) return invalid("zoom needs region [x0, y0, x1, y1] with x1 > x0 and y1 > y0.");
      const shot = await capture(() => driver.zoom({ x: r[0], y: r[1], width: r[2] - r[0], height: r[3] - r[1] }));
      check();
      return {
        content: `Zoomed into [${r.join(", ")}].`,
        status: "done",
        detail: `[${r.join(", ")}]`,
        outcome: "ok",
        image: { url: shot.dataUrl, caption: `${ZOOM_CAPTION} Its pixels are not page coordinates: use the last full screenshot for those.` },
      };
    }
    // computer
    const action = String(a.action ?? "");
    const spec = COMPUTER_ACTIONS[action];
    if (!spec) return invalid("computer needs one of: left_click, right_click, double_click, triple_click, hover, left_click_drag, scroll, type, key, wait.");
    const modifiers = typeof a.modifiers === "string" ? a.modifiers.split("+").map((m) => m.trim()).filter(Boolean) : [];
    let note: string;
    /** Where the wheel turned, in CSS pixels: what scrolled there is reported after. */
    let wheelAt: { x: number; y: number } | undefined;
    if (spec.element === "point" || action === "scroll") {
      const p = point(a.coordinate);
      if (!p) return invalid(`${action} needs coordinate [x, y].`);
      const css = await raced(driver.toCss(p));
      if (action === "scroll") wheelAt = css;
      if (action === "scroll") {
        const ticks = Math.min(10, Math.max(1, Number(a.scroll_amount) || 3));
        const px = ticks * 100;
        const dir = String(a.scroll_direction ?? "down");
        const delta = dir === "up" ? { y: -px } : dir === "left" ? { x: -px } : dir === "right" ? { x: px } : { y: px };
        await visual("visuals_cursor", { x: css.x, y: css.y }, tab);
        if ((await dispatch(() => driver.scroll(p, delta))) === null) return tookOver();
        note = `Scrolled ${dir} ${ticks} ticks at (${p.x}, ${p.y}).`;
      } else if (action === "hover") {
        await visual("visuals_cursor", { x: css.x, y: css.y }, tab);
        if ((await dispatch(() => driver.hover(p, modifiers))) === null) return tookOver();
        note = `Hovering at (${p.x}, ${p.y}).`;
      } else {
        await visual("visuals_cursor", { x: css.x, y: css.y, click: spec.kind }, tab);
        const clickCount = spec.kind === "double" ? 2 : spec.kind === "triple" ? 3 : 1;
        if ((await dispatch(() => driver.click(p, { button: spec.kind === "right" ? "right" : "left", clickCount, modifiers }))) === null) return tookOver();
        note = `${spec.kind === "right" ? "Right-clicked" : spec.kind === "double" ? "Double-clicked" : spec.kind === "triple" ? "Triple-clicked" : "Clicked"} at (${p.x}, ${p.y}).`;
      }
    } else if (action === "left_click_drag") {
      const from = point(a.start_coordinate);
      const to = point(a.coordinate);
      if (!from || !to) return invalid("left_click_drag needs start_coordinate and coordinate.");
      const cssTo = await raced(driver.toCss(to));
      await visual("visuals_cursor", { x: cssTo.x, y: cssTo.y }, tab);
      const result = await dispatch(() => driver.drag(from, to));
      if (result === null) return tookOver();
      note = `Dragged from (${from.x}, ${from.y}) to (${to.x}, ${to.y})${result.intercepted ? "" : " (as a pointer drag)"}.`;
    } else if (action === "type") {
      const text = typeof a.text === "string" ? a.text : "";
      if (!text) return invalid("type needs text.");
      if ((await dispatch(() => driver.type(text))) === null) return tookOver();
      note = `Typed ${text.length} characters.`;
    } else if (action === "key") {
      // As the rules read it: one character alone (a space) is that key, anything longer is trimmed.
      const key = typeof a.text === "string" ? ([...a.text].length === 1 ? a.text : a.text.trim()) : "";
      if (!key) return invalid("key needs the key to press in text, such as Enter or ctrl+a.");
      const pressed = await dispatch(() => driver.key(key));
      if (pressed === null) return tookOver();
      if (!pressed) return { content: `The agent cannot press "${clip(key, 40)}".`, status: "error", detail: "Unknown key", outcome: "error", extra: { error: "bad_key" } };
      note = `Pressed ${key}.`;
    } else {
      const seconds = Math.min(10, Math.max(0, Number(a.duration) || 1));
      await race(new Promise<void>((resolve) => setTimeout(resolve, seconds * 1000)));
      note = `Waited ${seconds} s.`;
    }
    check();
    await race(deps.browser.settle());
    check();
    const after = await deps.browser.current();
    check();
    const moved = after?.host && after.host !== site && !allowedSites.has(after.host) ? `\n${elsewhere(after.host)}` : "";
    // What was pressed, and where the keyboard went: the model checks this before it types.
    const saw = await aftermath(tab, after, spec.element === "point" || spec.element === "start" ? hit : undefined, action === "scroll" ? wheelAt : undefined);
    check();
    return { content: `${note}${moved}`, ...(saw.length ? { page: wrapPage(options.nonce, site, saw.join("\n")) } : {}), status: "done", detail: note, outcome: "ok" };
  }

  /** Carry out one allowed action; everything the page says comes back wrapped. */
  async function execute(tool: string, a: Record<string, unknown>, tab: WorkTab | null, element?: ElementInfo, controlled = false): Promise<Answer> {
    const site = tab?.host ?? "";
    if (tool === "tabs_list") {
      const tabs = await deps.browser.listTabs();
      const lines = tabs.map((t) => {
        const readable = t.host !== null && classifyAction({ tool: "read_page", args: {}, page: { url: t.url, host: t.host } }, options.rules).class !== "blocked";
        const label = readable ? `${clip(t.title || t.host!, 100)} (${t.host})` : "(a tab the agent may not read)";
        return `[${t.id}] ${label}${t.id === tab?.id ? " - you work here" : ""}`;
      });
      const body = lines.join("\n") || "(no tabs)";
      watch(body);
      return { content: "The open tabs of this window, by id:", page: wrapPage(options.nonce, "browser tabs", body), status: "done", detail: `${tabs.length} tabs`, outcome: "ok" };
    }
    if (tool === "tab_open" || tool === "navigate") {
      const url = String(a.url);
      let next: WorkTab;
      try {
        next = tool === "tab_open" ? await deps.browser.openTab(url) : await deps.browser.navigate(url);
      } catch (err) {
        // The browser would not: the tab limit, a tab that is gone. The model is told, and the run goes on.
        const message = err instanceof Error && err.message ? clip(err.message, 200) : "The browser could not open it.";
        return { content: message, status: "error", detail: message, outcome: "error", extra: { error: "browser_refused" } };
      }
      await raced(deps.browser.settle());
      check();
      // Where the tab is once it settled - the browser answers the update with the page it was leaving -
      // and inside the page tags: a page's address, down to its path, is the page's own words.
      const now = await deps.browser.current();
      check();
      const shows = now?.host ? whereTo(now.url) : "a page the agent cannot read";
      const moved = now?.host && !allowedSites.has(now.host) ? `\n${elsewhere(now.host)}` : "";
      const said = tool === "tab_open" ? `Opened a new tab (id ${next.id}); you work there now.` : "The tab has loaded.";
      return {
        content: said + moved,
        page: wrapPage(options.nonce, now?.host ?? "browser tabs", `It shows ${shows}.`),
        status: "done",
        outcome: "ok",
        site: now?.host ?? next.host ?? undefined,
      };
    }
    if (tool === "tab_switch") {
      const next = await deps.browser.switchTab(Number(a.tab_id));
      if (!next) return { content: `There is no tab ${String(a.tab_id)} in this window.`, status: "error", detail: "No such tab", outcome: "error", extra: { error: "no_tab" } };
      return {
        content: `You work in tab ${next.id} now.`,
        page: wrapPage(options.nonce, next.host ?? "browser tabs", `${clip(next.title, 100) || "(no title)"} (${next.host ?? "no web page"})`),
        status: "done",
        outcome: "ok",
        site: next.host ?? undefined,
      };
    }
    if (!tab) return { content: "The tab does not show a web page the agent can work on.", status: "error", outcome: "error", extra: { error: "no_page" } };
    if (CONTROL_TOOL_NAMES.has(tool)) return control(tool, a, tab, element);
    // Under full control, clicks, typing and keys by reference go through the real mouse and keyboard, as a person's do.
    const result = controlled && BY_HAND.has(tool) ? await byHand(tool, a, tab, element) : await page(tool as PageMethod, a, tab);
    if (!result.ok && result.error === "paused") return tookOver(result.message === TOOK_OVER_AFTER_CLEARING ? "after the field was cleared, before the text went in" : undefined);
    if (!result.ok) {
      return {
        content: notDone(result.error),
        page: wrapPage(options.nonce, site, result.message),
        status: "error",
        detail: result.message,
        outcome: "error",
        extra: { error: result.error },
      };
    }
    let moved = "";
    let after: WorkTab | null = tab;
    if (MAY_LOAD.has(tool)) {
      await raced(deps.browser.settle());
      check();
      after = await deps.browser.current();
      check();
      if (after?.host && after.host !== site && !allowedSites.has(after.host)) moved = elsewhere(after.host);
    }
    let body: string;
    let detail: string | undefined;
    if (tool === "read_page") {
      body = String(result.outline ?? "");
      detail = `${Array.isArray(result.elements) ? result.elements.length : 0} elements`;
      if (Array.isArray(result.elements)) remember(tab.id, result.elements as ElementInfo[]);
    } else if (tool === "get_page_text") {
      body = String(result.text ?? "") + (result.truncated ? "\n(The text was cut here.)" : "");
    } else if (tool === "find") {
      const matches = Array.isArray(result.matches) ? (result.matches as Array<{ ref: string; role: string; name: string; snippet?: string }>) : [];
      remember(tab.id, matches);
      body = matches.map((m) => `[${m.ref}] ${m.role}${m.name ? ` "${m.name}"` : ""}${m.snippet ? ` - ${m.snippet}` : ""}`).join("\n");
      detail = `${matches.length} found`;
    } else {
      // What the page said it did (the option it chose, how much the field holds): the page's words.
      body = typeof result.note === "string" ? result.note : "";
      detail = typeof result.note === "string" ? result.note : undefined;
    }
    // What the page just showed the agent - its outline, its text, a search's matches - may carry instructions aimed at it.
    if (tool === "read_page" || tool === "get_page_text" || tool === "find") watch(body);
    const read = tool === "read_page" ? "outline" : tool === "get_page_text" || tool === "find" ? "text" : undefined;
    // After an action, what the page is like now: the model learns whether its text went where it meant.
    if (AFTERMATH.has(tool)) body = [body, ...(await aftermath(tab, after))].filter(Boolean).join("\n");
    check();
    return {
      content: [read ? "" : "Done.", moved].filter(Boolean).join("\n"),
      ...(read || body ? { page: wrapPage(options.nonce, site, body) } : {}),
      ...(read ? { read } : {}),
      status: "done",
      detail,
      outcome: "ok",
    };
  }

  /** One tool call from the model: through the rules, maybe past the user, then carried out. */
  async function handle(call: ToolCall, skip: string | null): Promise<Answer & { denied?: boolean }> {
    const name = call.function.name;
    let a = args(call.function.arguments);
    if (skip) return { content: skip, status: "skipped", outcome: "skipped" };
    if (!a) return { content: "The arguments were not valid JSON for this tool. Send them again.", status: "error", detail: "Invalid arguments", outcome: "error", extra: { error: "invalid_arguments" } };
    if (name === "done") {
      const summary = typeof a.summary === "string" && a.summary.trim() ? clip(a.summary.trim(), 4000) : "Done.";
      return { content: "Finished.", status: "done", outcome: "ok", finish: summary };
    }
    if (name === "ask_user") {
      const question = typeof a.question === "string" && a.question.trim() ? clip(a.question.trim(), 1000) : "";
      if (!question) return { content: "Say what to ask the user.", status: "error", outcome: "error", extra: { error: "invalid_arguments" } };
      deps.onStep({ id: call.id, tool: name, summary: `Question: ${question}`, status: "waiting" });
      // Waiting on the person, as the page's border and the badge say - the question's card comes first.
      const shown = state("waiting", lastTab);
      const answer = (await deps.askUser(question, signal)).trim();
      await shown;
      await state("working", lastTab);
      check();
      return {
        content: answer ? `The user answered: ${clip(answer, 4000)}` : "The user did not answer.",
        status: "done",
        detail: answer ? clip(answer, 200) : "No answer",
        outcome: "ok",
      };
    }
    if (name === "update_plan") {
      if (options.mode !== "plan") {
        return { content: "There is no plan to set in this mode.", status: "error", outcome: "error", extra: { error: "no_plan" } };
      }
      const summary = typeof a.summary === "string" ? clip(a.summary.trim(), 1000) : "";
      const rawSites = Array.isArray(a.sites) ? a.sites : [];
      // Each site as a host, and only ones the rules do not keep out: a plan cannot grant a blocked site.
      const sites: string[] = [];
      const refused: string[] = [];
      for (const raw of rawSites.slice(0, 50)) {
        const page = typeof raw === "string" ? readablePage(/^https?:/i.test(raw) ? raw : `https://${raw.trim()}`) : null;
        if (!page) continue;
        const verdict = classifyAction({ tool: "read_page", args: {}, page: { url: page.origin, host: page.host } }, options.rules);
        if (verdict.class === "blocked") refused.push(page.host);
        else if (!sites.includes(page.host)) sites.push(page.host);
      }
      if (!summary || !sites.length) {
        return { content: "A plan needs a short summary and at least one site the agent may work on.", status: "error", detail: "Incomplete plan", outcome: "error", extra: { error: "invalid_plan" } };
      }
      const shown = `Plan: ${summary}\nSites: ${sites.join(", ")}${refused.length ? `\n(Not allowed, left out: ${refused.join(", ")})` : ""}`;
      deps.onStep({ id: call.id, tool: name, summary: shown, status: "waiting" });
      const waiting = state("waiting", lastTab);
      const ok = Boolean(await approve({ tool: "update_plan", summary: shown, verdict: { class: "sensitive", reason: "plan", message: "Approve this plan; the agent then works these sites without asking each action." } }));
      await waiting;
      await state("working", lastTab);
      check();
      if (!ok) {
        return { content: "The user did not approve the plan. Revise the approach or the sites and propose it again, or ask them what they want.", status: "denied", detail: "Plan not approved", outcome: "denied" };
      }
      planApproved = true;
      for (const host of sites) allowedSites.add(host);
      return { content: `Plan approved. You may act on: ${sites.join(", ")}. Anywhere else, and the actions that always ask, still ask.`, status: "done", detail: `${sites.length} sites`, outcome: "ok", extra: { sites: sites.length } };
    }
    const tab = await deps.browser.current();
    check();
    // Full control follows the tab the agent works in: its own session, attached the first time the agent works there -
    // for its mouse and screenshots, and so that a dialog the page opens is seen, whatever the tool.
    /** Whether this tab is under full control: then reference actions use the real mouse and keyboard too. */
    let controlled = Boolean(deps.driver && tab);
    if (deps.driver?.use && tab && PAGE_TOOLS.has(name)) {
      controlled = await raced(deps.driver.use(tab.id, tab.url));
      check();
      if (!controlled && CONTROL_TOOL_NAMES.has(name)) {
        return {
          content: "Full control is not available on this tab: the browser would not let the extension attach to it. Use read_page and the reference tools here.",
          status: "error",
          detail: "No full control on this tab",
          outcome: "error",
          extra: { error: "no_control" },
        };
      }
    }
    const pageNow = tab?.host ? { url: tab.url, host: tab.host } : undefined;
    // Nothing is asked of a page the agent may not work on, not even a description: the rules refuse the action below.
    const workable = Boolean(tab && pageNow && classifyAction({ tool: "read_page", args: {}, page: pageNow }, options.rules).class !== "blocked");
    let element: ElementInfo | undefined;
    /** The action goes where the keyboard is, and was judged by what had it: it is judged again just before. */
    let byFocus = false;
    /** When the reference named something else by now and the element meant was found again: said with the result. */
    let refNote: string | undefined;
    if (name === "press_key" && workable && tab) {
      // A key goes to the focused element, which decides what it does: Enter in a message box sends it.
      const focus = await page("describe_focus", {}, tab);
      byFocus = focus.ok;
      if (focus.ok && focus.element) element = focus.element as ElementInfo;
    } else if (ELEMENT_TOOLS.has(name) || (name === "scroll" && typeof a.ref === "string")) {
      if (!workable || !tab || !pageNow) {
        // The rules refuse it below, with the reason.
      } else {
        // For a click, the control it works on: the button around the words, the field of a label.
        const describeRef = (ref: unknown) =>
          page("describe", { ref, ...(name === "click" ? { activates: true } : {}), ...(name === "select_option" ? { choose: a!.value } : {}) }, tab);
        let described = await describeRef(a.ref);
        if (!described.ok) {
          return { content: notDone(described.error), page: wrapPage(options.nonce, pageNow.host, described.message), status: "error", detail: described.message, outcome: "error", site: pageNow.host, extra: { error: described.error } };
        }
        element = described.element as ElementInfo;
        // What the model was told this reference names: if the page put something else under it, that is not acted on.
        const was = typeof a.ref === "string" ? told.get(`${tab.id}:${a.ref}`) : undefined;
        if (was && (was.role !== element.role || looseName(was.name) !== looseName(element.name))) {
          const then = `${a.ref as string} was ${was.role} "${clip(was.name, 60)}" when you were told it, and is ${element.role} "${clip(element.name, 60)}" now`;
          // The same element may still be there under another reference: when exactly one matches, that is the one meant.
          const again = await page("find_ref", { role: was.role, name: was.name }, tab);
          const refs = again.ok && Array.isArray(again.refs) ? (again.refs as string[]) : [];
          const found = refs.length === 1 ? await describeRef(refs[0]) : null;
          if (!found?.ok) {
            return {
              content: "Not done (changed): that reference names something else on the page now. Read the page again for fresh references.",
              page: wrapPage(options.nonce, pageNow.host, `${then}.${refs.length > 1 ? ` ${refs.length} elements match what it was.` : ""}`),
              status: "error",
              detail: "The reference changed",
              outcome: "error",
              site: pageNow.host,
              extra: { error: "ref_changed" },
            };
          }
          described = found;
          element = described.element as ElementInfo;
          refNote = `${then}: the action went to ${refs[0]}, which is what ${a.ref as string} was.`;
          a = { ...a, ref: refs[0] };
          remember(tab.id, [element]);
        }
      }
    }
    // A computer action is judged as the action it amounts to, on what a click there (or the focus) would touch.
    let judgedAs = name;
    let judgedArgs = a;
    let targetRect: PointRect | undefined;
    /** For a point action: where the mouse will press, in CSS pixels, so the target can be judged again just before. */
    let pressAt: { x: number; y: number; activates: boolean } | undefined;
    let drop: ElementInfo | undefined;
    if (name === "computer") {
      const spec = COMPUTER_ACTIONS[String(a.action ?? "")];
      if (!spec) return invalid("computer needs one of: left_click, right_click, double_click, triple_click, hover, left_click_drag, scroll, type, key, wait.");
      judgedAs = spec.as;
      judgedArgs =
        spec.as === "type_text"
          ? { text: a.text }
          : spec.as === "press_key"
            ? { key: a.text }
            : spec.as === "scroll"
              ? { direction: a.scroll_direction }
              : spec.as === "click" && typeof a.modifiers === "string"
                ? { modifiers: a.modifiers }
                : {};
      if (workable && tab && pageNow && deps.driver) {
        if (spec.element === "point" || spec.element === "start") {
          const p = point(spec.element === "start" ? a.start_coordinate : a.coordinate);
          if (!p) return invalid(`${String(a.action)} needs ${spec.element === "start" ? "start_coordinate" : "coordinate"} [x, y].`);
          const css = await raced(deps.driver.toCss(p));
          pressAt = { x: css.x, y: css.y, activates: spec.as === "click" };
          const described = await page("describe_at", pressAt, tab);
          if (!described.ok) {
            return { content: notDone(described.error), page: wrapPage(options.nonce, pageNow.host, described.message), status: "error", detail: described.message, outcome: "error", site: pageNow.host, extra: { error: described.error } };
          }
          element = described.element as ElementInfo;
          targetRect = described.rect as PointRect;
          if (spec.as === "drag") {
            // Where it drops: judged too, since a drop on an upload zone uploads.
            const end = point(a.coordinate);
            if (!end) return invalid("left_click_drag needs coordinate [x, y] to drop at.");
            const endCss = await raced(deps.driver.toCss(end));
            const dropped = await page("describe_at", { x: endCss.x, y: endCss.y, activates: false }, tab);
            if (dropped.ok) drop = dropped.element as ElementInfo;
          }
        } else if (spec.element === "focus") {
          const focus = await page("describe_focus", {}, tab);
          byFocus = focus.ok;
          if (focus.ok && focus.element) element = focus.element as ElementInfo;
          // Text typed with nothing focused goes nowhere - or wherever the page puts it: the field comes first.
          if (focus.ok && !focus.element && spec.as === "type_text") {
            return {
              content: "Not typed: nothing on the page has the keyboard focus. Click the field first, check that the result says the keyboard is in it, then type.",
              status: "error",
              detail: "Nothing focused",
              outcome: "error",
              site: pageNow.host,
              extra: { error: "no_focus" },
            };
          }
        }
      }
    }
    // A key read through the same table as the keyboard's: one it does not know is a mistake to correct, not an action to judge.
    if (judgedAs === "press_key" && !parseKeyCombo(judgedArgs.key)) {
      return invalid(`"${clip(String(judgedArgs.key ?? ""), 40)}" is not a key the agent can press. It can press ${KEY_NAMES_SHOWN}.`);
    }
    // Deletion keys, one after another: past a run of them the next asks, whatever the mode.
    const deletionKey = judgedAs === "press_key" && ["Backspace", "Delete"].includes(parseKeyCombo(judgedArgs.key)?.key ?? "");
    if (deletionKey) deletionsInARow += 1;
    else if (!READ_ONLY.has(judgedAs)) deletionsInARow = 0;
    let target: SwitchTarget | undefined;
    if (name === "tab_switch") {
      const found = (await deps.browser.listTabs()).find((t) => t.id === Number(a.tab_id));
      check();
      if (found) {
        const readable = found.host !== null && classifyAction({ tool: "read_page", args: {}, page: { url: found.url, host: found.host } }, options.rules).class !== "blocked";
        target = { id: found.id, url: found.url, host: found.host, title: found.title, readable };
      }
    }
    const summary = name === "computer" ? describeComputer(a, element, drop) : describeAction(name, a, element, target);
    const verdict = TOOL_NAMES.has(name)
      ? classifyAction({ tool: judgedAs, args: judgedArgs, page: pageNow, element, drop, target: target && { url: target.url, host: target.host } }, options.rules)
      : ({ class: "blocked", reason: "unknown_tool", message: `The agent has no tool called ${clip(name, 40)}.` } as Verdict);
    const base = {
      site: verdict.site ?? pageNow?.host,
      extra: {
        class: verdict.class,
        reason: verdict.reason,
        ...(element ? { role: element.role, label: element.name } : {}),
        ...(name === "type_text" && typeof a.text === "string" ? { chars: a.text.length } : {}),
        // The key by its one name, however the model spelled it; a shortcut is not logged as a key.
        ...(judgedAs === "press_key" ? loggedKey(judgedArgs.key) : {}),
        ...(verdict.site ? { to_site: verdict.site } : {}),
      } as Record<string, unknown>,
    };
    if (verdict.class === "blocked") {
      // The rules' words name the page's element, whose name is the page's words: then they go back inside the tags.
      const wrapped = Boolean(element && pageNow);
      return {
        ...base,
        summary,
        content: wrapped ? `Refused (${verdict.reason}): the agent's rules do not allow this. Why, in the rules' words:` : `Refused (${verdict.reason}): ${verdict.message}`,
        ...(wrapped ? { page: wrapPage(options.nonce, pageNow!.host, verdict.message) } : {}),
        status: "blocked",
        detail: verdict.message,
        outcome: "blocked",
      };
    }
    // Plan mode: nothing that changes the page happens until a plan is approved.
    if (options.mode === "plan" && !planApproved && verdict.class !== "read") {
      return {
        ...base,
        summary,
        content: "Propose a plan with update_plan and wait for the user to approve it before you act.",
        status: "blocked",
        detail: "No approved plan yet",
        outcome: "blocked",
        extra: { ...base.extra, reason: "no_plan" },
      };
    }
    let approval = approvalFor(verdict, options.mode);
    // A site the page went to by itself: the user decides before the agent reads or acts there, in Auto mode too.
    // Reading counts: with every site granted, nothing else would stop an inbox the tab was sent to going to the model.
    const arrived = pageNow && (PAGE_TOOLS.has(name) || verdict.class !== "read") && !allowedSites.has(pageNow.host) ? pageNow.host : null;
    let judged: Verdict = arrived
      ? { ...verdict, message: `${verdict.message} The page went to ${arrived} without being asked to; allowing this lets the agent work there.` }
      : verdict;
    if (arrived) approval = "user";
    if (deletionKey && deletionsInARow > DELETION_RUN && verdict.class === "act") {
      judged = { ...judged, message: `${judged.message} That is the ${deletionsInARow}th deletion key in a row.` };
      approval = "user";
    }
    // The last page content read like instructions to the agent: the user decides before anything changes, in every mode.
    const suspect = injected && verdict.class !== "read" ? injected : null;
    if (suspect) {
      judged = { ...judged, message: `${judged.message} The page held text that reads like instructions to the agent ("${clip(suspect, 100)}"); it is not from the user. Approve only if you meant this.` };
      approval = "user";
      base.extra.injection = true;
    }
    // The browser has to allow a site before the agent can work there, and it asks only in a click.
    let access: ApprovalRequest["access"];
    // For a link to another site, that site: the page it is on is already the agent's.
    const needs =
      judgedAs === "click" && verdict.site && element?.href && /^https?:/.test(element.href)
        ? element.href
        : PAGE_TOOLS.has(name) && pageNow
          ? pageNow.url
          : name === "navigate" || name === "tab_open"
            ? String(a.url)
            : name === "tab_switch" && target?.host
              ? target.url
              : null;
    if (needs) {
      const origin = originPattern(needs);
      if (origin && !(await deps.browser.hasAccess(needs))) {
        access = origin;
        approval = "user";
      }
      check();
    }
    let reviewNote: string | undefined;
    if (approval === "review") {
      deps.onStep({ id: call.id, tool: name, summary, status: "running", detail: "Checking with the reviewer…" });
      // A crop around the target for a vision reviewer: only under full control, and only where a screenshot of this site may leave at all.
      let crop: string | undefined;
      if (deps.driver && targetRect && tab && options.rules.data?.modelSeesScreenshots !== false) {
        // The target's box is in CSS pixels, as the page described it: crop there, not in the screenshot's pixels.
        const shot = await visualCapture(() => deps.driver!.crop(targetRect!), tab);
        if (shot) crop = shot;
      }
      const verdictFromReview = await deps.review(
        {
          task: options.task,
          tool: name,
          site: pageNow?.host ?? verdict.site ?? "",
          target: element ? reviewTarget(element) : undefined,
          arguments: a,
          history: history.slice(-HISTORY_LINES),
          crop,
        },
        signal,
      );
      check();
      if (verdictFromReview.decision === "allow") approval = "none";
      else {
        approval = "user";
        reviewNote = verdictFromReview.reason;
      }
      base.extra.review = verdictFromReview.decision;
    }
    // A plain action, asked about only because this is Ask mode: the person may allow such actions on this site for
    // the rest of the run. Never an action that always asks, nor one asked about for another reason (a site the
    // page went to, text that reads like instructions, a run of deletion keys, the browser's own permission).
    // By the rule that judged it, not by its class: a case the administrator relaxed (sending, deleting, another site)
    // is an "act" too, and is never allowed site-wide.
    const plain =
      options.mode === "ask" &&
      verdict.class === "act" &&
      PLAIN_REASONS.has(verdict.reason) &&
      (!verdict.site || verdict.site === pageNow?.host) &&
      approval === "user" &&
      !arrived &&
      !suspect &&
      !access &&
      judged.message === verdict.message;
    const plainSite = plain && pageNow ? pageNow.host : undefined;
    let approvedBy = approval === "none" ? (base.extra.review === "allow" ? "review" : "not_needed") : "user";
    if (plainSite && siteWide.has(plainSite)) {
      approval = "none";
      // The user's, given once for the site: Admin Logs tells it from an answer to this action's own card.
      approvedBy = "user_site";
    }
    if (approval === "user") {
      deps.onStep({ id: call.id, tool: name, summary, status: "waiting" });
      // The card first: the target box and the amber border go up beside it, never before it.
      const shown = Promise.all([targetRect ? visual("visuals_target", { rect: targetRect }, tab) : undefined, state("waiting", tab)]);
      const allowed = await approve({ tool: name, summary, verdict: judged, review: reviewNote, access, ...(plainSite ? { offerSite: plainSite } : {}) });
      await shown;
      await state("working", tab);
      check();
      if (allowed === "site" && plainSite) siteWide.add(plainSite);
      if (!allowed) {
        await visual("visuals_target", { rect: null }, tab);
        return {
          ...base,
          summary,
          content: "Denied: the user did not allow this action. Do not try another way around it; adapt, or finish and say why.",
          status: "denied",
          outcome: "denied",
          denied: true,
        };
      }
      approvedBy = "user";
      if (arrived) allowedSites.add(arrived);
      if (deletionKey) deletionsInARow = 0;
      if (suspect) injected = null;
    }
    // Going to another site, allowed by the user, the reviewer or the administrator's rules: the agent may work there.
    if (verdict.site) allowedSites.add(verdict.site);
    base.extra.approval = approvedBy;
    // The person may have taken over meanwhile: nothing is pressed until they resume, and the point is judged again then.
    await gate(tab);
    // Judged twice: what is under the point just before the press. The page may have changed since -
    // a layout shift, a dialog, an element that moved - and then the press is not made.
    if (pressAt && element && targetRect && tab) {
      const again = await page("describe_at", pressAt, tab);
      const now = again.ok ? (again.element as ElementInfo) : undefined;
      const rect = again.ok ? (again.rect as PointRect) : undefined;
      if (!now || !rect || !sameTarget(element, now) || !closeTo(targetRect, rect)) {
        await visual("visuals_target", { rect: null }, tab);
        const why = !now ? (again.ok ? "nothing is there now" : again.message) : "something else is there now";
        // What the page is like now, so the model need not ask for it.
        const look = options.screenshotAfterAction ? await lookAfter() : undefined;
        return {
          ...base,
          summary,
          content: `Not done: the page changed since this action was judged (${why}). ${look ? "A fresh screenshot follows: look at it" : "Take a new screenshot and look"} before you act again.`,
          ...(look ? { image: look } : {}),
          status: "error",
          detail: "The page changed",
          outcome: "error",
          extra: { ...base.extra, error: "target_changed" },
        };
      }
      targetRect = rect;
    }
    // A key or text goes wherever the keyboard is when it is sent: after an approval, or a person's take-over, that may
    // be another field (a compose box, not the search box Enter was judged in) - then nothing is sent.
    if (byFocus && tab) {
      const focus = await page("describe_focus", {}, tab);
      const now = focus.ok ? (focus.element as ElementInfo | undefined) : undefined;
      const same = element ? Boolean(now && sameTarget(element, now)) : focus.ok && !now;
      if (!same) {
        return {
          ...base,
          summary,
          content: "Not done: the keyboard is somewhere else now than when this action was judged. Look at the page, click the field you mean, then try again.",
          status: "error",
          detail: "The focus moved",
          outcome: "error",
          extra: { ...base.extra, error: "target_changed" },
        };
      }
    }
    deps.onStep({ id: call.id, tool: name, summary, status: "running" });
    if (targetRect) await visual("visuals_target", { rect: targetRect }, tab);
    let answer: Answer;
    try {
      answer = await execute(name, a, tab, element, controlled);
    } finally {
      if (targetRect) await visual("visuals_target", { rect: null }, tab);
    }
    answer = withDialogs(answer, pageNow?.host ?? tab?.host ?? "");
    if (refNote) {
      // The names are the page's words: inside the tags, first.
      answer = { ...answer, page: answer.page ? { ...answer.page, body: [refNote, answer.page.body].filter(Boolean).join("\n") } : wrapPage(options.nonce, pageNow?.host ?? "", refNote) };
    }
    return { ...answer, summary, site: answer.site ?? base.site, extra: { ...base.extra, ...(answer.extra ?? {}), ...(name === "computer" ? { action: String(a.action ?? "") } : {}) } };
  }

  let lastTab: WorkTab | null = null;
  // The page's dialogs are answered as they open, whatever the run is doing then.
  deps.driver?.onDialog(answerDialog);
  try {
    const first = await deps.browser.current();
    startSite = first?.host ?? undefined;
    // The user started the run on this page.
    if (startSite) allowedSites.add(startSite);
    lastTab = first;
    // The model starts knowing where it is.
    const start = first ? await startingPoint(first) : null;
    if (start) entries[1] = { message: { role: "user", content: `${options.task}\n\n${start}` } };
    if (first?.host) await visual("visuals_show", {}, first);
    await state("working", first);
    for (steps = 1; steps <= options.maxSteps; steps += 1) {
      check();
      await gate(lastTab);
      // The administrator's time limit: a run past it ends here, before it asks the model again.
      if (options.maxMinutes !== undefined && steps > 1 && Date.now() - started > options.maxMinutes * 60_000) {
        steps -= 1;
        report("max_minutes");
        return { outcome: "max_minutes", summary: `The agent stopped at its time limit of ${options.maxMinutes} minutes.`, steps };
      }
      let reply: ModelReply;
      try {
        reply = await deps.model(conversation(entries, options.screenshotsKept), signal);
      } catch (err) {
        if (isAbort(err) || signal.aborted) throw abortError();
        throw err;
      }
      check();
      if (reply.text.trim()) deps.onText(reply.text.trim());
      const calls: ToolCall[] = reply.toolCalls.map((call, index) => {
        // Each call's id once in a run: a provider may repeat them (call_0 at every step), and the panel's step
        // rows and the saved run are keyed by it - a repeat would overwrite an earlier step. The model is answered
        // under the id it is given here.
        let id = call.id || `call_${steps}_${index}`;
        if (callIds.has(id)) id = `${id}_s${steps}_${index}`;
        callIds.add(id);
        return { id, type: "function", function: { name: call.name, arguments: call.arguments } };
      });
      // An empty reply - no words, no calls - is not kept: an assistant message with neither is one providers refuse.
      if (calls.length || reply.text.trim()) {
        // The model's reasoning goes back with its calls, as providers that sign it (Gemini's thought signatures) require.
        const reasoning = calls.length && reply.reasoningDetails?.length ? { reasoning_details: reply.reasoningDetails } : {};
        entries.push({ message: { role: "assistant", content: reply.text || null, ...(calls.length ? { tool_calls: calls } : {}), ...reasoning } });
      }
      if (!calls.length) {
        // Words alone are not the end: a model that says what it will do, and does not, is reminded once.
        if (!nudged) {
          nudged = true;
          entries.push({ message: { role: "user", content: NUDGE } });
          continue;
        }
        report("no_action");
        return { outcome: "no_action", summary: `The model answered without acting: ${clip(reply.text.trim() || "(no words)", 1000)}`, steps };
      }
      nudged = false;
      let skip: string | null = null;
      let finish: string | null = null;
      /** Why the run stops after this step, when too many actions in a row failed or were refused. */
      let tooManyErrors: string | null = null;
      const images: NonNullable<Answer["image"]>[] = [];
      /** Whether the step changed the page since its last screenshot: then it ends with one. */
      let unseen = false;
      for (const call of calls) {
        let answer: Answer & { denied?: boolean };
        try {
          answer = await handle(call, skip);
        } catch (err) {
          // The browser failed at it (a debugger session gone, a tab closed): the model is told, and can go on another way.
          if (isAbort(err) || signal.aborted) throw err;
          const message = err instanceof Error && err.message ? clip(err.message, 300) : "The browser could not do it.";
          answer = { content: `The action failed in the browser: ${message}`, status: "error", detail: message, outcome: "error", extra: { error: "browser_error" } };
        }
        entries.push({ message: { role: "tool", tool_call_id: call.id, content: answer.content }, ...(answer.page ? { page: answer.page } : {}), ...(answer.read ? { read: answer.read } : {}) });
        if (answer.image) images.push(answer.image);
        // A fresh screenshot came with the answer: the step needs no other.
        if (answer.image && !answer.image.caption.startsWith(ZOOM_CAPTION)) unseen = false;
        const name = call.function.name;
        const said = answer.summary ?? describeAction(name, args(call.function.arguments) ?? {});
        const kept = keptSummary(name, args(call.function.arguments) ?? {}, said);
        deps.onStep({ id: call.id, tool: name, summary: said, status: answer.status, detail: answer.detail, ...(kept ? { kept } : {}) });
        if (answer.status !== "skipped") {
          deps.report({
            kind: "agent_step",
            site: answer.site,
            action: TOOL_NAMES.has(name) ? name : "unknown",
            outcome: answer.status === "done" ? "ok" : answer.status,
            detail: { task_id: options.runId, step: steps, mode: options.mode, ...(answer.extra ?? {}) },
          });
          history.push(`${said}${answer.site ? ` on ${answer.site}` : ""}: ${answer.status}`);
        }
        if (answer.finish !== undefined) finish = answer.finish;
        if (answer.status === "done" && name === "screenshot") unseen = false;
        else if (answer.status === "done" && (CHANGES.has(name) || (name === "computer" && args(call.function.arguments)?.action !== "wait"))) unseen = true;
        if (answer.denied) skip = "Skipped: an earlier action in this step was denied.";
        if (answer.status === "error") {
          errorsInARow += 1;
          if (errorsInARow >= MAX_ERRORS_IN_A_ROW && !skip) {
            tooManyErrors = "The agent stopped after three failed actions in a row.";
            skip = "Skipped: the run stopped after three failed actions in a row.";
          }
        } else if (answer.status === "blocked") {
          refusalsInARow += 1;
          if (refusalsInARow >= MAX_REFUSALS_IN_A_ROW && !skip) {
            tooManyErrors = "The agent stopped after five refused actions in a row.";
            skip = "Skipped: the run stopped after five refused actions in a row.";
          }
        } else if (answer.status === "done") {
          errorsInARow = 0;
          refusalsInARow = 0;
        }
        // The rest of the step was planned on a page this action did not leave as expected - it failed, was refused,
        // the page changed under it, the user took over: nothing more is done, and nothing finished, until the model looks.
        const fell = answer.status === "error" || answer.status === "blocked" || answer.extra?.error === "took_over";
        if (fell && !skip) skip = SKIP_AFTER_FAILURE;
        if (finish !== null && !skip) skip = "Skipped: the task was already finished.";
      }
      if (unseen && finish === null && !tooManyErrors && options.screenshotAfterAction) {
        const look = await lookAfter();
        if (look) images.push(look);
      }
      // Screenshots go after the step's answers, as images the model reads (tool answers carry text only).
      for (const image of images) {
        entries.push({
          message: { role: "user", content: [{ type: "text", text: image.caption }, { type: "image_url", image_url: { url: image.url } }] },
        });
      }
      lastTab = (await deps.browser.current()) ?? lastTab;
      if (finish !== null) {
        report("done");
        return { outcome: "done", summary: finish, steps };
      }
      if (tooManyErrors) {
        report("errors");
        return { outcome: "errors", summary: tooManyErrors, steps };
      }
    }
    steps = options.maxSteps;
    report("max_steps");
    return { outcome: "max_steps", summary: `The agent stopped at its limit of ${options.maxSteps} steps.`, steps };
  } catch (err) {
    if (isAbort(err) || signal.aborted) {
      report("stopped");
      return { outcome: "stopped", summary: "Stopped.", steps };
    }
    report("failed");
    await visual("visuals_state", { state: "error" }, lastTab);
    const message = err instanceof Error && err.message ? err.message : "The agent could not go on.";
    return { outcome: "failed", summary: message, steps };
  } finally {
    deps.driver?.onDialog(null);
    // The layer goes with the run; the panel shows the outcome.
    const tab = lastTab;
    if (tab && deps.driver) {
      await deps.browser.page("visuals_hide", {}, tab, undefined, VISUAL_MS).catch(() => undefined);
    }
  }
}
