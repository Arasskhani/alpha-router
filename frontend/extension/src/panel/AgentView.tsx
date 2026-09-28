/**
 * The browser agent in the side panel: the task, the steps as they happen,
 * the approval cards, and Stop.
 *
 * The loop itself is agentRun.ts; this view gives it the model (a
 * /api/chat/completions call with the agent's tools), the browser, the user's
 * decisions and the review model, and shows what it does. Nothing of a run is
 * saved to the chat history: its steps go to Admin Logs.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../lib/api";
import { DEFAULT_APPROVALS, type AgentMode, type PolicyContext } from "../lib/agentPolicy";
import { clearBadge, showBadge } from "../lib/badge";
import { ChatStreamError } from "../lib/chatStream";
import { getClient } from "../lib/client";
import { fromTabScript, isExtensionMessage } from "../lib/messages";
import { readablePage } from "../lib/sites";
import { DisconnectedError, TemporaryError } from "../lib/tokens";
import { useActivePage, useSiteAccess } from "./activePage";
import { chooseDriver, TabDrivers } from "../lib/driver";
import { clampMaxSide } from "../lib/coords";
import { createAgentBrowser, type PanelBrowser } from "./agentBrowser";
import {
  runAgent,
  SCREENSHOTS_KEPT,
  type AgentDeps,
  type AgentEventReport,
  type ApprovalRequest,
  type ControlDriver,
  type RunOutcome,
  type StepView,
} from "./agentRun";
import { agentToolsFor } from "./agentTools";
import { modelStep, ModelTimeout } from "./modelStep";
import { createPauseGate, type PauseControl } from "./pauseGate";
import { pickModel, textModels, type ChatModel } from "./conversation";
import type { Me } from "./types";

const MODEL_KEY = "alpharouter.agentModel";
const MODE_KEY = "alpharouter.agentMode";
const DEFAULT_MAX_STEPS = 25;
const DEFAULT_MAX_MINUTES = 20;
const DEFAULT_MAX_TABS = 10;
/** What the server takes of a saved run: this many steps, each this long. */
const MAX_SAVED_STEPS = 200;
const MAX_SAVED_STEP_CHARS = 200;
/** Events go to the server in batches of this many, and whatever is left when a run ends. */
const EVENT_BATCH = 10;
/** Events kept while the server cannot take them: the newest this many. */
const MAX_QUEUED_EVENTS = 200;
/** What the reviewer takes (the server's limits): an action's arguments as JSON, in bytes, and a task, in characters. */
const REVIEW_ARGUMENT_BYTES = 4096;
const MAX_TASK_CHARS = 4000;
/** A crop sent to a vision reviewer is dropped past this many characters, so the request stays within the server's limit. */
const MAX_CROP_CHARS = 200_000;
/** When the server's per-minute limit is reached: how long to wait, and how often, before the run gives up. */
const RATE_LIMIT_WAIT_MS = 15_000;
const RATE_LIMIT_RETRIES = 3;

/** How long the end of a run may take to put things back: the debugger, the banners, the badge; and to save the run. */
const CLEANUP_MS = 3000;
const SAVE_MS = 8000;

/** `work`, but no longer than `ms`: what has not finished by then is left to finish on its own. */
function atMost(work: Promise<unknown> | undefined, ms: number): Promise<void> {
  if (!work) return Promise.resolve();
  return new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, ms);
    void work.then(
      () => {
        clearTimeout(timer);
        resolve();
      },
      () => {
        clearTimeout(timer);
        resolve();
      },
    );
  });
}

/** Wait `ms`, or less if the run is stopped (then it throws, as a stopped fetch does). */
function pause(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", stop);
      resolve();
    }, ms);
    const stop = () => {
      clearTimeout(timer);
      reject(new DOMException("The run was stopped.", "AbortError"));
    };
    if (signal.aborted) stop();
    else signal.addEventListener("abort", stop, { once: true });
  });
}

type LogItem =
  | { kind: "task"; id: string; text: string }
  | { kind: "step"; id: string; step: StepView }
  | { kind: "text"; id: string; text: string }
  | { kind: "result"; id: string; outcome: RunOutcome; summary: string }
  | { kind: "saved"; id: string; chatId: string };

