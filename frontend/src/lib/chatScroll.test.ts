import { describe, expect, it } from "vitest";
import {
  chatScrollJumpButtonVisible,
  isNearScrollBottom,
  pinAfterScrollEvent,
  scrollPinFromViewport,
} from "./chatScroll";

function box(overrides: Partial<{ scrollHeight: number; scrollTop: number; clientHeight: number }>) {
  return {
    scrollHeight: 2000,
    scrollTop: 0,
    clientHeight: 640,
    ...overrides,
  };
}

describe("scrollPinFromViewport", () => {
  it("keeps the pin when a long thread is at the bottom (large scrollTop)", () => {
    const el = box({ scrollTop: 2000 - 640 - 8 });
    expect(isNearScrollBottom(el)).toBe(true);
    expect(scrollPinFromViewport(el)).toBe(true);
    expect(chatScrollJumpButtonVisible(el)).toBe(false);
  });

  it("clears the pin when the user scrolls away from the bottom, even if scrollTop > 80", () => {
    const el = box({ scrollTop: 900 });
    expect(el.scrollTop).toBeGreaterThan(80);
    expect(isNearScrollBottom(el)).toBe(false);
    expect(scrollPinFromViewport(el)).toBe(false);
    expect(chatScrollJumpButtonVisible(el)).toBe(true);
  });

  it("does not treat sitting at the top of a long thread as pinned", () => {
    const el = box({ scrollTop: 0 });
    expect(scrollPinFromViewport(el)).toBe(false);
    expect(chatScrollJumpButtonVisible(el)).toBe(true);
  });
});

describe("pinAfterScrollEvent", () => {
  it("keeps the pin when content grows without a user gesture", () => {
    expect(pinAfterScrollEvent(true, false, false)).toBe(true);
  });

  it("clears the pin only when the user scrolls away", () => {
    expect(pinAfterScrollEvent(true, true, false)).toBe(false);
    expect(pinAfterScrollEvent(true, true, true)).toBe(true);
  });
});
