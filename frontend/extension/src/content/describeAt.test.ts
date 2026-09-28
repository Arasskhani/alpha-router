/**
 * @vitest-environment happy-dom
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { describeAt, locate, snapshot } from "./agent";
import { OVERLAY_ID } from "./overlay";
import { runAgentCall } from "./runtime";
import { VISUALS_ID } from "./visuals";

const visible = () => true;

function page(html: string): Document {
  document.body.innerHTML = html;
  return document;
}

/** Layout is not real here: say what sits at the point. */
function at(el: Element | null) {
  vi.spyOn(document, "elementFromPoint").mockReturnValue(el);
}

afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("describeAt", () => {
  it("describes the control a click at the point would activate, with its rect", () => {
    const doc = page(`<button id="b"><span id="s">Place order</span></button>`);
    at(doc.getElementById("s"));
    const result = describeAt(doc, 10, 10, visible, true);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.element.role).toBe("button");
      expect(result.element.name).toBe("Place order");
      expect(result.rect).toEqual(expect.objectContaining({ x: expect.any(Number), width: expect.any(Number) }));
    }
  });

  it("refuses a point with nothing under it, or the page background", () => {
    const doc = page(`<p>hi</p>`);
    at(null);
    expect(describeAt(doc, 1, 1, visible)).toMatchObject({ ok: false, error: "not_found" });
    at(doc.documentElement);
    expect(describeAt(doc, 1, 1, visible)).toMatchObject({ ok: false, error: "not_found" });
  });

  it("never reports the agent's own banner as the target, and says the banner is in the way", () => {
    const doc = page(`<div id="${OVERLAY_ID}"><button>Stop</button></div>`);
    at(doc.querySelector(`#${OVERLAY_ID} button`));
    const result = describeAt(doc, 1, 1, visible);
    expect(result).toMatchObject({ ok: false, error: "covered" });
    expect(String((result as { message: string }).message)).toMatch(/Alpharouter's banner/);
  });

  it("refuses a hidden element", () => {
    const doc = page(`<button id="b">x</button>`);
    at(doc.getElementById("b"));
    expect(describeAt(doc, 1, 1, () => false)).toMatchObject({ ok: false, error: "not_visible" });
  });

  it("wants numbers", () => {
    expect(describeAt(page(`<p>x</p>`), "1" as unknown, 2, visible)).toMatchObject({ ok: false, error: "bad_request" });
  });

  it("follows the point into a frame of the same site, and reports the rect in the page's pixels", () => {
    // Detached, so happy-dom does not go and load the frame's address.
    const doc = page(`<p>x</p>`);
    const frame = doc.createElement("iframe");
    frame.setAttribute("src", "/inner");
    const inner = document.implementation.createHTMLDocument("inner");
    inner.body.innerHTML = `<button id="ib">In the frame</button>`;
    const button = inner.getElementById("ib")!;
    Object.defineProperty(frame, "contentDocument", { value: inner, configurable: true });
    Object.defineProperty(frame, "clientLeft", { value: 2, configurable: true });
    Object.defineProperty(frame, "clientTop", { value: 2, configurable: true });
    vi.spyOn(frame, "getBoundingClientRect").mockReturnValue({ left: 100, top: 50, width: 300, height: 200, right: 400, bottom: 250, x: 100, y: 50, toJSON: () => ({}) } as DOMRect);
    vi.spyOn(button, "getBoundingClientRect").mockReturnValue({ left: 10, top: 20, width: 80, height: 30, right: 90, bottom: 50, x: 10, y: 20, toJSON: () => ({}) } as DOMRect);
    at(frame);
    const seen: Array<[number, number]> = [];
    Object.defineProperty(inner, "elementFromPoint", {
      value: (x: number, y: number) => {
        seen.push([x, y]);
        return button;
      },
      configurable: true,
    });
    const result = describeAt(doc, 150, 90, visible, true);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.element.name).toBe("In the frame");
      expect(result.element.frame).toBeUndefined();
      // The point, in the frame's pixels: past its position and its border.
      expect(seen).toEqual([[48, 38]]);
      // The rect, back in the page's pixels.
      expect(result.rect).toEqual({ x: 112, y: 72, width: 80, height: 30 });
    }
  });

  it("reports a frame of another site as a frame it cannot see into, with its site", () => {
    const doc = page(`<p>x</p>`);
    const frame = doc.createElement("iframe");
    frame.setAttribute("src", "https://pay.example/checkout");
    frame.setAttribute("title", "Payment");
    Object.defineProperty(frame, "contentDocument", { value: null, configurable: true });
    at(frame);
    const result = describeAt(doc, 5, 5, visible, true);
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.element).toMatchObject({ role: "frame", name: "Payment", frame: { host: "pay.example" } });
  });

  it("marks a target drawn too faint to see, and one a couple of pixels in size", () => {
    const doc = page(`<div id="veil" style="opacity:0.02"><button id="ghost">Confirm</button></div><a id="dot" href="https://x.example/">.</a>`);
    at(doc.getElementById("ghost"));
    const faint = describeAt(doc, 5, 5, visible, true);
    expect(faint.ok && faint.element.hidden).toBe("transparent");
    const dot = doc.getElementById("dot")!;
    vi.spyOn(dot, "getBoundingClientRect").mockReturnValue({ left: 10, top: 10, width: 1, height: 1, right: 11, bottom: 11, x: 10, y: 10, toJSON: () => ({}) } as DOMRect);
    at(dot);
    const tiny = describeAt(doc, 10, 10, visible, true);
    expect(tiny.ok && tiny.element.hidden).toBe("tiny");
    // An ordinary element is not marked.
    const doc2 = page(`<button id="b">Fine</button>`);
    at(doc2.getElementById("b"));
    const fine = describeAt(doc2, 5, 5, visible, true);
    expect(fine.ok && fine.element.hidden).toBeUndefined();
  });

  it("names a hidden checkbox under its label as the checkbox, boxed where the label is", () => {
    const doc = page(`<label id="l"><input type="checkbox" id="c" style="opacity:0"><span id="s">Remember me</span></label>`);
    at(doc.getElementById("s"));
    vi.spyOn(doc.getElementById("l")!, "getBoundingClientRect").mockReturnValue({ left: 20, top: 30, width: 120, height: 24, right: 140, bottom: 54, x: 20, y: 30, toJSON: () => ({}) } as DOMRect);
    const shown = (el: Element) => el.id !== "c";
    const result = describeAt(doc, 25, 35, shown, true);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.element).toMatchObject({ role: "checkbox", name: "Remember me", tag: "input" });
      expect(result.rect).toEqual({ x: 20, y: 30, width: 120, height: 24 });
    }
  });

  it("enters an open shadow root to the real element under the point", () => {
    const doc = page(`<div id="host"></div>`);
    const host = doc.getElementById("host")!;
    const shadow = host.attachShadow({ mode: "open" });
    shadow.innerHTML = `<button id="inner">Inside</button>`;
    const inner = shadow.getElementById("inner")!;
    at(host);
    // happy-dom's ShadowRoot has no elementFromPoint; a real one does.
    Object.defineProperty(shadow, "elementFromPoint", { value: () => inner, configurable: true });
    const result = describeAt(doc, 5, 5, visible, true);
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.element.name).toBe("Inside");
  });
});

