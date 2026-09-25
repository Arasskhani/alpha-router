import { useEffect, useRef, useState } from "react";

import { ApiError } from "../lib/api";
import { ChatStreamError, readChatStream } from "../lib/chatStream";
import { getClient } from "../lib/client";
import { DisconnectedError, TemporaryError } from "../lib/tokens";
import { compareVersions } from "../lib/version";
import { completionBody, pickModel, textModels, type ChatModel, type Turn } from "./chat";
import PanelMarkdown from "./PanelMarkdown";
import type { Me } from "./types";

const MODEL_KEY = "alpharouter.model";

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

  async function send() {
    const text = draft.trim();
    if (!text || busy || !modelId) return;
    const user: Turn = { id: crypto.randomUUID(), role: "user", content: text };
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
      else update({ streaming: false, error: describe(err) });
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
          </p>
        )}
        {turns.map((turn) => (
          <article key={turn.id} className={`turn turn--${turn.role}`}>
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
