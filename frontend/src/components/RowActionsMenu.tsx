import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useReadOnly } from "../context/ReadOnlyContext";
import { ADMIN_WRITE_LOCK_TITLE } from "../lib/adminWriteLock";

export type RowAction = {
  label: string;
  onClick: () => void;
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
};

const MENU_MIN_WIDTH = 168;
const MENU_MAX_HEIGHT = 260;
const VIEWPORT_PAD = 8;

export default function RowActionsMenu({ actions, label = "Actions", menuClassName = "" }: Props) {
  const readOnly = useReadOnly();
  const [open, setOpen] = useState(false);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const visible = actions.filter((a) => !a.disabled);

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
    if (!open) {
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
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      if (rootRef.current?.contains(t) || menuRef.current?.contains(t)) return;
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

  const menu =
    open && menuPos
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
                onClick={() => {
                  a.onClick();
                  setOpen(false);
                }}
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
      {menu}
    </div>
  );
}
