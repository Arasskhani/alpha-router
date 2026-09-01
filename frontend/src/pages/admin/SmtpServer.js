import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import AdminPage from "../../components/AdminPage";
import { api } from "../../api";
export default function SmtpServer() {
    const [cfg, setCfg] = useState({
        host: "",
        port: 587,
        username: "",
        password: "",
        from_address: "",
        use_tls: true,
    });
    const [msg, setMsg] = useState("");
    useEffect(() => {
        api("/api/admin/smtp").then((d) => d && setCfg({ ...cfg, ...d, password: d.password || "" }));
    }, []);
    async function save(e) {
        e.preventDefault();
        await api("/api/admin/smtp", { method: "PUT", body: JSON.stringify(cfg) });
        setMsg("SMTP settings saved.");
    }
    async function testConn(e) {
        e.preventDefault();
        const r = await api("/api/admin/smtp/test", { method: "POST", body: JSON.stringify(cfg) });
        setMsg(r.ok ? "Connection successful." : `Failed: ${r.error}`);
    }
    return (_jsxs(AdminPage, { title: "SMTP Server", children: [_jsx("p", { className: "muted-text", children: "Used for scheduled report emails. Only admins configure this; users can only receive reports." }), msg && _jsx("p", { className: "card", children: msg }), _jsxs("form", { className: "card", onSubmit: save, children: [_jsx("input", { placeholder: "SMTP host", value: cfg.host, onChange: (e) => setCfg({ ...cfg, host: e.target.value }), required: true, style: { width: "100%", marginBottom: 8 } }), _jsx("input", { type: "number", placeholder: "Port", value: cfg.port, onChange: (e) => setCfg({ ...cfg, port: Number(e.target.value) }), style: { width: "100%", marginBottom: 8 } }), _jsx("input", { placeholder: "Username", value: cfg.username, onChange: (e) => setCfg({ ...cfg, username: e.target.value }), style: { width: "100%", marginBottom: 8 } }), _jsx("input", { type: "password", placeholder: "Password", value: cfg.password, onChange: (e) => setCfg({ ...cfg, password: e.target.value }), style: { width: "100%", marginBottom: 8 } }), _jsx("input", { placeholder: "From address", value: cfg.from_address, onChange: (e) => setCfg({ ...cfg, from_address: e.target.value }), required: true, style: { width: "100%", marginBottom: 8 } }), _jsxs("label", { children: [_jsx("input", { type: "checkbox", checked: cfg.use_tls, onChange: (e) => setCfg({ ...cfg, use_tls: e.target.checked }) }), " Use TLS"] }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { className: "btn", type: "submit", children: "Save" }), _jsx("button", { type: "button", className: "btn btn-ghost dialog-actions-end", onClick: testConn, children: "Test connection" })] })] })] }));
}
