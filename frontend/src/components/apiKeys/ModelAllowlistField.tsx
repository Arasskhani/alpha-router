import { useEffect, useMemo, useState } from "react";

import { api } from "../../api";

export type ModelOption = {
  id: number;
  external_id: string;
  display_name: string;
  connection_id: number;
  connection_name: string | null;
  provider_type: string;
  is_enabled: boolean;
};

type Props = {
  ownerUserId: number;
  connectionIds: number[];
  restrictConnections: boolean;
  selectedIds: number[];
  onChange: (ids: number[]) => void;
  disabled?: boolean;
};

function modelLabel(m: ModelOption) {
  const base = m.display_name || m.external_id;
  return m.connection_name ? `${base} · ${m.connection_name}` : base;
}

export default function ModelAllowlistField({
  ownerUserId,
  connectionIds,
  restrictConnections,
  selectedIds,
  onChange,
  disabled,
}: Props) {
  const [items, setItems] = useState<ModelOption[]>([]);
  const [err, setErr] = useState("");
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!ownerUserId) {
      setItems([]);
      return;
    }
    let cancelled = false;
    const qs = new URLSearchParams();
    qs.set("owner_user_id", String(ownerUserId));
    if (restrictConnections) {
      for (const id of connectionIds) qs.append("connection_id", String(id));
    }
    api<{ items: ModelOption[] }>(`/api/admin/api-keys/model-options?${qs}`)
      .then((res) => {
        if (cancelled) return;
        const next = res.items || [];
        setItems(next);
        const allowed = new Set(next.map((m) => m.id));
        const pruned = selectedIds.filter((id) => allowed.has(id));
        if (pruned.length !== selectedIds.length) onChange(pruned);
      })
      .catch((e) => {
        if (!cancelled) setErr(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [ownerUserId, restrictConnections, connectionIds.join(",")]);

  const selected = useMemo(() => new Set(selectedIds), [selectedIds]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((m) => {
      const hay = `${m.display_name} ${m.external_id} ${m.connection_name || ""} ${m.provider_type}`.toLowerCase();
      return hay.includes(q);
    });
  }, [items, query]);

  function toggle(id: number) {
    if (selected.has(id)) onChange(selectedIds.filter((x) => x !== id));
    else onChange([...selectedIds, id]);
  }

  if (!ownerUserId) {
    return (
      <span className="muted-text api-key-form__hint">Select an owner first to pick allowed models.</span>
    );
  }

  if (err) {
    return <p className="alert alert-error">{err}</p>;
  }

  return (
    <div className="api-key-conn-picker">
      {items.length > 8 ? (
        <input
          type="search"
          className="input-block"
          placeholder="Search models…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={disabled}
        />
      ) : null}
      <div className="api-key-conn-picker__list" role="group" aria-label="Allowed models">
        {filtered.length === 0 ? (
          <p className="muted-text api-key-form__hint">
            {items.length === 0
              ? restrictConnections && connectionIds.length === 0
                ? "Select at least one connection or disable connection restriction."
                : "No enabled models available for this owner."
              : "No models match this search."}
          </p>
        ) : (
          filtered.map((m) => (
            <label key={m.id} className="api-key-conn-picker__option">
              <input
                type="checkbox"
                checked={selected.has(m.id)}
                onChange={() => toggle(m.id)}
                disabled={disabled}
              />
              <span>
                {modelLabel(m)}
                <span className="muted-text"> · {m.provider_type}</span>
              </span>
            </label>
          ))
        )}
      </div>
      {selectedIds.length === 0 ? (
        <span className="muted-text api-key-form__hint">
          No models selected — this key cannot call any model until you add at least one.
        </span>
      ) : null}
    </div>
  );
}
