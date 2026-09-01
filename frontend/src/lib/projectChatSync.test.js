import { describe, expect, it } from "vitest";
import { applyProjectChatSync, applyProjectPins, mergeIncomingProjectMessages, mergeProjectMessage, pickProjectSyncMessageBase, sortProjectSessions, } from "./projectChatSync";
function session(partial) {
    return {
        title: "New chat",
        model: "m",
        messages: [],
        revision: 1,
        createdAt: 1,
        updatedAt: 1,
        lastMessageAt: 1,
        pinned: false,
        ...partial,
    };
}
describe("applyProjectPins", () => {
    it("updates pin flags without requiring the session in the payload", () => {
        const local = [session({ id: "a", pinned: false }), session({ id: "b", pinned: true })];
        const next = applyProjectPins(local, ["a"]);
        expect(next.find((row) => row.id === "a")?.pinned).toBe(true);
        expect(next.find((row) => row.id === "b")?.pinned).toBe(false);
    });
});
describe("sortProjectSessions", () => {
    it("keeps pinned chats first", () => {
        const rows = [
            session({ id: "old", updatedAt: 9, lastMessageAt: 9, pinned: false }),
            session({ id: "pin", updatedAt: 1, lastMessageAt: 1, pinned: true }),
        ];
        expect(sortProjectSessions(rows).map((row) => row.id)).toEqual(["pin", "old"]);
    });
});
describe("pickProjectSyncMessageBase", () => {
    it("uses the on-screen thread when the sidebar row is empty", () => {
        const displayed = [
            { id: "1", role: "user", content: "hi", sequence: 1 },
            { id: "2", role: "assistant", content: "yo", sequence: 2, receivedAt: 9 },
        ];
        expect(pickProjectSyncMessageBase([], displayed)).toEqual(displayed);
    });
    it("keeps a longer sidebar copy so a prior merge is not discarded", () => {
        const sessionMsgs = [
            { id: "1", role: "user", content: "hi", sequence: 1 },
            { id: "2", role: "assistant", content: "yo", sequence: 2 },
            { id: "3", role: "user", content: "again", sequence: 3 },
        ];
        const displayed = sessionMsgs.slice(0, 2);
        expect(pickProjectSyncMessageBase(sessionMsgs, displayed)).toEqual(sessionMsgs);
    });
});
describe("mergeProjectMessage", () => {
    it("does not replace local assistant text with an empty persist placeholder", () => {
        const local = {
            id: "a1",
            role: "assistant",
            content: "hello world",
            sequence: 2,
            receivedAt: 5,
        };
        const incoming = { id: "a1", role: "assistant", content: "", sequence: 2 };
        const merged = mergeProjectMessage(local, incoming);
        expect(merged.content).toBe("hello world");
        expect(merged.receivedAt).toBe(5);
    });
    it("applies finalized receivedAt onto a streaming local row", () => {
        const local = {
            id: "a1",
            role: "assistant",
            content: "hello",
            sequence: 2,
            streaming: true,
        };
        const incoming = {
            id: "a1",
            role: "assistant",
            content: "hello",
            sequence: 2,
            streaming: false,
            receivedAt: 11,
        };
        const merged = mergeProjectMessage(local, incoming);
        expect(merged.streaming).toBe(false);
        expect(merged.receivedAt).toBe(11);
    });
});
describe("mergeIncomingProjectMessages", () => {
    it("appends incremental messages by id", () => {
        const local = [{ id: "1", role: "user", content: "hi", sequence: 1 }];
        const incoming = [{ id: "2", role: "assistant", content: "yo", sequence: 2 }];
        const merged = mergeIncomingProjectMessages(local, incoming, true);
        expect(merged.map((row) => row.id)).toEqual(["1", "2"]);
    });
    it("updates patched assistant content in place", () => {
        const local = [
            { id: "1", role: "user", content: "hi", sequence: 1 },
            { id: "2", role: "assistant", content: "", clientMessageId: "a1", sequence: 2 },
        ];
        const incoming = [
            { id: "2", role: "assistant", content: "hello world", clientMessageId: "a1", sequence: 2 },
        ];
        const merged = mergeIncomingProjectMessages(local, incoming, true);
        expect(merged).toHaveLength(2);
        expect(merged[1]?.content).toBe("hello world");
    });
    it("keeps local text when the incremental patch is still an empty placeholder", () => {
        const local = [
            { id: "1", role: "user", content: "hi", sequence: 1 },
            { id: "2", role: "assistant", content: "already streamed", sequence: 2 },
        ];
        const incoming = [{ id: "2", role: "assistant", content: "", sequence: 2 }];
        const merged = mergeIncomingProjectMessages(local, incoming, true);
        expect(merged[1]?.content).toBe("already streamed");
    });
});
describe("applyProjectChatSync", () => {
    it("applies live pins and new sessions", () => {
        const local = [session({ id: "a", pinned: false })];
        const { sessions } = applyProjectChatSync(local, {
            serverTimeMs: 10,
            total: 2,
            pinnedSessionIds: ["a"],
            sessionIds: ["b", "a"],
            sessions: [session({ id: "b", updatedAt: 20, lastMessageAt: 20 })],
            completeWindow: true,
        }, { previousSessionIds: ["a"] });
        expect(sessions.find((row) => row.id === "a")?.pinned).toBe(true);
        expect(sessions.some((row) => row.id === "b")).toBe(true);
    });
    it("drops deleted chats in a complete window", () => {
        const local = [session({ id: "keep" }), session({ id: "gone" })];
        const { sessions } = applyProjectChatSync(local, {
            serverTimeMs: 10,
            total: 1,
            pinnedSessionIds: [],
            sessionIds: ["keep"],
            sessions: [session({ id: "keep" })],
            completeWindow: true,
            goneSessionId: "gone",
        }, { previousSessionIds: ["keep", "gone"] });
        expect(sessions.map((row) => row.id)).toEqual(["keep"]);
    });
    it("does not drop a deep-linked chat that is outside the first window", () => {
        const local = [session({ id: "old" }), session({ id: "new" })];
        const { sessions } = applyProjectChatSync(local, {
            serverTimeMs: 10,
            total: 300,
            pinnedSessionIds: [],
            sessionIds: ["new"],
            sessions: [session({ id: "new" })],
            completeWindow: false,
        }, { previousSessionIds: ["new"] });
        expect(sessions.some((row) => row.id === "old")).toBe(true);
    });
    it("applies patched assistant content for the open thread", () => {
        const local = [
            session({
                id: "open",
                messages: [
                    { id: "u1", role: "user", content: "hi", sequence: 1 },
                    { id: "a1", role: "assistant", content: "", clientMessageId: "c-a", sequence: 2 },
                ],
            }),
        ];
        const { sessions, activeMessages } = applyProjectChatSync(local, {
            serverTimeMs: 10,
            total: 1,
            pinnedSessionIds: [],
            sessionIds: ["open"],
            sessions: [session({ id: "open", updatedAt: 20, lastMessageAt: 20 })],
            messages: [
                { id: "a1", role: "assistant", content: "done", clientMessageId: "c-a", sequence: 2 },
            ],
            messageSessionId: "open",
            completeWindow: true,
        }, { previousSessionIds: ["open"], activeSessionId: "open", incrementalMessages: true });
        expect(activeMessages?.at(-1)?.content).toBe("done");
        expect(sessions.find((row) => row.id === "open")?.messages.at(-1)?.content).toBe("done");
    });
    it("merges an incremental tail onto the displayed thread when the sidebar row is empty", () => {
        const displayed = [
            { id: "u1", role: "user", content: "hi", sequence: 1, receivedAt: 1 },
            { id: "a1", role: "assistant", content: "old", sequence: 2, receivedAt: 2 },
        ];
        const { activeMessages, sessions } = applyProjectChatSync([session({ id: "open", messages: [] })], {
            serverTimeMs: 10,
            total: 1,
            pinnedSessionIds: [],
            sessionIds: ["open"],
            sessions: [session({ id: "open", updatedAt: 30, lastMessageAt: 30 })],
            messages: [
                { id: "a1", role: "assistant", content: "old", sequence: 2 },
                { id: "u2", role: "user", content: "again", sequence: 3 },
                { id: "a2", role: "assistant", content: "new reply", sequence: 4 },
            ],
            messageSessionId: "open",
            completeWindow: true,
        }, {
            previousSessionIds: ["open"],
            activeSessionId: "open",
            incrementalMessages: true,
            activeLocalMessages: displayed,
        });
        expect(activeMessages?.map((row) => row.id)).toEqual(["u1", "a1", "u2", "a2"]);
        expect(activeMessages?.at(-1)?.content).toBe("new reply");
        expect(sessions.find((row) => row.id === "open")?.messages).toHaveLength(4);
    });
    it("does not skip message patches when the session is only marked streaming in the UI", () => {
        const local = [
            session({
                id: "open",
                messages: [
                    { id: "u1", role: "user", content: "hi", sequence: 1 },
                    { id: "a1", role: "assistant", content: "", sequence: 2 },
                ],
            }),
        ];
        const { activeMessages } = applyProjectChatSync(local, {
            serverTimeMs: 10,
            total: 1,
            pinnedSessionIds: [],
            sessionIds: ["open"],
            sessions: [session({ id: "open", updatedAt: 20, lastMessageAt: 20 })],
            messages: [{ id: "a1", role: "assistant", content: "done", sequence: 2, receivedAt: 9 }],
            messageSessionId: "open",
            completeWindow: true,
        }, {
            previousSessionIds: ["open"],
            activeSessionId: "open",
            incrementalMessages: true,
            protectedIds: [],
        });
        expect(activeMessages?.at(-1)?.content).toBe("done");
        expect(activeMessages?.at(-1)?.receivedAt).toBe(9);
    });
    it("still skips message patches while this tab is the local writer", () => {
        const local = [
            session({
                id: "open",
                messages: [
                    { id: "u1", role: "user", content: "hi", sequence: 1 },
                    { id: "a1", role: "assistant", content: "local stream", sequence: 2 },
                ],
            }),
        ];
        const { activeMessages, sessions } = applyProjectChatSync(local, {
            serverTimeMs: 10,
            total: 1,
            pinnedSessionIds: [],
            sessionIds: ["open"],
            sessions: [session({ id: "open", updatedAt: 20, lastMessageAt: 20 })],
            messages: [{ id: "a1", role: "assistant", content: "", sequence: 2 }],
            messageSessionId: "open",
            completeWindow: true,
        }, {
            previousSessionIds: ["open"],
            activeSessionId: "open",
            incrementalMessages: true,
            protectedIds: ["open"],
        });
        expect(activeMessages).toBeNull();
        expect(sessions.find((row) => row.id === "open")?.messages.at(-1)?.content).toBe("local stream");
    });
});
