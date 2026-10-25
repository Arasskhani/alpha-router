/**
 * @vitest-environment happy-dom
 *
 * A new chat with text waiting in its composer ("Ask Alpharouter" on an
 * email): the one-shot hand-over, its age limit, storage blocked, and the hook
 * the chat page uses (waits until ready, takes a request made while open, once
 * only, never after unmounting).
 */
import { StrictMode, act, useEffect, useRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  CHAT_PREFILL_EVENT,
  CHAT_PREFILL_MAX_AGE_MS,
  requestChatPrefill,
  takeChatPrefill,
  useChatPrefill,
} from "./chatPrefill";

const KEY = "alpha-router:chat-prefill";

beforeEach(() => {
  sessionStorage.clear();
  takeChatPrefill();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("requestChatPrefill / takeChatPrefill", () => {
  it("hands the text over once", () => {
    requestChatPrefill('Help me with this email (ref m7Q2): "Budget" from Sara.');
    expect(sessionStorage.getItem(KEY)).toContain("Budget");
    expect(takeChatPrefill()).toBe('Help me with this email (ref m7Q2): "Budget" from Sara.');
    expect(takeChatPrefill()).toBeNull();
    expect(sessionStorage.getItem(KEY)).toBeNull();
  });

  it("asks nothing for empty text and trims the rest", () => {
    requestChatPrefill("   ");
    expect(takeChatPrefill()).toBeNull();
    requestChatPrefill("  hello  ");
    expect(takeChatPrefill()).toBe("hello");
  });

  it("tells an open chat page through a window event", () => {
    const heard = vi.fn();
    window.addEventListener(CHAT_PREFILL_EVENT, heard);
    requestChatPrefill("hello");
    window.removeEventListener(CHAT_PREFILL_EVENT, heard);
    expect(heard).toHaveBeenCalledTimes(1);
  });

  it("drops a request nobody took in time", () => {
    vi.useFakeTimers();
    requestChatPrefill("old prompt");
    vi.advanceTimersByTime(CHAT_PREFILL_MAX_AGE_MS + 1000);
    expect(takeChatPrefill()).toBeNull();
    expect(sessionStorage.getItem(KEY)).toBeNull();
  });

  it("ignores a stored value that is not its own", () => {
    sessionStorage.setItem(KEY, "not json");
    expect(takeChatPrefill()).toBeNull();
    sessionStorage.setItem(KEY, JSON.stringify({ text: 5 }));
    expect(takeChatPrefill()).toBeNull();
  });

  it("works from memory when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    requestChatPrefill("from memory");
    expect(takeChatPrefill()).toBe("from memory");
    expect(takeChatPrefill()).toBeNull();
  });
});

describe("useChatPrefill", () => {
  let host: HTMLDivElement;
  let root: Root;
  let applied: string[];

  function Probe({ ready }: { ready: boolean }) {
    useChatPrefill(ready, (text) => applied.push(text));
    return null;
  }

  async function render(ready: boolean, strict = false) {
    await act(async () => {
      root.render(strict ? <StrictMode><Probe ready={ready} /></StrictMode> : <Probe ready={ready} />);
    });
    // The hand-over runs in a microtask after React's own work.
    await act(async () => undefined);
  }

  beforeEach(() => {
    applied = [];
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
  });

  afterEach(() => {
    act(() => root.unmount());
    host.remove();
  });

  it("waits until the chat is ready, then takes the waiting text once", async () => {
    requestChatPrefill("waiting");
    await render(false);
    expect(applied).toEqual([]);
    await render(true);
    expect(applied).toEqual(["waiting"]);
    await render(true);
    expect(applied).toEqual(["waiting"]);
    expect(takeChatPrefill()).toBeNull();
  });

  it("takes a request made while the chat is open", async () => {
    await render(true);
    expect(applied).toEqual([]);
    await act(async () => requestChatPrefill("while open"));
    await act(async () => undefined);
    expect(applied).toEqual(["while open"]);
  });

  it("runs after React's effects, not inside them (the chat calls flushSync)", async () => {
    function Ordered() {
      const effectsDone = useRef(false);
      useChatPrefill(true, () => applied.push(effectsDone.current ? "after effects" : "inside an effect"));
      useEffect(() => {
        effectsDone.current = true;
      });
      return null;
    }
    requestChatPrefill("x");
    await act(async () => {
      root.render(<Ordered />);
    });
    await act(async () => undefined);
    expect(applied).toEqual(["after effects"]);
  });

  it("takes it once under StrictMode's double mount", async () => {
    requestChatPrefill("strict");
    await render(true, true);
    expect(applied).toEqual(["strict"]);
  });

  it("leaves the text for the next chat page when unmounted first", async () => {
    await render(true);
    act(() => root.unmount());
    root = createRoot(host);
    requestChatPrefill("later");
    await act(async () => undefined);
    expect(applied).toEqual([]);
    expect(takeChatPrefill()).toBe("later");
  });
});
