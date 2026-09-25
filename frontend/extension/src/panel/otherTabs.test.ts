/**
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import { matchingTabs, mentionAt, type PickableTab } from "./otherTabs";

describe("an @ being typed", () => {
  it.each([
    ["@", 1, { start: 0, query: "" }],
    ["Compare @wik", 12, { start: 8, query: "wik" }],
    ["Line one\n@bud", 13, { start: 9, query: "bud" }],
  ])("is found in %j before the caret", (text, caret, found) => {
    expect(mentionAt(text, caret)).toEqual(found);
  });

  it.each([
    ["mail me at a@b.example", 22],
    ["@wiki and more", 14],
    ["Compare @wik", 5],
    ["no mention", 10],
  ])("is not found in %j", (text, caret) => {
    expect(mentionAt(text, caret)).toBeNull();
  });
});

describe("the tabs that match", () => {
  const tab = (title: string, host: string): PickableTab => ({
    tabId: title.length,
    url: `https://${host}/`,
    title,
    target: { host, origin: `https://${host}`, pattern: `https://${host}/*` },
    granted: false,
  });
  const tabs = [tab("Wiki home", "wiki.example.org"), tab("Budget", "sheets.example.net")];

  it("are all of them for nothing typed, else those whose title or site has it", () => {
    expect(matchingTabs(tabs, "")).toHaveLength(2);
    expect(matchingTabs(tabs, "WIKI").map((t) => t.title)).toEqual(["Wiki home"]);
    expect(matchingTabs(tabs, "sheets").map((t) => t.title)).toEqual(["Budget"]);
    expect(matchingTabs(tabs, "nothing")).toEqual([]);
  });
});
