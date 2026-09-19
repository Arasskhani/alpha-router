import { useEffect, useMemo, useState } from "react";

import { api } from "../../api";

export type ConnectionOption = {
  id: number;
  name: string;
  provider_type: string;
  is_active: boolean;
};

type Props = {
  selectedIds: number[];
  onChange: (ids: number[]) => void;
  disabled?: boolean;
};

export default function ConnectionAllowlistField({ selectedIds, onChange, disabled }: Props) {
  const [items, setItems] = useState<ConnectionOption[]>([]);
  const [err, setErr] = useState("");
  const [query, setQuery] = useState("");

  useEffect(() => {
    let cancelled = false;
    api<{ items: ConnectionOption[] }>("/api/admin/api-keys/connection-options")
      .then((res) => {
        if (!cancelled) setItems(res.items || []);
      })
      .catch((e) => {
        if (!cancelled) setErr(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selected = useMemo(() => new Set(selectedIds), [selectedIds]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        (c.provider_type || "").toLowerCase().includes(q),
    );
  }, [items, query]);

  function toggle(id: number) {
    if (selected.has(id)) onChange(selectedIds.filter((x) => x !== id));
    else onChange([...selectedIds, id]);
  }

  if (err) {
    return <p className="alert alert-error" role="alert">{err}</p>;
  }

  return (
    <div className="api-key-conn-picker">
      {items.length > 6 ? (
        <input
          type="search"
          className="input-block"
          placeholder="Search connections…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={disabled}
        />
      ) : null}
      <div className="api-key-conn-picker__list" role="group" aria-label="Allowed connections">
        {filtered.length === 0 ? (
          <p className="muted-text api-key-form__hint">
            {items.length === 0 ? "No connections configured yet." : "No connections match this search."}
          </p>
        ) : (
          filtered.map((c) => (
            <label key={c.id} className={`api-key-conn-picker__option${c.is_active ? "" : " is-inactive"}`}>
              <input
                type="checkbox"
                checked={selected.has(c.id)}
                onChange={() => toggle(c.id)}
                disabled={disabled}
              />
              <span>
                {c.name}
                <span className="muted-text"> · {c.provider_type}</span>
                {!c.is_active ? <span className="muted-text"> · inactive</span> : null}
              </span>
            </label>
          ))
        )}
      </div>
      {selectedIds.length === 0 ? (
        <span className="muted-text api-key-form__hint">
          No connections selected — this key cannot call any model until you add at least one.
        </span>
      ) : null}
    </div>
  );
}
