import { useEffect, useMemo, useRef, useState } from "react";

import AdminPage from "../../components/AdminPage";
import Modal from "../../components/Modal";
import ModelName from "../../components/ModelName";
import ModelsFilterBar from "../../components/models/ModelsFilterBar";
import ModelsNewFilterMenu from "../../components/models/ModelsNewFilterMenu";
import ModelsBrowseView from "../../components/models/ModelsBrowseView";
import ModelAccessModal from "../../components/models/ModelAccessModal";
import ModelCodeInterpreterModal from "../../components/models/ModelCodeInterpreterModal";
import SetDefaultModelModal, {
  type DefaultKind,
} from "../../components/models/SetDefaultModelModal";
import { api } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";
import { useDebounced } from "../../hooks/useDebounced";
import { BROWSER_EVENT_NAMES, STORAGE_KEYS } from "../../lib/brand";
import {
  accessCounts,
  accessTypeLabel,
  codeInterpreterButtonClass,
  codeInterpreterLabel,
  enabledCounts,
  filterCatalogModels,
  newWindowCounts,
  type CatalogModel,
  type ModelAccessFilter,
  type ModelEnabledFilter,
  type ModelKind,
  type ModelNewFilter,
} from "../../lib/modelCatalog";

type ViewMode = "table" | "browse";
type BulkAction = "on" | "off" | "delete" | "public" | "private";

function loadViewMode(): ViewMode {
  try {
    const v = localStorage.getItem(STORAGE_KEYS.modelsView);
    if (v === "browse" || v === "tile") return "browse";
    if (v === "table" || v === "list") return "table";
    return "browse";
  } catch {
    return "browse";
  }
}

