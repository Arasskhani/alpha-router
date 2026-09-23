import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useReadOnly } from "../context/ReadOnlyContext";
import { usePhoneLayout } from "../hooks/useMediaQuery";
import { ADMIN_WRITE_LOCK_TITLE } from "../lib/adminWriteLock";
import { normalizeRole, roleLabel, type RoleRecord } from "../lib/rbac";

type Props = {
  value: string[];
  roles: RoleRecord[];
  onChange: (roles: string[]) => void;
  className?: string;
};

type MenuPos = { top: number; left: number; width: number };

const MENU_MIN_WIDTH = 220;
const MENU_MAX_HEIGHT = 360;
const VIEWPORT_PAD = 8;

function summaryText(slugs: string[], catalog: RoleRecord[]): string {
  if (slugs.length === 0) return roleLabel(catalog, "user");
  if (slugs.length === 1) return roleLabel(catalog, slugs[0]);
  if (slugs.length === 2) return slugs.map((s) => roleLabel(catalog, s)).join(", ");
  return `${roleLabel(catalog, slugs[0])} +${slugs.length - 1}`;
}

export default function RoleMultiSelect({ value, roles, onChange, className }: Props) {
  const readOnly = useReadOnly();
  // On a phone the picker is a sheet from the bottom edge, like the row
  // actions, instead of a 220px popover beside the trigger.
  const phone = usePhoneLayout();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [menuPos, setMenuPos] = useState<MenuPos | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const sheetRootRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const normalizedValue = useMemo(() => value.map(normalizeRole).filter(Boolean), [value]);
  const sortedRoles = useMemo(
    () => [...roles].sort((a, b) => a.name.localeCompare(b.name)),
    [roles],
  );
  const filteredRoles = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sortedRoles;
    return sortedRoles.filter(
      (role) =>
        role.name.toLowerCase().includes(q) ||
        role.description.toLowerCase().includes(q) ||
        role.category.toLowerCase().includes(q),
    );
  }, [query, sortedRoles]);

  useEffect(() => {
    if (readOnly) setOpen(false);
  }, [readOnly]);

  useEffect(() => {
    if (open) {
      setDraft([...normalizedValue]);
      setQuery("");
    }
  }, [open, normalizedValue]);

  useEffect(() => {
    if (!open) return;
    // A phone would bring its keyboard up over the sheet for the search box:
    // focus goes to the first role there, and the search is a tap away.
    const t = window.setTimeout(() => {
      if (phone) menuRef.current?.querySelector<HTMLElement>(".role-multi-select__option input")?.focus({ preventScroll: true });
      else searchRef.current?.focus();
    }, 0);
    return () => window.clearTimeout(t);
  }, [open, phone]);

  function updatePosition() {
    const btn = triggerRef.current;
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    const menuWidth = Math.min(Math.max(MENU_MIN_WIDTH, rect.width), window.innerWidth - VIEWPORT_PAD * 2);
    let left = rect.left;
    left = Math.max(VIEWPORT_PAD, Math.min(left, window.innerWidth - menuWidth - VIEWPORT_PAD));

    const estimatedHeight = Math.min(MENU_MAX_HEIGHT, filteredRoles.length * 32 + 96);
    let top = rect.bottom + 6;
    if (top + estimatedHeight > window.innerHeight - VIEWPORT_PAD) {
      top = Math.max(VIEWPORT_PAD, rect.top - estimatedHeight - 6);
    }

    setMenuPos({ top, left, width: menuWidth });
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
  }, [open, phone, filteredRoles.length]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      // The sheet's backdrop closes it on click, not here: closing on mousedown
      // would let the same tap land on whatever is under the backdrop.
      if (triggerRef.current?.contains(t) || menuRef.current?.contains(t) || sheetRootRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        return;
      }
      // The sheet is modal: Tab goes round inside it, not out into the page.
      if (e.key !== "Tab" || !sheetRootRef.current) return;
      const stops = [...(menuRef.current?.querySelectorAll<HTMLElement>("input, button") ?? [])];
      if (stops.length === 0) return;
      e.preventDefault();
      const at = stops.indexOf(document.activeElement as HTMLElement);
      const step = e.shiftKey ? -1 : 1;
      stops[at < 0 ? 0 : (at + step + stops.length) % stops.length].focus();
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function toggleSlug(slug: string) {
    const s = normalizeRole(slug);
    setDraft((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]));
  }

  function apply() {
    const next = (draft.length ? draft : ["user"]).map(normalizeRole);
    setOpen(false);
    const prevKey = [...normalizedValue].sort().join("|");
    const nextKey = [...next].sort().join("|");
    if (prevKey !== nextKey) onChange(next);
  }

  const pos = menuPos;
  const title = normalizedValue.map((s) => roleLabel(roles, s)).join(", ");

  const panel = (
    <div
      ref={menuRef}
      className={`role-multi-select__menu ${phone ? "role-multi-select__menu--sheet" : "role-multi-select__menu--portal"}`}
      role="dialog"
      aria-label="Select roles"
      aria-modal={phone ? true : undefined}
      style={
        phone || !pos
          ? undefined
          : {
              position: "fixed",
              top: pos.top,
              left: pos.left,
              minWidth: MENU_MIN_WIDTH,
              width: pos.width,
              maxWidth: `min(20rem, calc(100vw - ${VIEWPORT_PAD * 2}px))`,
            }
      }
    >
      <div className="role-multi-select__search-wrap">
        <input
          ref={searchRef}
          type="search"
          className="role-multi-select__search"
          placeholder="Search roles…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.stopPropagation()}
        />
      </div>
      <div className="role-multi-select__list">
        {filteredRoles.map((role) => {
          const checked = draft.includes(normalizeRole(role.slug));
          return (
            <label key={role.slug} className="role-multi-select__option">
              <input
                type="checkbox"
                checked={checked}
                onChange={() => toggleSlug(role.slug)}
              />
              <span>{role.name}</span>
            </label>
          );
        })}
        {filteredRoles.length === 0 && (
          <p className="role-multi-select__empty muted-text">No roles match your search.</p>
        )}
      </div>
      <div className="role-multi-select__actions">
        <button type="button" className="btn btn-sm" onClick={apply}>
          Apply
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </div>
  );

  let menu: ReactNode = null;
  if (open && phone) {
    menu = createPortal(
      <div ref={sheetRootRef} className="role-multi-select-sheet-root">
        <div className="action-sheet-backdrop" aria-hidden onClick={() => setOpen(false)} />
        {panel}
      </div>,
      document.body,
    );
  } else if (open && pos) {
    menu = createPortal(panel, document.body);
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={`role-multi-select__trigger${className ? ` ${className}` : ""}`}
        onClick={() => !readOnly && setOpen((v) => !v)}
        disabled={readOnly}
        title={readOnly ? ADMIN_WRITE_LOCK_TITLE : title}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        <span className="role-multi-select__label">{summaryText(normalizedValue, roles)}</span>
        <span className="role-multi-select__caret" aria-hidden>
          ▾
        </span>
      </button>
      {menu}
    </>
  );
}
