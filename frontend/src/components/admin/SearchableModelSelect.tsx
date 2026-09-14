import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";

export type SearchableModelOption = {
  value: string;
  label: string;
};

export function filterModelOptions(
  options: SearchableModelOption[],
  query: string,
  limit = 80,
): SearchableModelOption[] {
  const q = query.trim().toLowerCase();
  const matched = q
    ? options.filter((option) => {
        const hay = `${option.label} ${option.value}`.toLowerCase();
        return hay.includes(q);
      })
    : options;
  return matched.slice(0, limit);
}

type Props = {
  value: string;
  options: SearchableModelOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
  placeholder?: string;
  emptyLabel?: string;
  allowEmpty?: boolean;
  ariaLabel?: string;
  id?: string;
};

export default function SearchableModelSelect({
  value,
  options,
  onChange,
  disabled,
  placeholder = "Search models…",
  emptyLabel = "Not configured",
  allowEmpty = true,
  ariaLabel,
  id,
}: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const selected = options.find((option) => option.value === value);
  const closedLabel = selected?.label || (value ? value : emptyLabel);

  const filtered = useMemo(() => {
    const rows = filterModelOptions(options, query);
    if (allowEmpty && !query.trim()) {
      return [{ value: "", label: emptyLabel }, ...rows];
    }
    if (allowEmpty && emptyLabel.toLowerCase().includes(query.trim().toLowerCase())) {
      return [{ value: "", label: emptyLabel }, ...rows];
    }
    return rows;
  }, [allowEmpty, emptyLabel, options, query]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  useEffect(() => {
    setActive(0);
  }, [query, open]);

  function pick(next: string) {
    onChange(next);
    setOpen(false);
    setQuery("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      setQuery("");
      inputRef.current?.blur();
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(i + 1, Math.max(filtered.length - 1, 0)));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const row = filtered[active] || filtered[0];
      if (row) pick(row.value);
    }
  }

  const listboxId = useId();

  return (
    <div className="admin-model-combobox" ref={rootRef}>
      <input
        ref={inputRef}
        id={id}
        type="search"
        className="admin-model-combobox__input"
        value={open ? query : closedLabel}
        placeholder={placeholder}
        disabled={disabled}
        autoComplete="off"
        role="combobox"
        aria-label={ariaLabel}
        aria-controls={listboxId}
        aria-expanded={open}
        aria-autocomplete="list"
        onFocus={() => {
          if (disabled) return;
          setOpen(true);
          setQuery("");
        }}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onKeyDown={onKeyDown}
      />
      {open && !disabled ? (
        <div className="admin-model-combobox__panel card" role="listbox" id={listboxId}>
          {filtered.length === 0 ? (
            <p className="muted-text admin-model-combobox__hint">No matches</p>
          ) : (
            <ul className="admin-model-combobox__list">
              {filtered.map((option, index) => (
                <li key={`${option.value || "empty"}:${option.label}`}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={option.value === value}
                    className={`admin-model-combobox__item${
                      index === active ? " admin-model-combobox__item--active" : ""
                    }${option.value === value ? " admin-model-combobox__item--selected" : ""}`}
                    onMouseDown={(event) => event.preventDefault()}
                    onMouseEnter={() => setActive(index)}
                    onClick={() => pick(option.value)}
                  >
                    {option.label}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
