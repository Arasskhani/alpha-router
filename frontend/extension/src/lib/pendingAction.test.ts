/**
 * @vitest-environment node
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { installChromeFake } from "../test/chromeFake";
import { PENDING_ACTION_MAX_AGE_MS, savePendingAction, takePendingAction, type PendingAction } from "./pendingAction";

const NOW = 1_800_000_000_000;
const action = (overrides: Partial<PendingAction> = {}): PendingAction => ({
  id: "a1",
  kind: "summarize",
  tabId: 4,
  windowId: 1,
  pageUrl: "https://docs.example.com/guide",
  title: "Guide",
  selection: "",
  createdAt: NOW,
  ...overrides,
});

beforeEach(() => {
  installChromeFake();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("work left for the side panel", () => {
  it("is taken once, by the panel of the window it was made in", async () => {
    await savePendingAction(action());
    expect(await takePendingAction(1, NOW + 1000)).toEqual(action());
    expect(await takePendingAction(1, NOW + 1000)).toBeNull();
  });

  it("stays for its own window when another window's panel looks", async () => {
    await savePendingAction(action({ windowId: 2 }));
    expect(await takePendingAction(1, NOW)).toBeNull();
    expect(await takePendingAction(2, NOW)).toEqual(action({ windowId: 2 }));
  });

  it("goes stale after two minutes, and is cleared", async () => {
    await savePendingAction(action());
    expect(await takePendingAction(1, NOW + PENDING_ACTION_MAX_AGE_MS + 1)).toBeNull();
    expect(await chrome.storage.session.get("alpharouter.pending-action")).toEqual({});
  });

  it("is refused when it claims to come from the future", async () => {
    await savePendingAction(action({ createdAt: NOW + 60_000 }));
    expect(await takePendingAction(1, NOW)).toBeNull();
  });

  it("carries a screenshot's image", async () => {
    const shot = action({ kind: "screenshot", image: "data:image/jpeg;base64,/9j/4AAQ" });
    await savePendingAction(shot);
    expect(await takePendingAction(1, NOW)).toEqual(shot);
  });

  it.each([{ kind: "delete-everything" }, { tabId: "4" }, { selection: 5 }, { image: 42 }, { image: "x".repeat(8_000_001) }])(
    "is refused when malformed: %j",
    async (bad) => {
      await chrome.storage.session.set({ "alpharouter.pending-action": { ...action(), ...bad } });
      expect(await takePendingAction(1, NOW)).toBeNull();
      expect(await chrome.storage.session.get("alpharouter.pending-action")).toEqual({});
    },
  );
});