type Props = {
  me: Me;
  /** The server this copy of the extension belongs to (its config.json). */
  server: string;
  /** Whether this view is the one on screen: a run goes on while the chat is shown. */
  hidden?: boolean;
  /** The server ended the session. */
  onDisconnected: () => void;
};

function randomHex(bytes: number): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(bytes)), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** A server address's host as the rules name hosts. */
function hostOf(url: string | null | undefined): string | null {
  return readablePage(url ?? undefined)?.host ?? null;
}

/** Models the agent may use: the text models this account may use, within both of the administrator's lists. */
export function agentModels(models: ChatModel[], me: Me): ChatModel[] {
  const agentList = me.policy?.agent_models ?? [];
  const pageList = me.policy?.page_content_models ?? [];
  return textModels(models).filter(
    (model) => (!agentList.length || agentList.includes(model.id)) && (!pageList.length || pageList.includes(model.id)),
  );
}

const STATUS_LABEL: Record<StepView["status"], string> = {
  running: "Working…",
  waiting: "Waiting for you",
  done: "Done",
  denied: "Denied",
  blocked: "Refused",
  skipped: "Skipped",
  error: "Failed",
  stopped: "Stopped",
};

const OUTCOME_LABEL: Record<RunOutcome, string> = {
  done: "Finished",
  stopped: "Stopped",
  max_steps: "Step limit reached",
  max_minutes: "Time limit reached",
  errors: "Stopped after errors",
  failed: "Could not go on",
  no_action: "Stopped: the model did not act",
};

function describeError(err: unknown): string {
  if (err instanceof ApiError || err instanceof ChatStreamError || err instanceof TemporaryError || err instanceof ModelTimeout) return err.message;
  return "Something went wrong.";
}

