import { describe, expect, it } from "vitest";
import { buildImageRequestBody, sessionHasIncompleteTextReply } from "./chatImage";

describe("image retry request identity", () => {
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
