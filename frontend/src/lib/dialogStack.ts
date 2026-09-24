/**
 * The open modal dialogs, in the order they opened. Only the topmost one
 * answers Tab and Escape: a confirmation opened from a dialog is a second
 * dialog on top of the first, and the first must neither pull focus back
 * into itself nor close on the Escape meant for the confirmation.
 */
const stack: HTMLElement[] = [];

/** Register an open dialog; call the returned function when it closes. */
export function pushDialog(panel: HTMLElement): () => void {
  stack.push(panel);
  return () => {
    const index = stack.lastIndexOf(panel);
    if (index >= 0) stack.splice(index, 1);
  };
}

/** Whether `panel` is the dialog on top, the one keys belong to. */
export function isTopDialog(panel: HTMLElement | null): boolean {
  return panel !== null && stack[stack.length - 1] === panel;
}

// What had focus before the element that has it now. A dialog whose child
// takes focus as it mounts (autoFocus) has lost its opener by the time its
// effect runs; this still knows it. Focus that left for nowhere counts as
// nothing: in Safari a click does not focus a button, and a search box typed
// in long before must not be taken for the opener, and be given focus back,
// scrolling the page to it, when the dialog closes.
let previousFocus: Element | null = null;
let currentFocus: Element | null = null;
if (typeof document !== "undefined") {
  document.addEventListener(
    "focusin",
    (event) => {
      previousFocus = currentFocus;
      currentFocus = event.target instanceof Element ? event.target : null;
    },
    true,
  );
  document.addEventListener(
    "focusout",
    (event) => {
      if (event.relatedTarget === null) currentFocus = null;
    },
    true,
  );
}

/** The element to give focus back to when the dialog in `panel` closes. */
export function openerOf(panel: HTMLElement): HTMLElement | null {
  const active = document.activeElement;
  if (active && panel.contains(active)) {
    return previousFocus instanceof HTMLElement && !panel.contains(previousFocus) ? previousFocus : null;
  }
  return active instanceof HTMLElement ? active : null;
}
