import { useEffect, useId, useRef, useState } from "react";
import { api } from "../../api";

export type OwnerUser = {
  id: number;
  username: string;
  email: string;
  display_name: string | null;
};

type Props = {
  value: number | null;
  onChange: (user: OwnerUser | null) => void;
  disabled?: boolean;
};

const OWNER_USERS_PATH = "/api/admin/api-keys/owner-users";
const MIN_SEARCH = 2;

export default function UserOwnerSelect({ value, onChange, disabled }: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [users, setUsers] = useState<OwnerUser[]>([]);
  const [selected, setSelected] = useState<OwnerUser | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!value) {
      setSelected(null);
      return;
    }
    if (selected?.id === value) return;
    api<OwnerUser[]>(`${OWNER_USERS_PATH}?user_id=${value}`)
      .then((rows) => {
        const hit = rows.find((u) => u.id === value);
        if (hit) setSelected(hit);
      })
      .catch(() => {});
  }, [value, selected?.id]);

  useEffect(() => {
    if (!open) return;
    const term = query.trim();
    const t = window.setTimeout(() => {
      setLoading(true);
      setLoadError("");
      const qs = new URLSearchParams();
      if (term.length >= MIN_SEARCH) qs.set("q", term);
      const suffix = qs.size ? `?${qs}` : "";
      api<OwnerUser[]>(`${OWNER_USERS_PATH}${suffix}`)
        .then(setUsers)
        .catch((err) => {
          setUsers([]);
          setLoadError(String(err));
        })
        .finally(() => setLoading(false));
    }, 200);
    return () => window.clearTimeout(t);
  }, [query, open]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  function pick(u: OwnerUser) {
    setSelected(u);
    onChange(u);
    setQuery("");
    setOpen(false);
  }

  function clearSelection() {
    setSelected(null);
    onChange(null);
    setQuery("");
  }

  const inputValue =
    open || !selected
      ? query
      : selected.display_name || selected.username || selected.email;

  const searching = query.trim().length >= MIN_SEARCH;

  const listboxId = useId();

  return (
    <div className="user-owner-select" ref={ref}>
      <input
        type="search"
        className="input-block user-owner-select__input"
        disabled={disabled}
        placeholder="Search name or email…"
        value={inputValue}
        onChange={(e) => {
          const next = e.target.value;
          if (selected && !open) clearSelection();
          setQuery(next);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        autoComplete="off"
        role="combobox"
        aria-controls={listboxId}
        aria-expanded={open}
        aria-autocomplete="list"
      />
      {open ? (
        <div className="user-owner-select__panel card">
          <ul className="user-owner-select__list" role="listbox" id={listboxId}>
            {loadError && <li className="muted-text user-owner-select__hint">{loadError}</li>}
            {!loadError && !searching && !loading && (
              <li className="muted-text user-owner-select__hint">
                Recent users — type {MIN_SEARCH}+ characters to narrow results
              </li>
            )}
            {loading && <li className="muted-text">Loading…</li>}
            {!loading && !loadError && searching && users.length === 0 && (
              <li className="muted-text">No users found</li>
            )}
            {!loading &&
              users.map((u) => (
                <li key={u.id}>
                  <button type="button" className="user-owner-select__item" onClick={() => pick(u)}>
                    <strong>{u.display_name || u.username}</strong>
                    <span className="muted-text">{u.email}</span>
                  </button>
                </li>
              ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
