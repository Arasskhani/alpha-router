/**
 * @vitest-environment happy-dom
 *
 * A tap in the composer box goes to the message field, unless it lands on
 * something that takes a tap of its own.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";

import { focusFieldOnBoxTap } from "./composerFocus";

let box: HTMLDivElement;
let field: HTMLTextAreaElement;

beforeEach(() => {
  document.body.innerHTML = `
    <div class="alpha-router-composer-box" role="presentation">
      <span class="alpha-router-pending-attachment">report.pdf <button type="button">×</button></span>
      <textarea></textarea>
      <div class="alpha-router-composer-bar">
        <div class="alpha-router-model-row"><button type="button" aria-label="Tools"><svg><path /></svg></button></div>
        <div class="alpha-router-send-group"><button type="button">Send</button></div>
      </div>
      <button type="button">Other</button>
    </div>`;
  box = document.querySelector(".alpha-router-composer-box")!;
  field = box.querySelector("textarea")!;
});

/** A mousedown (or a click) on `el`, as the box's handler sees it. */
function tap(el: Element, type: "mousedown" | "click" = "mousedown") {
  const event = new MouseEvent(type, { bubbles: true, cancelable: true });
  let went = false;
  box.addEventListener(type, (e) => (went = focusFieldOnBoxTap(e, field)), {
    once: true,
  });
  el.dispatchEvent(event);
  return { went, prevented: event.defaultPrevented };
}

describe("a tap in the composer box", () => {
  it("goes to the field from the box's own padding and the space around the bar's buttons", () => {
    for (const el of [
      box,
      box.querySelector(".alpha-router-composer-bar")!,
      box.querySelector(".alpha-router-model-row")!,
    ]) {
      field.blur();
      const { went, prevented } = tap(el);
      expect(went).toBe(true);
      // The tap's own default would take focus straight back out of the field.
      expect(prevented).toBe(true);
      expect(document.activeElement).toBe(field);
    }
    // An attachment's name is not a control either.
    field.blur();
    expect(
      tap(box.querySelector(".alpha-router-pending-attachment")!).went,
    ).toBe(true);
  });

  it("stays with a control, or anything inside one", () => {
    for (const el of [
      box.querySelector('[aria-label="Tools"] path')!,
      box.querySelector(".alpha-router-send-group button")!,
      box.querySelector(".alpha-router-pending-attachment button")!,
      field,
    ]) {
      const { went, prevented } = tap(el);
      expect(went).toBe(false);
      expect(prevented).toBe(false);
    }
  });

  it("brings focus back on the click after a finger's tap moved it", () => {
    // A tap moves focus after its mousedown; the click comes after that.
    const { went, prevented } = tap(box, "click");
    expect(went).toBe(true);
    // A click's default is left alone: a click in the box does nothing else.
    expect(prevented).toBe(false);
    expect(document.activeElement).toBe(field);
  });

  it("leaves a disabled field alone", () => {
    field.disabled = true;
    const { went, prevented } = tap(box);
    expect(went).toBe(false);
    expect(prevented).toBe(false);
    expect(document.activeElement).not.toBe(field);
  });
});

describe("the chat's composer box", () => {
  it("passes its taps to the field", () => {
    const source = readFileSync(join(__dirname, "..", "ChatPanel.tsx"), "utf8");
    // The box's opening tag: from its class to its first child, the file input.
    const at = source.indexOf("className={`alpha-router-composer-box");
    expect(at).toBeGreaterThan(0);
    const tag = source.slice(at, source.indexOf("<input", at));
    expect(tag).toContain(
      "onMouseDown={(event) => focusFieldOnBoxTap(event, textareaRef.current)}",
    );
    expect(tag).toContain(
      "onClick={(event) => focusFieldOnBoxTap(event, textareaRef.current)}",
    );
    expect(tag).toContain('role="presentation"');
  });
});
