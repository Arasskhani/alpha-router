/**
 * @vitest-environment happy-dom
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { describeAt } from "./agent";
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

  it("never reports the agent's own banner as the target", () => {
    const doc = page(`<div id="${OVERLAY_ID}"><button>Stop</button></div>`);
    at(doc.querySelector(`#${OVERLAY_ID} button`));
    expect(describeAt(doc, 1, 1, visible)).toMatchObject({ ok: false, error: "not_found" });
  });

  it("refuses a hidden element", () => {
    const doc = page(`<button id="b">x</button>`);
    at(doc.getElementById("b"));
    expect(describeAt(doc, 1, 1, () => false)).toMatchObject({ ok: false, error: "not_visible" });
  });

  it("wants numbers", () => {
    expect(describeAt(page(`<p>x</p>`), "1" as unknown, 2, visible)).toMatchObject({ ok: false, error: "bad_request" });
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
