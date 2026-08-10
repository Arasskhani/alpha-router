import { describe, expect, it } from "vitest";
import { textNeedsEnglishTranslation } from "./textDirection";

describe("textNeedsEnglishTranslation", () => {
  it("flags Persian drafts", () => {
    expect(textNeedsEnglishTranslation("یک گربه نارنجی")).toBe(true);
  });

  it("does not flag English drafts", () => {
    expect(textNeedsEnglishTranslation("An orange cat on a sofa")).toBe(false);
  });

  it("flags other non-Latin scripts", () => {
    expect(textNeedsEnglishTranslation("请总结这段文字")).toBe(true);
  });
});
