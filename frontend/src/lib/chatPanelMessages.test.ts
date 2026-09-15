import { describe, expect, it } from "vitest";
import type { ChatMessage } from "./chatStorage";
import {
  buildStoppedVideoMessages,
  extractMarkdownImage,
  isTextAssistantExportable,
  removePromptThreadFromMessages,
} from "./chatPanelMessages";
import { IMAGE_PENDING_MARKER } from "./chatImage";
import { VIDEO_PENDING_MARKER } from "./chatVideo";

const thread: ChatMessage[] = [
  { role: "user", content: "q1", clientMessageId: "u1" },
  { role: "assistant", content: "a1", clientMessageId: "a1" },
  { role: "user", content: "q2", clientMessageId: "u2" },
  { role: "assistant", content: "a2", clientMessageId: "a2" },
  { role: "assistant", content: "a2-followup", clientMessageId: "a3" },
];

describe("removePromptThreadFromMessages", () => {
  it("removes the prompt and every assistant reply that follows it", () => {
    const next = removePromptThreadFromMessages(thread, thread[2]);
    expect(next?.map((m) => m.clientMessageId)).toEqual(["u1", "a1"]);
  });

  it("finds the prompt by clientMessageId even when positions differ (server list)", () => {
    const server = [{ role: "user", content: "inserted elsewhere", clientMessageId: "x" } as ChatMessage, ...thread];
    const next = removePromptThreadFromMessages(server, thread[0], 0);
    expect(next?.map((m) => m.clientMessageId)).toEqual(["x", "u2", "a2", "a3"]);
  });

  it("returns null when the prompt is not in the list", () => {
    expect(removePromptThreadFromMessages(thread, { role: "user", content: "zzz", clientMessageId: "nope" })).toBeNull();
  });

  it("refuses to remove an assistant row", () => {
    expect(removePromptThreadFromMessages(thread, thread[1])).toBeNull();
  });
});

describe("buildStoppedVideoMessages", () => {
  it("replaces the pending placeholder with one stopped notice", () => {
    const msgs: ChatMessage[] = [
      { role: "user", content: "make a video" },
      { role: "assistant", content: VIDEO_PENDING_MARKER },
    ];
    const once = buildStoppedVideoMessages(msgs);
    const twice = buildStoppedVideoMessages(once);
    expect(once).toHaveLength(2);
    expect(once[1].content).toBe("Video generation stopped.");
    expect(twice).toEqual(once);
  });
});

describe("isTextAssistantExportable / extractMarkdownImage", () => {
  it("rejects placeholders and image-only replies", () => {
    expect(isTextAssistantExportable(IMAGE_PENDING_MARKER)).toBe(false);
    expect(isTextAssistantExportable("![img](https://x/y.png)")).toBe(false);
    expect(isTextAssistantExportable("Here you go\n\n![img](https://x/y.png)")).toBe(true);
    expect(isTextAssistantExportable("plain answer")).toBe(true);
  });

  it("splits the first markdown image from the text", () => {
    expect(extractMarkdownImage("Look:\n\n\n![alt](https://h/i.png)\n\nDone")).toEqual({
      imageUrl: "https://h/i.png",
      text: "Look:\n\nDone",
    });
  });
});
