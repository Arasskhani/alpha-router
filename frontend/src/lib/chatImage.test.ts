import { afterEach, describe, expect, it, vi } from "vitest";
import * as chatStorage from "./chatStorage";
import {
  awaitImagePreparation,
  buildImageMessage,
  buildImageRequestBody,
  ImagePreparationTimeoutError,
  isBackgroundImageRunning,
  parseImageMessage,
  runBackgroundImageGeneration,
  sessionHasIncompleteTextReply,
  stopBackgroundImageGeneration,
} from "./chatImage";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("image retry request identity", () => {
  it("round-trips the Alpha Router image wire marker", () => {
    const payload = {
      url: "/api/chat/media/42/file",
      prompt: "A red cat",
      model: "image-model",
    };
    const encoded = buildImageMessage(payload);

    expect(encoded.startsWith("__ALPHA_ROUTER_IMAGE_JSON__:")).toBe(true);
    expect(parseImageMessage(encoded)).toEqual(payload);
  });

  it("does not parse historical branded image markers", () => {
    expect(parseImageMessage('__UNSUPPORTED_IMAGE_JSON__:{"url":"old"}')).toBeNull();
    expect(parseImageMessage('__UNSUPPORTED_VENDOR_IMAGE_JSON__:{"url":"old"}')).toBeNull();
  });

  it("keeps the concrete model, tier, reference state, and routing metadata", () => {
    const initial = buildImageRequestBody({
      prompt: "A red cat",
      modelId: "google/gemini-3.1-flash-image",
      sessionId: "session-1",
      persist: true,
      referenceImage: "https://example.test/reference.png",
      imageSizeTier: "2K",
      routing: { selected_model: "google/gemini-3.1-flash-image", score: 900 },
    });
    const retry = buildImageRequestBody({
      prompt: "A red cat",
      modelId: "google/gemini-3.1-flash-image",
      sessionId: "session-1",
      persist: true,
      referenceImage: "https://example.test/reference.png",
      imageSizeTier: "2K",
      routing: { selected_model: "google/gemini-3.1-flash-image", score: 900 },
    });

    expect(retry).toEqual(initial);
    expect(retry.model).toBe("google/gemini-3.1-flash-image");
    expect(retry.operation).toBe("img2img");
  });

  it("does not classify a text assistant response as an in-flight image retry", () => {
    expect(
      sessionHasIncompleteTextReply([
        { role: "assistant", content: "I cannot draw that.", receivedAt: Date.now() },
      ]),
    ).toBe(false);
  });
});

describe("image preparation control", () => {
  it("aborts a stalled synchronization at its deadline", async () => {
    vi.useFakeTimers();
    let workSignal: AbortSignal | undefined;
    const job = new AbortController();
    const pending = awaitImagePreparation(
      (signal) => {
        workSignal = signal;
        return new Promise<void>(() => {});
      },
      job.signal,
      25,
    );
    const rejection = expect(pending).rejects.toBeInstanceOf(ImagePreparationTimeoutError);

    await vi.advanceTimersByTimeAsync(25);

    await rejection;
    expect(workSignal?.aborted).toBe(true);
  });

  it("releases immediately when the owning image job stops", async () => {
    const job = new AbortController();
    const pending = awaitImagePreparation(
      () => new Promise<void>(() => {}),
      job.signal,
      10_000,
    );
    const rejection = expect(pending).rejects.toMatchObject({ name: "AbortError" });

    job.abort();

    await rejection;
  });

  it("does not let a stopped job clear a newer retry", async () => {
    vi.spyOn(chatStorage, "syncSessionMessages").mockImplementation(
      () => new Promise<void>(() => {}),
    );
    vi.spyOn(chatStorage, "cancelStreamingReplyOnServer").mockResolvedValue();
    const common = {
      sessionId: "retry-race-session",
      historyWithUser: [{ role: "user" as const, content: "Draw a library" }],
      prompt: "Draw a library",
      modelId: "model::auto",
    };

    const first = runBackgroundImageGeneration(common);
    await Promise.resolve();
    stopBackgroundImageGeneration(common.sessionId);
    const retry = runBackgroundImageGeneration(common);
    await Promise.resolve();
    await Promise.resolve();

    expect(isBackgroundImageRunning(common.sessionId)).toBe(true);

    stopBackgroundImageGeneration(common.sessionId);
    await Promise.all([first, retry]);
    expect(isBackgroundImageRunning(common.sessionId)).toBe(false);
  });
});
