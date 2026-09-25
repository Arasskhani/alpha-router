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
 * its answer. The run ends when the model calls done (or answers in words
 * alone), at the step limit, after three failed tool calls in a row, or when
 * the user presses Stop.
 */

import { approvalFor, classifyAction, type AgentMode, type PolicyContext, type Verdict } from "../lib/agentPolicy";
import type { ElementInfo, PageMethod, PageResult } from "../lib/pageAgent";
import { readablePage } from "../lib/sites";
import { agentInstructions, TOOL_NAMES } from "./agentTools";

export type WorkTab = { id: number; url: string; host: string | null; title: string };

/** The browser as the agent uses it; the panel's own implementation is agentBrowser.ts. */
export type AgentBrowser = {
  /** The tab the agent works in now: the one next to the panel, then whichever tab_open or tab_switch chose. */
  current(): Promise<WorkTab | null>;
  listTabs(): Promise<Array<WorkTab & { active: boolean }>>;
  openTab(url: string): Promise<WorkTab>;
  switchTab(tabId: number): Promise<WorkTab | null>;
  navigate(url: string): Promise<WorkTab>;
  /** One action in the page of the tab the agent works in. */
  page(method: PageMethod, args?: Record<string, unknown>): Promise<PageResult>;
  /** Whether the browser lets the extension work on the pages of this address's site. */
  hasAccess(url: string): Promise<boolean>;
  /** After an action that may load a page: wait until the tab has settled. */
  settle(): Promise<void>;
};

type ToolCall = { id: string; type: "function"; function: { name: string; arguments: string } };

export type ApiMessage =
  | { role: "system" | "user"; content: string }
  | { role: "assistant"; content: string | null; tool_calls?: ToolCall[] }
  | { role: "tool"; tool_call_id: string; content: string };

export type ModelReply = { text: string; toolCalls: Array<{ id: string; name: string; arguments: string }> };

export type ApprovalRequest = {
  tool: string;
  /** What the action does, in words - what will be typed, where a page is. */
  summary: string;
  verdict: Verdict;
  /** Auto mode: the review model handed this to the user, and why. */
  review?: string;
  /** The site the browser must allow first; the panel asks for it in the Allow click. */
  access?: { pattern: string; host: string };
};

type ReviewInput = {
  task: string;
  tool: string;
  site: string;
  target?: string;
  arguments: Record<string, unknown>;
  history: string[];
};

type StepStatus = "running" | "waiting" | "done" | "denied" | "blocked" | "skipped" | "error" | "stopped";

/** One line of the step log. */
export type StepView = { id: string; tool: string; summary: string; status: StepStatus; detail?: string };

export type AgentEventReport = {
  kind: "agent_step" | "agent_task";
  site?: string;
  action?: string;
  outcome: string;
  detail: Record<string, unknown>;
};

export type AgentDeps = {
  model(messages: ApiMessage[], signal: AbortSignal): Promise<ModelReply>;
  browser: AgentBrowser;
  approve(request: ApprovalRequest, signal: AbortSignal): Promise<boolean>;
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
  rules: PolicyContext;
  runId: string;
  /** The page-content tag suffix for this run: random, fixed for the run. */
  nonce: string;
  /** The model, as the report names it ("model::7"). */
  modelRef?: string;
};

export type RunOutcome = "done" | "stopped" | "max_steps" | "errors" | "failed";

export type RunResult = { outcome: RunOutcome; summary: string; steps: number };

const MAX_ERRORS_IN_A_ROW = 3;
/** Older page content is cut to this, so a long run stays within the model's reach. */
const OLD_PAGE_CHARS = 1500;
/** How many of the latest page results stay whole. */
const WHOLE_PAGE_RESULTS = 2;
/** Past this much text the oldest steps are left out, each with its answers. */
const MAX_CONVERSATION_CHARS = 120_000;
const HISTORY_LINES = 10;

type Entry = { message: ApiMessage; page?: { open: string; body: string; close: string } };

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

function size(message: ApiMessage): number {
  const calls = message.role === "assistant" ? JSON.stringify(message.tool_calls ?? []).length : 0;
  return (typeof message.content === "string" ? message.content.length : 0) + calls;
}

/**
 * The conversation as the model reads it: older page content cut short, and
 * - when it is still too long - the oldest steps left out whole, a tool call
 * never without its answer.
 */
