import { useEffect, useRef, useState } from "react";
import { browserTimezoneName, formatTimezoneOffsetLabel } from "../../lib/activityTimezone";
import type { TimezoneMode } from "./types";

type Props = {
  value: TimezoneMode;
  onChange: (mode: TimezoneMode) => void;
};

/** Toolbar chip: browser offset by default; opens Local / UTC picker. */
export default function ActivityTimezoneChip({ value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const localLabel = formatTimezoneOffsetLabel();
  const tzName = browserTimezoneName();

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const chipLabel = value === "utc" ? "UTC" : localLabel;

  return (
    <div className="activity-timezone-chip" ref={ref}>
      <button
        type="button"
        className={`activity-timezone-chip__trigger${open ? " activity-timezone-chip__trigger--open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label={`Timezone: ${chipLabel}`}
        title={value === "local" ? tzName : "Coordinated Universal Time"}
      >
        <span>{chipLabel}</span>
      </button>
      {open ? (
        <div className="activity-timezone-chip__panel card" role="listbox">
          <button
            type="button"
            role="option"
            aria-selected={value === "local"}
            className={`activity-menu-item${value === "local" ? " activity-menu-item--active" : ""}`}
            onClick={() => {
              onChange("local");
              setOpen(false);
            }}
          >
            Browser local ({localLabel})
            {value === "local" ? " ✓" : ""}
          </button>
          <button
            type="button"
            role="option"
            aria-selected={value === "utc"}
            className={`activity-menu-item${value === "utc" ? " activity-menu-item--active" : ""}`}
            onClick={() => {
              onChange("utc");
              setOpen(false);
            }}
          >
            UTC
            {value === "utc" ? " ✓" : ""}
          </button>
        </div>
      ) : null}
    </div>
  );
}
