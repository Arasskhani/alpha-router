import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
const OWNER_USERS_PATH = "/api/admin/api-keys/owner-users";
const MIN_SEARCH = 2;
export default function UserOwnerSelect({ value, onChange, disabled }) {
    const [query, setQuery] = useState("");
    const [open, setOpen] = useState(false);
    const [users, setUsers] = useState([]);
    const [selected, setSelected] = useState(null);
    const [loading, setLoading] = useState(false);
    const [loadError, setLoadError] = useState("");
    const ref = useRef(null);
    useEffect(() => {
        if (!value) {
            setSelected(null);
            return;
        }
        if (selected?.id === value)
            return;
        api(`${OWNER_USERS_PATH}?user_id=${value}`)
            .then((rows) => {
            const hit = rows.find((u) => u.id === value);
            if (hit)
                setSelected(hit);
        })
            .catch(() => { });
    }, [value, selected?.id]);
    useEffect(() => {
        if (!open)
            return;
        const term = query.trim();
        const t = window.setTimeout(() => {
            setLoading(true);
            setLoadError("");
            const qs = new URLSearchParams();
            if (term.length >= MIN_SEARCH)
                qs.set("q", term);
            const suffix = qs.size ? `?${qs}` : "";
            api(`${OWNER_USERS_PATH}${suffix}`)
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
        if (!open)
            return;
        const onDoc = (e) => {
            if (ref.current && !ref.current.contains(e.target))
                setOpen(false);
        };
        document.addEventListener("mousedown", onDoc);
        return () => document.removeEventListener("mousedown", onDoc);
    }, [open]);
    function pick(u) {
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
    const inputValue = open || !selected
        ? query
        : selected.display_name || selected.username || selected.email;
    const searching = query.trim().length >= MIN_SEARCH;
    return (_jsxs("div", { className: "user-owner-select", ref: ref, children: [_jsx("input", { type: "search", className: "input-block user-owner-select__input", disabled: disabled, placeholder: "Search name or email\u2026", value: inputValue, onChange: (e) => {
                    const next = e.target.value;
                    if (selected && !open)
                        clearSelection();
                    setQuery(next);
                    setOpen(true);
                }, onFocus: () => setOpen(true), autoComplete: "off", "aria-expanded": open, "aria-autocomplete": "list" }), open ? (_jsx("div", { className: "user-owner-select__panel card", children: _jsxs("ul", { className: "user-owner-select__list", role: "listbox", children: [loadError && _jsx("li", { className: "muted-text user-owner-select__hint", children: loadError }), !loadError && !searching && !loading && (_jsxs("li", { className: "muted-text user-owner-select__hint", children: ["Recent users \u2014 type ", MIN_SEARCH, "+ characters to narrow results"] })), loading && _jsx("li", { className: "muted-text", children: "Loading\u2026" }), !loading && !loadError && searching && users.length === 0 && (_jsx("li", { className: "muted-text", children: "No users found" })), !loading &&
                            users.map((u) => (_jsx("li", { children: _jsxs("button", { type: "button", className: "user-owner-select__item", onClick: () => pick(u), children: [_jsx("strong", { children: u.display_name || u.username }), _jsx("span", { className: "muted-text", children: u.email })] }) }, u.id)))] }) })) : null] }));
}
