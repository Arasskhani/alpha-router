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
import { originOf, type AgentMode, type PolicyContext } from "../lib/agentPolicy";
import { ChatStreamError, readChatStream } from "../lib/chatStream";
import { getClient } from "../lib/client";
import { fromTabScript, isExtensionMessage } from "../lib/messages";
import { DisconnectedError, TemporaryError } from "../lib/tokens";
import { useActivePage, useSiteAccess } from "./activePage";
import { createAgentBrowser, type PanelBrowser } from "./agentBrowser";
import { runAgent, type AgentDeps, type AgentEventReport, type ApprovalRequest, type RunOutcome, type StepView } from "./agentRun";
import { AGENT_TOOLS } from "./agentTools";
import { pickModel, textModels, type ChatModel } from "./chat";
import type { Me } from "./types";

const MODEL_KEY = "alpharouter.agentModel";
const MODE_KEY = "alpharouter.agentMode";
const DEFAULT_MAX_STEPS = 25;
/** Events go to the server in batches of this many, and whatever is left when a run ends. */
const EVENT_BATCH = 10;
/** Each argument a review sees, cut to fit the reviewer's limit. */
const REVIEW_ARGUMENT_CHARS = 1500;

type LogItem =
  | { kind: "task"; id: string; text: string }
  | { kind: "step"; id: string; step: StepView }
  | { kind: "text"; id: string; text: string }
  | { kind: "result"; id: string; outcome: RunOutcome; summary: string };

type Props = {
  me: Me;
  /** Whether this view is the one on screen: a run goes on while the chat is shown. */
  hidden?: boolean;
  /** The server ended the session. */
  onDisconnected: () => void;
};

function randomHex(bytes: number): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(bytes)), (b) => b.toString(16).padStart(2, "0")).join("");
}

function serverHost(url: string | null): string | null {
  try {
    return url ? new URL(url).hostname : null;
  } catch {
    return null;
  }
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
  errors: "Stopped after errors",
  failed: "Could not go on",
};

function describeError(err: unknown): string {
  if (err instanceof ApiError || err instanceof ChatStreamError || err instanceof TemporaryError) return err.message;
  return "Something went wrong.";
}

