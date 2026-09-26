import { beforeEach, describe, expect, it } from "vitest";

import { installChromeFake, type ChromeFake } from "../test/chromeFake";
import { captureRegion, captureViewport, captureVisibleFallback, viewportSize } from "./capture";
import { CdpSession } from "./cdp";

let chrome: ChromeFake;

async function session(): Promise<CdpSession> {
  const s = new CdpSession(7);
  await s.attach();
  return s;
}

beforeEach(() => {
  chrome = installChromeFake();
});

describe("viewportSize", () => {
  it("reads the CSS visual viewport, falling back when there is none", async () => {
    const s = await session();
    chrome.debugger.answers.set("Page.getLayoutMetrics", { cssVisualViewport: { width: 1024, height: 768 } });
    expect(await viewportSize(s)).toEqual({ width: 1024, height: 768 });
    chrome.debugger.answers.set("Page.getLayoutMetrics", {});
    expect(await viewportSize(s)).toEqual({ width: 1280, height: 800 });
  });
});

describe("captureViewport", () => {
  it("captures the viewport at the frame scale and returns a data URL and frame", async () => {
    const s = await session();
    chrome.debugger.answers.set("Page.getLayoutMetrics", { cssVisualViewport: { width: 2560, height: 1440 } });
    chrome.debugger.answers.set("Page.captureScreenshot", { data: "AAAA" });
    const shot = await captureViewport(s, 1280);
    expect(shot.dataUrl).toBe("data:image/jpeg;base64,AAAA");
    expect(shot.frame).toMatchObject({ width: 1280, height: 720, scale: 0.5 });
    const call = chrome.debugger.sent.find((c) => c.method === "Page.captureScreenshot")!;
    expect(call.params).toMatchObject({ format: "jpeg", clip: { width: 2560, height: 1440, scale: 0.5 } });
  });

  it("throws when the capture returns no image", async () => {
    const s = await session();
    chrome.debugger.answers.set("Page.getLayoutMetrics", { cssVisualViewport: { width: 800, height: 600 } });
    chrome.debugger.answers.set("Page.captureScreenshot", {});
    await expect(captureViewport(s, 1280)).rejects.toThrow(/no image/);
  });
});

describe("captureRegion", () => {
  it("clips to the region and scales it up toward the max side", async () => {
    const s = await session();
    chrome.debugger.answers.set("Page.captureScreenshot", { data: "ZZ" });
    const shot = await captureRegion(s, { x: 100, y: 50, width: 200, height: 100 }, 800);
    expect(shot.frame.scale).toBe(4);
    const call = chrome.debugger.sent.find((c) => c.method === "Page.captureScreenshot")!;
    expect(call.params).toMatchObject({ clip: { x: 100, y: 50, width: 200, height: 100, scale: 4 } });
  });
});

describe("captureVisibleFallback", () => {
  it("uses chrome.tabs.captureVisibleTab", async () => {
    const url = await captureVisibleFallback(1);
    expect(url).toMatch(/^data:image\/jpeg/);
    expect(chrome.tabs.captureVisibleTab).toHaveBeenCalled();
  });
});
