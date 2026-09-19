import { ReactNode, useEffect, useRef } from "react";

const FOCUSABLE =
  'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"]), [contenteditable="true"]';

type Props = {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  /** When true, header shows only the close control (no title bar text). */
  compactHeader?: boolean;
  /** When false, clicking the backdrop does not close the modal. */
  closeOnBackdrop?: boolean;
  /** When false, Escape does not close the modal. */
  closeOnEscape?: boolean;
  /** Extra class on `.modal-panel` (e.g. size variants). */
  panelClassName?: string;
  /** Extra class on `.modal-body`. */
  bodyClassName?: string;
  /** Extra controls in the header, before the close button. */
  headerActions?: ReactNode;
};

export default function Modal({
  open,
  title,
  onClose,
  children,
  compactHeader,
  closeOnBackdrop = true,
  closeOnEscape = true,
  panelClassName = "",
  bodyClassName = "",
  headerActions,
}: Props) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || !closeOnEscape) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, closeOnEscape]);

  // The dialog pattern: focus moves in when it opens, Tab stays inside, and
  // focus goes back to whatever opened it when it closes. Without this a
  // keyboard user tabbed straight through the overlay into the page behind
  // it, and a screen-reader user was left wherever they had been.
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    const focusable = () =>
      panel
        ? [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
            (el) => !el.hasAttribute("disabled") && el.getAttribute("aria-hidden") !== "true",
          )
        : [];
    // A child with autoFocus has already taken focus during commit; respect
    // it. Otherwise prefer the first control in the body over the header's
    // close button.
    if (!panel?.contains(document.activeElement)) {
      const body = panel?.querySelector<HTMLElement>(".modal-body");
      const initial = body
        ? [...body.querySelectorAll<HTMLElement>(FOCUSABLE)].find((el) => !el.hasAttribute("disabled"))
        : null;
      (initial ?? focusable()[0] ?? panel)?.focus();
    }

    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const items = focusable();
      if (!items.length) {
        e.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === first || !panel?.contains(active))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (active === last || !panel?.contains(active))) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
      if (opener && document.contains(opener)) opener.focus();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="modal-overlay"
      onClick={closeOnBackdrop ? onClose : undefined}
      role="presentation"
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className={`modal-panel${panelClassName ? ` ${panelClassName}` : ""}`}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title || undefined}
      >
        <div className={`modal-header${compactHeader ? " modal-header--compact" : ""}`}>
          {compactHeader || !title ? <span aria-hidden="true" /> : <h3>{title}</h3>}
          <div className="modal-header-end">
            {headerActions}
            <button type="button" className="modal-close" onClick={onClose} aria-label="Close">×</button>
          </div>
        </div>
        <div className={`modal-body${bodyClassName ? ` ${bodyClassName}` : ""}`}>{children}</div>
      </div>
    </div>
  );
}
