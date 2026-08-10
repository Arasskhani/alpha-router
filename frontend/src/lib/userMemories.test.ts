import { describe, expect, it } from "vitest";
import { MAX_MEMORY_CHARS, normalizeMemoryDraft } from "./userMemories";

describe("normalizeMemoryDraft", () => {
  it("collapses whitespace and strips control chars", () => {
    expect(normalizeMemoryDraft("  hello\n\tworld  ")).toBe("hello world");
    expect(normalizeMemoryDraft("a\u0000b")).toBe("ab");
  });

  it("allows content up to the max length boundary for callers", () => {
    const text = "x".repeat(MAX_MEMORY_CHARS);
    expect(normalizeMemoryDraft(text).length).toBe(MAX_MEMORY_CHARS);
  });
});
