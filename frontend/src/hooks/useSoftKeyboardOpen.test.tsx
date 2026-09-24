/**
 * @vitest-environment happy-dom
 *
 * useSoftKeyboardOpen: whether a field that brings up the on-screen keyboard
 * has focus. The tab bar, the install suggestion and the home indicator's
 * padding step aside while it does.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { bringsUpKeyboard, useSoftKeyboardOpen } from "./useSoftKeyboardOpen";

let host: HTMLDivElement;
let root: Root;

function Probe() {
  return <output data-testid="open">{String(useSoftKeyboardOpen())}</output>;
}

beforeEach(async () => {
  host = document.createElement("div");
  host.innerHTML =
    '<input aria-label="Message"><input type="checkbox" aria-label="Pick"><textarea aria-label="Notes"></textarea>' +
    '<div contenteditable="true" aria-label="Rich"></div><button type="button">Send</button><div id="probe"></div>';
  document.body.appendChild(host);
  root = createRoot(host.querySelector("#probe")!);
  await act(async () => root.render(<Probe />));
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const open = () => host.querySelector("[data-testid=open]")!.textContent;
const field = (label: string) => host.querySelector<HTMLElement>(`[aria-label="${label}"]`)!;

describe("useSoftKeyboardOpen", () => {
  it("is open while a text field has focus and closed after", async () => {
    expect(open()).toBe("false");
    await act(async () => field("Message").focus());
    expect(open()).toBe("true");
    await act(async () => field("Message").blur());
    expect(open()).toBe("false");
  });

  it("stays open when focus moves from one field to the next", async () => {
    await act(async () => field("Message").focus());
    await act(async () => field("Notes").focus());
    expect(open()).toBe("true");
  });

  it("is closed for a checkbox or a button", async () => {
    await act(async () => field("Pick").focus());
    expect(open()).toBe("false");
    await act(async () => host.querySelector("button")!.focus());
    expect(open()).toBe("false");
  });

  it("notices on the next tap that a focused field left the page without a focusout", async () => {
    await act(async () => field("Message").focus());
    // Safari and Firefox fire no focusout when a focused element is removed.
    const input = field("Message");
    await act(async () => {
      input.parentNode!.removeChild(input);
    });
    await act(async () => document.dispatchEvent(new Event("pointerdown", { bubbles: true })));
    expect(open()).toBe("false");
  });
});

describe("bringsUpKeyboard", () => {
  it("knows which elements bring up the keyboard", () => {
    expect(bringsUpKeyboard(field("Message"))).toBe(true);
    expect(bringsUpKeyboard(field("Notes"))).toBe(true);
    expect(bringsUpKeyboard(field("Pick"))).toBe(false);
    expect(bringsUpKeyboard(host.querySelector("button"))).toBe(false);
    expect(bringsUpKeyboard(null)).toBe(false);
    expect(bringsUpKeyboard(document.createElement("input"))).toBe(false); // not in the page
  });
});
