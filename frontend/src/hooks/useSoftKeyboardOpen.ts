import { useEffect, useState } from "react";

/** Inputs that do not bring up the on-screen keyboard. */
const NON_TEXT_INPUTS = new Set(["button", "checkbox", "color", "file", "image", "radio", "range", "reset", "submit"]);

/** Whether focusing `target` brings up the on-screen keyboard. */
export function bringsUpKeyboard(target: EventTarget | null): boolean {
  if (!(target instanceof Node) || !target.isConnected) return false;
  if (target instanceof HTMLTextAreaElement) return true;
  if (target instanceof HTMLInputElement) return !NON_TEXT_INPUTS.has(target.type);
  return target instanceof HTMLElement && target.isContentEditable;
}

/**
 * Whether a field that brings up the on-screen keyboard has focus. On a phone
 * that means the keyboard is up, and what sits along the bottom edge (the tab
 * bar, the install suggestion, the home indicator's padding) steps aside.
 */
export function useSoftKeyboardOpen(): boolean {
  const [open, setOpen] = useState(() => bringsUpKeyboard(document.activeElement));
  useEffect(() => {
    const onFocusIn = (event: FocusEvent) => setOpen(bringsUpKeyboard(event.target));
    // Focus moving from one field to the next keeps it open: no flash between them.
    const onFocusOut = (event: FocusEvent) => setOpen(bringsUpKeyboard(event.relatedTarget));
    // A focused field that leaves the page (the model picker's search box,
    // closing with the picker) fires no focusout in Safari or Firefox. Look
    // again on the next tap and when the keyboard goes away.
    const recheck = () => setOpen(bringsUpKeyboard(document.activeElement));
    const viewport = window.visualViewport;
    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("focusout", onFocusOut);
    document.addEventListener("pointerdown", recheck, true);
    viewport?.addEventListener("resize", recheck);
    return () => {
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("focusout", onFocusOut);
      document.removeEventListener("pointerdown", recheck, true);
      viewport?.removeEventListener("resize", recheck);
    };
  }, []);
  return open;
}
