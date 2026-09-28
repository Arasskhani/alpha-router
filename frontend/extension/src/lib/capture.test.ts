import { beforeEach, describe, expect, it } from "vitest";

import { jpegOf, layoutMetrics } from "../test/cdpFixtures";
import { installChromeFake, type ChromeFake } from "../test/chromeFake";
import { captureRegion, captureViewport, captureVisibleFallback, jpegSize, viewportSize } from "./capture";
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
    chrome.debugger.answers.set("Page.getLayoutMetrics", layoutMetrics({ width: 1024, height: 768 }));
    expect(await viewportSize(s)).toEqual({ width: 1024, height: 768 });
    chrome.debugger.answers.set("Page.getLayoutMetrics", {});
    expect(await viewportSize(s)).toEqual({ width: 1280, height: 800 });
  });
});

describe("captureViewport", () => {
  it("captures the viewport at the frame scale and returns a data URL and frame", async () => {
    const s = await session();
    chrome.debugger.answers.set("Page.getLayoutMetrics", layoutMetrics({ width: 2560, height: 1440 }));
    chrome.debugger.answers.set("Page.captureScreenshot", { data: "AAAA" });
    const shot = await captureViewport(s, 1280);
    expect(shot.dataUrl).toBe("data:image/jpeg;base64,AAAA");
    expect(shot.frame).toMatchObject({ width: 1280, height: 720, scale: 0.5 });
    const call = chrome.debugger.sent.find((c) => c.method === "Page.captureScreenshot")!;
    expect(call.params).toMatchObject({ format: "jpeg", clip: { width: 2560, height: 1440, scale: 0.5 } });
  });

  it("divides the clip's scale by the display scale, so the image is the frame at 150 % too", async () => {
    const s = await session();
    // A tall window on a Windows laptop at 150 %: Chrome answers in device pixels.
    chrome.debugger.answers.set("Page.getLayoutMetrics", layoutMetrics({ width: 870, height: 968, dpr: 1.5 }));
    chrome.debugger.answers.set("Page.captureScreenshot", { data: jpegOf(870, 968) });
    const shot = await captureViewport(s, 1280);
    expect(shot.frame).toMatchObject({ width: 870, height: 968, scale: 1 });
    const call = chrome.debugger.sent.find((c) => c.method === "Page.captureScreenshot")!;
    expect((call.params as { clip: { scale: number } }).clip.scale).toBeCloseTo(1 / 1.5, 6);
  });

  it("scales a big viewport at 125 % to the frame, dividing by the display scale", async () => {
    const s = await session();
    chrome.debugger.answers.set("Page.getLayoutMetrics", layoutMetrics({ width: 1536, height: 864, dpr: 1.25 }));
    chrome.debugger.answers.set("Page.captureScreenshot", { data: jpegOf(1280, 720) });
    const shot = await captureViewport(s, 1280);
    expect(shot.frame).toMatchObject({ width: 1280, height: 720 });
    expect(shot.frame.scale).toBeCloseTo(1280 / 1536, 6);
    const call = chrome.debugger.sent.find((c) => c.method === "Page.captureScreenshot")!;
    expect((call.params as { clip: { scale: number } }).clip.scale).toBeCloseTo(1280 / 1536 / 1.25, 6);
  });

  it("takes the frame from the image when the image is another size than expected", async () => {
    const s = await session();
    // The metrics say scale 1, but the image came back at 1.5 times: the frame follows the image.
    chrome.debugger.answers.set("Page.getLayoutMetrics", layoutMetrics({ width: 800, height: 600 }));
    chrome.debugger.answers.set("Page.captureScreenshot", { data: jpegOf(1200, 900) });
    const shot = await captureViewport(s, 1280);
    expect(shot.frame).toMatchObject({ width: 1200, height: 900, scale: 1.5 });
  });

  it("throws when the capture returns no image", async () => {
    const s = await session();
    chrome.debugger.answers.set("Page.getLayoutMetrics", layoutMetrics({ width: 800, height: 600 }));
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

describe("jpegSize", () => {
  it("reads a JPEG's size from its frame header", () => {
    expect(jpegSize(`data:image/jpeg;base64,${jpegOf(1305, 1452)}`)).toEqual({ width: 1305, height: 1452 });
  });

  it("answers null for data that is not a JPEG", () => {
    expect(jpegSize("data:image/jpeg;base64,AAAA")).toBeNull();
    expect(jpegSize("data:image/jpeg;base64,***")).toBeNull();
  });
});

describe("captureVisibleFallback", () => {
  it("uses chrome.tabs.captureVisibleTab", async () => {
    const url = await captureVisibleFallback(1);
    expect(url).toMatch(/^data:image\/jpeg/);
    expect(chrome.tabs.captureVisibleTab).toHaveBeenCalled();
  });
});
