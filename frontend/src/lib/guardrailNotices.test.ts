import { describe, expect, it } from "vitest";

import { readGuardrailNotices } from "./guardrailNotices";

describe("readGuardrailNotices", () => {
  it("keeps distinct, non-empty text and drops anything else", () => {
    expect(readGuardrailNotices(["Masked.", " Masked. ", "", 3, null, "Answered by Llama."])).toEqual([
      "Masked.",
      "Answered by Llama.",
    ]);
  });

  it("is nothing when there is nothing to say", () => {
    expect(readGuardrailNotices(undefined)).toBeUndefined();
    expect(readGuardrailNotices("Masked.")).toBeUndefined();
    expect(readGuardrailNotices([" "])).toBeUndefined();
  });

  it("bounds what it keeps", () => {
    const many = Array.from({ length: 30 }, (_, i) => `n${i}`);
    expect(readGuardrailNotices(many)).toHaveLength(10);
    expect(readGuardrailNotices(["x".repeat(900)])![0]).toHaveLength(500);
  });
});