describe("locate", () => {
  const box = (left: number, top: number, width = 80, height = 30) => ({ left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) }) as DOMRect;
  const refOf = (name: string) => snapshot(document, { isVisible: visible }).elements.find((e) => e.name === name)!.ref;

  it("gives the element's box as it is, without scrolling what is in the window", () => {
    const doc = page(`<button id="b">Send</button>`);
    const button = doc.getElementById("b")!;
    vi.spyOn(button, "getBoundingClientRect").mockReturnValue(box(100, 200));
    const intoView = vi.fn();
    button.scrollIntoView = intoView;
    at(button);
    expect(locate(refOf("Send"), visible, true)).toMatchObject({ ok: true, element: { role: "button", name: "Send" }, rect: { x: 100, y: 200, width: 80, height: 30 } });
    expect(intoView).not.toHaveBeenCalled();
  });

  it("brings it into view when it is out of the window", () => {
    const doc = page(`<button id="b">Far</button>`);
    const button = doc.getElementById("b")!;
    vi.spyOn(button, "getBoundingClientRect").mockReturnValue(box(100, 5000));
    const intoView = vi.fn();
    button.scrollIntoView = intoView;
    at(button);
    locate(refOf("Far"), visible, true);
    expect(intoView).toHaveBeenCalledWith({ block: "center", inline: "center" });
  });

  it("refuses when something else would take the press, the agent's banner included", () => {
    const doc = page(`<button id="b">Send</button><div id="cookie">We use cookies</div><div id="${OVERLAY_ID}"><button>Stop</button></div>`);
    vi.spyOn(doc.getElementById("b")!, "getBoundingClientRect").mockReturnValue(box(100, 200));
    at(doc.getElementById("cookie"));
    expect(locate(refOf("Send"), visible, true)).toMatchObject({ ok: false, error: "covered", message: expect.stringContaining("We use cookies") });
    at(doc.querySelector(`#${OVERLAY_ID} button`));
    expect(locate(refOf("Send"), visible, true)).toMatchObject({ ok: false, error: "covered", message: expect.stringContaining("Alpharouter's banner") });
  });

  it("presses a hidden checkbox where its label is", () => {
    const doc = page(`<input type="checkbox" id="c" style="opacity:0"><label id="l" for="c">Remember me</label>`);
    const shown = (el: Element) => el.id !== "c";
    vi.spyOn(doc.getElementById("l")!, "getBoundingClientRect").mockReturnValue(box(20, 30, 120, 24));
    at(doc.getElementById("l"));
    const ref = snapshot(document, { isVisible: shown }).elements.find((e) => e.name === "Remember me")!.ref;
    expect(locate(ref, shown, true)).toMatchObject({ ok: true, element: { role: "checkbox" }, rect: { x: 20, y: 30, width: 120, height: 24 } });
  });
});

