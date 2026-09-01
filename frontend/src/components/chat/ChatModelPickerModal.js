import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useRef, useState } from "react";
import ModelName from "../ModelName";
import { catalogMonthLabel } from "../../lib/chatModelPresets";
/**
 * Centered model picker (Search / Add Model). Groups the list under a month label.
 */
export default function ChatModelPickerModal({ open, mode, models, selectedIds, defaultModelId, onClose, onSelect, onSetDefault, }) {
    const [query, setQuery] = useState("");
    const [highlight, setHighlight] = useState(0);
    const inputRef = useRef(null);
    const listRef = useRef(null);
    const month = catalogMonthLabel();
    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q)
            return models;
        return models.filter((m) => {
            const name = (m.name || m.external_id || m.id || "").toLowerCase();
            const id = (m.id || "").toLowerCase();
            const ext = (m.external_id || "").toLowerCase();
            return name.includes(q) || id.includes(q) || ext.includes(q);
        });
    }, [models, query]);
    useEffect(() => {
        if (!open)
            return;
        setQuery("");
        setHighlight(0);
        const t = window.setTimeout(() => inputRef.current?.focus(), 30);
        return () => window.clearTimeout(t);
    }, [open]);
    useEffect(() => {
        setHighlight(0);
    }, [query]);
    useEffect(() => {
        if (!open)
            return;
        const onKey = (e) => {
            if (e.key === "Escape") {
                e.preventDefault();
                onClose();
                return;
            }
            if (e.key === "ArrowDown") {
                e.preventDefault();
                setHighlight((h) => Math.min(h + 1, Math.max(filtered.length - 1, 0)));
            }
            else if (e.key === "ArrowUp") {
                e.preventDefault();
                setHighlight((h) => Math.max(h - 1, 0));
            }
            else if (e.key === "Enter") {
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
        if (el instanceof HTMLElement)
            el.scrollIntoView({ block: "nearest" });
    }, [highlight]);
    if (!open)
        return null;
    const title = mode === "append" ? "Add model" : "Select model";
    return (_jsx("div", { className: "alpha-router-model-modal-backdrop", onMouseDown: onClose, role: "presentation", children: _jsxs("div", { className: "alpha-router-model-modal", role: "dialog", "aria-modal": "true", "aria-label": title, onMouseDown: (e) => e.stopPropagation(), children: [_jsxs("div", { className: "alpha-router-model-modal__search", children: [_jsxs("svg", { viewBox: "0 0 24 24", width: "18", height: "18", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": true, children: [_jsx("circle", { cx: "11", cy: "11", r: "7" }), _jsx("path", { d: "M20 20l-3.5-3.5", strokeLinecap: "round" })] }), _jsx("input", { ref: inputRef, type: "search", placeholder: "Search Models", value: query, onChange: (e) => setQuery(e.target.value), "aria-label": "Search models" }), _jsx("kbd", { className: "alpha-router-kbd", children: "esc" })] }), _jsx("div", { className: "alpha-router-model-modal__month", children: month }), _jsx("ul", { className: "alpha-router-model-modal__list", ref: listRef, role: "listbox", children: filtered.length === 0 ? (_jsx("li", { className: "alpha-router-model-modal__empty", children: "No models match" })) : (filtered.map((m, idx) => {
                        const selected = selectedIds.includes(m.id);
                        const active = idx === highlight;
                        return (_jsxs("li", { "data-idx": idx, role: "option", "aria-selected": selected || active, children: [_jsx("button", { type: "button", className: `alpha-router-model-modal__item${active ? " is-active" : ""}${selected ? " is-selected" : ""}`, onMouseEnter: () => setHighlight(idx), onClick: () => onSelect(m.id), title: m.name || m.external_id || m.id, children: _jsx(ModelName, { modelId: m.external_id || m.id, label: m.name || m.external_id || m.id, size: 16 }) }), onSetDefault && mode === "replace" ? (_jsx("button", { type: "button", className: `alpha-router-model-default${defaultModelId === m.id ? " is-default" : ""}`, onClick: (e) => {
                                        e.stopPropagation();
                                        onSetDefault(m.id);
                                    }, "aria-label": defaultModelId === m.id
                                        ? `${m.name || m.id} is default model`
                                        : `Set ${m.name || m.id} as default model`, title: defaultModelId === m.id ? "Default model" : "Set as default for new chats", children: "\u2713" })) : null] }, m.id));
                    })) }), _jsxs("footer", { className: "alpha-router-model-modal__footer", children: [_jsx("span", { children: "\u2191 \u2193 Navigate" }), _jsx("span", { children: "\u21B5 Select" }), _jsxs("span", { className: "alpha-router-model-modal__count", children: [filtered.length, " models"] })] })] }) }));
}