export function conversation(entries: Entry[]): ApiMessage[] {
  const pageIndexes = entries.flatMap((entry, index) => (entry.page ? [index] : []));
  const whole = new Set(pageIndexes.slice(-WHOLE_PAGE_RESULTS));
  const messages = entries.map((entry, index) =>
    entry.page && entry.message.role === "tool" ? { ...entry.message, content: pageText(entry.page, whole.has(index)) } : entry.message,
  );
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

/** What an action does, in words for the step log and the approval card. */
function describeAction(tool: string, a: Record<string, unknown>, element?: ElementInfo): string {
  switch (tool) {
    case "tabs_list":
      return "List the open tabs";
    case "tab_open":
      return `Open ${whereTo(a.url)} in a new tab`;
    case "tab_switch":
      return `Switch to tab ${String(a.tab_id)}`;
    case "navigate":
      return `Open ${whereTo(a.url)}`;
    case "read_page":
      return "Read the page";
    case "find":
      return `Find "${clip(String(a.query ?? ""), 60)}"`;
    case "get_page_text":
      return "Read the page's text";
    case "click":
      return `Click ${named(element, a.ref)}`;
    case "type_text":
      return `Type "${clip(String(a.text ?? ""), 200)}" into ${named(element, a.ref)}${a.clear === true ? ", replacing what is there" : ""}`;
    case "select_option":
      return `Choose "${clip(String(a.value ?? ""), 60)}" in ${named(element, a.ref)}`;
    case "press_key":
      return `Press ${clip(String(a.key ?? "a key"), 20)}`;
    case "submit_form":
      return `Send the form${element?.name ? ` (${named(element, a.ref)})` : ""}`;
    case "scroll":
      return a.ref ? `Scroll to ${named(element, a.ref)}` : `Scroll ${typeof a.direction === "string" ? a.direction : "down"}`;
    case "wait_for":
      return typeof a.text === "string" && a.text ? `Wait for "${clip(a.text, 60)}"` : `Wait ${Number(a.seconds) || 2} seconds`;
    case "ask_user":
      return "Ask you a question";
    case "done":
      return "Finish";
    default:
      return `Use ${clip(tool, 40)}`;
  }
}

const ELEMENT_TOOLS = new Set(["click", "type_text", "select_option", "submit_form"]);
const PAGE_TOOLS = new Set(["read_page", "find", "get_page_text", "click", "type_text", "select_option", "submit_form", "press_key", "scroll", "wait_for"]);
/** Actions after which a page may be loading. */
const MAY_LOAD = new Set(["click", "submit_form", "press_key", "navigate", "tab_open", "tab_switch"]);

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
};

function originPattern(url: string): { pattern: string; host: string } | null {
  const page = readablePage(url);
  return page ? { pattern: page.pattern, host: page.host } : null;
}

