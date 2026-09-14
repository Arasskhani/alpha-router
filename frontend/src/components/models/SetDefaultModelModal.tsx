import { useEffect, useMemo, useRef, useState } from "react";

import Modal from "../Modal";
import ModelName from "../ModelName";
import type { CatalogModel } from "../../lib/modelCatalog";

type DefaultKindKey = "chat" | "voice" | "image" | "video";

export type DefaultKind = {
  key: DefaultKindKey;
  label: string;
  /** Catalog tag a model must carry to appear in this picker. */
  catalog_kind: string;
  requirement: string;
};

type Props = {
  kind: DefaultKind | null;
  models: CatalogModel[];
  currentId: number | null;
  busy: boolean;
  onClose: () => void;
  onPick: (modelId: number | null) => void;
};

/**
 * Pick the system default model for one capability.
 *
 * The list is pre-filtered to that capability, so every row shown is a valid
 * choice — there is no way to select something the server will reject.
 */
export default function SetDefaultModelModal({
  kind,
  models,
  currentId,
  busy,
  onClose,
  onPick,
}: Props) {
  const [search, setSearch] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!kind) return;
    setSearch("");
    const id = window.setTimeout(() => searchRef.current?.focus(), 0);
    return () => window.clearTimeout(id);
  }, [kind]);

  const eligible = useMemo(() => {
    if (!kind) return [];
    return models
      .filter(
        (m) =>
          (m.kinds || []).some((k) => k === kind.catalog_kind) &&
          m.enabled &&
          !m.admin_disabled &&
          (m.access_type || "public") === "public",
      )
      .sort((a, b) =>
        (a.display_name || a.external_id).localeCompare(b.display_name || b.external_id),
      );
  }, [models, kind]);

  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return eligible;
    return eligible.filter((m) =>
      `${m.external_id} ${m.display_name || ""}`.toLowerCase().includes(q),
    );
  }, [eligible, search]);

  if (!kind) return null;

  return (
    <Modal
      open
      title={`Set ${kind.label} Default`}
      onClose={onClose}
      panelClassName="set-default-modal"
    >
      <p className="muted-text set-default-modal__intro">
        Used for {kind.label.toLowerCase()} when a user has not chosen their own.
        Only public, enabled models that satisfy “{kind.requirement.toLowerCase()}”
        are listed.
      </p>

      <input
        ref={searchRef}
        className="set-default-modal__search"
        placeholder={`Search ${kind.label.toLowerCase()} models…`}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        aria-label={`Search ${kind.label} models`}
      />

      {eligible.length === 0 ? (
        <p className="alert alert-warning set-default-modal__empty">
          No {kind.label.toLowerCase()} model in the catalog yet. Sync a connection
          that offers one, then make it public and enabled.
        </p>
      ) : (
        <>
          <div className="set-default-modal__list" role="listbox" aria-label={`${kind.label} models`}>
            {shown.map((m) => {
              const selected = currentId !== null && m.id === currentId;
              return (
                <button
                  key={m.id}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  disabled={busy}
                  className={`set-default-modal__row${selected ? " set-default-modal__row--current" : ""}`}
                  onClick={() => onPick(selected ? null : m.id)}
                >
                  <span className="set-default-modal__row-name">
                    <ModelName modelId={m.external_id} label={m.display_name || m.external_id} size={16} />
                  </span>
                  <span className="set-default-modal__row-id">{m.external_id}</span>
                  {selected ? (
                    <span className="set-default-modal__row-badge">Current — click to clear</span>
                  ) : null}
                </button>
              );
            })}
            {shown.length === 0 ? (
              <p className="muted-text set-default-modal__empty">No model matches “{search.trim()}”.</p>
            ) : null}
          </div>
          <div className="set-default-modal__footer">
            <span className="muted-text">
              {shown.length} of {eligible.length} shown
            </span>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={busy || currentId === null}
              onClick={() => onPick(null)}
              title="Fall back to automatic selection"
            >
              Clear default
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}
