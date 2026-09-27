import { afterEach, describe, expect, it, vi } from "vitest";

import { clearBadge, showBadge } from "./badge";

function fakeAction() {
  const action = {
    setBadgeText: vi.fn(async () => undefined),
    setBadgeBackgroundColor: vi.fn(async () => undefined),
    setBadgeTextColor: vi.fn(async () => undefined),
    setTitle: vi.fn(async () => undefined),
  };
  vi.stubGlobal("chrome", { action });
  return action;
}

afterEach(() => vi.unstubAllGlobals());

describe("the toolbar badge", () => {
  it("shows a pill in the run's colour, with a title that says what the agent is doing", async () => {
    const action = fakeAction();
    await showBadge("working");
    expect(action.setBadgeText).toHaveBeenCalledWith({ text: "●" });
    expect(action.setBadgeBackgroundColor).toHaveBeenCalledWith({ color: "#2eaadc" });
    // The glyph in the pill's own colour: a plain pill, not a dot in a box.
    expect(action.setBadgeTextColor).toHaveBeenCalledWith({ color: "#2eaadc" });
    expect(action.setTitle).toHaveBeenCalledWith({ title: expect.stringContaining("working") });
    await showBadge("waiting");
    expect(action.setBadgeBackgroundColor).toHaveBeenLastCalledWith({ color: "#ffb347" });
    await showBadge("paused");
    expect(action.setBadgeBackgroundColor).toHaveBeenLastCalledWith({ color: "#969696" });
    expect(action.setTitle).toHaveBeenLastCalledWith({ title: expect.stringContaining("took over") });
  });

  it("goes when cleared, and the title goes back to the button's own", async () => {
    const action = fakeAction();
    await clearBadge();
    expect(action.setBadgeText).toHaveBeenCalledWith({ text: "" });
    expect(action.setTitle).toHaveBeenCalledWith({ title: "Open Alpharouter" });
  });

  it("never fails the run: no action API, or one that refuses", async () => {
    vi.stubGlobal("chrome", {});
    await expect(showBadge("working")).resolves.toBeUndefined();
    await expect(clearBadge()).resolves.toBeUndefined();
    const action = fakeAction();
    action.setBadgeText.mockRejectedValue(new Error("no"));
    await expect(showBadge("working")).resolves.toBeUndefined();
  });
});
