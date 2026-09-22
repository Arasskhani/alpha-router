import { describe, expect, it } from "vitest";
import {
  ATTACHMENT_MESSAGE_PREFIX,
  AUDIO_MESSAGE_PREFIX,
  attachmentKindFromName,
  attachmentMessage,
  buildApiMessageContent,
  canProcessAttachmentLocally,
  imageUrlNeedsAuthResolve,
  modelSupportsVision,
  readAttachmentMessage,
} from "./chatAttachments";

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
