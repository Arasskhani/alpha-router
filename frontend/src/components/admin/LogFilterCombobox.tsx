import { useEffect, useMemo, useRef, useState } from "react";

type Props = {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  placeholder: string;
  loading?: boolean;
  disabled?: boolean;
  id?: string;
  onOpen?: () => void;
};

export default function LogFilterCombobox({
  value,
  onChange,
  options,
  placeholder,
  loading = false,
  disabled,
  id,
  onOpen,
}: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState(value);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) setQuery(value);
  }, [value, open]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options.slice(0, 80);
    return options.filter((o) => o.toLowerCase().includes(q)).slice(0, 80);
  }, [options, query]);

  function pick(option: string) {
    onChange(option);
    setQuery(option);
    setOpen(false);
  }

  return (
    <div className="log-filter-combobox" ref={ref}>
      <input
        id={id}
        type="search"
        placeholder={placeholder}
        value={open ? query : value}
        disabled={disabled}
        autoComplete="off"
        aria-expanded={open}
        aria-autocomplete="list"
        onFocus={() => {
          onOpen?.();
          setOpen(true);
        }}
        onChange={(e) => {
          setQuery(e.target.value);
          onChange(e.target.value);
          setOpen(true);
        }}
      />
      {open ? (
        <div className="log-filter-combobox__panel card" role="listbox">
          {loading ? <p className="muted-text log-filter-combobox__hint">Loading…</p> : null}
          {!loading && options.length === 0 ? (
            <p className="muted-text log-filter-combobox__hint">No values in current logs</p>
          ) : null}
          {!loading && options.length > 0 && filtered.length === 0 ? (
            <p className="muted-text log-filter-combobox__hint">No matches</p>
          ) : null}
          <ul className="log-filter-combobox__list">
            {filtered.map((option) => (
              <li key={option}>
                <button
                  type="button"
                  className={`log-filter-combobox__item${option === value ? " log-filter-combobox__item--active" : ""}`}
                  onClick={() => pick(option)}
                >
                  {option}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
