import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import AdminPage from "../../components/AdminPage";
import Modal from "../../components/Modal";
import ModelName from "../../components/ModelName";
import ModelsFilterBar from "../../components/models/ModelsFilterBar";
import ModelsNewFilterMenu from "../../components/models/ModelsNewFilterMenu";
import ModelsBrowseView from "../../components/models/ModelsBrowseView";
import ModelAccessModal from "../../components/models/ModelAccessModal";
import ModelCodeInterpreterModal from "../../components/models/ModelCodeInterpreterModal";
import { api } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";
import { useDebounced } from "../../hooks/useDebounced";
import { BROWSER_EVENT_NAMES, STORAGE_KEYS } from "../../lib/brand";
import { accessCounts, accessTypeLabel, codeInterpreterButtonClass, codeInterpreterLabel, enabledCounts, filterCatalogModels, newWindowCounts, } from "../../lib/modelCatalog";
import { modelSupportsTextChat } from "../../lib/chatModels";
function loadViewMode() {
    try {
        const v = localStorage.getItem(STORAGE_KEYS.modelsView);
        if (v === "browse" || v === "tile")
            return "browse";
        if (v === "table" || v === "list")
            return "table";
        return "browse";
    }
    catch {
        return "browse";
    }
}
export default function Models() {
    const { confirm } = useConfirm();
    const [allModels, setAllModels] = useState([]);
    const [search, setSearch] = useState("");
    const [activeKind, setActiveKind] = useState(null);
    const [enabledFilter, setEnabledFilter] = useState(null);
    const [accessFilter, setAccessFilter] = useState(null);
    const [newFilter, setNewFilter] = useState(null);
    const [viewMode, setViewMode] = useState(loadViewMode);
    const [selectedIds, setSelectedIds] = useState([]);
    const [bulkOpen, setBulkOpen] = useState(false);
    const [bulkBusy, setBulkBusy] = useState(false);
    const [accessModelId, setAccessModelId] = useState(null);
    const [compatModelId, setCompatModelId] = useState(null);
    const [msg, setMsg] = useState("");
    const debouncedSearch = useDebounced(search, 280);
    async function loadModels() {
        return api("/api/admin/models", { cache: "no-store" });
    }
    const models = useMemo(() => filterCatalogModels(allModels, debouncedSearch, activeKind, enabledFilter, accessFilter, newFilter), [allModels, debouncedSearch, activeKind, enabledFilter, accessFilter, newFilter]);
    const statusCounts = useMemo(() => enabledCounts(allModels), [allModels]);
    const accessFilterCounts = useMemo(() => accessCounts(allModels), [allModels]);
    const newFilterCounts = useMemo(() => newWindowCounts(allModels), [allModels]);
    const accessModel = allModels.find((m) => m.id === accessModelId) || null;
    const compatModel = allModels.find((m) => m.id === compatModelId) || null;
    const selectedDefaultTarget = selectedIds.length === 1
        ? allModels.find((m) => m.id === selectedIds[0]) || null
        : null;
    const canSetDefault = Boolean(selectedDefaultTarget
        && selectedDefaultTarget.enabled
        && !selectedDefaultTarget.admin_disabled
        && (selectedDefaultTarget.access_type || "public") === "public"
        && modelSupportsTextChat({
            id: String(selectedDefaultTarget.id),
            name: selectedDefaultTarget.display_name || selectedDefaultTarget.external_id,
            external_id: selectedDefaultTarget.external_id,
            kinds: selectedDefaultTarget.kinds,
        })
        && !selectedDefaultTarget.is_system_default);
    const setDefaultTitle = !selectedDefaultTarget
        ? "Select exactly one model"
        : selectedDefaultTarget.is_system_default
            ? "Already the system default"
            : !selectedDefaultTarget.enabled || selectedDefaultTarget.admin_disabled
                ? "Model must be enabled"
                : (selectedDefaultTarget.access_type || "public") === "private"
                    ? "Model must be public"
                    : !modelSupportsTextChat({
                        id: String(selectedDefaultTarget.id),
                        external_id: selectedDefaultTarget.external_id,
                        kinds: selectedDefaultTarget.kinds,
                    })
                        ? "Model must support text chat"
                        : "System default for new chats. Does not change users who already picked their own.";
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
            }
            catch {
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
        }
        catch {
            /* ignore */
        }
    }, [viewMode]);
    const visibleIds = useMemo(() => models.map((m) => m.id), [models]);
    const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.includes(id));
    function toggleSelectAllVisible() {
        if (allVisibleSelected) {
            setSelectedIds((prev) => prev.filter((id) => !visibleIds.includes(id)));
        }
        else {
            setSelectedIds((prev) => [...new Set([...prev, ...visibleIds])]);
        }
    }
    function toggleRowSelection(id) {
        setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
    }
    async function toggle(id, enabled) {
        await api(`/api/admin/models/${id}/toggle?enabled=${!enabled}`, { method: "PATCH" });
        setAllModels(await loadModels());
    }
    async function setSystemDefault() {
        if (!selectedDefaultTarget || !canSetDefault)
            return;
        const ok = await confirm({
            title: "Set Default",
            message: "New chats will start with this model when a user has not chosen their own default. Existing personal defaults are not changed.",
            confirmLabel: "Set Default",
        });
        if (!ok)
            return;
        setMsg("");
        try {
            await api("/api/admin/models/default", {
                method: "PUT",
                body: JSON.stringify({ model_id: selectedDefaultTarget.id }),
            });
            setMsg(`Set ${selectedDefaultTarget.external_id} as the system default for new chats.`);
            setSelectedIds([]);
            setAllModels(await loadModels());
        }
        catch (e) {
            setMsg(String(e));
        }
    }
    async function runBulk(action) {
        if (!selectedIds.length)
            return;
        if (action === "delete") {
            const ok = await confirm({
                title: "Delete models",
                message: `Delete ${selectedIds.length} selected model(s) from the catalog?`,
                confirmLabel: "Delete",
                danger: true,
            });
            if (!ok)
                return;
        }
        if (action === "public") {
            const ok = await confirm({
                title: "Set Public",
                message: `Set ${selectedIds.length} model(s) to Public and clear private assignments?`,
                confirmLabel: "Set Public",
            });
            if (!ok)
                return;
        }
        setBulkBusy(true);
        setMsg("");
        try {
            const r = await api(`/api/admin/models/bulk?action=${action}`, {
                method: "POST",
                body: JSON.stringify({ ids: selectedIds }),
            });
            const labels = {
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
        }
        catch (e) {
            setMsg(String(e));
        }
        finally {
            setBulkBusy(false);
        }
    }
    return (_jsxs(AdminPage, { title: "Models", children: [_jsxs("div", { className: "models-page", children: [_jsxs("div", { className: "models-page__toolbar", children: [_jsxs("div", { className: "models-page__search-wrap", children: [_jsx("svg", { className: "models-page__search-icon", viewBox: "0 0 24 24", width: 18, height: 18, "aria-hidden": true, children: _jsx("path", { fill: "currentColor", d: "M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C8.01 14 6 11.99 6 9.5S8.01 5 9.5 5 13 7.01 13 9.5 10.99 14 9.5 14z" }) }), _jsx("input", { className: "models-page__search", placeholder: "Search models\u2026", value: search, onChange: (e) => setSearch(e.target.value) })] }), _jsxs("div", { className: "models-page__actions", children: [_jsx("div", { className: "models-status-filter", role: "group", "aria-label": "Filter by status", children: [
                                            { key: "on", label: "ON" },
                                            { key: "off", label: "OFF" },
                                        ].map(({ key, label }) => {
                                            const selected = enabledFilter === key;
                                            return (_jsxs("button", { type: "button", className: `models-filter-chip${selected ? " models-filter-chip--active" : ""}`, onClick: () => setEnabledFilter(selected ? null : key), "aria-pressed": selected, children: [_jsx("span", { children: label }), _jsx("span", { className: "models-filter-chip__count", children: statusCounts[key] })] }, key));
                                        }) }), _jsx("div", { className: "models-status-filter", role: "group", "aria-label": "Filter by access", children: [
                                            { key: "public", label: "Public" },
                                            { key: "private", label: "Private" },
                                        ].map(({ key, label }) => {
                                            const selected = accessFilter === key;
                                            return (_jsxs("button", { type: "button", className: `models-filter-chip${selected ? " models-filter-chip--active" : ""}`, onClick: () => setAccessFilter(selected ? null : key), "aria-pressed": selected, children: [_jsx("span", { children: label }), _jsx("span", { className: "models-filter-chip__count", children: accessFilterCounts[key] })] }, key));
                                        }) }), _jsx(ModelsNewFilterMenu, { value: newFilter, counts: newFilterCounts, onChange: setNewFilter }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: !canSetDefault, onClick: () => void setSystemDefault(), title: setDefaultTitle, children: "Set Default" }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: selectedIds.length === 0, onClick: () => setBulkOpen(true), title: selectedIds.length ? `${selectedIds.length} selected` : "Select models first", children: "Bulk Edit" }), _jsxs("div", { className: "models-view-toggle", role: "group", "aria-label": "View mode", children: [_jsx("button", { type: "button", className: `models-view-toggle__btn${viewMode === "browse" ? " models-view-toggle__btn--active" : ""}`, onClick: () => setViewMode("browse"), title: "Browse view", "aria-pressed": viewMode === "browse", children: _jsx("svg", { viewBox: "0 0 24 24", width: 18, height: 18, "aria-hidden": true, children: _jsx("path", { fill: "currentColor", d: "M4 5h16v3H4V5zm0 5h16v3H4v-3zm0 5h10v3H4v-3z" }) }) }), _jsx("button", { type: "button", className: `models-view-toggle__btn${viewMode === "table" ? " models-view-toggle__btn--active" : ""}`, onClick: () => setViewMode("table"), title: "Table view", "aria-pressed": viewMode === "table", children: _jsx("svg", { viewBox: "0 0 24 24", width: 18, height: 18, "aria-hidden": true, children: _jsx("path", { fill: "currentColor", d: "M3 5h18v2H3V5zm0 6h18v2H3v-2zm0 6h18v2H3v-2z" }) }) })] })] })] }), _jsx(ModelsFilterBar, { models: allModels, active: activeKind, onChange: setActiveKind }), _jsx("p", { className: "muted-text models-page__hint", children: "Pricing per 1K tokens from provider (read-only). Descriptions load from provider catalog after sync." }), msg && _jsx("p", { className: "alert alert-success", children: msg }), _jsxs("p", { style: { color: "var(--muted)", fontSize: "0.85rem" }, children: [models.length, " model(s) shown", allModels.length !== models.length ? ` · ${allModels.length} total` : "", selectedIds.length > 0 ? ` · ${selectedIds.length} selected` : ""] }), viewMode === "browse" ? (_jsx(ModelsBrowseView, { models: models, selectedIds: selectedIds, onToggleSelect: toggleRowSelection, onToggleEnabled: toggle, onEditAccess: (id) => setAccessModelId(id) })) : (_jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "card data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { className: "col-sm", children: _jsx("input", { type: "checkbox", checked: allVisibleSelected, onChange: toggleSelectAllVisible, "aria-label": "Select all visible models" }) }), _jsx("th", { children: "Model" }), _jsx("th", { children: "Input / 1K" }), _jsx("th", { children: "Output / 1K" }), _jsx("th", { children: "Total / 1K" }), _jsx("th", { children: "Access Type" }), _jsx("th", { children: "Code Interpreter" }), _jsx("th", { className: "col-onoff", children: "ON/OFF" })] }) }), _jsx("tbody", { children: models.map((m) => (_jsxs("tr", { children: [_jsx("td", { className: "col-sm", children: _jsx("input", { type: "checkbox", checked: selectedIds.includes(m.id), onChange: () => toggleRowSelection(m.id), "aria-label": `Select ${m.external_id}` }) }), _jsx("td", { children: _jsx(ModelName, { modelId: m.external_id, label: m.external_id, size: 15 }) }), _jsx("td", { children: m.input_cost_per_1k ?? "—" }), _jsx("td", { children: m.output_cost_per_1k ?? "—" }), _jsx("td", { children: m.total_cost_per_1k }), _jsx("td", { children: _jsx("button", { type: "button", className: `btn btn-sm btn-ghost model-access-btn${(m.access_type || "public") === "private" ? " model-access-btn--private" : ""}`, onClick: () => setAccessModelId(m.id), children: accessTypeLabel(m) }) }), _jsx("td", { children: _jsx("button", { type: "button", className: `btn btn-sm btn-ghost${codeInterpreterButtonClass(m)}`, onClick: () => setCompatModelId(m.id), title: m.code_interpreter?.reason_detail ||
                                                        "Code Interpreter compatibility and probe history", children: codeInterpreterLabel(m) }) }), _jsx("td", { className: "col-onoff", children: _jsxs("div", { className: "model-onoff-cell", children: [_jsx("button", { type: "button", className: `btn btn-sm model-toggle-btn${m.enabled ? " model-toggle-btn--on" : ""}`, onClick: () => toggle(m.id, m.enabled), children: m.enabled ? "ON" : "OFF" }), m.admin_disabled ? (_jsx("span", { className: "model-admin-off-badge", title: "Disabled by admin \u2014 sync will not re-enable", children: "Admin off" })) : null, m.is_system_default ? (_jsx("span", { className: "model-default-badge", title: "System default for new chats. Does not change users who already picked their own.", children: "Default" })) : null] }) })] }, m.id))) })] }) }))] }), _jsxs(Modal, { open: bulkOpen, title: `Bulk Edit (${selectedIds.length} models)`, onClose: () => !bulkBusy && setBulkOpen(false), children: [_jsx("p", { className: "muted-text", children: "Apply an action to all selected models." }), _jsxs("div", { className: "dialog-actions", style: { flexWrap: "wrap", gap: "0.5rem" }, children: [_jsx("button", { type: "button", className: "btn", disabled: bulkBusy, onClick: () => runBulk("on"), children: bulkBusy ? "…" : "ON" }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: bulkBusy, onClick: () => runBulk("off"), children: "OFF" }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: bulkBusy, onClick: () => runBulk("public"), children: "Public" }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: bulkBusy, onClick: () => runBulk("private"), children: "Private" }), _jsx("button", { type: "button", className: "btn btn-danger", disabled: bulkBusy, onClick: () => runBulk("delete"), children: "Delete" }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: bulkBusy, onClick: () => setBulkOpen(false), children: "Cancel" })] })] }), _jsx(ModelAccessModal, { open: accessModelId != null, modelId: accessModelId, modelLabel: accessModel?.external_id || "", onClose: () => setAccessModelId(null), onSaved: async () => setAllModels(await loadModels()) }), _jsx(ModelCodeInterpreterModal, { open: compatModelId != null, modelId: compatModelId, modelLabel: compatModel?.external_id || "", onClose: () => setCompatModelId(null), onSaved: async () => setAllModels(await loadModels()) })] }));
}
