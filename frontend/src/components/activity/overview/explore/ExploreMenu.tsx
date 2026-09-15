import { useEffect, useMemo, useRef, useState } from "react";

type ExploreMenuOption = { value: string; label: string };

type Props = {
  value: string;
  options: ExploreMenuOption[];
  onChange: (value: string) => void;
  /** Shown on the trigger; defaults to selected option label. */
  triggerLabel?: string;
  /** Optional prefix inside trigger, e.g. "Rollup: " */
  triggerPrefix?: string;
  searchable?: boolean;
  searchPlaceholder?: string;
  className?: string;
  ariaLabel?: string;
  align?: "left" | "right";
};

function Chevron() {
  return (
    <svg viewBox="0 0 12 16" width="10" height="12" aria-hidden className="explore-menu__chevron">
      <path d="M3 5.5 L6 2.5 L9 5.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <path d="M3 10.5 L6 13.5 L9 10.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

export default function ExploreMenu({
  value,
  options,
  onChange,
  triggerLabel,
  triggerPrefix,
  searchable = false,
  searchPlaceholder = "Search",
  className = "",
  ariaLabel,
  align = "left",
}: Props) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const selected = options.find((o) => o.value === value);
  const label = triggerLabel ?? selected?.label ?? value;

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return options;
    return options.filter((o) => o.label.toLowerCase().includes(needle) || o.value.toLowerCase().includes(needle));
  }, [options, q]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  useEffect(() => {
    if (!open) setQ("");
  }, [open]);

  return (
    <div className={`explore-menu ${className}`.trim()} ref={ref}>
      <button
        type="button"
        className={`explore-menu__trigger${open ? " is-open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label={ariaLabel}
      >
        <span>
          {triggerPrefix ? <span className="explore-menu__prefix">{triggerPrefix}</span> : null}
          {label}
        </span>
        <Chevron />
      </button>
      {open ? (
        <div className={`explore-menu__panel card${align === "right" ? " explore-menu__panel--right" : ""}`} role="listbox">
          {searchable ? (
            <div className="explore-menu__search">
              <input
                type="text"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder={searchPlaceholder}
                autoFocus
              />
              <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden>
                <circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" strokeWidth="2" />
                <path d="M20 20l-3.5-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
            </div>
          ) : null}
          <div className="explore-menu__list">
            {filtered.map((opt) => {
              const active = opt.value === value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  role="option"
                  aria-selected={active}
                  className={`explore-menu__item${active ? " is-active" : ""}`}
                  onClick={() => {
                    onChange(opt.value);
                    setOpen(false);
                  }}
                >
                  <span>{opt.label}</span>
                  {active ? <span className="explore-menu__dot" aria-hidden /> : null}
                </button>
              );
            })}
            {filtered.length === 0 ? <p className="explore-menu__empty muted-text">No matches</p> : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
