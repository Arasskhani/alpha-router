import { useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../lib/api";
import { ChatStreamError, readChatStream } from "../lib/chatStream";
import { getClient } from "../lib/client";
import { MAX_PAGE_SITES, PageReadError, pageRefusal, readPage, type PageContext, type SiteRules } from "../lib/pageContext";
import { DisconnectedError, TemporaryError } from "../lib/tokens";
import { compareVersions } from "../lib/version";
import { useActivePage, useSiteAccess } from "./activePage";
import { completionBody, pagesIn, pickModel, textModels, type ChatModel, type Turn } from "./chat";
import PanelMarkdown from "./PanelMarkdown";
import type { Me } from "./types";

const MODEL_KEY = "alpharouter.model";

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
        setModels(usable);
        setModelId(pickModel(usable, typeof stored[MODEL_KEY] === "string" ? stored[MODEL_KEY] : null)?.id ?? "");
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

  const version = chrome.runtime.getManifest().version;
  const tooOld = compareVersions(version, me.extension.min_version || "0") < 0;
  const newer = me.extension.latest_version && compareVersions(version, me.extension.latest_version) < 0;
  const attached = Boolean(
    target && activePage && attachFor && attachFor.tabId === activePage.tabId && attachFor.origin === target.origin,
  );
  const pageModels = me.policy?.page_content_models ?? [];
  /** Why "This page" cannot be used right now, if it cannot. */
  const pageBlock = target
    ? (pageRefusal(target.host, rules) ??
      (pageModels.length && !pageModels.includes(modelId)
        ? "Your administrator does not allow pages to be sent to this model. Choose another model."
        : null))
    : null;

  function chooseModel(id: string) {
    setModelId(id);
    void chrome.storage.local.set({ [MODEL_KEY]: id });
  }

  async function nameTheChat(sid: string, question: string, answer: string) {
    const { api } = getClient();
    try {
      const { title } = await api.json<{ title: string }>("/api/chat/session-title", {
        method: "POST",
        body: JSON.stringify({
          model: modelId,
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

  /** The page to send with this question, read now; null when none; throws PageReadError. */
  async function pageToSend(): Promise<PageContext | null> {
    if (!attached || !activePage || !target) return null;
    if (pageBlock) throw new PageReadError(pageBlock);
    const sites = new Set(pagesIn(turns).map((page) => page.host));
    if (!sites.has(target.host) && sites.size >= MAX_PAGE_SITES) {
      throw new PageReadError(`This chat already has pages from ${MAX_PAGE_SITES} sites. Start a new chat to share more.`);
    }
    return (await readPage({ id: activePage.tabId, url: activePage.url }, rules)).page;
  }

  /** The server refused a site: its pages leave the conversation, so the next question can go. */
  function dropPagesFrom(host: string) {
    setTurns((all) =>
      all.map((turn) => (turn.pages?.some((page) => page.host === host) ? { ...turn, pages: turn.pages.filter((page) => page.host !== host) } : turn)),
    );
  }

  async function send() {
    const text = draft.trim();
    if (!text || busy || !modelId) return;
    let page: PageContext | null = null;
    if (attached) {
      setBusy(true);
      setReading(true);
      setBanner("");
      try {
        page = await pageToSend();
      } catch (err) {
        setBanner(err instanceof PageReadError ? err.message : "Alpharouter could not read this page.");
        return;
      } finally {
        setReading(false);
        setBusy(false);
      }
      setAttachFor(null);
    }
    const user: Turn = { id: crypto.randomUUID(), role: "user", content: text, ...(page ? { pages: [page] } : {}) };
    const assistant: Turn = { id: crypto.randomUUID(), role: "assistant", content: "", streaming: true };
    const history = turns;
    if (!privateMode) sessionId.current ??= crypto.randomUUID();
    const sid = privateMode ? null : sessionId.current;
    setTurns([...history, user, assistant]);
    setDraft("");
    setBusy(true);
    setBanner("");
    const abort = new AbortController();
    controller.current = abort;
    const update = (patch: Partial<Turn>) =>
      setTurns((all) => all.map((turn) => (turn.id === assistant.id ? { ...turn, ...patch } : turn)));
    try {
      const response = await getClient().api.request("/api/chat/completions", {
        method: "POST",
        body: JSON.stringify(
          completionBody({ model: modelId, history, user, assistantId: assistant.id, sessionId: sid, sentAt: Date.now() }),
        ),
        signal: abort.signal,
      });
      if (!response.ok) throw await ApiError.from(response);
      const result = await readChatStream(response, { onText: (full) => update({ content: full }) });
      update({ content: result.text, streaming: false });
      if (sid && history.length === 0 && result.text) void nameTheChat(sid, text, result.text);
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
      setBusy(false);
    }
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
                <span className="turn__page-title">{shared.title || shared.host}</span>
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
        {target && activePage && (
          <div className="chat__context">
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
            {reading && (
              <span className="chat__context-note" role="status">
                Reading the page…
              </span>
            )}
            {!reading && pageBlock && <span className="chat__context-note">{pageBlock}</span>}
          </div>
        )}
        <textarea
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
