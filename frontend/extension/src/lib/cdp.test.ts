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

  it("hands a JavaScript dialog to its owner as it opens, and can answer it", async () => {
    const session = new CdpSession(7);
    await session.attach();
    const seen: unknown[] = [];
    session.onDialog((dialog) => seen.push(dialog));
    chrome.debugger.emitEvent(7, "Page.javascriptDialogOpening", { type: "confirm", message: "sure?" });
    expect(seen).toEqual([{ type: "confirm", message: "sure?" }]);
    expect(session.hasDialog).toBe(true);
    await session.handleDialog(true);
    expect(chrome.debugger.sent.at(-1)).toMatchObject({ method: "Page.handleJavaScriptDialog", params: { accept: true } });
    expect(session.hasDialog).toBe(false);
    // Closed by the page or the person: the session knows too.
    chrome.debugger.emitEvent(7, "Page.javascriptDialogOpening", { type: "alert", message: "hi" });
    chrome.debugger.emitEvent(7, "Page.javascriptDialogClosed", { result: true });
    expect(session.hasDialog).toBe(false);
    session.onDialog(null);
    chrome.debugger.emitEvent(7, "Page.javascriptDialogOpening", { type: "alert", message: "again" });
    expect(seen).toHaveLength(2);
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

  it("hears nothing more once Chrome ended it: the tab's next session answers its dialogs, alone", async () => {
    const first = new CdpSession(7);
    const heard: string[] = [];
    first.onDialog(() => heard.push("first"));
    await first.attach();
    chrome.debugger.emitDetach(7, "target_closed");
    const second = new CdpSession(7);
    second.onDialog(() => heard.push("second"));
    await second.attach();
    chrome.debugger.emitEvent(7, "Page.javascriptDialogOpening", { type: "confirm", message: "Leave?" });
    expect(heard).toEqual(["second"]);
    expect(chrome.debugger.onEvent.listeners.size).toBe(1);
  });

  it("gives up on a command the browser does not answer, but not while a dialog holds the page", async () => {
    const session = new CdpSession(7);
    await session.attach();
    chrome.debugger.sendCommand.mockImplementation(() => undefined); // never answers
    await expect(session.send("Page.getLayoutMetrics", {}, 20)).rejects.toThrow(/did not answer/);
    chrome.debugger.emitEvent(7, "Page.javascriptDialogOpening", { type: "confirm", message: "sure?" });
    let failed = false;
    const waiting = session.send("Input.dispatchMouseEvent", { type: "mouseReleased" }, 20).catch(() => {
      failed = true;
    });
    await new Promise((resolve) => setTimeout(resolve, 60));
    expect(failed).toBe(false);
    chrome.debugger.emitEvent(7, "Page.javascriptDialogClosed", { result: true });
    await waiting;
    expect(failed).toBe(true);
  });
});
