import { describe, expect, it } from "vitest";
import {
  isAllowedVideoDuration,
  normalizeChatTools,
  videoDurationChoices,
} from "./chatTools";

describe("video duration selection", () => {
  it("keeps a user-selected duration above 8 seconds", () => {
    expect(normalizeChatTools({ videoDuration: 30 }).videoDuration).toBe(30);
    expect(normalizeChatTools({ videoDuration: 8 }).videoDuration).toBe(8);
  });

  it("exposes only catalog durations without a hardcoded fallback list", () => {
    expect(videoDurationChoices([4, 8, 30])).toEqual([4, 8, 30]);
    expect(videoDurationChoices([])).toEqual([]);
    expect(videoDurationChoices(undefined)).toEqual([]);
  });

  it("accepts a duration only when the model lists it", () => {
    expect(isAllowedVideoDuration(30, [4, 8, 30])).toBe(true);
    expect(isAllowedVideoDuration(8, [4, 8, 30])).toBe(true);
    expect(isAllowedVideoDuration(12, [4, 8, 30])).toBe(false);
  });
});
