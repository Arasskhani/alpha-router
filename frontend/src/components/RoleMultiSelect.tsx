import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useReadOnly } from "../context/ReadOnlyContext";
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
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [menuPos, setMenuPos] = useState<MenuPos | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
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
    const t = window.setTimeout(() => searchRef.current?.focus(), 0);
    return () => window.clearTimeout(t);
  }, [open]);

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
  }, [open, filteredRoles.length]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      if (triggerRef.current?.contains(t) || menuRef.current?.contains(t)) return;
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

  const menu =
    open && pos
      ? createPortal(
          <div
            ref={menuRef}
            className="role-multi-select__menu role-multi-select__menu--portal"
            role="dialog"
            aria-label="Select roles"
            style={{
              position: "fixed",
              top: pos.top,
              left: pos.left,
              minWidth: MENU_MIN_WIDTH,
              width: pos.width,
              maxWidth: `min(20rem, calc(100vw - ${VIEWPORT_PAD * 2}px))`,
            }}
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
          </div>,
          document.body,
        )
      : null;

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
