import { useEffect, useRef, useState } from "react";
import { groupByLabel } from "./formatters";
import type { GroupBy } from "./types";

const OPTIONS: { value: GroupBy; label: string }[] = [
  { value: "model", label: "By Model" },
  { value: "user", label: "By Creator" },
  { value: "app", label: "By API Key" },
];

type Props = {
  value: GroupBy;
  onChange: (groupBy: GroupBy) => void;
};

export default function ActivityGroupByMenu({ value, onChange }: Props) {
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

  return (
    <div className="activity-period-menu" ref={ref}>
      <button
        type="button"
        className={`activity-period-trigger${open ? " activity-period-trigger--open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <span>{groupByLabel(value)}</span>
      </button>
      {open ? (
        <div className="activity-period-panel activity-period-panel--narrow card" role="listbox">
          {OPTIONS.map((item) => (
            <button
              key={item.value}
              type="button"
              role="option"
              aria-selected={value === item.value}
              className={`activity-menu-item${value === item.value ? " activity-menu-item--active" : ""}`}
              onClick={() => {
                onChange(item.value);
                setOpen(false);
              }}
            >
              {item.label}
              {value === item.value ? " ✓" : ""}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
