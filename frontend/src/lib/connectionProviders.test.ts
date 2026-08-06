import { describe, expect, it } from "vitest";
import {
  resolveConnectionProvider,
  suggestConnectionProviders,
} from "./connectionProviders";

describe("connectionProviders", () => {
  it("suggests well-known providers from partial input", () => {
    const hits = suggestConnectionProviders("open");
    expect(hits.map((p) => p.id)).toEqual(expect.arrayContaining(["openrouter", "openai"]));
  });

  it("resolves aliases to canonical provider and base URL", () => {
    expect(resolveConnectionProvider("claude")?.id).toBe("anthropic");
    expect(resolveConnectionProvider("gemini")?.baseUrl).toContain("generativelanguage.googleapis.com");
    expect(resolveConnectionProvider("grok")?.id).toBe("xai");
  });

  it("returns exact openrouter defaults", () => {
    const preset = resolveConnectionProvider("openrouter");
    expect(preset).toEqual(
      expect.objectContaining({
        id: "openrouter",
        baseUrl: "https://openrouter.ai/api/v1",
      }),
    );
  });
});
