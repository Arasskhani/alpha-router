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

const SHOP = { tabId: 7, host: "shop.example.com", origin: "https://shop.example.com" };

describe("a call to the page", () => {
  it("injects content.js, then runs the action with the origin it expects", async () => {
    chromeFake.scripting.executeScript
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ result: { ok: true, note: "Typed 5 characters." } }]);
    await expect(callPage(SHOP, "type_text", { ref: "e3", text: "hello" })).resolves.toEqual({
      ok: true,
      note: "Typed 5 characters.",
    });
    const [inject, run] = chromeFake.scripting.executeScript.mock.calls.map(([injection]) => injection as Injection);
    expect(inject).toEqual({ target: { tabId: 7 }, files: ["content.js"] });
    expect(run.target).toEqual({ tabId: 7 });
    expect(run.args).toEqual(["https://shop.example.com", "type_text", { ref: "e3", text: "hello" }, null]);
  });

  it("does not send the action once the run is stopped, however long the page kept the injection back", async () => {
    const abort = new AbortController();
    chromeFake.scripting.executeScript.mockImplementationOnce(async () => {
      abort.abort();
      return [];
    });
    await expect(callPage(SHOP, "click", { ref: "e1" }, null, abort.signal)).resolves.toMatchObject({ ok: false, error: "stopped" });
    expect(chromeFake.scripting.executeScript).toHaveBeenCalledTimes(1);
  });

  it("puts the run's banner up before the action, when asked to", async () => {
    chromeFake.scripting.executeScript.mockResolvedValue([]);
    await callPage(SHOP, "click", { ref: "e1" }, { run: "run-1", label: "Working" });
    const run = chromeFake.scripting.executeScript.mock.calls[1][0] as Injection;
    expect(run.args?.[3]).toEqual({ run: "run-1", label: "Working" });
    const seen: string[] = [];
    vi.stubGlobal("__alpharouter", { agent: vi.fn((method: string) => (seen.push(method), { ok: true })) });
    vi.stubGlobal("location", { origin: "https://shop.example.com" });
    run.func!(...run.args!);
    expect(seen).toEqual(["show_overlay", "click"]);
    // The action goes with its run, which the page refuses once the user stopped it there.
    const agent = (globalThis as unknown as { __alpharouter: { agent: ReturnType<typeof vi.fn> } }).__alpharouter.agent;
    expect(agent).toHaveBeenLastCalledWith("click", { ref: "e1" }, "run-1");
    // Not on a page that is no longer the one judged.
    seen.length = 0;
    vi.stubGlobal("location", { origin: "https://evil.example.net" });
    expect(run.func!(...run.args!)).toMatchObject({ error: "moved" });
    expect(seen).toEqual([]);
  });

  it("checks the origin inside the page, where no navigation comes between", async () => {
    chromeFake.scripting.executeScript.mockResolvedValue([]);
    await callPage(SHOP, "click", { ref: "e1" });
    const run = chromeFake.scripting.executeScript.mock.calls[1][0] as Injection;
    const agent = vi.fn(() => ({ ok: true }));
    vi.stubGlobal("__alpharouter", { agent });
    // Another site, and the same host on another port or scheme: not the page the rules judged.
    for (const origin of ["https://evil.example.net", "https://shop.example.com:8443", "http://shop.example.com"]) {
      vi.stubGlobal("location", { origin });
      expect(run.func!("https://shop.example.com", "click", { ref: "e1" }, null)).toMatchObject({ ok: false, error: "moved" });
    }
    expect(agent).not.toHaveBeenCalled();
    vi.stubGlobal("location", { origin: "https://shop.example.com" });
    expect(run.func!("https://shop.example.com", "click", { ref: "e1" }, null)).toEqual({ ok: true });
    expect(agent).toHaveBeenCalledWith("click", { ref: "e1" }, undefined);
  });

  it.each([
    ["Cannot access contents of url. Extension manifest must request permission to access this host.", "no_access"],
    ["No tab with id: 7.", "moved"],
    ["Frame with ID 0 is showing error page", "failed"],
  ])("turns %s into %s", async (message, error) => {
    chromeFake.scripting.executeScript.mockRejectedValueOnce(new Error(message));
    await expect(callPage(SHOP, "read_page")).resolves.toMatchObject({ ok: false, error });
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
