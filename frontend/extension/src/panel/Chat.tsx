import { useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../lib/api";
import { ChatStreamError, readChatStream } from "../lib/chatStream";
import { getClient } from "../lib/client";
import { fromOwnPages, isExtensionMessage } from "../lib/messages";
import {
  MAX_PAGE_SITES,
  PageReadError,
  pageRefusal,
  readPage,
  selectionContext,
  type PageContext,
  type SiteRules,
} from "../lib/pageContext";
import { takePendingAction, type PendingAction, type PendingActionKind } from "../lib/pendingAction";
import { readablePage } from "../lib/sites";
import { DisconnectedError, TemporaryError } from "../lib/tokens";
import { compareVersions } from "../lib/version";
import { useActivePage, useSiteAccess } from "./activePage";
import { completionBody, pagesIn, pickModel, textModels, type ChatModel, type Turn } from "./chat";
import PanelMarkdown from "./PanelMarkdown";
import type { Me } from "./types";

const MODEL_KEY = "alpharouter.model";

/** What a right-click action asks; the page or the selection goes with it. */
const ACTION_QUESTIONS: Record<Exclude<PendingActionKind, "ask">, string> = {
  summarize: "Summarize this page.",
  explain: "Explain the selected text.",
  translate: "Translate the selected text to Persian.",
};

function hostOf(url: string): string | null {
  try {
    return new URL(url).hostname;
  } catch {
    return null;
  }
}

function PageIcon() {
  return (
    <svg className="chip__icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false">
      <path d="M4 1.5h5l3 3v10H4z" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M9 1.5v3h3M6 8h4M6 10.5h4" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

type Props = {
  me: Me;
  server: string;
  /** The user chose Disconnect. */
  onDisconnect: () => void;
  /** The server ended the session while chatting. */
  onDisconnected: () => void;
};

function describe(err: unknown): string {
  if (err instanceof ApiError || err instanceof ChatStreamError || err instanceof TemporaryError) return err.message;
  return "Something went wrong. Try again.";
}

export default function Chat({ me, server, onDisconnect, onDisconnected }: Props) {
  const [models, setModels] = useState<ChatModel[] | null>(null);
  const [modelId, setModelId] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [privateMode, setPrivateMode] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");
  const [copied, setCopied] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  // A ref, not state: Stop right after the first Send must know the new id.
  const sessionId = useRef<string | null>(null);
  const log = useRef<HTMLDivElement | null>(null);
  const disconnected = useRef(onDisconnected);
  const activePage = useActivePage();
  const target = me.features.page_context ? (activePage?.target ?? null) : null;
  const siteAccess = useSiteAccess(target?.pattern ?? null);
  // "This page" is chosen for one tab and origin: switching tabs or sites turns it off.
  const [attachFor, setAttachFor] = useState<{ tabId: number; origin: string } | null>(null);
  const [reading, setReading] = useState(false);
  /** Text selected on a page ("Ask Alpharouter about…"), sent with the next question. */
  const [selections, setSelections] = useState<PageContext[]>([]);
  // Refs for the right-click actions, which arrive from Chrome at any time.
  const modelRef = useRef("");
  const busyRef = useRef(false);
  const waitingAction = useRef<PendingAction | null>(null);
  const actionHandler = useRef<(action: PendingAction) => void>(() => undefined);
  const composer = useRef<HTMLTextAreaElement | null>(null);
  const rules = useMemo<SiteRules>(
    () => ({
      policy: { allowed_sites: me.policy?.allowed_sites ?? [], blocked_sites: me.policy?.blocked_sites ?? [] },
      serverHost: hostOf(server),
    }),
    [me.policy, server],
  );

  useEffect(() => {
    disconnected.current = onDisconnected;
  }, [onDisconnected]);

  useEffect(() => {
    let active = true;
    Promise.all([getClient().api.json<ChatModel[]>("/api/chat/models"), chrome.storage.local.get(MODEL_KEY)])
      .then(([rows, stored]) => {
        if (!active) return;
        const usable = textModels(rows);
        const picked = pickModel(usable, typeof stored[MODEL_KEY] === "string" ? stored[MODEL_KEY] : null)?.id ?? "";
        setModels(usable);
        setModelId(picked);
        modelRef.current = picked;
        // A right-click action that opened the panel waited for the models.
        const waiting = waitingAction.current;
        if (waiting && picked) {
          waitingAction.current = null;
          actionHandler.current(waiting);
        }
      })
      .catch((err: unknown) => {
        if (!active) return;
        if (err instanceof DisconnectedError) {
          disconnected.current();
          return;
        }
        setModels([]);
        setBanner(describe(err));
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const el = log.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns]);

  // The latest render's handler: the listener below lives as long as the panel.
  useEffect(() => {
    actionHandler.current = (action) => void runAction(action);
  });

  useEffect(() => {
    let active = true;
    const check = () => {
      chrome.windows
        .getCurrent()
        .then((win) => (win.id === undefined ? null : takePendingAction(win.id)))
        .then((action) => {
          if (!active || !action) return;
          if (modelRef.current) actionHandler.current(action);
          else waitingAction.current = action;
        })
        .catch(() => undefined);
    };
    const listener = (message: unknown, sender: chrome.runtime.MessageSender) => {
      if (fromOwnPages(sender) && isExtensionMessage(message) && message.type === "pending-action") check();
    };
    check();
    chrome.runtime.onMessage.addListener(listener);
    return () => {
      active = false;
      chrome.runtime.onMessage.removeListener(listener);
    };
  }, []);

  const version = chrome.runtime.getManifest().version;
  const tooOld = compareVersions(version, me.extension.min_version || "0") < 0;
  const newer = me.extension.latest_version && compareVersions(version, me.extension.latest_version) < 0;
  const attached = Boolean(
    target && activePage && attachFor && attachFor.tabId === activePage.tabId && attachFor.origin === target.origin,
  );
  const pageModels = me.policy?.page_content_models ?? [];

  /** Why this site's pages cannot go to this model, if they cannot. */
  function pageBlockFor(host: string, model: string): string | null {
    return (
      pageRefusal(host, rules) ??
      (pageModels.length && !pageModels.includes(model)
        ? "Your administrator does not allow pages to be sent to this model. Choose another model."
        : null)
    );
  }

  /** "This page", unless the rules keep it from going right now. */
  const pageBlock = target ? pageBlockFor(target.host, modelId) : null;

  /** A chat carries pages from at most as many sites as the server accepts in one request. */
  function siteLimitError(hosts: string[]): string | null {
    const sites = new Set(pagesIn(turns).map((page) => page.host));
    for (const host of hosts) sites.add(host);
    return sites.size > MAX_PAGE_SITES
      ? `This chat already has pages from ${MAX_PAGE_SITES} sites. Start a new chat to share more.`
      : null;
  }

  function markBusy(value: boolean) {
    busyRef.current = value;
    setBusy(value);
  }

  function chooseModel(id: string) {
    modelRef.current = id;
    setModelId(id);
    void chrome.storage.local.set({ [MODEL_KEY]: id });
  }

  async function nameTheChat(sid: string, question: string, answer: string, model: string) {
    const { api } = getClient();
    try {
      const { title } = await api.json<{ title: string }>("/api/chat/session-title", {
        method: "POST",
        body: JSON.stringify({
          model,
          messages: [
            { role: "user", content: question },
            { role: "assistant", content: answer },
          ],
        }),
      });
      if (title) {
        await api.request(`/api/user/chats/sessions/${encodeURIComponent(sid)}`, {
          method: "PATCH",
          body: JSON.stringify({ title, titleGenerated: true }),
        });
      }
    } catch {
      // The server already titled the chat from the question.
    }
  }

  function togglePage() {
    if (!target || !activePage) return;
    if (attached) {
      setAttachFor(null);
      return;
    }
    const choice = { tabId: activePage.tabId, origin: target.origin };
    if (siteAccess) {
      setAttachFor(choice);
      return;
    }
    const { host } = target;
    // Chrome asks the user only while the click is being handled: nothing may come first.
    chrome.permissions
      .request({ origins: [target.pattern] })
      .then((granted) => {
        if (granted) {
          setAttachFor(choice);
          setBanner("");
        } else {
          setBanner(`Alpharouter can read pages on ${host} only if you allow it when Chrome asks.`);
        }
      })
      .catch(() => setBanner("Chrome could not ask for permission. Try again."));
  }

  /** Read a tab's page for the question about to go; the banner says why not, and null comes back. */
  async function readForQuestion(tab: { id: number; url: string }): Promise<PageContext | null> {
    markBusy(true);
    setReading(true);
    setBanner("");
    try {
      return (await readPage(tab, rules)).page;
    } catch (err) {
      setBanner(err instanceof PageReadError ? err.message : "Alpharouter could not read this page.");
      return null;
    } finally {
      setReading(false);
      markBusy(false);
    }
  }

  /** The server refused a site: its pages leave the conversation, so the next question can go. */
  function dropPagesFrom(host: string) {
    setTurns((all) =>
      all.map((turn) => (turn.pages?.some((page) => page.host === host) ? { ...turn, pages: turn.pages.filter((page) => page.host !== host) } : turn)),
    );
  }

  async function send() {
    const text = draft.trim();
    if (!text || busyRef.current || !modelId) return;
    const pages = [...selections];
    const tab = attached && activePage && target ? { id: activePage.tabId, url: activePage.url, host: target.host } : null;
    const hosts = [...pages.map((page) => page.host), ...(tab ? [tab.host] : [])];
    const refused = hosts.map((host) => pageBlockFor(host, modelId)).find(Boolean) ?? (hosts.length ? siteLimitError(hosts) : null);
    if (refused) {
      setBanner(refused);
      return;
    }
    if (tab) {
      const page = await readForQuestion(tab);
      if (!page) return;
      pages.push(page);
    }
    setAttachFor(null);
    setSelections([]);
    setDraft("");
    await sendTurn(text, pages, modelId);
  }

  /** A question for the model, with the pages that go with it. */
  async function sendTurn(text: string, pages: PageContext[], model: string) {
    const user: Turn = { id: crypto.randomUUID(), role: "user", content: text, ...(pages.length ? { pages } : {}) };
    const assistant: Turn = { id: crypto.randomUUID(), role: "assistant", content: "", streaming: true };
    const history = turns;
    if (!privateMode) sessionId.current ??= crypto.randomUUID();
    const sid = privateMode ? null : sessionId.current;
    setTurns([...history, user, assistant]);
    markBusy(true);
    setBanner("");
    const abort = new AbortController();
    controller.current = abort;
    const update = (patch: Partial<Turn>) =>
      setTurns((all) => all.map((turn) => (turn.id === assistant.id ? { ...turn, ...patch } : turn)));
    try {
      const response = await getClient().api.request("/api/chat/completions", {
        method: "POST",
        body: JSON.stringify(
          completionBody({ model, history, user, assistantId: assistant.id, sessionId: sid, sentAt: Date.now() }),
        ),
        signal: abort.signal,
      });
      if (!response.ok) throw await ApiError.from(response);
      const result = await readChatStream(response, { onText: (full) => update({ content: full }) });
      update({ content: result.text, streaming: false });
      if (sid && history.length === 0 && result.text) void nameTheChat(sid, text, result.text, model);
    } catch (err) {
      if (abort.signal.aborted) update({ streaming: false, stopped: true });
      else if (err instanceof DisconnectedError) disconnected.current();
      else {
        if (err instanceof ApiError && err.code === "site_not_allowed" && typeof err.detail.site === "string") {
          dropPagesFrom(err.detail.site);
        }
        update({ streaming: false, error: describe(err) });
      }
    } finally {
      controller.current = null;
      markBusy(false);
    }
  }

  /** A right-click action: summarize the page, or explain, translate or ask about the selection. */
  async function runAction(action: PendingAction) {
    if (!me.features.chat || tooOld) return;
    if (busyRef.current) {
      setBanner("Alpharouter is still answering. Stop it or wait, then try again.");
      return;
    }
    const model = modelRef.current;
    const page = me.features.page_context ? readablePage(action.pageUrl) : null;
    if (!page) {
      setBanner(
        action.kind === "summarize" || !me.features.page_context
          ? "Alpharouter cannot read this page."
          : "Alpharouter cannot read text selected in that part of the page.",
      );
      return;
    }
    const refused = pageBlockFor(page.host, model) ?? siteLimitError([page.host]);
    if (refused) {
      setBanner(refused);
      return;
    }
    if (action.kind === "summarize") {
      const read = await readForQuestion({ id: action.tabId, url: action.pageUrl });
      if (read) await sendTurn(ACTION_QUESTIONS.summarize, [read], model);
      return;
    }
    const selected = selectionContext(action.pageUrl, action.title, action.selection);
    if (!selected) {
      setBanner("Select some text on the page first.");
      return;
    }
    setBanner("");
    if (action.kind === "ask") {
      setSelections((all) => [...all.filter((item) => item.text !== selected.text || item.host !== selected.host), selected]);
      composer.current?.focus();
      return;
    }
    await sendTurn(ACTION_QUESTIONS[action.kind], [selected], model);
  }

  function stop() {
    controller.current?.abort();
    const sid = sessionId.current;
    if (sid && !privateMode) {
      // The server keeps generating for a saved chat until told.
      void getClient()
        .api.request(`/api/user/chat-sessions/${encodeURIComponent(sid)}/cancel-stream`, { method: "POST" })
        .catch(() => undefined);
    }
  }

  function newChat() {
    if (busy) stop();
    setTurns([]);
    setSelections([]);
    setBanner("");
    sessionId.current = null;
  }

  function togglePrivate() {
    newChat();
    setPrivateMode((on) => !on);
  }

  async function copy(turn: Turn) {
    try {
      await navigator.clipboard.writeText(turn.content);
      setCopied(turn.id);
      window.setTimeout(() => setCopied((id) => (id === turn.id ? null : id)), 1500);
    } catch {
      setBanner("Copying is not allowed here.");
    }
  }

  if (!me.features.chat || tooOld) {
    return (
      <main className="panel panel__center">
        <h1 className="panel__title">Alpharouter</h1>
        <p className="banner banner--warning" role="status">
          {tooOld
            ? "This copy of the extension is too old for your Alpharouter. Download the new version from Settings → Extension."
            : "The browser extension is not enabled for your account. Ask your administrator if you need it."}
        </p>
        <div className="panel__actions">
          <button type="button" className="btn" onClick={onDisconnect}>
            Disconnect
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="panel chat">
      <header className="chat__header">
        <select
          className="chat__model"
          aria-label="Model"
          value={modelId}
          disabled={!models?.length || busy}
          onChange={(event) => chooseModel(event.target.value)}
        >
          {!models && <option value="">Loading models…</option>}
          {models?.length === 0 && <option value="">No models available</option>}
          {models?.map((model) => (
            <option key={model.id} value={model.id}>
              {model.name}
            </option>
          ))}
        </select>
        {privateMode && <span className="chat__private">Private</span>}
        <button type="button" className="btn btn--quiet" onClick={newChat}>
          New chat
        </button>
        <details className="chat__menu">
          <summary aria-label="More">⋯</summary>
          <div className="chat__menu-items">
            {me.features.private_mode && (
              <button type="button" className="btn btn--quiet" onClick={togglePrivate}>
                {privateMode ? "Leave Private" : "Private chat"}
              </button>
            )}
            <a className="btn btn--quiet" href={`${server}/app/chat`} target="_blank" rel="noopener noreferrer">
              Open Alpharouter
            </a>
            <button type="button" className="btn btn--quiet" onClick={onDisconnect}>
              Disconnect
            </button>
          </div>
        </details>
      </header>

      {newer && (
        <p className="banner banner--warning chat__notice" role="status">
          A new version of the extension is available. Download it from Settings → Extension in Alpharouter.
        </p>
      )}
      {banner && (
        <p className="banner banner--error chat__notice" role="alert">
          {banner}
        </p>
      )}

      <div className="chat__log" role="log" aria-live="polite" ref={log}>
        {turns.length === 0 && (
          <p className="chat__empty">
            {privateMode
              ? "Private chat: nothing is saved, and it is gone when you start a new chat."
              : `Ask anything, ${me.user.display_name || me.user.username}. Chats are saved to your Alpharouter history.`}
            {me.features.page_context && " To ask about the page next to this panel, turn on “This page” below."}
          </p>
        )}
        {turns.map((turn) => (
          <article key={turn.id} className={`turn turn--${turn.role}`}>
            {turn.pages?.map((shared, index) => (
              <p key={index} className="turn__page" title={shared.url}>
                <PageIcon />
                <span className="turn__page-title">
                  {shared.part === "selection" ? "Selected text" : shared.title || shared.host}
                </span>
                <span className="turn__page-site">{shared.truncated ? `${shared.host}, first part` : shared.host}</span>
              </p>
            ))}
            {turn.role === "user" ? <p className="turn__text">{turn.content}</p> : turn.content && <PanelMarkdown text={turn.content} />}
            {turn.streaming && !turn.content && <p className="turn__pending">Thinking…</p>}
            {turn.stopped && <p className="turn__meta">Stopped.</p>}
            {turn.error && (
              <p className="banner banner--error" role="alert">
                {turn.error}
              </p>
            )}
            {turn.role === "assistant" && !turn.streaming && turn.content && (
              <button type="button" className="btn btn--quiet turn__copy" aria-label="Copy answer" onClick={() => void copy(turn)}>
                {copied === turn.id ? "Copied" : "Copy"}
              </button>
            )}
          </article>
        ))}
      </div>

      <form
        className="chat__composer"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        {(selections.length > 0 || (target && activePage)) && (
          <div className="chat__context">
            {selections.map((selected, index) => (
              <span key={index} className="chip chip--on chip--static" title={selected.text.slice(0, 300)}>
                <PageIcon />
                <span className="chip__label">Selected text</span>
                <span className="chip__site">{selected.host}</span>
                <button
                  type="button"
                  className="chip__remove"
                  aria-label={`Remove the text selected on ${selected.host}`}
                  disabled={busy}
                  onClick={() => setSelections((all) => all.filter((_, i) => i !== index))}
                >
                  ×
                </button>
              </span>
            ))}
            {target && activePage && (
              <button
                type="button"
                className={`chip${attached ? " chip--on" : ""}`}
                aria-pressed={attached}
                disabled={Boolean(pageBlock) || busy}
                onClick={togglePage}
                title={activePage.url}
              >
                <PageIcon />
                <span className="chip__label">{attached ? "Sending this page" : "This page"}</span>
                <span className="chip__site">{activePage.title || target.host}</span>
              </button>
            )}
            {reading && (
              <span className="chat__context-note" role="status">
                Reading the page…
              </span>
            )}
            {!reading && pageBlock && <span className="chat__context-note">{pageBlock}</span>}
          </div>
        )}
        <textarea
          ref={composer}
          aria-label="Message"
          value={draft}
          rows={2}
          placeholder={privateMode ? "Private message…" : "Message Alpharouter…"}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void send();
            }
          }}
        />
        {busy ? (
          <button type="button" className="btn" onClick={stop}>
            Stop
          </button>
        ) : (
          <button type="submit" className="btn btn--primary" disabled={!draft.trim() || !modelId}>
            Send
          </button>
        )}
      </form>
    </main>
  );
}
