/**
 * Bringing back a reply cut off by a lost connection: the server's saved reply
 * replaces the error, a reply still being written is waited for, an abandoned
 * one is closed, and nothing else in the thread is touched.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CONNECTION_LOST_CONTENT } from "./chatConnection";
import type { ChatMessage } from "./chatStorage";
import {
  RECOVERY_MAX_TRIES,
  RECOVERY_RETRY_MS,
  RECOVERY_STUCK_MS,
  createReplyRecovery,
  type ReplyRecoveryDeps,
} from "./replyRecovery";

const prompt: ChatMessage = { role: "user", content: "Write a long answer", clientMessageId: "u1" };
const cutOff: ChatMessage = { role: "assistant", content: CONNECTION_LOST_CONTENT, clientMessageId: "a1", receivedAt: 1 };
const saved: ChatMessage = { role: "assistant", content: "Here is the first half", clientMessageId: "a1", receivedAt: 2 };

let clock = 0;
let timers: Array<{ fn: () => void; at: number }> = [];
let local: ChatMessage[];
let remote: ChatMessage[] | null | Error;
type Deps = ReplyRecoveryDeps & {
  replaceLast: ReturnType<typeof vi.fn<ReplyRecoveryDeps["replaceLast"]>>;
  finalizeAbandoned: ReturnType<typeof vi.fn<ReplyRecoveryDeps["finalizeAbandoned"]>>;
  fetchRemote: ReturnType<typeof vi.fn<ReplyRecoveryDeps["fetchRemote"]>>;
};
let deps: Deps;
let active: string | null;
let privateChat: boolean;
let busy: boolean;

/** Run every timer due within `ms`, letting each attempt's promise settle. */
async function advance(ms: number) {
  const until = clock + ms;
  for (;;) {
    timers.sort((a, b) => a.at - b.at);
    const next = timers[0];
    if (!next || next.at > until) break;
    timers.shift();
    clock = next.at;
    next.fn();
    await flush();
  }
  clock = until;
}

async function flush() {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
}

beforeEach(() => {
  clock = 0;
  timers = [];
  local = [prompt, cutOff];
  remote = [prompt, saved];
  active = "s1";
  privateChat = false;
  busy = false;
  deps = {
    activeSessionId: () => active,
    messagesOf: () => local,
    skip: () => privateChat,
    busy: () => busy,
    fetchRemote: vi.fn<ReplyRecoveryDeps["fetchRemote"]>(async () => {
      if (remote instanceof Error) throw remote;
      return remote;
    }),
    replaceLast: vi.fn<ReplyRecoveryDeps["replaceLast"]>((_sid, message) => {
      local = [...local.slice(0, -1), message];
    }),
    finalizeAbandoned: vi.fn<ReplyRecoveryDeps["finalizeAbandoned"]>(),
    now: () => clock,
    setTimer: (fn, ms) => {
      const timer = { fn, at: clock + ms };
      timers.push(timer);
      return timer;
    },
    clearTimer: (timer) => {
      timers = timers.filter((t) => t !== timer);
    },
  };
});

