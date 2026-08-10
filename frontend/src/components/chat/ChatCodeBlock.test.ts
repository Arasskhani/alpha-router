import { describe, expect, it } from "vitest";
import {
  CODE_BLOCK_COLLAPSED_PREVIEW_LINES,
  codeBlockExpandStateKey,
  getCollapsedCodePreview,
} from "./ChatCodeBlock";

describe("getCollapsedCodePreview", () => {
  it("returns the full short block without truncating", () => {
    const code = "a\nb\nc";
    expect(getCollapsedCodePreview(code)).toEqual({ preview: code, truncated: false });
  });

  it("keeps only the first preview lines for long blocks", () => {
    const lines = Array.from({ length: CODE_BLOCK_COLLAPSED_PREVIEW_LINES + 5 }, (_, i) => `line-${i + 1}`);
    const code = lines.join("\n");
    const { preview, truncated } = getCollapsedCodePreview(code);
    expect(truncated).toBe(true);
    expect(preview.split("\n")).toEqual(lines.slice(0, CODE_BLOCK_COLLAPSED_PREVIEW_LINES));
    expect(preview).not.toContain(`line-${CODE_BLOCK_COLLAPSED_PREVIEW_LINES + 1}`);
  });

  it("still leaves the original string intact for Copy callers", () => {
    const code = Array.from({ length: 20 }, (_, i) => `x${i}`).join("\n");
    const { preview } = getCollapsedCodePreview(code);
    expect(code.startsWith(preview)).toBe(true);
    expect(code.length).toBeGreaterThan(preview.length);
  });
});

describe("codeBlockExpandStateKey", () => {
  it("stays stable when only lines after the preview change", () => {
    const head = Array.from({ length: CODE_BLOCK_COLLAPSED_PREVIEW_LINES }, (_, i) => `h${i}`).join("\n");
    const a = `${head}\ntail-a`;
    const b = `${head}\ntail-b\nmore`;
    expect(codeBlockExpandStateKey(a, "python", "code")).toBe(
      codeBlockExpandStateKey(b, "python", "code"),
    );
  });
});
