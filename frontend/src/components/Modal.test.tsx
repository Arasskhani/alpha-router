/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Modal from "./Modal";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let opener: HTMLButtonElement;

function mount(open: boolean, onClose = vi.fn()) {
  act(() => {
    root.render(
      <Modal open={open} title="Example" onClose={onClose}>
        <input id="first" aria-label="first" />
        <button id="second" type="button">
          second
        </button>
      </Modal>,
    );
  });
  return onClose;
}

function key(el: Element | null, key: string, shiftKey = false) {
  act(() => {
    (el ?? document).dispatchEvent(new KeyboardEvent("keydown", { key, shiftKey, bubbles: true, cancelable: true }));
  });
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  opener = document.createElement("button");
  opener.textContent = "open";
  document.body.appendChild(opener);
  opener.focus();
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  opener.remove();
  document.body.style.overflow = "";
});

describe("Modal", () => {
  it("moves focus into the dialog when it opens", () => {
    mount(true);
    const dialog = container.querySelector('[role="dialog"]')!;
    expect(dialog.contains(document.activeElement), "focus is inside the dialog").toBe(true);
  });

  it("keeps Tab inside the dialog", () => {
    mount(true);
    const focusable = [...container.querySelectorAll<HTMLElement>("button, input")];
    const last = focusable[focusable.length - 1];
    const first = focusable[0];

    last.focus();
    key(last, "Tab");
    expect(document.activeElement, "Tab from the last control wraps to the first").toBe(first);

    first.focus();
    key(first, "Tab", true);
    expect(document.activeElement, "Shift+Tab from the first control wraps to the last").toBe(last);
  });

  it("returns focus to the element that opened it", () => {
    const onClose = mount(true);
    key(null, "Escape");
    expect(onClose).toHaveBeenCalled();
    mount(false, onClose);
    expect(document.activeElement, "focus is back on the opener").toBe(opener);
  });

  it("stops the page behind it from scrolling while open", () => {
    mount(true);
    expect(document.body.style.overflow).toBe("hidden");
    mount(false);
    expect(document.body.style.overflow).toBe("");
  });
});

describe("Modal with an autoFocus child", () => {
  it("leaves focus where the child put it", () => {
    act(() => {
      root.render(
        <Modal open title="Confirm" onClose={() => {}}>
          <button type="button">Cancel</button>
          {/* eslint-disable-next-line jsx-a11y/no-autofocus -- the case under test */}
          <button id="confirm" type="button" autoFocus>
            Confirm
          </button>
        </Modal>,
      );
    });
    expect(document.activeElement?.id).toBe("confirm");
  });

  it("still gives focus back to the element that opened it", () => {
    const render = (open: boolean) =>
      act(() => {
        root.render(
          <Modal open={open} title="Confirm" onClose={() => {}}>
            {/* eslint-disable-next-line jsx-a11y/no-autofocus -- the case under test */}
            <button id="confirm" type="button" autoFocus>
              Confirm
            </button>
          </Modal>,
        );
      });
    render(true);
    expect(document.activeElement?.id).toBe("confirm");
    render(false);
    expect(document.activeElement, "focus is back on the opener, not lost with the child").toBe(opener);
  });
});
