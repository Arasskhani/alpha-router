/**
 * @vitest-environment node
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { installChromeFake, type ChromeFake } from "../test/chromeFake";
import { callPage, cleanElement, cleanPageResult } from "./pageAgent";

let chromeFake: ChromeFake;

beforeEach(() => {
  chromeFake = installChromeFake();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

type Injection = { target: { tabId: number }; files?: string[]; func?: (...args: unknown[]) => unknown; args?: unknown[] };

describe("a call to the page", () => {
  it("injects content.js, then runs the action with the site it expects", async () => {
    chromeFake.scripting.executeScript
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ result: { ok: true, note: "Typed 5 characters." } }]);
    await expect(callPage(7, "shop.example.com", "type_text", { ref: "e3", text: "hello" })).resolves.toEqual({
      ok: true,
      note: "Typed 5 characters.",
    });
    const [inject, run] = chromeFake.scripting.executeScript.mock.calls.map(([injection]) => injection as Injection);
    expect(inject).toEqual({ target: { tabId: 7 }, files: ["content.js"] });
    expect(run.target).toEqual({ tabId: 7 });
    expect(run.args).toEqual(["shop.example.com", "type_text", { ref: "e3", text: "hello" }]);
  });

  it("checks the site inside the page, where no navigation comes between", async () => {
    chromeFake.scripting.executeScript.mockResolvedValue([]);
    await callPage(7, "shop.example.com", "click", { ref: "e1" });
    const run = chromeFake.scripting.executeScript.mock.calls[1][0] as Injection;
    const agent = vi.fn(() => ({ ok: true }));
    vi.stubGlobal("location", { hostname: "evil.example.net" });
    vi.stubGlobal("__alpharouter", { agent });
    expect(run.func!("shop.example.com", "click", { ref: "e1" })).toMatchObject({ ok: false, error: "moved" });
    expect(agent).not.toHaveBeenCalled();
    vi.stubGlobal("location", { hostname: "shop.example.com." });
    expect(run.func!("shop.example.com", "click", { ref: "e1" })).toEqual({ ok: true });
    expect(agent).toHaveBeenCalledWith("click", { ref: "e1" });
  });

  it.each([
    ["Cannot access contents of url. Extension manifest must request permission to access this host.", "no_access"],
    ["No tab with id: 7.", "moved"],
    ["Frame with ID 0 is showing error page", "failed"],
  ])("turns %s into %s", async (message, error) => {
    chromeFake.scripting.executeScript.mockRejectedValueOnce(new Error(message));
    await expect(callPage(7, "shop.example.com", "read_page")).resolves.toMatchObject({ ok: false, error });
  });
});

describe("what the page answers", () => {
  it("is checked for its action, and cut to size", () => {
    const read = cleanPageResult("read_page", {
      ok: true,
      url: "https://shop.example.com/",
      title: "Shop",
      outline: "x".repeat(40_000),
      elements: [{ ref: "e1", role: "button", name: "Buy", tag: "button" }, { ref: "not a ref", role: "link", tag: "a" }, "junk"],
      truncated: false,
    });
    expect(read.ok).toBe(true);
    if (!read.ok) return;
    expect((read.outline as string).length).toBe(30_000);
    expect(read.elements).toEqual([{ ref: "e1", role: "button", name: "Buy", tag: "button" }]);
  });

  it("is a failure when it is out of shape", () => {
    expect(cleanPageResult("read_page", { ok: true })).toMatchObject({ ok: false, error: "failed" });
    expect(cleanPageResult("describe", { ok: true, element: {} })).toMatchObject({ ok: false });
    expect(cleanPageResult("click", null)).toMatchObject({ ok: false, error: "failed" });
    expect(cleanPageResult("click", { ok: false, error: "something new", message: 42 })).toEqual({
      ok: false,
      error: "failed",
      message: "The action failed.",
    });
  });

  it("never carries a sensitive field's value, even if one came back", () => {
    expect(cleanElement({ ref: "e2", role: "textbox", name: "Password", tag: "input", sensitive: true, value: "hunter2" })).toEqual({
      ref: "e2",
      role: "textbox",
      name: "Password",
      tag: "input",
      sensitive: true,
    });
  });
});
