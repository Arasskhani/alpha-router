import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useReadOnly } from "../context/ReadOnlyContext";
import { usePhoneLayout } from "../hooks/useMediaQuery";
import { ADMIN_WRITE_LOCK_TITLE } from "../lib/adminWriteLock";

export type RowAction = {
  label: string;
  /**
   * May return a promise. It used to be typed ``() => void``, so a rejected one
   * was simply dropped: delete a connection, revoke an API key, remove an IP
   * allowlist entry or a TLS certificate, and a 403, 409 or 500 produced
   * nothing at all - no message, no reload, the row still there. The
   * administrator could not tell "the server refused" from "the click did not
   * register", and retried.
   */
  onClick: () => void | Promise<void>;
  danger?: boolean;
  disabled?: boolean;
  /** Allow label to wrap (keeps the menu narrow for long labels). */
  menuWrap?: boolean;
};

type Props = {
  actions: RowAction[];
  label?: string;
  /** Extra class on the portaled menu panel (e.g. size variants). */
  menuClassName?: string;
  /**
   * Shown the error when an action rejects. Pages that already surface their
   * own errors pass their setter; the fallback keeps the failure visible on the
   * ones that do not, rather than losing it.
   */
  onError?: (message: string) => void;
};

const MENU_MIN_WIDTH = 168;
const MENU_MAX_HEIGHT = 260;
const VIEWPORT_PAD = 8;

export default function RowActionsMenu({ actions, label = "Actions", menuClassName = "", onError }: Props) {
  const readOnly = useReadOnly();
  // On a phone the menu is an action sheet along the bottom edge: a finger-sized
  // list in reach of the thumb, instead of a small popover next to the button.
  const phone = usePhoneLayout();
  const [open, setOpen] = useState(false);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const sheetRootRef = useRef<HTMLDivElement>(null);

  const [actionError, setActionError] = useState("");
  const visible = actions.filter((a) => !a.disabled);

  async function runAction(action: RowAction) {
    setOpen(false);
    setActionError("");
    try {
      await action.onClick();
    } catch (err) {
      const message = `${action.label} failed: ${String(err)}`;
      if (onError) onError(message);
      else setActionError(message);
    }
  }

  useEffect(() => {
    if (readOnly) setOpen(false);
  }, [readOnly]);

  function updatePosition() {
    const btn = triggerRef.current;
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    const menuWidth = Math.min(Math.max(MENU_MIN_WIDTH, 184), window.innerWidth - VIEWPORT_PAD * 2);
    let left = rect.right - menuWidth;
    left = Math.max(VIEWPORT_PAD, Math.min(left, window.innerWidth - menuWidth - VIEWPORT_PAD));

    const estimatedHeight = Math.min(MENU_MAX_HEIGHT, visible.length * 36 + 14);
    let top = rect.bottom + 6;
    if (top + estimatedHeight > window.innerHeight - VIEWPORT_PAD) {
      top = Math.max(VIEWPORT_PAD, rect.top - estimatedHeight - 6);
    }

    setMenuPos({ top, left });
  }

  useLayoutEffect(() => {
    if (!open || phone) {
      setMenuPos(null);
      return;
    }
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [open, phone]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      // The sheet's backdrop closes it on click, not here: closing on mousedown
      // would let the same tap land on whatever is under the backdrop.
      if (rootRef.current?.contains(t) || menuRef.current?.contains(t) || sheetRootRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // The sheet is a layer of its own: focus goes in when it opens and back to
  // the button when it closes, as with the other sheets on a phone.
  const sheetOpen = open && phone;
  const sheetWasOpen = useRef(false);
  useEffect(() => {
    if (sheetOpen) {
      menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus({ preventScroll: true });
    } else if (sheetWasOpen.current && document.activeElement === document.body) {
      triggerRef.current?.focus({ preventScroll: true });
    }
    sheetWasOpen.current = sheetOpen;
  }, [sheetOpen]);

  // A modal layer: Tab goes round the sheet's items, not out into the page behind.
  useEffect(() => {
    if (!sheetOpen) return;
    const onTab = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const items = [...(menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])];
      if (items.length === 0) return;
      event.preventDefault();
      const at = items.indexOf(document.activeElement as HTMLElement);
      const step = event.shiftKey ? -1 : 1;
      items[at < 0 ? 0 : (at + step + items.length) % items.length].focus();
    };
    document.addEventListener("keydown", onTab);
    return () => document.removeEventListener("keydown", onTab);
  }, [sheetOpen]);

  const sheetLabel = label === "⋯" || label === "⋮" ? "Actions" : label;
  // The sheet covers the page (a backdrop takes every tap), so it is a modal
  // dialog to assistive technology too: VoiceOver stays inside it.
  const sheet = sheetOpen
    ? createPortal(
        <div ref={sheetRootRef} className="action-sheet-root" role="dialog" aria-modal="true" aria-label={sheetLabel}>
          <div className="action-sheet-backdrop" aria-hidden onClick={() => setOpen(false)} />
          <div ref={menuRef} className="action-sheet" role="menu" aria-label={sheetLabel}>
            {visible.map((a) => (
              <button
                key={a.label}
                type="button"
                role="menuitem"
                className={`action-sheet__item${a.danger ? " action-sheet__item--danger" : ""}`}
                onClick={() => void runAction(a)}
              >
                {a.label}
              </button>
            ))}
            <button type="button" role="menuitem" className="action-sheet__cancel" onClick={() => setOpen(false)}>
              Cancel
            </button>
          </div>
        </div>,
        document.body,
      )
    : null;

  const menu =
    open && !phone && menuPos
      ? createPortal(
          <div
            ref={menuRef}
            className={`row-actions-menu row-actions-menu--portal${menuClassName ? ` ${menuClassName}` : ""}`}
            role="menu"
            style={{
              position: "fixed",
              top: menuPos.top,
              left: menuPos.left,
              minWidth: MENU_MIN_WIDTH,
              maxWidth: `min(16rem, calc(100vw - ${VIEWPORT_PAD * 2}px))`,
            }}
          >
            {visible.map((a) => (
              <button
                key={a.label}
                type="button"
                role="menuitem"
                className={`row-actions-item${a.danger ? " row-actions-item-danger" : ""}${a.menuWrap ? " row-actions-item--wrap" : ""}`}
                onClick={() => void runAction(a)}
              >
                {a.label}
              </button>
            ))}
          </div>,
          document.body,
        )
      : null;

  return (
    <div className="row-actions" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className="btn-sm btn-ghost row-actions-trigger"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="menu"
        disabled={readOnly || visible.length === 0}
        title={readOnly ? ADMIN_WRITE_LOCK_TITLE : undefined}
      >
        {label}
        {label !== "⋯" && label !== "⋮" ? <span aria-hidden>▾</span> : null}
      </button>
      {actionError ? (
        <p className="row-actions-error" role="alert">
          {actionError}
        </p>
      ) : null}
      {menu}
      {sheet}
    </div>
  );
}
