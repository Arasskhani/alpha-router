import { describe, expect, it } from "vitest";
import {
  isPromptQueueCollapsed,
  PROMPT_QUEUE_INLINE_LIMIT,
  promptQueueCountLabel,
  shouldShowPromptQueueBar,
} from "./promptQueue";

describe("isPromptQueueCollapsed", () => {
  it("keeps one or two items expanded so edit/remove stay one click away", () => {
    expect(isPromptQueueCollapsed({ count: 1, expanded: false })).toBe(false);
    expect(isPromptQueueCollapsed({ count: PROMPT_QUEUE_INLINE_LIMIT, expanded: false })).toBe(false);
  });

  it("collapses a long queue until the user opens it", () => {
    expect(isPromptQueueCollapsed({ count: 3, expanded: false })).toBe(true);
    expect(isPromptQueueCollapsed({ count: 12, expanded: false })).toBe(true);
    expect(isPromptQueueCollapsed({ count: 12, expanded: true })).toBe(false);
  });

  it("never treats an empty queue as collapsed", () => {
    expect(isPromptQueueCollapsed({ count: 0, expanded: false })).toBe(false);
  });
});

describe("shouldShowPromptQueueBar", () => {
  it("hides the summary bar for a short queue", () => {
    expect(shouldShowPromptQueueBar(2)).toBe(false);
    expect(shouldShowPromptQueueBar(3)).toBe(true);
  });
});

describe("promptQueueCountLabel", () => {
  it("uses singular copy for one item", () => {
    expect(promptQueueCountLabel(1)).toBe("1 in queue");
    expect(promptQueueCountLabel(8)).toBe("8 in queue");
  });
});
