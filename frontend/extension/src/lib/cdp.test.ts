import { beforeEach, describe, expect, it } from "vitest";

import { layoutMetrics } from "../test/cdpFixtures";
import { installChromeFake, type ChromeFake } from "../test/chromeFake";
import { CdpSession } from "./cdp";

let chrome: ChromeFake;

beforeEach(() => {
  chrome = installChromeFake();
});

describe("CdpSession", () => {
  it("attaches, sends commands, and detaches", async () => {
    const session = new CdpSession(7);
    await session.attach();
    expect(session.isAttached).toBe(true);
    expect(chrome.debugger.attached.has(7)).toBe(true);

    chrome.debugger.answers.set("Page.getLayoutMetrics", layoutMetrics({ width: 800, height: 600 }));
    const metrics = await session.send("Page.getLayoutMetrics");
    expect(metrics).toEqual(layoutMetrics({ width: 800, height: 600 }));
    expect(chrome.debugger.sent.at(-1)).toMatchObject({ tabId: 7, method: "Page.getLayoutMetrics" });

    await session.detach();
    expect(session.isAttached).toBe(false);
    expect(chrome.debugger.attached.has(7)).toBe(false);
  });

  it("rejects a command when attach failed (a policy blocking it)", async () => {
    chrome.debugger.attachError = "Cannot access contents of the page";
    const session = new CdpSession(7);
    await expect(session.attach()).rejects.toThrow(/Cannot access/);
    expect(session.isAttached).toBe(false);
  });

  it("surfaces a command error from chrome.runtime.lastError", async () => {
    const session = new CdpSession(7);
    await session.attach();
    chrome.debugger.sendCommand.mockImplementationOnce((_t, method, _p, cb) => {
      (chrome.runtime as { lastError?: { message: string } }).lastError = { message: "boom" };
      cb();
      delete (chrome.runtime as { lastError?: unknown }).lastError;
    });
    await expect(session.send("Input.dispatchMouseEvent")).rejects.toThrow(/boom/);
  });

  it("refuses to send before attaching", async () => {
    await expect(new CdpSession(7).send("X")).rejects.toThrow(/not attached/);
  });

  it("buffers intercepted drag data for this tab only, and hands it over once", async () => {
    const session = new CdpSession(7);
    await session.attach();
    chrome.debugger.emitEvent(9, "Input.dragIntercepted", { data: { items: ["other tab"] } });
    expect(await session.takeDragData()).toBeNull();
    chrome.debugger.emitEvent(7, "Input.dragIntercepted", { data: { items: ["mine"] } });
    expect(await session.takeDragData()).toEqual({ items: ["mine"] });
    expect(await session.takeDragData()).toBeNull();
  });

  it("captures a JavaScript dialog and can answer it", async () => {
    const session = new CdpSession(7);
    await session.attach();
    chrome.debugger.emitEvent(7, "Page.javascriptDialogOpening", { type: "confirm", message: "sure?" });
    expect(session.takeDialog()).toMatchObject({ type: "confirm", message: "sure?" });
    expect(session.takeDialog()).toBeNull();
    await session.handleDialog(true);
    expect(chrome.debugger.sent.at(-1)).toMatchObject({ method: "Page.handleJavaScriptDialog", params: { accept: true } });
  });

  it("reports a detach (the user's Cancel on the bar) once", async () => {
    const session = new CdpSession(7);
    const reasons: string[] = [];
    session.onDetached((r) => reasons.push(r));
    await session.attach();
    chrome.debugger.emitDetach(7, "canceled_by_user");
    expect(session.isAttached).toBe(false);
    expect(reasons).toEqual(["canceled_by_user"]);
    // A later detach() is quiet and safe.
    await session.detach();
    expect(reasons).toEqual(["canceled_by_user"]);
  });
});
