import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useRef, useState } from "react";
import ModelProviderIcon from "../ModelProviderIcon";
const CATEGORIES = [
    { key: "user", label: "User" },
    { key: "model", label: "Model" },
    { key: "apiKey", label: "API Key" },
    { key: "app", label: "App" },
    { key: "status", label: "Response status" },
];
const STATUS_OPTIONS = [
    { key: "", label: "All responses" },
    { key: "success", label: "Success" },
    { key: "fail", label: "Fail" },
];
function IconFilter() {
    return (_jsx("svg", { viewBox: "0 0 24 24", width: "15", height: "15", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": true, children: _jsx("path", { d: "M4 6h16M7 12h10M10 18h4" }) }));
}
function IconChevron() {
    return (_jsx("svg", { viewBox: "0 0 24 24", width: "12", height: "12", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": true, children: _jsx("path", { d: "m9 6 6 6-6 6" }) }));
}
function IconSearch() {
    return (_jsxs("svg", { viewBox: "0 0 24 24", width: "13", height: "13", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": true, children: [_jsx("circle", { cx: "11", cy: "11", r: "7" }), _jsx("path", { d: "m20 20-3.5-3.5" })] }));
}
function IconKey() {
    return (_jsxs("svg", { viewBox: "0 0 24 24", width: "14", height: "14", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": true, children: [_jsx("circle", { cx: "8", cy: "15", r: "4" }), _jsx("path", { d: "M12 15h9v-2h-2v-2h-2v-2h-3" })] }));
}
function initials(label) {
    const parts = label.trim().split(/[\s@._-]+/).filter(Boolean);
    if (parts.length === 0)
        return "?";
    if (parts.length === 1)
        return parts[0].slice(0, 2).toUpperCase();
    return `${parts[0][0] ?? ""}${parts[1][0] ?? ""}`.toUpperCase();
}
/** OpenRouter-style cascading filter: primary list + left flyout. */
export default function ActivityFilterMenu({ model, user, app, status, apiKey, models, users, apps, apiKeys, visibleKeys, onChange, onClear, }) {
    const [open, setOpen] = useState(false);
    const [activeCategory, setActiveCategory] = useState("model");
    const [categoryQuery, setCategoryQuery] = useState("");
    const [valueQuery, setValueQuery] = useState("");
    const ref = useRef(null);
    const values = { model, user, app, status, apiKey };
    const visibleCategories = useMemo(() => (visibleKeys?.length ? CATEGORIES.filter((c) => visibleKeys.includes(c.key)) : CATEGORIES), [visibleKeys]);
    const activeCount = visibleCategories.reduce((n, c) => n + (values[c.key] ? 1 : 0), 0);
    useEffect(() => {
        if (!open)
            return;
        const onDoc = (e) => {
            if (ref.current && !ref.current.contains(e.target))
                setOpen(false);
        };
        document.addEventListener("mousedown", onDoc);
        return () => document.removeEventListener("mousedown", onDoc);
    }, [open]);
    useEffect(() => {
        if (!open) {
            setCategoryQuery("");
            setValueQuery("");
            setActiveCategory(visibleCategories[0]?.key ?? "model");
        }
    }, [open]);
    useEffect(() => {
        setValueQuery("");
    }, [activeCategory]);
    const filteredCategories = useMemo(() => {
        const q = categoryQuery.trim().toLowerCase();
        if (!q)
            return visibleCategories;
        return visibleCategories.filter((c) => c.label.toLowerCase().includes(q));
    }, [categoryQuery, visibleCategories]);
    const optionsForCategory = useMemo(() => {
        switch (activeCategory) {
            case "model":
                return models;
            case "user":
                return users;
            case "app":
                return apps;
            case "apiKey":
                return apiKeys;
            case "status":
                return STATUS_OPTIONS;
            default:
                return [];
        }
    }, [activeCategory, models, users, apps, apiKeys]);
    const filteredOptions = useMemo(() => {
        const q = valueQuery.trim().toLowerCase();
        if (!q)
            return optionsForCategory;
        return optionsForCategory.filter((o) => o.label.toLowerCase().includes(q) ||
            o.key.toLowerCase().includes(q) ||
            ("name" in o && String(o.name || "").toLowerCase().includes(q)) ||
            ("prefix" in o && String(o.prefix || "").toLowerCase().includes(q)));
    }, [optionsForCategory, valueQuery]);
    const activeCategoryMeta = CATEGORIES.find((c) => c.key === activeCategory);
    const selectedKey = activeCategory ? values[activeCategory] : "";
    function pickValue(key) {
        if (!activeCategory)
            return;
        onChange({ [activeCategory]: key });
        setOpen(false);
    }
    function clearCategory() {
        if (!activeCategory)
            return;
        onChange({ [activeCategory]: "" });
    }
    const searchPlaceholder = activeCategory === "user"
        ? "Search for a user…"
        : activeCategory === "model"
            ? "Search models"
            : activeCategory === "apiKey"
                ? "Search API keys"
                : activeCategory === "app"
                    ? "Search apps"
                    : "Search…";
    return (_jsxs("div", { className: "activity-filter-menu", ref: ref, children: [_jsx("button", { type: "button", className: `activity-icon-btn${open ? " activity-icon-btn--active" : ""}${activeCount ? " activity-icon-btn--badge" : ""}`, onClick: () => setOpen((v) => !v), "aria-label": "Filters", "aria-expanded": open, "aria-haspopup": "dialog", title: "Filters", children: _jsx(IconFilter, {}) }), open ? (_jsxs("div", { className: "activity-filter-popover", role: "dialog", "aria-label": "Activity filters", children: [activeCategory && activeCategoryMeta ? (_jsxs("div", { className: "activity-filter-flyout card", children: [_jsxs("div", { className: "activity-filter-mode", role: "group", "aria-label": "Filter mode", children: [_jsx("button", { type: "button", className: "activity-filter-mode__btn is-active", "aria-pressed": "true", children: "Include" }), _jsx("button", { type: "button", className: "activity-filter-mode__btn", "aria-pressed": "false", disabled: true, title: "Coming soon", children: "Exclude" })] }), _jsxs("div", { className: "activity-filter-flyout__search", children: [_jsx("span", { className: "activity-filter-flyout__search-icon", children: _jsx(IconSearch, {}) }), _jsx("input", { type: "text", className: "activity-filter-flyout__search-input", placeholder: searchPlaceholder, value: valueQuery, onChange: (e) => setValueQuery(e.target.value), "aria-label": searchPlaceholder, autoFocus: true, autoComplete: "off", spellCheck: false }), _jsxs("span", { className: "activity-filter-flyout__count muted-text", children: [filteredOptions.length, " ", activeCategoryMeta.label.toLowerCase(), filteredOptions.length === 1 ? "" : "s"] })] }), _jsxs("div", { className: "activity-filter-flyout__section", children: [_jsxs("div", { className: "activity-filter-flyout__section-head", children: [_jsx("span", { children: activeCategory === "status"
                                                    ? "Status"
                                                    : activeCategory === "apiKey"
                                                        ? "API Keys"
                                                        : `${activeCategoryMeta.label}s` }), selectedKey ? (_jsx("button", { type: "button", className: "activity-filter-flyout__clear", onClick: clearCategory, children: "Clear" })) : null] }), _jsx("ul", { className: "activity-filter-flyout__list", role: "listbox", children: filteredOptions.length === 0 ? (_jsx("li", { className: "activity-filter-flyout__empty muted-text", children: valueQuery.trim()
                                                ? "No matches"
                                                : "No usage in this period" })) : (filteredOptions.map((opt) => {
                                            const active = selectedKey === opt.key;
                                            const keyOpt = opt;
                                            return (_jsx("li", { children: _jsxs("button", { type: "button", role: "option", "aria-selected": active, className: `activity-filter-flyout__item${active ? " is-active" : ""}`, onClick: () => pickValue(opt.key), children: [activeCategory === "user" ? (_jsx("span", { className: "activity-filter-avatar", "aria-hidden": true, children: initials(opt.label) })) : activeCategory === "apiKey" ? (_jsx("span", { className: "activity-filter-item-icon", "aria-hidden": true, children: _jsx(IconKey, {}) })) : activeCategory === "model" ? (_jsx("span", { className: "activity-filter-item-icon activity-filter-item-icon--model", "aria-hidden": true, children: _jsx(ModelProviderIcon, { modelId: opt.key, size: 16 }) })) : null, _jsxs("span", { className: "activity-filter-flyout__item-text", children: [_jsx("span", { className: "activity-filter-flyout__item-label", children: keyOpt.name || opt.label }), activeCategory === "apiKey" && keyOpt.prefix ? (_jsx("span", { className: "activity-filter-flyout__item-meta", children: keyOpt.prefix })) : null] })] }) }, opt.key || "__all__"));
                                        })) })] })] })) : null, _jsxs("div", { className: "activity-filter-primary card", children: [_jsx("input", { type: "text", className: "activity-filter-primary__search", placeholder: "Search filters\u2026", value: categoryQuery, onChange: (e) => setCategoryQuery(e.target.value), "aria-label": "Search filter categories", autoComplete: "off", spellCheck: false }), _jsx("ul", { className: "activity-filter-primary__list", children: filteredCategories.map((cat) => {
                                    const hasValue = Boolean(values[cat.key]);
                                    return (_jsx("li", { children: _jsxs("button", { type: "button", className: `activity-filter-primary__item${activeCategory === cat.key ? " is-active" : ""}`, onMouseEnter: () => setActiveCategory(cat.key), onFocus: () => setActiveCategory(cat.key), onClick: () => setActiveCategory(cat.key), children: [_jsx("span", { children: cat.label }), _jsxs("span", { className: "activity-filter-primary__meta", children: [hasValue ? _jsx("span", { className: "activity-filter-dot", "aria-hidden": true }) : null, _jsx(IconChevron, {})] })] }) }, cat.key));
                                }) }), activeCount ? (_jsx("button", { type: "button", className: "activity-filter-primary__clear", onClick: () => {
                                    onClear();
                                }, children: "Clear all filters" })) : null] })] })) : null] }));
}
