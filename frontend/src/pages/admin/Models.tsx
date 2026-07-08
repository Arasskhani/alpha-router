import { useEffect, useMemo, useState } from "react";

import AdminPage from "../../components/AdminPage";
import Modal from "../../components/Modal";
import ModelsFilterBar from "../../components/models/ModelsFilterBar";
import ModelsBrowseView from "../../components/models/ModelsBrowseView";
import { api } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";
import { useDebounced } from "../../hooks/useDebounced";
import {
  filterCatalogModels,
  type CatalogModel,
  type ModelKind,
} from "../../lib/modelCatalog";

type ViewMode = "table" | "browse";

const VIEW_STORAGE_KEY = "alpha-router-models-view";

function loadViewMode(): ViewMode {
  try {
    const v = localStorage.getItem(VIEW_STORAGE_KEY);
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
  const [viewMode, setViewMode] = useState<ViewMode>(loadViewMode);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const debouncedSearch = useDebounced(search, 280);

  async function loadModels() {
    return api<CatalogModel[]>("/api/admin/models");
  }

  const models = useMemo(
    () => filterCatalogModels(allModels, debouncedSearch, activeKind),
    [allModels, debouncedSearch, activeKind],
  );

  useEffect(() => {
    loadModels().then(setAllModels).catch(() => setAllModels([]));
    setSelectedIds([]);
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
    window.addEventListener("alpha-router-models-sync-flash", onSyncFlash);
    return () => window.removeEventListener("alpha-router-models-sync-flash", onSyncFlash);
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(VIEW_STORAGE_KEY, viewMode);
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

  async function runBulk(action: "on" | "off" | "delete") {
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
    setBulkBusy(true);
    setMsg("");
    try {
      const r = await api<{ count: number }>(`/api/admin/models/bulk?action=${action}`, {
        method: "POST",
        body: JSON.stringify({ ids: selectedIds }),
      });
      setMsg(
        action === "delete"
          ? `Deleted ${r.count} model(s).`
          : `Turned ${action === "on" ? "on" : "off"} ${r.count} model(s).`,
      );
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
                    <td>{m.external_id}</td>
                    <td>{m.input_cost_per_1k ?? "—"}</td>
                    <td>{m.output_cost_per_1k ?? "—"}</td>
                    <td>{m.total_cost_per_1k}</td>
                    <td className="col-onoff">
                      <button
                        type="button"
                        className={`btn btn-sm model-toggle-btn${m.enabled ? " model-toggle-btn--on" : ""}`}
                        onClick={() => toggle(m.id, m.enabled)}
                      >
                        {m.enabled ? "ON" : "OFF"}
                      </button>
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
          <button type="button" className="btn btn-danger" disabled={bulkBusy} onClick={() => runBulk("delete")}>
            Delete
          </button>
          <button type="button" className="btn btn-ghost" disabled={bulkBusy} onClick={() => setBulkOpen(false)}>
            Cancel
          </button>
        </div>
      </Modal>
    </AdminPage>
  );
}
