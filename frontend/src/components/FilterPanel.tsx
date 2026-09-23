import { useId, useState, type ReactNode } from "react";

import { usePhoneLayout } from "../hooks/useMediaQuery";

type Props = {
  /** How many filters currently have a value; shown on the toggle. */
  activeCount: number;
  children: ReactNode;
};

/**
 * On a phone, a list page's filters fold away behind one "Filters" button.
 *
 * At 390px the filters of Users, API Logs, Admin Logs and Sign-in Activity
 * took 350–430 pixels, so the first row of data started at the bottom of the
 * screen. Folded, the list starts right under the title; the button says how
 * many filters are set, and opens by itself when some are.
 *
 * The fields sit in the same wrapper at every width, so they stay the same
 * elements, and keep what was typed into them, when a tablet turns or a
 * window crosses the breakpoint; folded, the wrapper is `hidden`. Shown, it
 * is `display: contents` (styles.css), so the page's own layout is what it
 * was without it. The toggle exists on a phone only.
 */
export default function FilterPanel({ activeCount, children }: Props) {
  const phone = usePhoneLayout();
  const id = useId();
  const [open, setOpen] = useState(() => activeCount > 0);

  return (
    <>
      {phone ? (
        <button
          type="button"
          className="filter-panel-toggle"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen((value) => !value)}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <path d="M3 5h18M6 12h12M10 19h4" strokeLinecap="round" />
          </svg>
          <span>{open ? "Hide filters" : "Filters"}</span>
          {activeCount > 0 ? (
            <span className="filter-panel-toggle__count" aria-label={`${activeCount} active`}>
              {activeCount}
            </span>
          ) : null}
        </button>
      ) : null}
      <div id={id} className="filter-panel" hidden={phone && !open}>
        {children}
      </div>
    </>
  );
}

/** How many of these filter values are set (non-blank after trimming). */
export function countActiveFilters(values: Array<string | null | undefined | boolean>): number {
  return values.filter((value) => (typeof value === "boolean" ? value : Boolean((value ?? "").trim()))).length;
}
