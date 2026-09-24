/**
 * @vitest-environment happy-dom
 *
 * The confirmation dialog: a modal dialog in its own right (focus in, Tab kept
 * inside, focus back to the opener), and one that is often opened from another
 * dialog, whose keys it must not lose to the dialog behind it.
 */
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ConfirmModal from "./ConfirmModal";
import Modal from "./Modal";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let opener: HTMLButtonElement;

function key(el: Element | null, name: string, shiftKey = false) {
  act(() => {
    (el ?? document).dispatchEvent(
      new KeyboardEvent("keydown", { key: name, shiftKey, bubbles: true, cancelable: true }),
    );
  });
}

const confirmPanel = () => document.querySelector<HTMLElement>('[role="alertdialog"]');
const buttonsIn = (panel: HTMLElement | null) => [...(panel?.querySelectorAll<HTMLElement>("button, input") ?? [])];

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  opener = document.createElement("button");
  opener.textContent = "Delete";
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

function renderConfirm(open: boolean, handlers = { onConfirm: vi.fn(), onCancel: vi.fn() }, promptLabel?: string) {
  act(() => {
    root.render(
      <ConfirmModal
        open={open}
        title="Delete the chat?"
        message="This cannot be undone."
        confirmLabel="Delete"
        cancelLabel="Keep"
        secondaryLabel="Archive"
        onSecondary={() => {}}
        promptLabel={promptLabel}
        {...handlers}
      />,
    );
  });
  return handlers;
}

describe("ConfirmModal on its own", () => {
  it("is a labelled alert dialog that takes focus", () => {
    renderConfirm(true);
    const panel = confirmPanel()!;
    expect(panel.getAttribute("aria-modal")).toBe("true");
    const title = document.getElementById(panel.getAttribute("aria-labelledby")!);
    expect(title?.textContent).toBe("Delete the chat?");
    expect(panel.contains(document.activeElement)).toBe(true);
  });

  it("keeps Tab inside itself", () => {
    renderConfirm(true, undefined, "Type DELETE");
    const items = buttonsIn(confirmPanel()).filter((el) => !el.hasAttribute("disabled"));
    const first = items[0];
    const last = items[items.length - 1];

    last.focus();
    key(last, "Tab");
    expect(document.activeElement, "Tab from the last control wraps to the first").toBe(first);

    first.focus();
    key(first, "Tab", true);
    expect(document.activeElement, "Shift+Tab from the first control wraps to the last").toBe(last);
  });

  it("gives focus back to what opened it when it closes", () => {
    const handlers = renderConfirm(true);
    key(null, "Escape");
    expect(handlers.onCancel).toHaveBeenCalledTimes(1);
    renderConfirm(false, handlers);
    expect(document.activeElement).toBe(opener);
  });

  it("gives focus back to nothing when nothing had it as it opened", () => {
    // In Safari a click does not focus a button: the search box typed in
    // earlier lost focus to nothing, and must not get it back, the page
    // scrolling up to it, when a confirmation opened further down closes.
    const search = document.createElement("input");
    document.body.appendChild(search);
    search.focus();
    act(() => search.blur());
    const handlers = renderConfirm(true);
    key(null, "Escape");
    renderConfirm(false, handlers);
    expect(document.activeElement).not.toBe(search);
    search.remove();
  });
});

/** A dialog with a button that asks for confirmation, as the file type lists do. */
function DialogWithConfirm({ onDialogClose, onConfirmCancel }: { onDialogClose: () => void; onConfirmCancel: () => void }) {
  const [confirming, setConfirming] = useState(false);
  return (
    <>
      <Modal open title="File types" onClose={onDialogClose}>
        <input aria-label="Search" />
        <button type="button" id="remove" onClick={() => setConfirming(true)}>
          Remove .exe
        </button>
      </Modal>
      <ConfirmModal
        open={confirming}
        title="Remove .exe?"
        message="Uploads of .exe files will be allowed."
        secondaryLabel="Remove all"
        onSecondary={() => setConfirming(false)}
        onConfirm={() => setConfirming(false)}
        onCancel={() => {
          onConfirmCancel();
          setConfirming(false);
        }}
      />
    </>
  );
}

describe("ConfirmModal over another dialog", () => {
  function openBoth() {
    const onDialogClose = vi.fn();
    const onConfirmCancel = vi.fn();
    act(() => root.render(<DialogWithConfirm onDialogClose={onDialogClose} onConfirmCancel={onConfirmCancel} />));
    const remove = document.getElementById("remove")!;
    remove.focus();
    act(() => remove.click());
    return { onDialogClose, onConfirmCancel, remove };
  }

  it("keeps Tab in the confirmation instead of the dialog behind it", () => {
    openBoth();
    const panel = confirmPanel()!;
    const items = buttonsIn(panel);
    items[items.length - 1].focus();
    key(items[items.length - 1], "Tab");
    expect(panel.contains(document.activeElement), "focus stayed in the confirmation").toBe(true);
    expect(document.activeElement).toBe(items[0]);
    items[0].focus();
    key(items[0], "Tab", true);
    expect(document.activeElement).toBe(items[items.length - 1]);
  });

  it("leaves an ordinary Tab alone, never passing focus through the dialog behind it", () => {
    openBoth();
    const panel = confirmPanel()!;
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]')!;
    const touched: EventTarget[] = [];
    dialog.addEventListener("focusin", (e) => touched.push(e.target!));
    const middle = buttonsIn(panel)[1];
    middle.focus();
    const event = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    act(() => {
      middle.dispatchEvent(event);
    });
    // The browser moves focus to the next control; neither dialog steps in.
    expect(event.defaultPrevented).toBe(false);
    expect(touched).toEqual([]);
    expect(document.activeElement).toBe(middle);
  });

  it("closes alone on Escape, and focus goes back into the dialog", () => {
    const { onDialogClose, onConfirmCancel, remove } = openBoth();
    key(null, "Escape");
    expect(onConfirmCancel).toHaveBeenCalledTimes(1);
    expect(onDialogClose).not.toHaveBeenCalled();
    expect(confirmPanel()).toBeNull();
    expect(document.activeElement).toBe(remove);
  });

  it("hands Tab and Escape back to the dialog once it has closed", () => {
    const { onDialogClose } = openBoth();
    key(null, "Escape");
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]')!;
    const items = [...dialog.querySelectorAll<HTMLElement>("button, input")];
    items[items.length - 1].focus();
    key(items[items.length - 1], "Tab");
    expect(document.activeElement).toBe(items[0]);
    key(null, "Escape");
    expect(onDialogClose).toHaveBeenCalledTimes(1);
  });
});

describe("a dialog opened over a confirmation", () => {
  it("takes Escape for itself", () => {
    const onCancel = vi.fn();
    const onClose = vi.fn();
    act(() =>
      root.render(
        <>
          <ConfirmModal open title="Delete?" message="Sure?" onConfirm={() => {}} onCancel={onCancel} />
          <Modal open title="What gets deleted" onClose={onClose}>
            <button type="button">OK</button>
          </Modal>
        </>,
      ),
    );
    key(null, "Escape");
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });
});
