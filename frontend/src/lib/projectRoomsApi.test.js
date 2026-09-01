import { describe, expect, it } from "vitest";
import { MAX_ROOM_HANDOFF_BRIEF, normalizeProjectRoom, normalizeProjectRoomMessage, } from "./projectRoomsApi";
describe("normalizeProjectRoom", () => {
    it("forces channelKind to member and fills defaults", () => {
        expect(normalizeProjectRoom({
            id: "room-1",
            title: "Nowruz teaser",
            messageCount: 3,
            revision: 4,
            createdByUserId: "12",
        })).toEqual({
            id: "room-1",
            title: "Nowruz teaser",
            messageCount: 3,
            revision: 4,
            channelKind: "member",
            createdByUserId: 12,
            createdAt: null,
            updatedAt: null,
            lastMessageAt: null,
        });
    });
});
describe("normalizeProjectRoomMessage", () => {
    it("forces role user", () => {
        expect(normalizeProjectRoomMessage({
            id: "m1",
            role: "assistant",
            content: "hello",
            sequence: 2,
            authorDisplayName: "Ada",
            clientMessageId: "c1",
        })).toEqual({
            id: "m1",
            role: "user",
            content: "hello",
            sequence: 2,
            authorDisplayName: "Ada",
            clientMessageId: "c1",
            userId: null,
            mine: false,
            edited: false,
            replyToMessageId: null,
            replyToAuthor: null,
            replyToContent: null,
        });
    });
});
describe("handoff limits", () => {
    it("caps briefs at 8k", () => {
        expect(MAX_ROOM_HANDOFF_BRIEF).toBe(8000);
    });
});