export default function AgentView({ me, hidden = false, onDisconnected }: Props) {
  const [models, setModels] = useState<ChatModel[] | null>(null);
  const [modelsFailed, setModelsFailed] = useState(false);
  const [modelLoads, setModelLoads] = useState(0);
  const [modelId, setModelId] = useState("");
  const [mode, setMode] = useState<AgentMode>("ask");
  const [draft, setDraft] = useState("");
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState<LogItem[]>([]);
  const [approval, setApproval] = useState<{ request: ApprovalRequest; resolve: (ok: boolean) => void } | null>(null);
  const [question, setQuestion] = useState<{ text: string; resolve: (answer: string) => void } | null>(null);
  const [answer, setAnswer] = useState("");
  const [banner, setBanner] = useState("");
  const controller = useRef<AbortController | null>(null);
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
  const rules = useMemo<PolicyContext>(
    () => ({
      policy: { allowed_sites: me.policy?.allowed_sites ?? [], blocked_sites: me.policy?.blocked_sites ?? [] },
      serverHost: serverHost(me.server.url),
      serverOrigin: originOf(me.server.url),
    }),
    [me],
  );

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
        setMode(autoAllowed && stored[MODE_KEY] === "auto" ? "auto" : "ask");
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
  }, [me, autoAllowed, modelLoads]);

  // Stop from the banner on the page the agent works in: only from our own script there, for this run.
  useEffect(() => {
    const listener = (message: unknown, sender: chrome.runtime.MessageSender) => {
      const tabId = browser.current?.workingTab();
      if (tabId === null || tabId === undefined || !isExtensionMessage(message) || message.type !== "agent-stop") return;
      if (message.run === runId.current && fromTabScript(sender, tabId)) controller.current?.abort();
    };
    chrome.runtime.onMessage.addListener(listener);
    return () => chrome.runtime.onMessage.removeListener(listener);
  }, []);

  useEffect(() => {
    logEnd.current?.scrollIntoView?.({ block: "end" });
  }, [log, approval, question]);

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

  function showStep(step: StepView) {
    setLog((items) => {
      const at = items.findIndex((item) => item.kind === "step" && item.id === step.id);
      if (at < 0) return [...items, { kind: "step", id: step.id, step }];
      const next = items.slice();
      next[at] = { kind: "step", id: step.id, step };
      return next;
    });
  }

  async function flush() {
    const batch = events.current.splice(0, 50);
    if (!batch.length) return;
    try {
      await getClient().api.request("/api/extension/events", { method: "POST", body: JSON.stringify({ events: batch }) });
    } catch {
      // The trail is best effort: a lost batch never stops the agent.
    }
  }

  function deps(model: string): AgentDeps {
    const { api } = getClient();
    return {
      async model(messages, stepSignal) {
        try {
          const response = await api.request("/api/chat/completions", {
            method: "POST",
            // No chat, no history, no assistant message id: each step stands alone.
            body: JSON.stringify({ model, messages, stream: true, browser_tools: AGENT_TOOLS, browser_tool_choice: "auto" }),
            signal: stepSignal,
          });
          if (!response.ok) throw await ApiError.from(response);
          const result = await readChatStream(response);
          return { text: result.text, toolCalls: result.toolCalls };
        } catch (err) {
          if (err instanceof DisconnectedError) disconnected.current();
          if (err instanceof DOMException && err.name === "AbortError") throw err;
          throw new Error(describeError(err));
        }
      },
      browser: browser.current!,
      approve: (request, stepSignal) =>
        new Promise<boolean>((resolve) => {
          const settle = (ok: boolean) => {
            stepSignal.removeEventListener("abort", onAbort);
            setApproval(null);
            resolve(ok);
          };
          const onAbort = () => settle(false);
          stepSignal.addEventListener("abort", onAbort, { once: true });
          setApproval({ request, resolve: settle });
        }),
      askUser: (text, stepSignal) =>
        new Promise<string>((resolve) => {
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
        const clipped = Object.fromEntries(
          Object.entries(input.arguments).map(([key, value]) => [key, typeof value === "string" ? value.slice(0, REVIEW_ARGUMENT_CHARS) : value]),
        );
        try {
          const verdict = await api.json<{ decision?: string; reason?: string }>("/api/extension/review-action", {
            method: "POST",
            body: JSON.stringify({ ...input, arguments: clipped }),
            signal: stepSignal,
          });
          return verdict.decision === "allow"
            ? { decision: "allow", reason: verdict.reason ?? "" }
            : { decision: "ask", reason: verdict.reason || "The reviewer wants you to decide." };
        } catch (err) {
          if (err instanceof DOMException && err.name === "AbortError") throw err;
          return { decision: "ask", reason: "The reviewer could not be reached." };
        }
      },
      report(event) {
        events.current.push(event);
        if (events.current.length >= EVENT_BATCH) void flush();
      },
      onStep: showStep,
      onText: (text) => append({ kind: "text", id: randomHex(6), text }),
    };
  }

  async function begin(task: string) {
    const run = `run-${randomHex(8)}`;
    const abort = new AbortController();
    controller.current = abort;
    runId.current = run;
    browser.current = createAgentBrowser({ startTabId: activePage?.tabId ?? null, runId: run });
    setBanner("");
    setDraft("");
    setLog([{ kind: "task", id: run, text: task }]);
    setRunning(true);
    try {
      const result = await runAgent(
        { task, mode, maxSteps, rules, runId: run, nonce: randomHex(6), modelRef: modelId },
        deps(modelId),
        abort.signal,
      );
      append({ kind: "result", id: `${run}-end`, outcome: result.outcome, summary: result.summary });
    } finally {
      await browser.current?.cleanup().catch(() => undefined);
      await flush();
      setRunning(false);
      setApproval(null);
      setQuestion(null);
      if (controller.current === abort) controller.current = null;
    }
  }

  function start() {
    const task = draft.trim();
    if (!task || running || !modelId) return;
    if (target && siteAccess === false) {
      // Chrome asks only while a click is being handled: at once, nothing awaited first.
      chrome.permissions
        .request({ origins: [target.pattern] })
        .then((granted) => {
          if (granted) void begin(task);
          else setBanner(`The agent needs your permission to work on ${target.host}.`);
        })
        .catch(() => setBanner(`The agent needs your permission to work on ${target.host}.`));
      return;
    }
    void begin(task);
  }

  function stop() {
    controller.current?.abort();
  }

  function allow() {
    const pending = approval;
    if (!pending) return;
    const access = pending.request.access;
    if (access) {
      // The site's permission, asked for in this click: Chrome shows its prompt only now.
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
        {autoAllowed && (
          <div className="agent__modes" role="radiogroup" aria-label="Mode">
            {(["ask", "auto"] as const).map((value) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={mode === value}
                className={`agent__mode${mode === value ? " agent__mode--on" : ""}`}
                disabled={running}
                onClick={() => chooseMode(value)}
              >
                {value === "ask" ? "Ask" : "Auto"}
              </button>
            ))}
          </div>
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
          const { step } = item;
          return (
            <div key={item.id} className={`agent__step agent__step--${step.status}`} data-step-status={step.status}>
              <span className="agent__step-summary">{step.summary}</span>
              <span className="agent__step-status">{STATUS_LABEL[step.status]}</span>
              {step.detail && step.status !== "running" && <span className="agent__step-detail">{step.detail}</span>}
            </div>
          );
        })}

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
              <button type="button" className="btn btn--primary" onClick={allow}>
                Allow
              </button>
              <button type="button" className="btn" onClick={() => approval.resolve(false)}>
                Deny
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
          disabled={running}
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
          <button type="submit" className="btn btn--primary" disabled={!draft.trim() || !modelId}>
            Start
          </button>
        )}
      </form>
    </main>
  );
}
