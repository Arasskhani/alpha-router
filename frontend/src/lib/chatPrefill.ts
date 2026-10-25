/**
 * Open a new chat with text already in its composer, not sent: "Ask
 * Alpharouter" on an email that needs action (the Connections page and the
 * mail toasts) hands the chat a prompt the person can read and edit first.
 *
 * The chat page is often not mounted when the request is made (the person is on
 * Connections), so the text waits here, one-shot, until the chat is ready to
 * take it: in sessionStorage (it survives the chat page's code loading or a
 * reload in this tab, and no other tab sees it) or, when storage is blocked, in
 * memory. A chat page already open is told through a window event. A request
 * nobody takes within a few minutes is dropped, so an old prompt never turns up
 * in a chat opened much later.
 */
import { useEffect, useRef } from "react";

const STORAGE_KEY = "alpha-router:chat-prefill";
export const CHAT_PREFILL_EVENT = "alpha-router:chat-prefill";
export const CHAT_PREFILL_MAX_AGE_MS = 5 * 60_000;
/** Longer text is cut: a composer prompt, not a document. */
const MAX_CHARS = 4000;

type Pending = { text: string; at: number };

let memory: Pending | null = null;

function write(pending: Pending | null): void {
  memory = pending;
  try {
    if (pending) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(pending));
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage blocked: the copy in memory serves this page */
  }
}

function read(): Pending | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) {
      const value = JSON.parse(raw) as Partial<Pending>;
      if (typeof value.text === "string" && typeof value.at === "number") return { text: value.text, at: value.at };
    }
  } catch {
    /* storage blocked or the value is not ours */
  }
  return memory;
}

/** Ask the chat to open a new chat with `text` in its composer. Empty text asks nothing. */
export function requestChatPrefill(text: string): void {
  const value = (text ?? "").trim().slice(0, MAX_CHARS);
  if (!value) return;
  write({ text: value, at: Date.now() });
  window.dispatchEvent(new Event(CHAT_PREFILL_EVENT));
}

/** The waiting text, removed so it is used once; null when there is none or it is too old. */
export function takeChatPrefill(): string | null {
  const pending = read();
  if (!pending) return null;
  write(null);
  const age = Date.now() - pending.at;
  if (age < 0 || age > CHAT_PREFILL_MAX_AGE_MS) return null;
  return pending.text;
}

/**
 * For the chat page: once `ready` (chats and models loaded, a personal chat),
 * hand any waiting text to `apply`, which starts the new chat and fills its
 * composer; and again whenever a new request arrives while the page is open.
 */
export function useChatPrefill(ready: boolean, apply: (text: string) => void): void {
  // The latest `apply`, without re-subscribing on every render: the chat's own functions change each time.
  const applyRef = useRef(apply);
  useEffect(() => {
    applyRef.current = apply;
  });

  useEffect(() => {
    if (!ready) return undefined;
    let live = true;
    // Just after React's own work, not inside it: the chat makes the new chat with flushSync, which
    // cannot flush from inside an effect or an event React is handling.
    const take = () =>
      queueMicrotask(() => {
        if (!live) return;
        const text = takeChatPrefill();
        if (text) applyRef.current(text);
      });
    take();
    window.addEventListener(CHAT_PREFILL_EVENT, take);
    return () => {
      live = false;
      window.removeEventListener(CHAT_PREFILL_EVENT, take);
    };
  }, [ready]);
}
