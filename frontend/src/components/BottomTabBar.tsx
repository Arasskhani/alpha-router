import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { getCachedSession } from "../api";
import type { SessionRbac } from "../lib/rbac";
import { topbarShortcutsForSession } from "../lib/userPanelNav";
import type { NavItem } from "../nav/types";
import { NavIcon } from "./icons/navIcons";

/** The sections a thumb reaches most; everything else is under "More". */
const TAB_PATHS = ["/app/chat", "/app/projects", "/app/media", "/app/my-activity"];

/** Fields that bring up the on-screen keyboard. */
const NON_TEXT_INPUTS = new Set(["button", "checkbox", "color", "file", "image", "radio", "range", "reset", "submit"]);

function bringsUpKeyboard(target: EventTarget | null): boolean {
  if (target instanceof HTMLTextAreaElement) return true;
  if (target instanceof HTMLInputElement) return !NON_TEXT_INPUTS.has(target.type);
  return target instanceof HTMLElement && target.isContentEditable;
}

function isActive(path: string, to: string): boolean {
  return path === to || path.startsWith(`${to}/`);
}

/**
 * Phone only, under /app: the user's sections as tabs along the bottom edge,
 * where a thumb reaches them, instead of two taps away in the menu drawer.
 * The bar is part of the layout (not fixed over it), so the page and the chat
 * composer end above it; it steps aside while a field has the keyboard up.
 */
export default function BottomTabBar() {
  const loc = useLocation();
  const path = loc.pathname.replace(/\/$/, "") || "/";
  const [typing, setTyping] = useState(() => bringsUpKeyboard(document.activeElement));
  const [moreOpen, setMoreOpen] = useState(false);
  const moreButtonRef = useRef<HTMLButtonElement>(null);
  const sheetRef = useRef<HTMLDivElement>(null);

  const items = topbarShortcutsForSession(getCachedSession() as SessionRbac | null);
  const tabs = TAB_PATHS.map((to) => items.find((item) => item.to === to)).filter(
    (item): item is NavItem => item !== undefined,
  );
  const more = items.filter((item) => !TAB_PATHS.includes(item.to));
  const moreActive = more.some((item) => isActive(path, item.to));

  useEffect(() => {
    const onFocusIn = (event: FocusEvent) => setTyping(bringsUpKeyboard(event.target));
    // Focus moving from one field to the next keeps the bar away: no flash between them.
    const onFocusOut = (event: FocusEvent) => setTyping(bringsUpKeyboard(event.relatedTarget));
    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("focusout", onFocusOut);
    return () => {
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("focusout", onFocusOut);
    };
  }, []);

  // A navigation by any means (a link in the sheet, the back button) closes it.
  const [sheetPath, setSheetPath] = useState(path);
  if (sheetPath !== path) {
    setSheetPath(path);
    setMoreOpen(false);
  }

  useEffect(() => {
    if (!moreOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMoreOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [moreOpen]);

  // Focus goes into the sheet, and back to the More button when it closes.
  const sheetWasOpen = useRef(false);
  useEffect(() => {
    if (moreOpen) {
      sheetRef.current?.querySelector<HTMLElement>("a")?.focus({ preventScroll: true });
    } else if (sheetWasOpen.current) {
      moreButtonRef.current?.focus({ preventScroll: true });
    }
    sheetWasOpen.current = moreOpen;
  }, [moreOpen]);

  if (typing) return null;

  return (
    <>
      <nav className="bottom-tab-bar" aria-label="Sections">
        {tabs.map((item) => {
          const active = isActive(path, item.to);
          return (
            <Link
              key={item.to}
              to={item.to}
              className={`bottom-tab${active ? " is-active" : ""}`}
              aria-current={active ? "page" : undefined}
            >
              {item.icon ? <NavIcon name={item.icon} className="bottom-tab__icon" /> : null}
              <span className="bottom-tab__label">{item.label}</span>
            </Link>
          );
        })}
        {more.length > 0 ? (
          <button
            ref={moreButtonRef}
            type="button"
            className={`bottom-tab${moreActive || moreOpen ? " is-active" : ""}`}
            aria-haspopup="dialog"
            aria-expanded={moreOpen}
            aria-controls="bottom-tab-more"
            onClick={() => setMoreOpen((open) => !open)}
          >
            <svg className="bottom-tab__icon" width="16" height="16" viewBox="0 0 24 24" aria-hidden>
              <circle cx="5" cy="12" r="1.8" fill="currentColor" />
              <circle cx="12" cy="12" r="1.8" fill="currentColor" />
              <circle cx="19" cy="12" r="1.8" fill="currentColor" />
            </svg>
            <span className="bottom-tab__label">More</span>
          </button>
        ) : null}
      </nav>
      {moreOpen ? (
        <>
          <div className="bottom-sheet-backdrop" aria-hidden onClick={() => setMoreOpen(false)} />
          <div
            ref={sheetRef}
            id="bottom-tab-more"
            className="bottom-sheet"
            role="dialog"
            aria-modal="true"
            aria-label="More sections"
          >
            <ul className="bottom-sheet__list">
              {more.map((item) => {
                const active = isActive(path, item.to);
                return (
                  <li key={item.to}>
                    <Link
                      to={item.to}
                      className={`bottom-sheet__item${active ? " is-active" : ""}`}
                      aria-current={active ? "page" : undefined}
                      onClick={() => setMoreOpen(false)}
                    >
                      {item.icon ? <NavIcon name={item.icon} className="bottom-sheet__icon" /> : null}
                      <span>{item.label}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        </>
      ) : null}
    </>
  );
}
