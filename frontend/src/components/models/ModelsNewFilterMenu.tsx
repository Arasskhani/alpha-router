import { useEffect, useRef, useState } from "react";
import { MODEL_NEW_WINDOWS, type ModelNewFilter } from "../../lib/modelCatalog";

type Props = {
  value: ModelNewFilter | null;
  counts: Record<ModelNewFilter, number>;
  onChange: (days: ModelNewFilter | null) => void;
};

function windowLabel(days: ModelNewFilter): string {
  return days === 1 ? "Last 1 day" : `Last ${days} days`;
}

export default function ModelsNewFilterMenu({ value, counts, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
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

  function pick(days: ModelNewFilter) {
    onChange(value === days ? null : days);
    setOpen(false);
  }

  return (
    <div className="models-new-filter" ref={ref}>
      <button
        type="button"
        className={`models-filter-chip${value || open ? " models-filter-chip--active" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label="Filter by newly listed"
        title={value ? windowLabel(value) : "Filter models first listed in Alpha Router"}
      >
        <span>{value ? `New ${value}d` : "New"}</span>
        {value ? <span className="models-filter-chip__count">{counts[value]}</span> : null}
        <svg
          className="models-new-filter__chevron"
          viewBox="0 0 24 24"
          width={14}
          height={14}
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>
      {open ? (
        <div className="models-new-filter__menu card" role="listbox" aria-label="New model windows">
          {MODEL_NEW_WINDOWS.map((days) => {
            const selected = value === days;
            return (
              <button
                key={days}
                type="button"
                role="option"
                aria-selected={selected}
                className={`models-new-filter__item${selected ? " models-new-filter__item--active" : ""}`}
                onClick={() => pick(days)}
              >
                <span>{windowLabel(days)}</span>
                <span className="models-filter-chip__count">{counts[days]}</span>
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
