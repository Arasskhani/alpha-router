import { describe, expect, it } from "vitest";

import { readGuardrailBlocked, readGuardrailNotices, refusalFromDetail, refusalFromStream } from "./guardrailNotices";

describe("readGuardrailNotices", () => {
  it("keeps distinct, non-empty notices with the action they tell of", () => {
    expect(
      readGuardrailNotices([
        { action: "redact", message: "Masked." },
        { action: "redact", message: " Masked. " },
        { action: "route", message: "Answered by Llama." },
        { action: "block", message: "Odd." },
        3,
        null,
      ]),
    ).toEqual([
      { action: "redact", message: "Masked." },
      { action: "route", message: "Answered by Llama." },
      { action: "notice", message: "Odd." },
    ]);
  });

  it("reads answers saved when notices were text alone", () => {
    expect(readGuardrailNotices(["Masked.", ""])).toEqual([{ action: "notice", message: "Masked." }]);
  });

  it("is nothing when there is nothing to say, and bounds what it keeps", () => {
    expect(readGuardrailNotices(undefined)).toBeUndefined();
    expect(readGuardrailNotices([" "])).toBeUndefined();
    expect(readGuardrailNotices(Array.from({ length: 30 }, (_, i) => `n${i}`))).toHaveLength(10);
    expect(readGuardrailNotices(["x".repeat(900)])![0].message).toHaveLength(500);
  });
});

describe("refusals", () => {
  it("come from a 422 with what the chat keeps of the message", () => {
    expect(
      refusalFromDetail({ code: "guardrail_blocked", message: "No cards.", user_content: "refund 603…453", persisted: true }),
    ).toEqual({ message: "No cards.", userContent: "refund 603…453", persisted: true, heldBack: true });
    expect(refusalFromDetail({ code: "other", message: "x" })).toBeNull();
    expect(refusalFromDetail("guardrail_blocked")).toBeNull();
  });

  it("come from the stream when what the platform added was refused", () => {
    expect(refusalFromStream({ message: "Memory holds a card.", persisted: false })).toEqual({
      message: "Memory holds a card.",
      persisted: false,
      heldBack: false,
    });
    expect(refusalFromStream({})!.message).toMatch(/organisation/);
  });

  it("are read back from a saved answer", () => {
    expect(readGuardrailBlocked({ message: " No cards. " })).toEqual({ message: "No cards." });
    expect(readGuardrailBlocked({})).toBeUndefined();
  });
});
