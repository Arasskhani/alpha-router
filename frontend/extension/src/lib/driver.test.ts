import { beforeEach, describe, expect, it } from "vitest";

import { layoutMetrics } from "../test/cdpFixtures";
import { installChromeFake, type ChromeFake } from "../test/chromeFake";
import { chooseDriver } from "./driver";

let chrome: ChromeFake;

beforeEach(() => {
  chrome = installChromeFake();
  chrome.debugger.answers.set("Page.getLayoutMetrics", layoutMetrics({ width: 800, height: 600 }));
});

describe("chooseDriver", () => {
  it("uses the dom path when full control is off, without attaching", async () => {
    const choice = await chooseDriver(7, { fullControl: false, maxSide: 1280 });
    expect(choice.mode).toBe("dom");
    expect(chrome.debugger.attached.has(7)).toBe(false);
  });

  it("attaches the cdp driver when full control is on", async () => {
    const choice = await chooseDriver(7, { fullControl: true, maxSide: 1280 });
    expect(choice.mode).toBe("cdp");
    expect(chrome.debugger.attached.has(7)).toBe(true);
    if (choice.mode === "cdp") await choice.driver.stop();
  });

  it("falls back to the dom path with a reason when Chrome refuses the attach", async () => {
    chrome.debugger.attachError = "Cannot attach: blocked by policy";
    const choice = await chooseDriver(7, { fullControl: true, maxSide: 1280 });
    expect(choice.mode).toBe("dom");
    if (choice.mode === "dom") expect(choice.reason).toMatch(/blocked by policy/);
    expect(chrome.debugger.attached.has(7)).toBe(false);
  });
});