export default function Models() {
  const { confirm } = useConfirm();
  const [allModels, setAllModels] = useState<CatalogModel[]>([]);
  const [search, setSearch] = useState("");
  const [activeKind, setActiveKind] = useState<ModelKind | null>(null);
  const [enabledFilter, setEnabledFilter] = useState<ModelEnabledFilter | null>(null);
  const [accessFilter, setAccessFilter] = useState<ModelAccessFilter | null>(null);
  const [newFilter, setNewFilter] = useState<ModelNewFilter | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>(loadViewMode);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [accessModelId, setAccessModelId] = useState<number | null>(null);
  const [compatModelId, setCompatModelId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");
  const [defaultKinds, setDefaultKinds] = useState<DefaultKind[]>([]);
  const [systemDefaults, setSystemDefaults] = useState<Record<string, number | null>>({});
  const [defaultMenuOpen, setDefaultMenuOpen] = useState(false);
  const [defaultKind, setDefaultKind] = useState<DefaultKind | null>(null);
  const [defaultBusy, setDefaultBusy] = useState(false);
  const defaultMenuRef = useRef<HTMLDivElement>(null);
  const debouncedSearch = useDebounced(search, 280);

  async function loadModels() {
    return api<CatalogModel[]>("/api/admin/models", { cache: "no-store" });
  }

  async function loadSystemDefaults() {
    const data = await api<{
      defaults: Record<string, number | null>;
      kinds: DefaultKind[];
    }>("/api/admin/models/defaults", { cache: "no-store" });
    setSystemDefaults(data.defaults || {});
    setDefaultKinds(data.kinds || []);
  }

  async function pickSystemDefault(modelId: number | null) {
    if (!defaultKind) return;
    const kind = defaultKind;
    setDefaultBusy(true);
    setMsg("");
    try {
      await api(`/api/admin/models/defaults/${kind.key}`, {
        method: "PUT",
        body: JSON.stringify({ model_id: modelId }),
      });
      const label =
        modelId === null
          ? `${kind.label} default cleared — falling back to automatic selection.`
          : `${kind.label} default set. Users who picked their own are not changed.`;
      setMsg(label);
      setDefaultKind(null);
      await loadSystemDefaults();
      setAllModels(await loadModels());
    } catch (e) {
      setMsg(String(e));
    } finally {
      setDefaultBusy(false);
    }
  }

  const models = useMemo(
    () =>
      filterCatalogModels(
        allModels,
        debouncedSearch,
        activeKind,
        enabledFilter,
        accessFilter,
        newFilter,
      ),
    [allModels, debouncedSearch, activeKind, enabledFilter, accessFilter, newFilter],
  );
  const statusCounts = useMemo(() => enabledCounts(allModels), [allModels]);
  const accessFilterCounts = useMemo(() => accessCounts(allModels), [allModels]);
  const newFilterCounts = useMemo(() => newWindowCounts(allModels), [allModels]);
  const accessModel = allModels.find((m) => m.id === accessModelId) || null;
  const compatModel = allModels.find((m) => m.id === compatModelId) || null;
  useEffect(() => {
    if (!defaultMenuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (!defaultMenuRef.current?.contains(e.target as Node)) setDefaultMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDefaultMenuOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [defaultMenuOpen]);

  useEffect(() => {
    loadModels().then(setAllModels).catch(() => setAllModels([]));
    setSelectedIds([]);
    loadSystemDefaults().catch(() => {
      setSystemDefaults({});
      setDefaultKinds([]);
    });
  }, []);

  useEffect(() => {
    const onSyncFlash = async () => {
      setAllModels((prev) => (prev.length ? prev.map((m) => ({ ...m, enabled: false })) : prev));
      await new Promise((r) => window.setTimeout(r, 140));
      try {
        setAllModels(await loadModels());
      } catch {
        setAllModels([]);
      }
      setSelectedIds([]);
    };
    window.addEventListener(BROWSER_EVENT_NAMES.modelsSyncFlash, onSyncFlash);
    return () => window.removeEventListener(BROWSER_EVENT_NAMES.modelsSyncFlash, onSyncFlash);
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEYS.modelsView, viewMode);
    } catch {
      /* ignore */
    }
  }, [viewMode]);

  const visibleIds = useMemo(() => models.map((m) => m.id), [models]);
  const allVisibleSelected =
    visibleIds.length > 0 && visibleIds.every((id) => selectedIds.includes(id));

  function toggleSelectAllVisible() {
    if (allVisibleSelected) {
      setSelectedIds((prev) => prev.filter((id) => !visibleIds.includes(id)));
    } else {
      setSelectedIds((prev) => [...new Set([...prev, ...visibleIds])]);
    }
  }

  function toggleRowSelection(id: number) {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  async function toggle(id: number, enabled: boolean) {
    await api(`/api/admin/models/${id}/toggle?enabled=${!enabled}`, { method: "PATCH" });
    setAllModels(await loadModels());
  }


  async function runBulk(action: BulkAction) {
    if (!selectedIds.length) return;
    if (action === "delete") {
      const ok = await confirm({
        title: "Delete models",
        message: `Delete ${selectedIds.length} selected model(s) from the catalog?`,
        confirmLabel: "Delete",
        danger: true,
      });
      if (!ok) return;
    }
    if (action === "public") {
      const ok = await confirm({
        title: "Set Public",
        message: `Set ${selectedIds.length} model(s) to Public and clear private assignments?`,
        confirmLabel: "Set Public",
      });
      if (!ok) return;
    }
    setBulkBusy(true);
    setMsg("");
    try {
      const r = await api<{ count: number }>(`/api/admin/models/bulk?action=${action}`, {
        method: "POST",
        body: JSON.stringify({ ids: selectedIds }),
      });
      const labels: Record<BulkAction, string> = {
        on: `Turned on ${r.count} model(s).`,
        off: `Turned off ${r.count} model(s).`,
        delete: `Deleted ${r.count} model(s).`,
        public: `Set ${r.count} model(s) to Public.`,
        private: `Set ${r.count} model(s) to Private.`,
      };
      setMsg(labels[action]);
      setBulkOpen(false);
      setSelectedIds([]);
      setAllModels(await loadModels());
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBulkBusy(false);
    }
  }

  return (
    <AdminPage title="Models">
      <div className="models-page">
        <div className="models-page__toolbar">
          <div className="models-page__search-wrap">
            <svg className="models-page__search-icon" viewBox="0 0 24 24" width={18} height={18} aria-hidden>
              <path
                fill="currentColor"
                d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C8.01 14 6 11.99 6 9.5S8.01 5 9.5 5 13 7.01 13 9.5 10.99 14 9.5 14z"
              />
            </svg>
            <input
              className="models-page__search"
              placeholder="Search models…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="models-page__actions">
            <div className="models-status-filter" role="group" aria-label="Filter by status">
              {(
                [
                  { key: "on" as const, label: "ON" },
                  { key: "off" as const, label: "OFF" },
                ] as const
              ).map(({ key, label }) => {
                const selected = enabledFilter === key;
                return (
                  <button
                    key={key}
                    type="button"
                    className={`models-filter-chip${selected ? " models-filter-chip--active" : ""}`}
                    onClick={() => setEnabledFilter(selected ? null : key)}
                    aria-pressed={selected}
                  >
                    <span>{label}</span>
                    <span className="models-filter-chip__count">{statusCounts[key]}</span>
                  </button>
                );
              })}
            </div>
            <div className="models-status-filter" role="group" aria-label="Filter by access">
              {(
                [
                  { key: "public" as const, label: "Public" },
                  { key: "private" as const, label: "Private" },
                ] as const
              ).map(({ key, label }) => {
                const selected = accessFilter === key;
                return (
                  <button
                    key={key}
                    type="button"
                    className={`models-filter-chip${selected ? " models-filter-chip--active" : ""}`}
                    onClick={() => setAccessFilter(selected ? null : key)}
                    aria-pressed={selected}
                  >
                    <span>{label}</span>
                    <span className="models-filter-chip__count">{accessFilterCounts[key]}</span>
                  </button>
                );
              })}
            </div>
            <ModelsNewFilterMenu
              value={newFilter}
              counts={newFilterCounts}
              onChange={setNewFilter}
            />
            <div className="models-default-menu" ref={defaultMenuRef}>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setDefaultMenuOpen((o) => !o)}
                aria-expanded={defaultMenuOpen}
                aria-haspopup="menu"
                title="Choose the system default model for a capability"
              >
                Set as Default ▾
              </button>
              {defaultMenuOpen ? (
                <div className="models-default-menu__list" role="menu">
                  {defaultKinds.map((k) => {
                    const currentId = systemDefaults[k.key] ?? null;
                    const current = currentId
                      ? allModels.find((m) => m.id === currentId)
                      : null;
                    return (
                      <button
                        key={k.key}
                        type="button"
                        role="menuitem"
                        className="models-default-menu__item"
                        onClick={() => {
                          setDefaultMenuOpen(false);
                          setDefaultKind(k);
                        }}
                      >
                        <span className="models-default-menu__item-label">{k.label}</span>
                        <span className="models-default-menu__item-current">
                          {current ? current.display_name || current.external_id : "Automatic"}
                        </span>
                      </button>
                    );
                  })}
                </div>
              ) : null}
            </div>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={selectedIds.length === 0}
              onClick={() => setBulkOpen(true)}
              title={selectedIds.length ? `${selectedIds.length} selected` : "Select models first"}
            >
              Bulk Edit
            </button>
            <div className="models-view-toggle" role="group" aria-label="View mode">
              <button
                type="button"
                className={`models-view-toggle__btn${viewMode === "browse" ? " models-view-toggle__btn--active" : ""}`}
                onClick={() => setViewMode("browse")}
                title="Browse view"
                aria-pressed={viewMode === "browse"}
              >
                <svg viewBox="0 0 24 24" width={18} height={18} aria-hidden>
                  <path
                    fill="currentColor"
                    d="M4 5h16v3H4V5zm0 5h16v3H4v-3zm0 5h10v3H4v-3z"
                  />
                </svg>
              </button>
              <button
                type="button"
                className={`models-view-toggle__btn${viewMode === "table" ? " models-view-toggle__btn--active" : ""}`}
                onClick={() => setViewMode("table")}
                title="Table view"
                aria-pressed={viewMode === "table"}
              >
                <svg viewBox="0 0 24 24" width={18} height={18} aria-hidden>
                  <path fill="currentColor" d="M3 5h18v2H3V5zm0 6h18v2H3v-2zm0 6h18v2H3v-2z" />
                </svg>
              </button>
            </div>
          </div>
        </div>

        <ModelsFilterBar models={allModels} active={activeKind} onChange={setActiveKind} />

        <p className="muted-text models-page__hint">
          Pricing per 1K tokens from provider (read-only). Descriptions load from provider catalog after sync.
        </p>
        {msg && <p className="alert alert-success">{msg}</p>}

        <p style={{ color: "var(--muted)", fontSize: "0.85rem" }}>
          {models.length} model(s) shown
          {allModels.length !== models.length ? ` · ${allModels.length} total` : ""}
          {selectedIds.length > 0 ? ` · ${selectedIds.length} selected` : ""}
        </p>

        {viewMode === "browse" ? (
          <ModelsBrowseView
            models={models}
            selectedIds={selectedIds}
            onToggleSelect={toggleRowSelection}
            onToggleEnabled={toggle}
            onEditAccess={(id) => setAccessModelId(id)}
          />
        ) : (
          <div className="table-wrap">
            <table className="card data-table">
              <thead>
                <tr>
                  <th className="col-sm">
                    <input
                      type="checkbox"
                      checked={allVisibleSelected}
                      onChange={toggleSelectAllVisible}
                      aria-label="Select all visible models"
                    />
                  </th>
                  <th>Model</th>
                  <th>Input / 1K</th>
                  <th>Output / 1K</th>
                  <th>Total / 1K</th>
                  <th>Access Type</th>
                  <th>Code Interpreter</th>
                  <th className="col-onoff">ON/OFF</th>
                </tr>
              </thead>
              <tbody>
                {models.map((m) => (
                  <tr key={m.id}>
                    <td className="col-sm">
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(m.id)}
                        onChange={() => toggleRowSelection(m.id)}
                        aria-label={`Select ${m.external_id}`}
                      />
                    </td>
                    <td>
                      <ModelName modelId={m.external_id} label={m.external_id} size={15} />
                    </td>
                    <td>{m.input_cost_per_1k ?? "—"}</td>
                    <td>{m.output_cost_per_1k ?? "—"}</td>
                    <td>{m.total_cost_per_1k}</td>
                    <td>
                      <button
                        type="button"
                        className={`btn btn-sm btn-ghost model-access-btn${
                          (m.access_type || "public") === "private" ? " model-access-btn--private" : ""
                        }`}
                        onClick={() => setAccessModelId(m.id)}
                      >
                        {accessTypeLabel(m)}
                      </button>
                    </td>
                    <td>
                      <button
                        type="button"
                        className={`btn btn-sm btn-ghost${codeInterpreterButtonClass(m)}`}
                        onClick={() => setCompatModelId(m.id)}
                        title={
                          m.code_interpreter?.reason_detail ||
                          "Code Interpreter compatibility and probe history"
                        }
                      >
                        {codeInterpreterLabel(m)}
                      </button>
                    </td>
                    <td className="col-onoff">
                      <div className="model-onoff-cell">
                        <button
                          type="button"
                          className={`btn btn-sm model-toggle-btn${m.enabled ? " model-toggle-btn--on" : ""}`}
                          onClick={() => toggle(m.id, m.enabled)}
                        >
                          {m.enabled ? "ON" : "OFF"}
                        </button>
                        {m.admin_disabled ? (
                          <span
                            className="model-admin-off-badge"
                            title="Stays off until an administrator turns it on. A sync or a connection change will not enable it — new models arrive in this state."
                          >
                            Needs approval
                          </span>
                        ) : null}
                        {m.is_system_default ? (
                          <span
                            className="model-default-badge"
                            title="System default for new chats. Does not change users who already picked their own."
                          >
                            Default
                          </span>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <Modal
        open={bulkOpen}
        title={`Bulk Edit (${selectedIds.length} models)`}
        onClose={() => !bulkBusy && setBulkOpen(false)}
      >
        <p className="muted-text">Apply an action to all selected models.</p>
        <div className="dialog-actions" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
          <button type="button" className="btn" disabled={bulkBusy} onClick={() => runBulk("on")}>
            {bulkBusy ? "…" : "ON"}
          </button>
          <button type="button" className="btn btn-ghost" disabled={bulkBusy} onClick={() => runBulk("off")}>
            OFF
          </button>
          <button type="button" className="btn btn-ghost" disabled={bulkBusy} onClick={() => runBulk("public")}>
            Public
          </button>
          <button type="button" className="btn btn-ghost" disabled={bulkBusy} onClick={() => runBulk("private")}>
            Private
          </button>
          <button type="button" className="btn btn-danger" disabled={bulkBusy} onClick={() => runBulk("delete")}>
            Delete
          </button>
          <button type="button" className="btn btn-ghost" disabled={bulkBusy} onClick={() => setBulkOpen(false)}>
            Cancel
          </button>
        </div>
      </Modal>

      <SetDefaultModelModal
        kind={defaultKind}
        models={allModels}
        currentId={defaultKind ? systemDefaults[defaultKind.key] ?? null : null}
        busy={defaultBusy}
        onClose={() => setDefaultKind(null)}
        onPick={(id) => void pickSystemDefault(id)}
      />
      <ModelAccessModal
        open={accessModelId != null}
        modelId={accessModelId}
        modelLabel={accessModel?.external_id || ""}
        onClose={() => setAccessModelId(null)}
        onSaved={async () => setAllModels(await loadModels())}
      />

      <ModelCodeInterpreterModal
        open={compatModelId != null}
        modelId={compatModelId}
        modelLabel={compatModel?.external_id || ""}
        onClose={() => setCompatModelId(null)}
        onSaved={async () => setAllModels(await loadModels())}
      />
    </AdminPage>
  );
}
