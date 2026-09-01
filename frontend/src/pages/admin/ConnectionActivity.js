import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useCallback, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api";
import ActivityView from "../../components/activity/ActivityView";
import ConnectionChangelog from "../../components/connections/ConnectionChangelog";
export default function ConnectionActivity() {
    const { connId } = useParams();
    const id = Number(connId);
    const [meta, setMeta] = useState(null);
    const [toggleBusy, setToggleBusy] = useState(false);
    const [toggleMsg, setToggleMsg] = useState("");
    const onActivityLoaded = useCallback((data) => {
        const c = data.connection;
        if (!c)
            return;
        setMeta({
            id: c.id,
            name: c.name,
            provider_type: c.provider_type,
            base_url: c.base_url ?? null,
            is_active: c.is_active,
        });
    }, []);
    async function toggleActive() {
        if (!meta)
            return;
        setToggleBusy(true);
        setToggleMsg("");
        try {
            const res = await api(`/api/admin/connections/${meta.id}/toggle?enabled=${!meta.is_active}`, { method: "PATCH" });
            setMeta((m) => (m ? { ...m, is_active: res.is_active } : m));
            setToggleMsg(res.is_active ? "Connection enabled." : "Connection disabled.");
        }
        catch (ex) {
            setToggleMsg(String(ex));
        }
        finally {
            setToggleBusy(false);
        }
    }
    const toolbarExtra = meta ? (_jsxs("div", { className: "connection-activity-actions", children: [_jsx("button", { type: "button", className: `btn btn-ghost btn-sm${meta.is_active ? "" : " connection-activity-actions__enable"}`, disabled: toggleBusy, onClick: () => void toggleActive(), children: toggleBusy ? "…" : meta.is_active ? "Disable connection" : "Enable connection" }), toggleMsg ? _jsx("span", { className: "muted-text connection-activity-actions__msg", children: toggleMsg }) : null] })) : null;
    return (_jsx(ActivityView, { scope: "connection", connectionId: id, backLink: { to: "/admin/connections", label: "Connections" }, toolbarExtra: toolbarExtra, onDataLoaded: onActivityLoaded, footer: Number.isFinite(id) ? _jsx(ConnectionChangelog, { connectionId: id }) : null }));
}
