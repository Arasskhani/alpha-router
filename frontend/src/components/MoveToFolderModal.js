import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import Modal from "./Modal";
import { IconFolder } from "./icons/navIcons";
export default function MoveToFolderModal({ open, folders, currentFolderId, onClose, onMove, }) {
    const [query, setQuery] = useState("");
    useEffect(() => {
        if (open)
            setQuery("");
    }, [open]);
    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q)
            return folders;
        return folders.filter((f) => (f.name || "").toLowerCase().includes(q));
    }, [folders, query]);
    return (_jsx(Modal, { open: open, title: "Move to folder", onClose: onClose, panelClassName: "modal-panel--move-folder", bodyClassName: "modal-body--move-folder", children: _jsxs("div", { className: "move-folder", children: [_jsx("input", { type: "search", className: "move-folder__search", placeholder: "Search folders\u2026", value: query, onChange: (e) => setQuery(e.target.value), autoFocus: true, "aria-label": "Search folders" }), _jsxs("div", { className: "move-folder__list", role: "listbox", "aria-label": "Folders", children: [_jsxs("button", { type: "button", role: "option", "aria-selected": currentFolderId == null, className: `move-folder__item${currentFolderId == null ? " is-current" : ""}`, onClick: () => {
                                onMove(null);
                                onClose();
                            }, children: [_jsx("span", { className: "move-folder__item-icon", "aria-hidden": true, children: _jsx(IconFolder, {}) }), _jsx("span", { className: "move-folder__item-label", children: "No folder" }), currentFolderId == null ? _jsx("span", { className: "move-folder__check", children: "\u2713" }) : null] }), filtered.map((f) => {
                            const selected = currentFolderId === f.id;
                            return (_jsxs("button", { type: "button", role: "option", "aria-selected": selected, className: `move-folder__item${selected ? " is-current" : ""}`, style: f.color ? { ["--folder-accent"]: f.color } : undefined, onClick: () => {
                                    onMove(f.id);
                                    onClose();
                                }, children: [_jsx("span", { className: "move-folder__item-icon", "aria-hidden": true, children: _jsx(IconFolder, {}) }), _jsx("span", { className: "move-folder__item-label", children: f.name }), selected ? _jsx("span", { className: "move-folder__check", children: "\u2713" }) : null] }, f.id));
                        }), filtered.length === 0 ? (_jsx("p", { className: "move-folder__empty muted-text", children: "No folders match" })) : null] })] }) }));
}
