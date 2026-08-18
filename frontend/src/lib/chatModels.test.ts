import { describe, expect, it } from "vitest";
import {
  findTextChatFallbackModel,
  modelSupportsTextChat,
  resolvePromptAssistModel,
} from "./chatModels";
import { resolveNewChatModel } from "./chatStorage";

describe("modelSupportsTextChat", () => {
  it("accepts text models and Auto Router", () => {
    expect(modelSupportsTextChat({ id: "m1", kinds: ["text"] })).toBe(true);
    expect(
      modelSupportsTextChat({
        id: "auto",
        name: "Auto Router",
        external_id: "openrouter/auto",
        kinds: [],
      }),
    ).toBe(true);
  });

  it("rejects pure rerank and embeddings models", () => {
    expect(
      modelSupportsTextChat({
        id: "m2",
        name: "VoyageAI by MongoDB: reran…",
        external_id: "mongodb/voyage-rerank",
        kinds: ["rerank"],
      }),
    ).toBe(false);
    expect(
      modelSupportsTextChat({
        id: "m3",
        kinds: ["embeddings"],
      }),
    ).toBe(false);
  });

  it("treats missing kinds as text-capable for older payloads", () => {
    expect(modelSupportsTextChat({ id: "legacy" })).toBe(true);
  });
});

describe("findTextChatFallbackModel", () => {
  it("prefers Auto Router over other text models", () => {
    const models = [
      { id: "rerank", kinds: ["rerank"] },
      { id: "text-1", kinds: ["text"] },
      { id: "auto", name: "Auto Router", external_id: "openrouter/auto", kinds: ["text"] },
    ];
    expect(findTextChatFallbackModel(models)?.id).toBe("auto");
  });

  it("returns the first text model when Auto Router is absent", () => {
    const models = [
      { id: "rerank", kinds: ["rerank"] },
      { id: "text-1", kinds: ["text"] },
      { id: "text-2", kinds: ["text"] },
    ];
    expect(findTextChatFallbackModel(models)?.id).toBe("text-1");
  });
});

describe("resolvePromptAssistModel", () => {
  it("keeps the preferred text model", () => {
    const models = [
      { id: "img", kinds: ["image"] },
      { id: "text-1", kinds: ["text"] },
    ];
    expect(resolvePromptAssistModel(models, "text-1")?.id).toBe("text-1");
  });

  it("falls back from a non-text preferred model to a concrete text model", () => {
    const models = [
      { id: "img", kinds: ["image"] },
      { id: "auto", name: "Auto Router", external_id: "openrouter/auto", kinds: ["text"] },
      { id: "text-1", kinds: ["text"] },
    ];
    expect(resolvePromptAssistModel(models, "img")?.id).toBe("text-1");
  });
});

describe("resolveNewChatModel system default", () => {
  const catalog = [
    { id: "model::1", external_id: "openai/first" },
    { id: "model::2", external_id: "openai/user-pick" },
    { id: "model::3", external_id: "openai/system", is_system_default: true },
  ];

  it("uses the user default when set and never falls through to system default", () => {
    expect(resolveNewChatModel(catalog, "model::1", "model::2")).toBe("model::2");
  });

  it("uses the admin system default only when the user has no personal default", () => {
    expect(resolveNewChatModel(catalog, "model::1", "")).toBe("model::3");
    expect(resolveNewChatModel(catalog, "model::1", null)).toBe("model::3");
  });

  it("does not treat a missing system default as a write to user preference", () => {
    const noFlag = [
      { id: "model::1", external_id: "openai/first" },
      { id: "model::2", external_id: "openai/second" },
    ];
    expect(resolveNewChatModel(noFlag, undefined, "")).toBe("model::1");
  });
});