describe("the page methods for full control", () => {
  const send = () => undefined;

  it("describe_at goes through the runtime", async () => {
    const doc = page(`<a id="l" href="https://x.example/p">Go</a>`);
    at(doc.getElementById("l"));
    const result = await runAgentCall(doc, "describe_at", { x: 3, y: 4, activates: true }, visible, send);
    expect(result).toMatchObject({ ok: true, element: { role: "link", name: "Go" } });
  });

  it("shows, drives and hides the visuals", async () => {
    const doc = page(`<p>x</p>`);
    expect(await runAgentCall(doc, "visuals_show", {}, visible, send)).toEqual({ ok: true });
    expect(doc.getElementById(VISUALS_ID)).not.toBeNull();
    expect(await runAgentCall(doc, "visuals_state", { state: "waiting" }, visible, send)).toEqual({ ok: true });
    expect(await runAgentCall(doc, "visuals_state", { state: "purple" }, visible, send)).toMatchObject({ ok: false });
    expect(await runAgentCall(doc, "visuals_cursor", { x: 10, y: 20, click: "left" }, visible, send)).toEqual({ ok: true });
    expect(await runAgentCall(doc, "visuals_cursor", { x: "10" }, visible, send)).toMatchObject({ ok: false });
    expect(await runAgentCall(doc, "visuals_target", { rect: { x: 1, y: 2, width: 3, height: 4 } }, visible, send)).toEqual({ ok: true });
    expect(await runAgentCall(doc, "visuals_target", { rect: null }, visible, send)).toEqual({ ok: true });
    expect(await runAgentCall(doc, "visuals_hide", {}, visible, send)).toEqual({ ok: true });
    expect(doc.getElementById(VISUALS_ID)).toBeNull();
  });
});
