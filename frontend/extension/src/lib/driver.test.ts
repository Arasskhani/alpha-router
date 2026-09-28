import { beforeEach, describe, expect, it } from "vitest";

import { layoutMetrics } from "../test/cdpFixtures";
import { installChromeFake, type ChromeFake } from "../test/chromeFake";
import { CdpSession } from "./cdp";
import { CdpDriver } from "./cdpDriver";
import { chooseDriver, TabDrivers } from "./driver";

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

describe("TabDrivers", () => {
  async function drivers(onDetached: (reason: string) => void = () => undefined) {
    const first = new CdpDriver(new CdpSession(7), { maxSide: 1280 });
    await first.start();
    return new TabDrivers({ tabId: 7, driver: first }, { maxSide: 1280, onDetached });
  }
  const sentTo = (method: string) => chrome.debugger.sent.filter((c) => c.method === method).map((c) => c.tabId);

  it("works in the tab it was started on, then attaches to another tab the first time it is used", async () => {
    const d = await drivers();
    expect(await d.use(7)).toBe(true);
    await d.click({ x: 10, y: 10 });
    expect(await d.use(9)).toBe(true);
    expect(chrome.debugger.attached.has(9)).toBe(true);
    chrome.debugger.sent.length = 0;
    await d.screenshot().catch(() => undefined);
    await d.click({ x: 10, y: 10 });
    // Capture and input go to the tab the agent works in now, which is brought to the front for the capture.
    expect(new Set(sentTo("Page.captureScreenshot"))).toEqual(new Set([9]));
    expect(sentTo("Page.bringToFront")).toEqual([9]);
    expect(new Set(sentTo("Input.dispatchMouseEvent"))).toEqual(new Set([9]));
    await d.stop();
    expect(chrome.debugger.attached.size).toBe(0);
  });

  it("says so when Chrome will not attach to a tab, and does not try again", async () => {
    const d = await drivers();
    chrome.debugger.attachError = "Cannot access a chrome:// URL";
    expect(await d.use(9)).toBe(false);
    chrome.debugger.attachError = null;
    expect(await d.use(9)).toBe(false);
    expect(await d.use(7)).toBe(true);
  });

  it("attaches again to a tab whose session ended", async () => {
    const d = await drivers();
    chrome.debugger.emitDetach(7, "target_closed");
    expect(chrome.debugger.attached.has(7)).toBe(false);
    expect(await d.use(7)).toBe(true);
    expect(chrome.debugger.attached.has(7)).toBe(true);
  });

  it("tells its owner when a session ends, with the reason", async () => {
    const reasons: string[] = [];
    const d = await drivers((reason) => {
      reasons.push(reason);
    });
    await d.use(9);
    chrome.debugger.emitDetach(9, "canceled_by_user");
    expect(reasons).toEqual(["canceled_by_user"]);
  });

  it("answers a dialog in the tab it opened in, whichever tab the agent is on", async () => {
    const d = await drivers();
    await d.use(9);
    const seen: unknown[] = [];
    d.onDialog(async (dialog) => {
      seen.push(dialog);
      await d.handleDialog(true);
    });
    await d.use(7);
    chrome.debugger.sent.length = 0;
    chrome.debugger.emitEvent(9, "Page.javascriptDialogOpening", { type: "alert", message: "from 9" });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(seen).toMatchObject([{ message: "from 9" }]);
    expect(sentTo("Page.handleJavaScriptDialog")).toEqual([9]);
  });
});
