import { beforeEach, describe, expect, it } from "vitest";

import { layoutMetrics } from "../test/cdpFixtures";
import { installChromeFake, type ChromeFake } from "../test/chromeFake";
import { CdpSession } from "./cdp";
import { CdpDriver } from "./cdpDriver";

let chrome: ChromeFake;

function metrics(width: number, height: number) {
  chrome.debugger.answers.set("Page.getLayoutMetrics", layoutMetrics({ width, height }));
}

async function driver(maxSide = 1280): Promise<CdpDriver> {
  metrics(2560, 1440); // scale 0.5
  chrome.debugger.answers.set("Page.captureScreenshot", { data: "IMG" });
  const d = new CdpDriver(new CdpSession(7), { maxSide });
  await d.start();
  return d;
}

const mouseEvents = () =>
  chrome.debugger.sent.filter((c) => c.method === "Input.dispatchMouseEvent").map((c) => c.params as Record<string, unknown>);

beforeEach(() => {
  chrome = installChromeFake();
});

describe("CdpDriver", () => {
  it("attaches on start and detaches on stop", async () => {
    const d = await driver();
    expect(chrome.debugger.attached.has(7)).toBe(true);
    await d.stop();
    expect(chrome.debugger.attached.has(7)).toBe(false);
  });

  it("maps a frame point to a CSS pixel before clicking (scale 0.5 → ×2)", async () => {
    const d = await driver();
    await d.click({ x: 320, y: 180 });
    const pressed = mouseEvents().find((e) => e.type === "mousePressed")!;
    expect(pressed).toMatchObject({ x: 640, y: 360, button: "left" });
  });

  it("clamps a point that falls outside the viewport", async () => {
    const d = await driver();
    await d.click({ x: 99999, y: 0 }); // frame x way past the right edge
    const pressed = mouseEvents().find((e) => e.type === "mousePressed")!;
    expect(pressed.x).toBe(2559); // css width 2560, clamped to width-1
  });

  it("takes a screenshot and updates the frame it maps by", async () => {
    const d = await driver();
    const shot = await d.screenshot();
    expect(shot.dataUrl).toBe("data:image/jpeg;base64,IMG");
    expect(shot.frame.scale).toBe(0.5);
  });

  it("types Persian text through insertText", async () => {
    const d = await driver();
    await d.type("سلام");
    expect(chrome.debugger.sent.at(-1)).toMatchObject({ method: "Input.insertText", params: { text: "سلام" } });
  });

  it("presses a named key", async () => {
    const d = await driver();
    expect(await d.key("Enter")).toBe(true);
    expect(chrome.debugger.sent.some((c) => c.method === "Input.dispatchKeyEvent")).toBe(true);
  });

  it("drags from one frame point to another, mapped to CSS", async () => {
    const d = await driver();
    // Hand over drag data on the first take so the drop is dispatched.
    let handed = false;
    chrome.debugger.sendCommand.mockImplementation((_t, method, params, cb) => {
      chrome.debugger.sent.push({ tabId: 7, method, params });
      if (method === "Input.dispatchMouseEvent" && (params as { type?: string }).type === "mouseMoved" && !handed) {
        handed = true;
        chrome.debugger.emitEvent(7, "Input.dragIntercepted", { data: { items: ["x"] } });
      }
      cb(chrome.debugger.answers.get(method));
    });
    const result = await d.drag({ x: 10, y: 10 }, { x: 200, y: 10 });
    expect(result.intercepted).toBe(true);
    const drops = chrome.debugger.sent.filter((c) => c.method === "Input.dispatchDragEvent");
    expect(drops.map((c) => (c.params as { type: string }).type)).toEqual(["dragEnter", "dragOver", "drop"]);
    // Target x 200 in frame → 400 in CSS.
    expect((drops[0].params as { x: number }).x).toBe(400);
  });

  it("passes a dialog through and answers it", async () => {
    const d = await driver();
    chrome.debugger.emitEvent(7, "Page.javascriptDialogOpening", { type: "alert", message: "hi" });
    expect(d.takeDialog()).toMatchObject({ type: "alert" });
    await d.handleDialog(true);
    expect(chrome.debugger.sent.at(-1)).toMatchObject({ method: "Page.handleJavaScriptDialog", params: { accept: true } });
  });
});
