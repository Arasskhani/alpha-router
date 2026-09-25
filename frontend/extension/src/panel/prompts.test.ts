/**
 * @vitest-environment node
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { installChromeFake } from "../test/chromeFake";
import { BUILT_IN_PROMPTS, loadPrompts, matchingPrompts, promptError, savePrompts, slashAt, type Prompt } from "./prompts";

beforeEach(() => {
  installChromeFake();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const mine: Prompt = { id: "p1", name: "weekly-report", text: "Write this week's report from these notes:" };

describe("a / being typed", () => {
  it.each([
    ["/", 1, ""],
    ["/sum", 4, "sum"],
    ["/Weekly-R", 9, "weekly-r"],
  ])("is found in %j", (text, caret, query) => {
    expect(slashAt(text, caret)).toEqual({ query });
  });

  it.each([
    ["Hello /sum", 10],
    ["/sum and more", 13],
    ["a/b", 3],
  ])("is not found in %j: only a slash at the start, before anything else", (text, caret) => {
    expect(slashAt(text, caret)).toBeNull();
  });
});

describe("the prompts that match", () => {
  const all = [...BUILT_IN_PROMPTS, mine];

  it("are all for a bare slash, else names that start with it first", () => {
    expect(matchingPrompts(all, "")).toHaveLength(all.length);
    expect(matchingPrompts(all, "re").map((p) => p.name)).toEqual(["reply", "weekly-report"]);
    expect(matchingPrompts(all, "zzz")).toEqual([]);
  });
});

describe("a saved prompt", () => {
  it("keeps to lower-case names that no other prompt has", () => {
    expect(promptError("weekly-report", "Text", [], null)).toBeNull();
    expect(promptError("Weekly", "Text", [], null)).toMatch(/lower-case/);
    expect(promptError("has space", "Text", [], null)).toMatch(/lower-case/);
    expect(promptError("summarize", "Text", [], null)).toBe("There is already a prompt called /summarize.");
    expect(promptError("weekly-report", "Text", [mine], null)).toBe("There is already a prompt called /weekly-report.");
    expect(promptError("weekly-report", "New text", [mine], "p1")).toBeNull();
    expect(promptError("x", "   ", [], null)).toBe("Write the prompt's text.");
    expect(promptError("x", "y".repeat(4001), [], null)).toMatch(/at most 4,000/);
  });

  it("stays in this browser's local storage, and what this code did not write is left out", async () => {
    await savePrompts([mine]);
    expect(await chrome.storage.local.get("alpharouter.prompts")).toEqual({ "alpharouter.prompts": [mine] });
    await chrome.storage.local.set({
      "alpharouter.prompts": [mine, { id: "p2", name: "Bad Name", text: "x" }, { id: "p3", name: "empty", text: "" }, 5],
    });
    expect(await loadPrompts()).toEqual([mine]);
  });
});
