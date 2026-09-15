import { useEffect, useMemo, useRef, useState } from "react";
import ModelName from "../ModelName";
import { catalogMonthLabel } from "../../lib/chatModelPresets";

type PickerModel = {
  id: string;
  name?: string;
  external_id?: string;
};

type Props = {
  open: boolean;
  mode: "replace" | "append";
  models: PickerModel[];
  selectedIds: string[];
  defaultModelId?: string;
  onClose: () => void;
  onSelect: (modelId: string) => void;
  onSetDefault?: (modelId: string) => void;
};

/**
 * Centered model picker (Search / Add Model). Groups the list under a month label.
 */
export default function ChatModelPickerModal({
  open,
  mode,
  models,
  selectedIds,
  defaultModelId,
  onClose,
  onSelect,
  onSetDefault,
}: Props) {
  const [query, setQuery] = useState("");
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const month = catalogMonthLabel();

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return models;
    return models.filter((m) => {
      const name = (m.name || m.external_id || m.id || "").toLowerCase();
      const id = (m.id || "").toLowerCase();
      const ext = (m.external_id || "").toLowerCase();
      return name.includes(q) || id.includes(q) || ext.includes(q);
    });
  }, [models, query]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setHighlight(0);
    const t = window.setTimeout(() => inputRef.current?.focus(), 30);
    return () => window.clearTimeout(t);
  }, [open]);

  useEffect(() => {
    setHighlight(0);
  }, [query]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlight((h) => Math.min(h + 1, Math.max(filtered.length - 1, 0)));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlight((h) => Math.max(h - 1, 0));
      } else if (e.key === "Enter") {
        const m = filtered[highlight];
        if (m) {
          e.preventDefault();
          onSelect(m.id);
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, filtered, highlight, onClose, onSelect]);

  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-idx="${highlight}"]`);
    if (el instanceof HTMLElement) el.scrollIntoView({ block: "nearest" });
  }, [highlight]);

  if (!open) return null;

  const title = mode === "append" ? "Add model" : "Select model";

  return (
    <div className="alpha-router-model-modal-backdrop" onMouseDown={onClose} role="presentation">
      <div
        className="alpha-router-model-modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="alpha-router-model-modal__search">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-3.5-3.5" strokeLinecap="round" />
          </svg>
          <input
            ref={inputRef}
            type="search"
            placeholder="Search Models"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search models"
          />
          <kbd className="alpha-router-kbd">esc</kbd>
        </div>

        <div className="alpha-router-model-modal__month">{month}</div>

        <ul className="alpha-router-model-modal__list" ref={listRef} role="listbox">
          {filtered.length === 0 ? (
            <li className="alpha-router-model-modal__empty">No models match</li>
          ) : (
            filtered.map((m, idx) => {
              const selected = selectedIds.includes(m.id);
              const active = idx === highlight;
              return (
                <li key={m.id} data-idx={idx} role="option" aria-selected={selected || active}>
                  <button
                    type="button"
                    className={`alpha-router-model-modal__item${active ? " is-active" : ""}${selected ? " is-selected" : ""}`}
                    onMouseEnter={() => setHighlight(idx)}
                    onClick={() => onSelect(m.id)}
                    title={m.name || m.external_id || m.id}
                  >
                    <ModelName
                      modelId={m.external_id || m.id}
                      label={m.name || m.external_id || m.id}
                      size={16}
                    />
                  </button>
                  {onSetDefault && mode === "replace" ? (
                    <button
                      type="button"
                      className={`alpha-router-model-default${defaultModelId === m.id ? " is-default" : ""}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        onSetDefault(m.id);
                      }}
                      aria-label={
                        defaultModelId === m.id
                          ? `${m.name || m.id} is default model`
                          : `Set ${m.name || m.id} as default model`
                      }
                      title={defaultModelId === m.id ? "Default model" : "Set as default for new chats"}
                    >
                      ✓
                    </button>
                  ) : null}
                </li>
              );
            })
          )}
        </ul>

        <footer className="alpha-router-model-modal__footer">
          <span>↑ ↓ Navigate</span>
          <span>↵ Select</span>
          <span className="alpha-router-model-modal__count">{filtered.length} models</span>
        </footer>
      </div>
    </div>
  );
}