export async function runAgent(options: AgentOptions, deps: AgentDeps, signal: AbortSignal): Promise<RunResult> {
  const entries: Entry[] = [
    { message: { role: "system", content: agentInstructions(options.nonce) } },
    { message: { role: "user", content: options.task } },
  ];
  const history: string[] = [];
  let errorsInARow = 0;
  let steps = 0;
  let startSite: string | undefined;
  const started = Date.now();

  const check = () => {
    if (signal.aborted) throw abortError();
  };

  /** Stop takes effect at once, even while the page is busy (a wait, a slow page): what it does then no longer matters. */
  const stopped = new Promise<never>((_, reject) => {
    const fail = () => reject(abortError());
    if (signal.aborted) fail();
    else signal.addEventListener("abort", fail, { once: true });
  });
  stopped.catch(() => undefined);

  async function page(method: PageMethod, a: Record<string, unknown> = {}): Promise<PageResult> {
    check();
    const result = await Promise.race([deps.browser.page(method, a), stopped]);
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

  /** Carry out one allowed action; everything the page says comes back wrapped. */
  async function execute(tool: string, a: Record<string, unknown>, tab: WorkTab | null): Promise<Answer> {
    const site = tab?.host ?? "";
    if (tool === "tabs_list") {
      const tabs = await deps.browser.listTabs();
      const lines = tabs.map((t) => {
        const readable = t.host !== null && classifyAction({ tool: "read_page", args: {}, page: { url: t.url, host: t.host } }, options.rules).class !== "blocked";
        const label = readable ? `${clip(t.title || t.host!, 100)} (${t.host})` : "(a tab the agent may not read)";
        return `[${t.id}] ${label}${t.id === tab?.id ? " - you work here" : ""}`;
      });
      const body = lines.join("\n") || "(no tabs)";
      return { content: "", page: wrapPage(options.nonce, "browser tabs", body), status: "done", detail: `${tabs.length} tabs`, outcome: "ok" };
    }
    if (tool === "tab_open" || tool === "navigate") {
      const url = String(a.url);
      const next = tool === "tab_open" ? await deps.browser.openTab(url) : await deps.browser.navigate(url);
      await Promise.race([deps.browser.settle(), stopped]);
      check();
      const where = next.host ? `${next.host}` : "a page";
      return {
        content: tool === "tab_open" ? `Opened ${where} in a new tab (id ${next.id}); you work there now.` : `The tab shows ${whereTo(next.url)} now.`,
        status: "done",
        outcome: "ok",
        site: next.host ?? undefined,
      };
    }
    if (tool === "tab_switch") {
      const next = await deps.browser.switchTab(Number(a.tab_id));
      if (!next) return { content: `There is no tab ${String(a.tab_id)} in this window.`, status: "error", detail: "No such tab", outcome: "error", extra: { error: "no_tab" } };
      return {
        content: "",
        page: wrapPage(options.nonce, next.host ?? "browser tabs", `You work in tab ${next.id} now: ${clip(next.title, 100)} (${next.host ?? "no web page"}).`),
        status: "done",
        outcome: "ok",
        site: next.host ?? undefined,
      };
    }
    const result = await page(tool as PageMethod, a);
    if (!result.ok) {
      return {
        content: "",
        page: wrapPage(options.nonce, site, `The action failed (${result.error}): ${result.message}`),
        status: "error",
        detail: result.message,
        outcome: "error",
        extra: { error: result.error },
      };
    }
    if (MAY_LOAD.has(tool)) {
      await Promise.race([deps.browser.settle(), stopped]);
      check();
    }
    let body: string;
    let detail: string | undefined;
    if (tool === "read_page") {
      body = String(result.outline ?? "");
      detail = `${Array.isArray(result.elements) ? result.elements.length : 0} elements`;
    } else if (tool === "get_page_text") {
      body = String(result.text ?? "") + (result.truncated ? "\n(The text was cut here.)" : "");
    } else if (tool === "find") {
      const matches = Array.isArray(result.matches) ? (result.matches as Array<{ ref: string; role: string; name: string; snippet?: string }>) : [];
      body = matches.map((m) => `[${m.ref}] ${m.role}${m.name ? ` "${m.name}"` : ""}${m.snippet ? ` - ${m.snippet}` : ""}`).join("\n");
      detail = `${matches.length} found`;
    } else {
      body = typeof result.note === "string" && result.note ? result.note : "Done.";
      detail = typeof result.note === "string" ? result.note : undefined;
    }
    return { content: "", page: wrapPage(options.nonce, site, body), status: "done", detail, outcome: "ok" };
  }

  /** One tool call from the model: through the rules, maybe past the user, then carried out. */
  async function handle(call: ToolCall, skip: string | null): Promise<Answer & { denied?: boolean }> {
    const name = call.function.name;
    const a = args(call.function.arguments);
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
      const answer = (await deps.askUser(question, signal)).trim();
      check();
      return {
        content: answer ? `The user answered: ${clip(answer, 4000)}` : "The user did not answer.",
        status: "done",
        detail: answer ? clip(answer, 200) : "No answer",
        outcome: "ok",
      };
    }
    const tab = await deps.browser.current();
    check();
    const pageNow = tab?.host ? { url: tab.url, host: tab.host } : undefined;
    let element: ElementInfo | undefined;
    if (ELEMENT_TOOLS.has(name) || (name === "scroll" && typeof a.ref === "string")) {
      if (!pageNow) {
        // The rules refuse it below, with the reason.
      } else {
        // For a click, the control it works on: the button around the words, the field of a label.
        const described = await page("describe", { ref: a.ref, ...(name === "click" ? { activates: true } : {}) });
        if (!described.ok) {
          return { content: "", page: wrapPage(options.nonce, pageNow.host, `${described.message}`), status: "error", detail: described.message, outcome: "error", site: pageNow.host, extra: { error: described.error } };
        }
        element = described.element as ElementInfo;
      }
    }
    const summary = describeAction(name, a, element);
    const verdict = TOOL_NAMES.has(name)
      ? classifyAction({ tool: name, args: a, page: pageNow, element }, options.rules)
      : ({ class: "blocked", reason: "unknown_tool", message: `The agent has no tool called ${clip(name, 40)}.` } as Verdict);
    const base = {
      site: verdict.site ?? pageNow?.host,
      extra: {
        class: verdict.class,
        ...(element ? { role: element.role, label: element.name } : {}),
        ...(name === "type_text" && typeof a.text === "string" ? { chars: a.text.length } : {}),
        ...(name === "press_key" && typeof a.key === "string" ? { key: a.key } : {}),
        ...(verdict.site ? { to_site: verdict.site } : {}),
      } as Record<string, unknown>,
    };
    if (verdict.class === "blocked") {
      const refused = `Refused: ${verdict.message}`;
      return {
        ...base,
        summary,
        // An element's name is the page's words: it goes back wrapped like the rest of the page.
        content: element ? "" : refused,
        ...(element && pageNow ? { page: wrapPage(options.nonce, pageNow.host, refused) } : {}),
        status: "blocked",
        detail: verdict.message,
        outcome: "blocked",
        extra: { ...base.extra, reason: verdict.reason },
      };
    }
    let approval = approvalFor(verdict, options.mode);
    // The browser has to allow a site before the agent can work there, and it asks only in a click.
    let access: ApprovalRequest["access"];
    const needs =
      PAGE_TOOLS.has(name) && pageNow
        ? pageNow.url
        : name === "navigate" || name === "tab_open"
          ? String(a.url)
          : name === "click" && element?.href && /^https?:/.test(element.href)
            ? element.href
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
      const verdictFromReview = await deps.review(
        {
          task: options.task,
          tool: name,
          site: pageNow?.host ?? verdict.site ?? "",
          target: element ? clip(`${element.role}: ${element.name}`, 300) : undefined,
          arguments: a,
          history: history.slice(-HISTORY_LINES),
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
    let approvedBy = approval === "none" ? (base.extra.review === "allow" ? "review" : "not_needed") : "user";
    if (approval === "user") {
      deps.onStep({ id: call.id, tool: name, summary, status: "waiting" });
      const allowed = await deps.approve({ tool: name, summary, verdict, review: reviewNote, access }, signal);
      check();
      if (!allowed) {
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
    }
    base.extra.approval = approvedBy;
    deps.onStep({ id: call.id, tool: name, summary, status: "running" });
    const answer = await execute(name, a, tab);
    return { ...answer, summary, site: answer.site ?? base.site, extra: { ...base.extra, ...(answer.extra ?? {}) } };
  }

  try {
    const first = await deps.browser.current();
    startSite = first?.host ?? undefined;
    for (steps = 1; steps <= options.maxSteps; steps += 1) {
      check();
      let reply: ModelReply;
      try {
        reply = await deps.model(conversation(entries), signal);
      } catch (err) {
        if (isAbort(err) || signal.aborted) throw abortError();
        throw err;
      }
      check();
      if (reply.text.trim()) deps.onText(reply.text.trim());
      const calls: ToolCall[] = reply.toolCalls.map((call, index) => ({
        id: call.id || `call_${steps}_${index}`,
        type: "function",
        function: { name: call.name, arguments: call.arguments },
      }));
      entries.push({ message: { role: "assistant", content: reply.text || null, ...(calls.length ? { tool_calls: calls } : {}) } });
      if (!calls.length) {
        // Words alone: the model has finished.
        report("done");
        return { outcome: "done", summary: reply.text.trim() || "Done.", steps };
      }
      let skip: string | null = null;
      let finish: string | null = null;
      let tooManyErrors = false;
      for (const call of calls) {
        const answer = await handle(call, skip);
        entries.push({ message: { role: "tool", tool_call_id: call.id, content: answer.content }, ...(answer.page ? { page: answer.page } : {}) });
        const name = call.function.name;
        const said = answer.summary ?? describeAction(name, args(call.function.arguments) ?? {});
        deps.onStep({ id: call.id, tool: name, summary: said, status: answer.status, detail: answer.detail });
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
        if (answer.denied) skip = "Skipped: an earlier action in this step was denied.";
        if (answer.status === "error" || answer.status === "blocked") {
          errorsInARow += 1;
          if (errorsInARow >= MAX_ERRORS_IN_A_ROW && !skip) {
            tooManyErrors = true;
            skip = "Skipped: the run stopped after three failed actions in a row.";
          }
        } else if (answer.status === "done") {
          errorsInARow = 0;
        }
        if (finish !== null && !skip) skip = "Skipped: the task was already finished.";
      }
      if (finish !== null) {
        report("done");
        return { outcome: "done", summary: finish, steps };
      }
      if (tooManyErrors) {
        report("errors");
        return { outcome: "errors", summary: "The agent stopped after three failed actions in a row.", steps };
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
    const message = err instanceof Error && err.message ? err.message : "The agent could not go on.";
    return { outcome: "failed", summary: message, steps };
  }
}
