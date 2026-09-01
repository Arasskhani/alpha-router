import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import Modal from "../Modal";
import AuthenticatedImage from "../AuthenticatedImage";
import { formatMediaBytes } from "../../lib/mediaLibrary";
import { attachSlotOverflowMessage, capAttachSelection, composerAttachEligibility, listComposerAttachMedia, mediaCandidatesToFiles, } from "../../lib/composerAttachSources";
export default function ComposerMediaPicker({ open, projectId, privateMode, remainingSlots, onClose, onPick, onPickMediaIds, }) {
    const [query, setQuery] = useState("");
    const [items, setItems] = useState([]);
    const [total, setTotal] = useState(0);
    const [selected, setSelected] = useState([]);
    const [loading, setLoading] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [flash, setFlash] = useState("");
    useEffect(() => {
        if (!open)
            return;
        setQuery("");
        setSelected([]);
        setError("");
        setFlash("");
    }, [open]);
    useEffect(() => {
        if (!open)
            return;
        let cancelled = false;
        const delay = query.trim() ? 250 : 0;
        const handle = window.setTimeout(() => {
            setLoading(true);
            void listComposerAttachMedia({ projectId, query, limit: 60 })
                .then((res) => {
                if (cancelled)
                    return;
                setItems(res.items);
                setTotal(res.total);
                setError("");
            })
                .catch((err) => {
                if (cancelled)
                    return;
                setError(err instanceof Error ? err.message : String(err));
            })
                .finally(() => {
                if (!cancelled)
                    setLoading(false);
            });
        }, delay);
        return () => {
            cancelled = true;
            window.clearTimeout(handle);
        };
    }, [open, projectId, query]);
    const title = projectId ? "Attach from project Media" : "Attach from Media";
    const rows = useMemo(() => items.map((item) => ({
        item,
        eligibility: composerAttachEligibility(item, { privateMode }),
    })), [items, privateMode]);
    function toggle(id, attachable) {
        if (!attachable)
            return;
        const next = capAttachSelection(selected, id, remainingSlots);
        setSelected(next.ids);
        setFlash(next.blocked ? attachSlotOverflowMessage(remainingSlots) : "");
    }
    async function confirm() {
        const chosen = rows
            .filter((row) => selected.includes(row.item.id) && row.eligibility.attachable)
            .map((row) => row.item);
        if (!chosen.length || busy)
            return;
        setBusy(true);
        setError("");
        try {
            if (onPickMediaIds && !privateMode) {
                await onPickMediaIds(chosen.map((item) => item.id));
            }
            else {
                const files = await mediaCandidatesToFiles(chosen);
                await onPick(files);
            }
        }
        catch (err) {
            setError(err instanceof Error ? err.message : String(err));
        }
        finally {
            setBusy(false);
        }
    }
    return (_jsxs(Modal, { open: open, title: title, onClose: onClose, panelClassName: "modal-panel--composer-media", headerActions: remainingSlots > 0 ? (_jsxs("span", { className: "alpha-router-media-picker__slots", children: [remainingSlots, " slot", remainingSlots === 1 ? "" : "s", " left"] })) : null, children: [privateMode ? (_jsx("p", { className: "alpha-router-media-picker__note", children: "Private Mode can attach images and plain-text files only. Documents that need server extraction stay disabled." })) : null, remainingSlots <= 0 ? (_jsx("p", { className: "alpha-router-media-picker__note", children: attachSlotOverflowMessage(0) })) : null, _jsx("label", { className: "alpha-router-media-picker__search", children: _jsx("input", { type: "search", value: query, onChange: (e) => setQuery(e.target.value), placeholder: "Search files", "aria-label": "Search media", autoFocus: true }) }), error ? _jsx("p", { className: "form-error", children: error }) : null, flash ? _jsx("p", { className: "alpha-router-media-picker__flash", children: flash }) : null, loading && !items.length ? _jsx("p", { className: "muted-text", children: "Loading media\u2026" }) : null, !loading && !items.length && !error ? (_jsx("p", { className: "muted-text", children: query.trim() ? "No media matches your search." : "No media files yet." })) : null, _jsx("div", { className: "alpha-router-media-picker__grid", children: rows.map(({ item, eligibility }) => {
                    const checked = selected.includes(item.id);
                    const disabled = !eligibility.attachable || (remainingSlots <= 0 && !checked);
                    return (_jsxs("button", { type: "button", className: `alpha-router-media-picker__card${checked ? " is-selected" : ""}${disabled ? " is-disabled" : ""}`, disabled: disabled && !checked, title: eligibility.reason || item.fileName, onClick: () => toggle(item.id, eligibility.attachable), children: [_jsx("span", { className: "alpha-router-media-picker__thumb", children: item.kind === "image" ? (_jsx(AuthenticatedImage, { url: item.url, alt: item.fileName })) : (_jsx("span", { className: "alpha-router-media-picker__kind", children: item.kind || "file" })) }), _jsx("span", { className: "alpha-router-media-picker__name", title: item.fileName, children: item.fileName }), _jsx("span", { className: "alpha-router-media-picker__meta", children: item.sizeBytes != null ? formatMediaBytes(item.sizeBytes) : item.mimeType })] }, item.id));
                }) }), total > items.length ? (_jsxs("p", { className: "muted-text", children: ["Showing ", items.length, " of ", total, ". Search to find older files."] })) : null, _jsxs("div", { className: "alpha-router-media-picker__foot", children: [_jsx("span", { className: "muted-text", children: selected.length ? `${selected.length} selected` : "Select files to attach" }), _jsxs("div", { className: "alpha-router-media-picker__actions", children: [_jsx("button", { type: "button", className: "btn btn-ghost", onClick: onClose, disabled: busy, children: "Cancel" }), _jsx("button", { type: "button", className: "btn", onClick: () => void confirm(), disabled: !selected.length || busy || remainingSlots <= 0, children: busy ? "Attaching…" : selected.length ? `Attach ${selected.length}` : "Attach" })] })] })] }));
}