describe("createReplyRecovery", () => {
  it("puts the server's saved reply in place of the error, and only that message", async () => {
    createReplyRecovery(deps).nudge();
    await flush();
    expect(deps.replaceLast).toHaveBeenCalledWith("s1", saved);
    expect(local).toEqual([prompt, saved]);
    expect(timers).toHaveLength(0);
  });

  it("waits for the turn that failed to wind down before the first look", async () => {
    busy = true;
    createReplyRecovery(deps).nudge(RECOVERY_RETRY_MS);
    await flush();
    expect(deps.fetchRemote).not.toHaveBeenCalled();
    await advance(RECOVERY_RETRY_MS);
    expect(deps.fetchRemote).not.toHaveBeenCalled();
    busy = false;
    await advance(RECOVERY_RETRY_MS);
    expect(local).toEqual([prompt, saved]);
  });

  it("keeps looking while offline, and succeeds once the server answers", async () => {
    remote = new TypeError("Failed to fetch");
    createReplyRecovery(deps).nudge();
    await flush();
    await advance(RECOVERY_RETRY_MS * 3);
    expect(deps.replaceLast).not.toHaveBeenCalled();
    remote = [prompt, saved];
    await advance(RECOVERY_RETRY_MS);
    expect(local).toEqual([prompt, saved]);
  });

  it("waits for a reply the server is still writing, then shows it finished", async () => {
    remote = [prompt, { ...saved, streaming: true }];
    createReplyRecovery(deps).nudge();
    await flush();
    await advance(RECOVERY_RETRY_MS * 2);
    expect(deps.replaceLast).not.toHaveBeenCalled();
    remote = [prompt, { ...saved, content: "Here is the whole answer" }];
    await advance(RECOVERY_RETRY_MS);
    expect(local.at(-1)?.content).toBe("Here is the whole answer");
    expect(deps.finalizeAbandoned).not.toHaveBeenCalled();
  });

  it("closes a reply the server abandoned mid-stream, keeping its first part", async () => {
    remote = [prompt, { ...saved, streaming: true }];
    createReplyRecovery(deps).nudge();
    await flush();
    await advance(RECOVERY_STUCK_MS + RECOVERY_RETRY_MS);
    expect(deps.finalizeAbandoned).toHaveBeenCalledTimes(1);
    const closed = local.at(-1)!;
    expect(closed.content).toBe(`Here is the first half\n\n${CONNECTION_LOST_CONTENT}`);
    expect(closed.streaming).toBe(false);
    expect(timers).toHaveLength(0);
  });

  it("gives up after a while when the server never has the reply", async () => {
    remote = [prompt];
    createReplyRecovery(deps).nudge();
    await flush();
    await advance(RECOVERY_RETRY_MS * (RECOVERY_MAX_TRIES + 5));
    expect(deps.fetchRemote).toHaveBeenCalledTimes(RECOVERY_MAX_TRIES);
    expect(timers).toHaveLength(0);
    expect(local.at(-1)).toBe(cutOff);
  });

  it("stops when the user moves to another chat or sends something new", async () => {
    remote = new TypeError("Failed to fetch");
    const recovery = createReplyRecovery(deps);
    recovery.nudge();
    await flush();
    active = "s2";
    await advance(RECOVERY_RETRY_MS);
    expect(timers).toHaveLength(0);

    active = "s1";
    recovery.nudge();
    await flush();
    local = [prompt, cutOff, { role: "user", content: "Try again", clientMessageId: "u2" }];
    remote = [prompt, saved];
    await advance(RECOVERY_RETRY_MS);
    expect(deps.replaceLast).not.toHaveBeenCalled();
  });

  it("does not replace a newer local thread that arrived while it waited for the server", async () => {
    let answer: (value: ChatMessage[]) => void = () => {};
    deps.fetchRemote.mockImplementationOnce(() => new Promise<ChatMessage[]>((resolve) => (answer = resolve)));
    createReplyRecovery(deps).nudge();
    await flush();
    local = [prompt, { ...cutOff, clientMessageId: "a2" }];
    answer([prompt, saved]);
    await flush();
    expect(deps.replaceLast).not.toHaveBeenCalled();
  });

  it("leaves private chats and other endings alone", async () => {
    privateChat = true;
    createReplyRecovery(deps).nudge();
    await flush();
    privateChat = false;
    local = [prompt, { role: "assistant", content: "Error: Model is overloaded", clientMessageId: "a1" }];
    createReplyRecovery(deps).nudge();
    await flush();
    expect(deps.fetchRemote).not.toHaveBeenCalled();
  });

  it("looks at once when nudged again, without starting a second loop", async () => {
    remote = new TypeError("Failed to fetch");
    const recovery = createReplyRecovery(deps);
    recovery.nudge();
    await flush();
    remote = [prompt, saved];
    recovery.nudge();
    await flush();
    expect(local).toEqual([prompt, saved]);
    expect(timers).toHaveLength(0);
  });
});
