import { useEffect, useRef, useState } from "react";
import { periodLabel, periodShortBadge } from "./formatters";
import type { Period as PeriodType } from "./types";

const RELATIVE: { value: PeriodType; label: string }[] = [
  { value: "15m", label: "Past 15 Minutes" },
  { value: "30m", label: "Past 30 Minutes" },
  { value: "1h", label: "Past 1 Hour" },
  { value: "3h", label: "Past 3 Hours" },
  { value: "day", label: "Past 1 Day" },
  { value: "2d", label: "Past 2 Days" },
  { value: "week", label: "Past 1 Week" },
  { value: "month", label: "Past 1 Month" },
  { value: "year", label: "Past 1 Year" },
];

const CALENDAR: { value: PeriodType; label: string }[] = [
  { value: "day", label: "Today" },
  { value: "day", label: "Yesterday" },
  { value: "week", label: "This Week" },
  { value: "week", label: "Prev Week" },
  { value: "month", label: "This Month" },
  { value: "month", label: "Prev Month" },
  { value: "year", label: "This Year" },
  { value: "year", label: "Prev Year" },
];

type Props = {
  value: PeriodType;
  onChange: (period: PeriodType) => void;
};

export function parseActivityPeriod(raw: string | null): PeriodType {
  const allowed = new Set(RELATIVE.map((r) => r.value));
  if (raw && allowed.has(raw as PeriodType)) return raw as PeriodType;
  return "day";
}

export default function ActivityPeriodMenu({ value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  function pick(p: PeriodType) {
    onChange(p);
    setOpen(false);
  }

  return (
    <div className="activity-period-menu" ref={ref}>
      <button
        type="button"
        className={`activity-period-trigger${open ? " activity-period-trigger--open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <span className="activity-period-trigger__badge">{periodShortBadge(value)}</span>
        <span>{periodLabel(value)}</span>
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>
      {open ? (
        <div className="activity-period-panel card" role="listbox">
          <p className="activity-menu-heading">Relative</p>
          {RELATIVE.map((item) => (
            <button
              key={item.label}
              type="button"
              role="option"
              aria-selected={value === item.value}
              className={`activity-menu-item${value === item.value ? " activity-menu-item--active" : ""}`}
              onClick={() => pick(item.value)}
            >
              {item.label}
              {value === item.value ? " ✓" : ""}
            </button>
          ))}
          <p className="activity-menu-heading">Periods</p>
          <div className="activity-period-grid">
            {CALENDAR.map((item) => (
              <button
                key={item.label}
                type="button"
                className="activity-period-grid__btn"
                onClick={() => pick(item.value)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
