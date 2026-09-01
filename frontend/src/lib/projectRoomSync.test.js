import { describe, expect, it } from "vitest";
import { applyProjectRoomSync, mergeIncomingRoomMessages, sortProjectRooms, } from "./projectRoomSync";
function room(partial) {
    return {
        title: "Room",
        messageCount: 0,
        revision: 1,
        channelKind: "member",
        createdAt: 1,
        updatedAt: 1,
        lastMessageAt: 1,
        ...partial,
    };
}
function msg(partial) {
    return {
        role: "user",
        content: "",
        ...partial,
    };
}
describe("sortProjectRooms", () => {
    it("sorts by last activity", () => {
        const rows = [
            room({ id: "old", lastMessageAt: 1 }),
            room({ id: "new", lastMessageAt: 9 }),
        ];
        expect(sortProjectRooms(rows).map((row) => row.id)).toEqual(["new", "old"]);
    });
});
describe("mergeIncomingRoomMessages", () => {
    it("appends incremental messages by id and clientMessageId", () => {
        const local = [msg({ id: "1", content: "hi", sequence: 1, clientMessageId: "c1" })];
        const incoming = [
            msg({ id: "1", content: "hi", sequence: 1, clientMessageId: "c1" }),
            msg({ id: "2", content: "next", sequence: 2 }),
        ];
        expect(mergeIncomingRoomMessages(local, incoming, true).map((row) => row.id)).toEqual([
            "1",
            "2",
        ]);
    });
    it("replaces with a complete snapshot when not incremental", () => {
        const local = [msg({ id: "1", content: "old", sequence: 1 })];
        const incoming = [
            msg({ id: "1", content: "old", sequence: 1 }),
            msg({ id: "2", content: "new", sequence: 2 }),
        ];
        expect(mergeIncomingRoomMessages(local, incoming, false)).toEqual(incoming);
    });
});
describe("applyProjectRoomSync", () => {
    it("merges rooms and drops gone ids", () => {
        const local = [room({ id: "keep" }), room({ id: "gone" })];
        const sync = {
            serverTimeMs: 10,
            total: 1,
            sessionIds: ["keep"],
            sessions: [room({ id: "keep", title: "Updated", lastMessageAt: 20 })],
            completeWindow: true,
        };
        const next = applyProjectRoomSync(local, sync, { previousSessionIds: ["keep", "gone"] });
        expect(next.rooms.map((row) => row.id)).toEqual(["keep"]);
        expect(next.rooms[0].title).toBe("Updated");
    });
    it("merges messages only for the active room", () => {
        const local = [room({ id: "a" })];
        const sync = {
            serverTimeMs: 10,
            total: 1,
            sessionIds: ["a"],
            sessions: [room({ id: "a" })],
            messages: [msg({ id: "m1", content: "brief" })],
            messageSessionId: "a",
        };
        const next = applyProjectRoomSync(local, sync, {
            previousSessionIds: ["a"],
            activeRoomId: "a",
            incrementalMessages: false,
            activeLocalMessages: [],
        });
        expect(next.activeMessages?.map((row) => row.content)).toEqual(["brief"]);
    });
});
