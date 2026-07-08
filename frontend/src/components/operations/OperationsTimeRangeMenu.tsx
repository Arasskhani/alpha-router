import { useEffect, useRef, useState } from "react";

export type OpsRangeKey =
  | "past_15m"
  | "past_30m"
  | "past_1h"
  | "past_3h"
  | "past_1d"
  | "past_2d"
  | "past_1w"
  | "past_1mo"
  | "past_1y"
  | "today"
  | "yesterday"
  | "this_week"
  | "prev_week";

export const DEFAULT_OPS_RANGE: OpsRangeKey = "past_1d";

const RELATIVE: { value: OpsRangeKey; label: string }[] = [
  { value: "past_15m", label: "Past 15 Minutes" },
  { value: "past_30m", label: "Past 30 Minutes" },
  { value: "past_1h", label: "Past 1 Hour" },
  { value: "past_3h", label: "Past 3 Hours" },
  { value: "past_1d", label: "Past 1 Day" },
  { value: "past_2d", label: "Past 2 Days" },
  { value: "past_1w", label: "Past 1 Week" },
  { value: "past_1mo", label: "Past 1 Month" },
  { value: "past_1y", label: "Past 1 Year" },
];

const PERIODS: { value: OpsRangeKey; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "yesterday", label: "Yesterday" },
  { value: "this_week", label: "This Week" },
  { value: "prev_week", label: "Prev Week" },
];

const META: Record<OpsRangeKey, { label: string; badge: string }> = {
  past_15m: { label: "Past 15 Minutes", badge: "15m" },
  past_30m: { label: "Past 30 Minutes", badge: "30m" },
  past_1h: { label: "Past 1 Hour", badge: "1h" },
  past_3h: { label: "Past 3 Hours", badge: "3h" },
  past_1d: { label: "Past 1 Day", badge: "1d" },
  past_2d: { label: "Past 2 Days", badge: "2d" },
  past_1w: { label: "Past 1 Week", badge: "1w" },
  past_1mo: { label: "Past 1 Month", badge: "1mo" },
  past_1y: { label: "Past 1 Year", badge: "1y" },
  today: { label: "Today", badge: "TD" },
  yesterday: { label: "Yesterday", badge: "YD" },
  this_week: { label: "This Week", badge: "TW" },
  prev_week: { label: "Prev Week", badge: "PW" },
};

export function parseOpsRangeKey(raw: string | null): OpsRangeKey {
  if (raw && raw in META) return raw as OpsRangeKey;
  return DEFAULT_OPS_RANGE;
}

type Props = {
  value: OpsRangeKey;
  onChange: (key: OpsRangeKey) => void;
  disabled?: boolean;
};

export default function OperationsTimeRangeMenu({ value, onChange, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const meta = META[value];

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  function pick(key: OpsRangeKey) {
    onChange(key);
    setOpen(false);
  }

  return (
    <div className="activity-period-menu operations-time-range-menu" ref={ref}>
      <button
        type="button"
        className={`activity-period-trigger${open ? " activity-period-trigger--open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="listbox"
        disabled={disabled}
        aria-label="Time range"
      >
        <span className="activity-period-trigger__badge">{meta.badge}</span>
        <span>{meta.label}</span>
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>
      {open ? (
        <div className="activity-period-panel card operations-time-range-panel" role="listbox">
          <p className="activity-menu-heading">Relative</p>
          {RELATIVE.map((item) => (
            <button
              key={item.value}
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
            {PERIODS.map((item) => (
              <button
                key={item.value}
                type="button"
                role="option"
                aria-selected={value === item.value}
                className={`activity-period-grid__btn${value === item.value ? " activity-period-grid__btn--active" : ""}`}
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