export default function AgentView({ me, server, hidden = false, onDisconnected }: Props) {
  const [models, setModels] = useState<ChatModel[] | null>(null);
  const [modelsFailed, setModelsFailed] = useState(false);
  const [modelLoads, setModelLoads] = useState(0);
  const [modelId, setModelId] = useState("");
  const [mode, setMode] = useState<AgentMode>("ask");
  const [draft, setDraft] = useState("");
  const [running, setRunning] = useState(false);
  /** Between Start and the run beginning (Chrome's site prompt may be open): no second Start. */
  const [starting, setStarting] = useState(false);
  /** Set at once in the Start click, before any render: two quick presses start one run. */
  const busy = useRef(false);
  const [log, setLog] = useState<LogItem[]>([]);
  /** The card waiting for the user; `asking` while Chrome's own prompt for its site is open. */
  const [approval, setApproval] = useState<{ request: ApprovalRequest; resolve: (ok: boolean) => void; asking?: boolean } | null>(null);
  const [question, setQuestion] = useState<{ text: string; resolve: (answer: string) => void } | null>(null);
  const [answer, setAnswer] = useState("");
  const [banner, setBanner] = useState("");
  /** The model is answering the step: since when, and its words so far. */
  const [thinking, setThinking] = useState<{ since: number; text: string } | null>(null);
  /** Ticks once a second while the model thinks, so the wait shows how long it has been. */
  const [, setTick] = useState(0);
  /** The person took over the page (or paused from here): the run waits for Resume. */
  const [paused, setPaused] = useState(false);
  /** A private run: not saved to the person's chat history (its steps still go to Admin Logs). */
  const [privateRun, setPrivateRun] = useState(false);
  /** The run's steps as they ended, in order, for the chat it becomes. */
  const stepsTaken = useRef<Map<string, StepView>>(new Map());
  const controller = useRef<AbortController | null>(null);
  const gate = useRef<PauseControl | null>(null);
  const browser = useRef<PanelBrowser | null>(null);
  const runId = useRef<string | null>(null);
  const events = useRef<AgentEventReport[]>([]);
  const logEnd = useRef<HTMLDivElement | null>(null);
  const disconnected = useRef(onDisconnected);
  const activePage = useActivePage();
  const target = activePage?.target ?? null;
  const siteAccess = useSiteAccess(target?.pattern ?? null);
  const autoAllowed = me.features.auto_mode;
  const maxSteps = me.policy?.agent_max_steps ?? DEFAULT_MAX_STEPS;
  /** The modes on offer: Ask always; Plan unless the administrator turned it off; Auto only when turned on. */
  const modes = useMemo<AgentMode[]>(() => {
    const offered = me.policy?.agent_modes;
    const plan = !offered || offered.includes("plan");
    return ["ask", ...(plan ? (["plan"] as const) : []), ...(autoAllowed ? (["auto"] as const) : [])];
  }, [me, autoAllowed]);
  /** What a run starts in: the administrator's choice when it is on offer; Ask otherwise (and from a server that has no such setting). */
  const defaultMode = useMemo<AgentMode>(() => {
    const wanted = me.policy?.agent_default_mode;
    return (wanted === "plan" || wanted === "auto" || wanted === "ask") && modes.includes(wanted) ? wanted : "ask";
  }, [me, modes]);
  const maxMinutes = me.policy?.agent_max_minutes ?? DEFAULT_MAX_MINUTES;
  const maxTabs = me.policy?.agent_max_tabs ?? DEFAULT_MAX_TABS;
  const screenshotsKept = me.policy?.screenshots_kept ?? SCREENSHOTS_KEPT;
  const maxSide = clampMaxSide(me.policy?.screenshot_max_side);
  /** Finished runs become chats unless the administrator turned that off. */
  const savesRuns = me.policy?.save_runs !== false;
  /** A run may be kept out of the history when the person has Private Mode and the administrator allows private runs. */
  const privateOffered = savesRuns && me.features.private_mode && me.policy?.private_runs !== false;
  const rules = useMemo<PolicyContext>(() => {
    // Both addresses: the server this copy talks to, and the one the server gives, if they differ.
    const own = [hostOf(server), hostOf(me.server.url)].filter((host): host is string => host !== null);
    const data = me.policy?.data;
    return {
      policy: {
        allowed_sites: me.policy?.allowed_sites ?? [],
        blocked_sites: me.policy?.blocked_sites ?? [],
        read_only_sites: me.policy?.read_only_sites ?? [],
        protected_sites: me.policy?.protected_sites ?? [],
      },
      serverHost: hostOf(me.server.url) ?? hostOf(server),
      ownHosts: [...new Set(own)],
      approvals: { ...DEFAULT_APPROVALS, ...(me.policy?.approvals ?? {}) },
      data: {
        internalSites: data?.internal_sites ?? [],
        modelSeesInternal: !data?.internal_models || data.internal_models.includes(modelId),
        modelSeesScreenshots: !data?.screenshot_models || data.screenshot_models.includes(modelId),
      },
    };
  }, [me, server, modelId]);

  useEffect(() => {
    disconnected.current = onDisconnected;
  }, [onDisconnected]);

  useEffect(() => {
    let active = true;
    Promise.all([getClient().api.json<ChatModel[]>("/api/chat/models"), chrome.storage.local.get([MODEL_KEY, MODE_KEY])])
      .then(([all, stored]) => {
        if (!active) return;
        const usable = agentModels(all, me);
        setModels(usable);
        setModelsFailed(false);
        setModelId(pickModel(usable, typeof stored[MODEL_KEY] === "string" ? stored[MODEL_KEY] : null)?.id ?? "");
        // The person's last choice, when it is still on offer; else what the administrator set.
        const saved = stored[MODE_KEY];
        setMode(typeof saved === "string" && (modes as string[]).includes(saved) ? (saved as AgentMode) : defaultMode);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DisconnectedError) disconnected.current();
        setModels([]);
        setModelsFailed(true);
      });
    return () => {
      active = false;
    };
  }, [me, modes, defaultMode, modelLoads]);

  // Stop, a take-over and Resume from a banner the run put on a page: only from our own script in one of those tabs, for this run.
  useEffect(() => {
    const listener = (message: unknown, sender: chrome.runtime.MessageSender) => {
      if (!isExtensionMessage(message) || !("run" in message) || message.run !== runId.current) return;
      const tabs = browser.current?.bannerTabs() ?? [];
      if (!tabs.some((tabId) => fromTabScript(sender, tabId))) return;
      if (message.type === "agent-stop") controller.current?.abort();
      else if (message.type === "agent-takeover") gate.current?.pause();
      else if (message.type === "agent-resume") gate.current?.resume();
    };
    chrome.runtime.onMessage.addListener(listener);
    return () => chrome.runtime.onMessage.removeListener(listener);
  }, []);

  useEffect(() => {
    logEnd.current?.scrollIntoView?.({ block: "end" });
  }, [log, approval, question, paused, thinking]);

  useEffect(() => {
    if (!thinking) return;
    const timer = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, [thinking]);

  // A run does not outlive the panel: closing it stops the run (and its fetch).
  useEffect(() => () => controller.current?.abort(), []);

  function chooseModel(id: string) {
    setModelId(id);
    void chrome.storage.local.set({ [MODEL_KEY]: id });
  }

  function chooseMode(next: AgentMode) {
    setMode(next);
    void chrome.storage.local.set({ [MODE_KEY]: next });
  }

  function append(item: LogItem) {
    setLog((items) => [...items, item]);
  }

  function closeOpenSteps(status: "stopped" | "error") {
    setLog((items) =>
      items.map((item) =>
        item.kind === "step" && (item.step.status === "running" || item.step.status === "waiting") ? { ...item, step: { ...item.step, status } } : item,
      ),
    );
    for (const [id, step] of stepsTaken.current) {
      if (step.status === "running" || step.status === "waiting") stepsTaken.current.set(id, { ...step, status });
    }
  }

  function showStep(step: StepView) {
    stepsTaken.current.set(step.id, step);
    setLog((items) => {
      const at = items.findIndex((item) => item.kind === "step" && item.id === step.id);
      if (at < 0) return [...items, { kind: "step", id: step.id, step }];
      const next = items.slice();
      next[at] = { kind: "step", id: step.id, step };
      return next;
    });
  }

  /**
   * Send the waiting events. A batch the server did not take - it could not
   * be reached, it was busy (5xx, 429) - goes back in the queue for the next
   * flush, so a hiccup does not erase steps from the trail; one it refused
   * (another 4xx) could never be taken. Never throws: the trail never stops
   * the agent.
   */
  async function flush() {
    const batch = events.current.splice(0, 50);
    if (!batch.length) return;
    let kept = false;
    try {
      const response = await getClient().api.request("/api/extension/events", { method: "POST", body: JSON.stringify({ events: batch }) });
      kept = response.status >= 500 || response.status === 429;
    } catch (err) {
      kept = !(err instanceof DisconnectedError);
    }
    if (kept) events.current = [...batch, ...events.current].slice(-MAX_QUEUED_EVENTS);
  }

  function deps(model: string, driver: ControlDriver | null, startedAt: number): AgentDeps {
    const { api } = getClient();
    const browserTools = agentToolsFor({ fullControl: driver !== null, plan: mode === "plan" });
    return {
      async model(messages, stepSignal) {
        // No chat, no history, no assistant message id: each step stands alone.
        // The run's start goes with every step, so an administrator's stop can end it.
        const body = JSON.stringify({
          model,
          messages,
          stream: true,
          browser_tools: browserTools,
          browser_tool_choice: "auto",
          browser_run_started_at: startedAt,
        });
        // While the model thinks, the panel says so, with its words as they come.
        setThinking({ since: Date.now(), text: "" });
        try {
          for (let attempt = 0; ; attempt += 1) {
            try {
              const result = await modelStep(
                {
                  request: (signal) => api.request("/api/chat/completions", { method: "POST", body, signal }),
                  onText: (full) => setThinking((now) => (now ? { ...now, text: full } : now)),
                  onRetry: (why) => append({ kind: "text", id: randomHex(6), text: `${why} Trying once more…` }),
                },
                stepSignal,
              );
              return { text: result.text, toolCalls: result.toolCalls };
            } catch (err) {
              if (err instanceof DisconnectedError) disconnected.current();
              if (err instanceof DOMException && err.name === "AbortError") throw err;
              // A fast run can reach the server's per-minute limit: wait for it, a few times, rather than give up.
              if (err instanceof ApiError && err.status === 429 && attempt < RATE_LIMIT_RETRIES) {
                const note = randomHex(6);
                append({ kind: "text", id: note, text: "Too many requests in a minute: waiting a little before the next step…" });
                await pause(RATE_LIMIT_WAIT_MS, stepSignal);
                continue;
              }
              throw new Error(describeError(err));
            }
          }
        } finally {
          setThinking(null);
        }
      },
      browser: browser.current!,
      driver,
      approve: (request, stepSignal) =>
        new Promise<boolean>((resolve) => {
          // Stopped just before the card would show: no card, and no waiting on one.
          if (stepSignal.aborted) {
            resolve(false);
            return;
          }
          let settled = false;
          const settle = (ok: boolean) => {
            if (settled) return;
            settled = true;
            stepSignal.removeEventListener("abort", onAbort);
            // Only this card: a late answer to an earlier one must not take the next card away.
            setApproval((current) => (current?.request === request ? null : current));
            resolve(ok);
          };
          const onAbort = () => settle(false);
          stepSignal.addEventListener("abort", onAbort, { once: true });
          setApproval({ request, resolve: settle });
        }),
      askUser: (text, stepSignal) =>
        new Promise<string>((resolve) => {
          if (stepSignal.aborted) {
            resolve("");
            return;
          }
          const settle = (value: string) => {
            stepSignal.removeEventListener("abort", onAbort);
            setQuestion(null);
            setAnswer("");
            resolve(value);
          };
          const onAbort = () => settle("");
          stepSignal.addEventListener("abort", onAbort, { once: true });
          setQuestion({ text, resolve: settle });
        }),
      async review(input, stepSignal) {
        // Cut short, an action would be judged on its start alone: one too long for the reviewer is the user's to judge.
        if (new TextEncoder().encode(JSON.stringify(input.arguments)).length > REVIEW_ARGUMENT_BYTES || input.task.length > MAX_TASK_CHARS) {
          return { decision: "ask", reason: "The action is too long for the reviewer to check in full." };
        }
        // A crop too large for the server's limit is left out; the reviewer then judges without it.
        const crop = input.crop && input.crop.length <= MAX_CROP_CHARS ? input.crop : undefined;
        try {
          const verdict = await api.json<{ decision?: string; reason?: string }>("/api/extension/review-action", {
            method: "POST",
            // A tab that shows no web page still names a place for the reviewer.
            body: JSON.stringify({ ...input, crop, site: input.site || "no web page" }),
            signal: stepSignal,
          });
          return verdict.decision === "allow"
            ? { decision: "allow", reason: verdict.reason ?? "" }
            : { decision: "ask", reason: verdict.reason || "The reviewer wants you to decide." };
        } catch (err) {
          if (err instanceof DOMException && err.name === "AbortError") throw err;
          if (err instanceof DisconnectedError) disconnected.current();
          const refused = err instanceof ApiError && err.status >= 400 && err.status < 500 && err.status !== 429;
          return { decision: "ask", reason: refused ? `The reviewer did not take the request: ${err.message}` : "The reviewer could not be reached." };
        }
      },
      report(event) {
        events.current.push(event);
        if (events.current.length >= EVENT_BATCH) void flush();
      },
      onStep: showStep,
      onText: (text) => append({ kind: "text", id: randomHex(6), text }),
      pause: gate.current ?? undefined,
      onState: (state) => void showBadge(state),
    };
  }

  /**
   * The finished run, kept as a chat of the person's: the task, how it ended,
   * and each step as the panel showed it - never page text or screenshots,
   * which the panel does not send and the server would not take.
   */
  async function saveRun(run: string, finished: { task: string; outcome: RunOutcome; summary: string; model: string; mode: AgentMode; startedAt: number }) {
    const steps = [...stepsTaken.current.values()]
      .filter((step) => step.status !== "running" && step.status !== "waiting")
      .slice(0, MAX_SAVED_STEPS)
      .map((step) => ({
        tool: step.tool,
        // Never what was typed: the kept form has its length instead.
        summary: (step.kept ?? step.summary).slice(0, MAX_SAVED_STEP_CHARS),
        status: step.status,
        ...(step.detail ? { detail: step.detail.slice(0, MAX_SAVED_STEP_CHARS) } : {}),
      }));
    try {
      const { chat_id } = await getClient().api.json<{ chat_id: string }>("/api/extension/runs", {
        method: "POST",
        body: JSON.stringify({
          task: finished.task,
          outcome: finished.outcome,
          summary: finished.summary.slice(0, MAX_TASK_CHARS),
          steps,
          model: finished.model,
          mode: finished.mode,
          duration_ms: Math.min(86_400_000, Math.max(0, Date.now() - finished.startedAt)),
        }),
      });
      append({ kind: "saved", id: `${run}-saved`, chatId: chat_id });
    } catch (err) {
      if (err instanceof DisconnectedError) disconnected.current();
      // Not saved (the administrator turned it off since, or the server was busy): the run is still in Admin Logs.
    }
  }

  async function begin(task: string) {
    // One run at a time: a second one would take over the Stop buttons and leave the first running unseen.
    if (controller.current) return;
    const run = `run-${randomHex(8)}`;
    // When this run began: every step carries it, so an administrator's stop can end it.
    const startedAt = Date.now();
    const abort = new AbortController();
    controller.current = abort;
    runId.current = run;
    stepsTaken.current = new Map();
    browser.current = createAgentBrowser({ startTabId: activePage?.tabId ?? null, runId: run, maxTabs });
    const pauseGate = createPauseGate(abort.signal);
    pauseGate.onChange(setPaused);
    gate.current = pauseGate;
    setBanner("");
    setDraft("");
    setLog([{ kind: "task", id: run, text: task }]);
    setRunning(true);
    setStarting(false);
    void showBadge("working");
    // Full control: the admin's switch and the user's grant, a model that reads images, and a tab to attach to.
    const readsImages = Boolean(models?.find((m) => m.id === modelId)?.supports_vision);
    const wantsControl = Boolean(me.features.full_control);
    let driver: ControlDriver | null = null;
    let stopDriver: (() => Promise<void>) | null = null;
    try {
      if (wantsControl && activePage?.tabId != null) {
        if (!readsImages) {
          append({ kind: "text", id: `${run}-driver`, text: "Working without full control: this model does not read images. Choose a vision model for a real mouse and screenshots." });
        } else {
          const choice = await chooseDriver(activePage.tabId, { fullControl: true, maxSide });
          if (choice.mode === "cdp") {
            // Each tab the agent works in gets its own session; Cancel on Chrome's bar, on any of them, stops the run.
            const drivers = new TabDrivers(
              { tabId: activePage.tabId, driver: choice.driver },
              {
                maxSide,
                onDetached: (reason) => {
                  if (reason === "canceled_by_user") abort.abort();
                },
              },
            );
            driver = drivers;
            stopDriver = () => drivers.stop();
            append({ kind: "text", id: `${run}-driver`, text: "Full control is on: a real mouse and keyboard, and screenshots. Chrome shows its debugging bar while this runs." });
          } else {
            append({ kind: "text", id: `${run}-driver`, text: `Working without full control: ${choice.reason}.` });
          }
        }
      }
      const result = await runAgent(
        { task, mode, maxSteps, maxMinutes, screenshotsKept, rules, runId: run, nonce: randomHex(6), modelRef: modelId },
        deps(modelId, driver, startedAt),
        abort.signal,
      );
      // A step still shown as working or waiting when the run ended - stopped, or cut short - did not finish.
      closeOpenSteps(result.outcome === "stopped" ? "stopped" : "error");
      append({ kind: "result", id: `${run}-end`, outcome: result.outcome, summary: result.summary });
      if (savesRuns && !(privateOffered && privateRun)) {
        await atMost(saveRun(run, { task, outcome: result.outcome, summary: result.summary, model: modelId, mode, startedAt }), SAVE_MS);
      }
    } finally {
      // Putting things back never holds the panel up for long: a page or a server that does not answer is left.
      await atMost(stopDriver?.().catch(() => undefined), CLEANUP_MS);
      await atMost(browser.current?.cleanup().catch(() => undefined), CLEANUP_MS);
      await atMost(clearBadge(), CLEANUP_MS);
      await atMost(flush(), SAVE_MS);
      setRunning(false);
      setPaused(false);
      setApproval(null);
      setQuestion(null);
      if (gate.current === pauseGate) gate.current = null;
      if (controller.current === abort) controller.current = null;
      busy.current = false;
    }
  }

  /**
   * Resume from the panel: the page is told first, so it takes the agent's
   * next action, then the run goes on. (Resume on the page's banner tells us,
   * the other way round.)
   */
  async function resume() {
    const pending = gate.current;
    if (!pending?.paused()) return;
    const run = runId.current;
    if (run && browser.current?.workingTab() != null) {
      await browser.current.page("takeover_resume", { run }, undefined, undefined, CLEANUP_MS).catch(() => undefined);
    }
    pending.resume();
  }

  function start() {
    const task = draft.trim();
    if (!task || running || busy.current || !modelId) return;
    if (!rules.ownHosts.length) {
      // Without Alpharouter's own address the rules cannot keep the agent off its pages.
      setBanner("The agent cannot tell Alpharouter's own pages from others. Download the extension again from Settings → Extension.");
      return;
    }
    busy.current = true;
    setStarting(true);
    const refused = () => {
      busy.current = false;
      setStarting(false);
      setBanner(`The agent needs your permission to work on ${target?.host ?? "this site"}.`);
    };
    if (target && siteAccess === false) {
      // Chrome asks only while a click is being handled: at once, nothing awaited first.
      chrome.permissions
        .request({ origins: [target.pattern] })
        .then((granted) => (granted ? void begin(task) : refused()))
        .catch(refused);
      return;
    }
    void begin(task);
  }

  function stop() {
    controller.current?.abort();
  }

  function allow() {
    const pending = approval;
    if (!pending || pending.asking) return;
    const access = pending.request.access;
    if (access) {
      // The site's permission, asked for in this click: Chrome shows its prompt only now. The
      // card waits for its answer, Allow and Deny disabled, so the two can never cross.
      setApproval((current) => (current?.request === pending.request ? { ...current, asking: true } : current));
      chrome.permissions
        .request({ origins: [access.pattern] })
        .then((granted) => pending.resolve(granted))
        .catch(() => pending.resolve(false));
      return;
    }
    pending.resolve(true);
  }

  if (!me.features.agent) return null;

  const empty =
    mode === "auto"
      ? "Tell Alpharouter what to do in your browser. In Auto mode it acts on the sites your administrator allows without asking; a reviewer checks each action, and it always asks before it sends, deletes, or goes to another site."
      : mode === "plan"
        ? "Tell Alpharouter what to do in your browser. In Plan mode it looks, proposes a plan and the sites it will work on, and waits for you to approve it once; then it works those sites on its own, and still asks before it sends, deletes, or leaves them."
        : "Tell Alpharouter what to do in your browser. It works in the tab next to this panel, and asks you before it changes anything.";

  return (
    <main className="panel agent" hidden={hidden}>
      <header className="chat__header">
        <select
          className="chat__model"
          aria-label="Agent model"
          value={modelId}
          disabled={!models?.length || running}
          onChange={(event) => chooseModel(event.target.value)}
        >
          {!models && <option value="">Loading models…</option>}
          {models?.length === 0 && <option value="">No models the agent may use</option>}
          {models?.map((model) => (
            <option key={model.id} value={model.id}>
              {model.name}
            </option>
          ))}
        </select>
        {modelsFailed && (
          <button type="button" className="btn btn--quiet" onClick={() => setModelLoads((n) => n + 1)}>
            Try again
          </button>
        )}
        <div className="agent__modes" role="radiogroup" aria-label="Mode">
          {modes.map((value) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={mode === value}
              className={`agent__mode${mode === value ? " agent__mode--on" : ""}`}
              disabled={running}
              onClick={() => chooseMode(value)}
            >
              {value === "ask" ? "Ask" : value === "plan" ? "Plan" : "Auto"}
            </button>
          ))}
        </div>
        {privateOffered && (
          <label className="agent__private">
            <input type="checkbox" checked={privateRun} disabled={running} onChange={(event) => setPrivateRun(event.target.checked)} />
            Private run
          </label>
        )}
      </header>

      {banner && (
        <p className="banner banner--error chat__notice" role="alert">
          {banner}
        </p>
      )}

      <div className="chat__log agent__log" role="log" aria-live="polite">
        {log.length === 0 && <p className="chat__empty">{empty}</p>}
        {log.map((item) => {
          if (item.kind === "task") {
            return (
              <article key={item.id} className="turn turn--user">
                <p className="turn__text">{item.text}</p>
              </article>
            );
          }
          if (item.kind === "text") {
            return (
              <p key={item.id} className="agent__text">
                {item.text}
              </p>
            );
          }
          if (item.kind === "result") {
            return (
              <div key={item.id} className={`agent__result agent__result--${item.outcome}`} role="status">
                <strong>{OUTCOME_LABEL[item.outcome]}</strong>
                <p className="agent__summary">{item.summary}</p>
              </div>
            );
          }
          if (item.kind === "saved") {
            return (
              <p key={item.id} className="agent__text agent__saved">
                Saved to your chat history.{" "}
                <a href={`${server}/app/chat?session=${encodeURIComponent(item.chatId)}`} target="_blank" rel="noopener noreferrer">
                  Open it
                </a>
              </p>
            );
          }
          const { step } = item;
          return (
            <div key={item.id} className={`agent__step agent__step--${step.status}`} data-step-status={step.status}>
              <span className="agent__step-summary">{step.summary}</span>
              <span className="agent__step-status">{STATUS_LABEL[step.status]}</span>
              {step.detail && step.status !== "running" && <span className="agent__step-detail">{step.detail}</span>}
            </div>
          );
        })}

        {thinking && (
          <p className="agent__text agent__thinking" role="status">
            <span className="agent__thinking-label">
              Thinking… ({models?.find((m) => m.id === modelId)?.name ?? "the model"}, {Math.max(0, Math.round((Date.now() - thinking.since) / 1000))} s)
            </span>
            {thinking.text && <span className="agent__thinking-text">{thinking.text}</span>}
          </p>
        )}

        {approval && (
          <div className="agent__card" role="alertdialog" aria-label="Allow this action?">
            <p className="agent__card-title">Allow this action?</p>
            <p className="agent__card-action">{approval.request.summary}</p>
            <p className="agent__card-why">{approval.request.verdict.message}</p>
            {approval.request.review && <p className="agent__card-why">Reviewer: {approval.request.review}</p>}
            {approval.request.access && (
              <p className="agent__card-why">Chrome will ask you to let Alpharouter work on {approval.request.access.host}.</p>
            )}
            <div className="panel__actions">
              <button type="button" className="btn btn--primary" onClick={allow} disabled={approval.asking}>
                Allow
              </button>
              <button type="button" className="btn" onClick={() => approval.resolve(false)} disabled={approval.asking}>
                Deny
              </button>
            </div>
          </div>
        )}

        {paused && (
          <div className="agent__card" role="status" aria-label="You took over">
            <p className="agent__card-title">You took over</p>
            <p className="agent__card-action">The agent is paused while you use the page. Resume when you are ready, or stop the run.</p>
            <div className="panel__actions">
              <button type="button" className="btn btn--primary" onClick={() => void resume()}>
                Resume
              </button>
              <button type="button" className="btn" onClick={stop}>
                Stop
              </button>
            </div>
          </div>
        )}

        {question && (
          <form
            className="agent__card"
            aria-label="The agent asks"
            onSubmit={(event) => {
              event.preventDefault();
              question.resolve(answer);
            }}
          >
            <p className="agent__card-title">The agent asks</p>
            <p className="agent__card-action">{question.text}</p>
            <textarea
              aria-label="Your answer"
              value={answer}
              rows={2}
              onChange={(event) => setAnswer(event.target.value)}
            />
            <div className="panel__actions">
              <button type="submit" className="btn btn--primary" disabled={!answer.trim()}>
                Answer
              </button>
              <button type="button" className="btn" onClick={() => question.resolve("")}>
                Skip
              </button>
            </div>
          </form>
        )}
        <div ref={logEnd} />
      </div>

      <form
        className="chat__composer"
        onSubmit={(event) => {
          event.preventDefault();
          start();
        }}
      >
        <textarea
          aria-label="Task"
          value={draft}
          rows={2}
          maxLength={MAX_TASK_CHARS}
          disabled={running || starting}
          placeholder="What should Alpharouter do in your browser?"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              start();
            }
          }}
        />
        {running ? (
          <button type="button" className="btn" onClick={stop}>
            Stop
          </button>
        ) : (
          <button type="submit" className="btn btn--primary" disabled={!draft.trim() || !modelId || starting}>
            Start
          </button>
        )}
      </form>
    </main>
  );
}
