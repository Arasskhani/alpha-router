import { type RefObject, useEffect } from "react";

import { isTopDialog, openerOf, pushDialog } from "../lib/dialogStack";

const FOCUSABLE =
  'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"]), [contenteditable="true"]';

/**
 * The modal dialog pattern for the panel in `panelRef` while `open`: focus
 * moves in when it opens, Tab stays inside, and focus goes back to whatever
 * opened it when it closes. Only the dialog on top traps Tab (lib/dialogStack),
 * so a confirmation opened from a dialog keeps focus in the confirmation.
 */
export function useDialogFocus(panelRef: RefObject<HTMLElement | null>, open: boolean): void {
  useEffect(() => {
    const panel = panelRef.current;
    if (!open || !panel) return;
    const opener = openerOf(panel);
    const release = pushDialog(panel);
    const focusable = () =>
      [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
        (el) => !el.hasAttribute("disabled") && el.getAttribute("aria-hidden") !== "true",
      );
    // A child with autoFocus has already taken focus during commit; respect
    // it. Otherwise prefer the first control in the body over the header's
    // close button.
    if (!panel.contains(document.activeElement)) {
      const body = panel.querySelector<HTMLElement>(".modal-body");
      const initial = body
        ? [...body.querySelectorAll<HTMLElement>(FOCUSABLE)].find((el) => !el.hasAttribute("disabled"))
        : null;
      (initial ?? focusable()[0] ?? panel).focus();
    }

    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Tab" || !isTopDialog(panel)) return;
      const items = focusable();
      if (!items.length) {
        e.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      // The panel itself takes focus (a click on its text): Shift+Tab from it
      // would leave for the page behind.
      if (e.shiftKey && (active === first || active === panel || !panel.contains(active))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (active === last || !panel.contains(active))) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      release();
      if (opener && document.contains(opener)) opener.focus();
    };
  }, [open, panelRef]);
}
