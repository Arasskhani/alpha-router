import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import AdminPage from "../../components/AdminPage";
import { api } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";
import { useAdminWriteLock } from "../../lib/adminWriteLock";
import { userHasSuperAdminAccess } from "../../lib/rbac";
import { canEnableEnforce, expiryBannerLevel, httpsHealthUrl, isReservedHttpsPort, parseCidrInput, } from "../../lib/securitySettings";
export default function SecuritySettings() {
    const { confirm } = useConfirm();
    const { readOnly, writeLockProps } = useAdminWriteLock();
    const [tab, setTab] = useState("https");
    const [session, setSession] = useState(null);
    const [msg, setMsg] = useState("");
    const [allowlist, setAllowlist] = useState(null);
    const [cidr, setCidr] = useState("");
    const [label, setLabel] = useState("");
    const [certs, setCerts] = useState([]);
    const [tls, setTls] = useState(null);
    const [httpsPort, setHttpsPort] = useState(443);
    const [httpMode, setHttpMode] = useState("loopback_only");
    const [hsts, setHsts] = useState(false);
    const [selectedCertId, setSelectedCertId] = useState(null);
    const [certLabel, setCertLabel] = useState("");
    const [certPassword, setCertPassword] = useState("");
    const [busy, setBusy] = useState(false);
    const canWrite = useMemo(() => !readOnly && userHasSuperAdminAccess(session?.roles, session?.role), [readOnly, session]);
    async function load() {
        const [sessionRow, allow, certList, status] = await Promise.all([
            api("/api/auth/session"),
            api("/api/admin/security/ip-allowlist"),
            api("/api/admin/security/tls/certificates"),
            api("/api/admin/security/tls/status"),
        ]);
        setSession(sessionRow);
        setAllowlist(allow);
        setCerts(certList.items);
        setTls(status);
        if (status.https_port)
            setHttpsPort(status.https_port);
        if (status.http_mode)
            setHttpMode(status.http_mode);
        setHsts(Boolean(status.hsts));
        const active = certList.items.find((item) => item.is_active) || certList.items[0];
        if (active)
            setSelectedCertId(active.id);
    }
    useEffect(() => {
        load().catch((err) => setMsg(String(err)));
    }, []);
    async function addCidr(e) {
        e.preventDefault();
        const parsed = parseCidrInput(cidr);
        if (!parsed.ok) {
            setMsg(parsed.error);
            return;
        }
        setBusy(true);
        try {
            await api("/api/admin/security/ip-allowlist", {
                method: "POST",
                body: JSON.stringify({ cidr: parsed.cidr, label }),
            });
            setCidr("");
            setLabel("");
            setMsg("IP allowlist entry added.");
            await load();
        }
        catch (err) {
            setMsg(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function addCurrentIp() {
        if (!allowlist?.detected_client_ip)
            return;
        setCidr(allowlist.detected_client_ip);
        setLabel("This browser");
    }
    async function changeMode(mode) {
        if (!allowlist)
            return;
        if (mode === "enforce") {
            const gate = canEnableEnforce({
                clientIp: allowlist.detected_client_ip,
                entries: allowlist.entries,
            });
            if (!gate.ok) {
                setMsg(gate.reason);
                return;
            }
            const ok = await confirm({
                title: "Enforce admin IP restriction",
                message: "Admin pages and /api/admin will only accept listed IP addresses. If you lose access, use the break-glass CLI on the host.",
                danger: true,
                confirmLabel: "Enforce",
            });
            if (!ok)
                return;
        }
        setBusy(true);
        try {
            await api("/api/admin/security/ip-allowlist/mode", {
                method: "PUT",
                body: JSON.stringify({ mode }),
            });
            setMsg(`IP restriction mode set to ${mode}.`);
            await load();
        }
        catch (err) {
            setMsg(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function removeEntry(id) {
        const ok = await confirm({
            title: "Remove allowlist entry",
            message: "This IP or CIDR will no longer be allowed when restriction is enforced.",
            danger: true,
            confirmLabel: "Remove",
        });
        if (!ok)
            return;
        await api(`/api/admin/security/ip-allowlist/${id}`, { method: "DELETE" });
        await load();
    }
    async function uploadCertificate(e) {
        e.preventDefault();
        const input = document.getElementById("tls-cert-file");
        const file = input?.files?.[0];
        const body = new FormData();
        body.append("label", certLabel);
        body.append("password", certPassword);
        if (file)
            body.append("file", file);
        setBusy(true);
        try {
            const stored = await api("/api/admin/security/tls/certificates", { method: "POST", body });
            setSelectedCertId(stored.id);
            setCertLabel("");
            setCertPassword("");
            if (input)
                input.value = "";
            const uploaded = `Certificate uploaded (${stored.sha256_fingerprint.slice(0, 12)}…).`;
            setMsg(stored.warnings?.length ? `${uploaded} ${stored.warnings.join(" ")}` : uploaded);
            await load();
        }
        catch (err) {
            setMsg(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function activateHttps(e) {
        e.preventDefault();
        if (!selectedCertId) {
            setMsg("Upload or select a certificate first.");
            return;
        }
        if (isReservedHttpsPort(httpsPort)) {
            setMsg(`Port ${httpsPort} is reserved by Alpharouter services.`);
            return;
        }
        const ok = await confirm({
            title: "Activate HTTPS",
            message: `The edge proxy will listen on TCP ${httpsPort}. Keep this HTTP session open until you confirm the new URL.`,
            confirmLabel: "Activate",
        });
        if (!ok)
            return;
        setBusy(true);
        try {
            await api("/api/admin/security/tls/activate", {
                method: "POST",
                body: JSON.stringify({
                    certificate_id: selectedCertId,
                    https_port: httpsPort,
                    http_mode: httpMode,
                    hsts_enabled: hsts,
                }),
            });
            // The edge proxy polls the shared volume, so the listener needs a few
            // seconds before it answers.
            let verified = { ok: false, error: "not ready yet" };
            for (let attempt = 0; attempt < 6; attempt += 1) {
                await new Promise((resolve) => setTimeout(resolve, 2500));
                verified = await api("/api/admin/security/tls/verify", {
                    method: "POST",
                    body: JSON.stringify({ https_port: httpsPort }),
                });
                if (verified.ok)
                    break;
            }
            setMsg(verified.ok
                ? `HTTPS is listening on port ${httpsPort}. Update FRONTEND_URL / API_PUBLIC_URL and bind HTTP to 127.0.0.1 after you confirm.`
                : `HTTPS was requested. Listener check: ${verified.error || "not ready yet"}. Use Revert to HTTP if needed.`);
            await load();
        }
        catch (err) {
            setMsg(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function revertHttp() {
        const ok = await confirm({
            title: "Revert to HTTP",
            message: "The TLS edge proxy will stop listening. The app remains on port 8080.",
            danger: true,
            confirmLabel: "Revert",
        });
        if (!ok)
            return;
        setBusy(true);
        try {
            await api("/api/admin/security/tls/active", { method: "DELETE" });
            setMsg("HTTPS deactivated.");
            await load();
        }
        catch (err) {
            setMsg(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function deleteCert(id) {
        const ok = await confirm({
            title: "Delete certificate",
            message: "The stored certificate and encrypted private key will be removed.",
            danger: true,
            confirmLabel: "Delete",
        });
        if (!ok)
            return;
        await api(`/api/admin/security/tls/certificates/${id}`, { method: "DELETE" });
        await load();
    }
    const expiry = expiryBannerLevel(tls?.days_remaining ?? certs.find((c) => c.is_active)?.days_remaining ?? null);
    const health = httpsHealthUrl(window.location.hostname, httpsPort);
    return (_jsxs(AdminPage, { title: "Security Settings", children: [_jsx("p", { className: "muted-text", children: "TLS termination and admin IP restrictions. Write access is Super Admin only. Private keys never leave the server." }), msg && _jsx("p", { className: "card", children: msg }), expiry !== "none" && (_jsx("p", { className: expiry === "expired" || expiry === "critical" ? "alert-error" : "alert-warning", children: expiry === "expired"
                    ? "The active TLS certificate has expired. HTTPS clients will fail until you replace it."
                    : `The active TLS certificate expires in ${tls?.days_remaining ?? "a few"} days. Upload a replacement soon.` })), _jsxs("div", { className: "tabs", children: [_jsx("button", { type: "button", className: `tab ${tab === "https" ? "active" : ""}`, onClick: () => setTab("https"), children: "HTTPS" }), _jsx("button", { type: "button", className: `tab ${tab === "ip" ? "active" : ""}`, onClick: () => setTab("ip"), children: "Admin IP Restrictions" })] }), tab === "https" && (_jsxs(_Fragment, { children: [_jsxs("form", { className: "card", onSubmit: uploadCertificate, children: [_jsx("h3", { style: { marginTop: 0 }, children: "Upload certificate" }), _jsx("p", { className: "muted-text", children: "PEM (certificate + key, optional chain) or PKCS#12 (.pfx / .p12)." }), _jsxs("label", { className: "input-block", children: [_jsx("span", { className: "muted-text", children: "Label" }), _jsx("input", { value: certLabel, onChange: (e) => setCertLabel(e.target.value), style: { width: "100%" } })] }), _jsxs("label", { className: "input-block", style: { marginTop: 8 }, children: [_jsx("span", { className: "muted-text", children: "Certificate file" }), _jsx("input", { id: "tls-cert-file", type: "file", accept: ".pem,.crt,.cer,.key,.p12,.pfx,.xml" })] }), _jsxs("label", { className: "input-block", style: { marginTop: 8 }, children: [_jsx("span", { className: "muted-text", children: "Passphrase (if the key or PFX is encrypted)" }), _jsx("input", { type: "password", value: certPassword, onChange: (e) => setCertPassword(e.target.value), style: { width: "100%" } })] }), _jsx("div", { className: "dialog-actions", children: _jsx("button", { className: "btn", type: "submit", ...writeLockProps, disabled: !canWrite || busy, children: "Upload" }) })] }), _jsxs("div", { className: "card table-wrap", children: [_jsx("h3", { style: { marginTop: 0 }, children: "Stored certificates" }), _jsxs("table", { children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", {}), _jsx("th", { children: "Label" }), _jsx("th", { children: "Subject" }), _jsx("th", { children: "Expires" }), _jsx("th", { children: "Fingerprint" }), _jsx("th", {})] }) }), _jsxs("tbody", { children: [certs.length === 0 && (_jsx("tr", { children: _jsx("td", { colSpan: 6, className: "muted-text", children: "No certificates uploaded." }) })), certs.map((cert) => (_jsxs("tr", { children: [_jsx("td", { children: _jsx("input", { type: "radio", name: "tls-cert", checked: selectedCertId === cert.id, onChange: () => setSelectedCertId(cert.id), disabled: !canWrite }) }), _jsxs("td", { children: [cert.label, cert.is_active ? " (active)" : ""] }), _jsx("td", { children: cert.subject }), _jsx("td", { children: cert.not_after || "—" }), _jsx("td", { children: _jsxs("code", { children: [cert.sha256_fingerprint.slice(0, 16), "\u2026"] }) }), _jsx("td", { children: _jsx("button", { type: "button", className: "btn btn-ghost", disabled: !canWrite || cert.is_active, onClick: () => deleteCert(cert.id), children: "Delete" }) })] }, cert.id)))] })] })] }), _jsxs("form", { className: "card", onSubmit: activateHttps, children: [_jsx("h3", { style: { marginTop: 0 }, children: "Activate HTTPS" }), _jsxs("label", { className: "input-block", children: [_jsx("span", { className: "muted-text", children: "HTTPS port" }), _jsx("input", { type: "number", min: 1, max: 65535, value: httpsPort, onChange: (e) => setHttpsPort(Number(e.target.value)), disabled: !canWrite })] }), _jsxs("label", { className: "input-block", style: { marginTop: 8 }, children: [_jsx("span", { className: "muted-text", children: "HTTP mode" }), _jsxs("select", { value: httpMode, onChange: (e) => setHttpMode(e.target.value), children: [_jsx("option", { value: "loopback_only", children: "Keep HTTP on 8080 (recommended during cutover)" }), _jsx("option", { value: "redirect", children: "Also listen on port 80 and redirect to HTTPS" })] })] }), _jsxs("label", { style: { display: "block", marginTop: 8 }, children: [_jsx("input", { type: "checkbox", checked: hsts, onChange: (e) => setHsts(e.target.checked), disabled: !canWrite }), " ", "Send HSTS from the edge proxy"] }), _jsxs("p", { className: "muted-text", children: ["After activation, open ", _jsx("a", { href: health, children: health }), " and then set", " ", _jsx("code", { children: "ALPHAROUTER_HTTP_BIND=127.0.0.1" }), " so clients cannot skip TLS."] }), tls?.http_published_on_all_interfaces && tls.enabled && (_jsxs("p", { className: "alert-warning", children: ["HTTP is still published on all interfaces (", tls.http_bind, ":8080). Bind it to 127.0.0.1 after you confirm HTTPS."] })), tls?.apply_status && tls.apply_status.ok === false && (_jsxs("p", { className: "alert-error", children: ["Edge proxy failed: ", tls.apply_status.error || "unknown error"] })), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { className: "btn", type: "submit", ...writeLockProps, disabled: !canWrite || busy, children: "Activate HTTPS" }), _jsx("button", { type: "button", className: "btn btn-ghost dialog-actions-end", disabled: !canWrite || busy, onClick: revertHttp, children: "Revert to HTTP" })] })] })] })), tab === "ip" && allowlist && (_jsxs(_Fragment, { children: [allowlist.kill_switch && (_jsxs("p", { className: "alert-warning", children: [_jsx("code", { children: "ADMIN_IP_RESTRICTION_DISABLED" }), " is set. The allowlist is not enforced."] })), allowlist.mode === "enforce" && allowlist.http_bind === "0.0.0.0" && (_jsx("p", { className: "alert-warning", children: "HTTP is published on 0.0.0.0:8080. Attackers who can reach that port may bypass an upstream proxy. Bind HTTP to 127.0.0.1 after HTTPS is active." })), _jsxs("div", { className: "card", children: [_jsx("h3", { style: { marginTop: 0 }, children: "Restriction mode" }), _jsxs("p", { className: "muted-text", children: ["Applies to ", _jsx("code", { children: "/admin" }), " and ", _jsx("code", { children: "/api/admin" }), " only. Login and end-user routes stay open. Detected IP: ", _jsx("strong", { children: allowlist.detected_client_ip || "unknown" })] }), _jsx("div", { className: "dialog-actions", children: ["off", "monitor", "enforce"].map((mode) => (_jsx("button", { type: "button", className: `btn ${allowlist.mode === mode ? "" : "btn-ghost"}`, disabled: !canWrite || busy, onClick: () => changeMode(mode), children: mode }, mode))) })] }), _jsxs("form", { className: "card", onSubmit: addCidr, children: [_jsx("h3", { style: { marginTop: 0 }, children: "Add IP or CIDR" }), _jsx("input", { placeholder: "192.168.1.10 or 10.0.0.0/8", value: cidr, onChange: (e) => setCidr(e.target.value), style: { width: "100%", marginBottom: 8 } }), _jsx("input", { placeholder: "Label (optional)", value: label, onChange: (e) => setLabel(e.target.value), style: { width: "100%", marginBottom: 8 } }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { className: "btn", type: "submit", ...writeLockProps, disabled: !canWrite || busy, children: "Add" }), _jsxs("button", { type: "button", className: "btn btn-ghost", disabled: !canWrite || !allowlist.detected_client_ip, onClick: addCurrentIp, children: ["Add my current IP", allowlist.detected_client_ip ? ` (${allowlist.detected_client_ip})` : ""] })] })] }), _jsx("div", { className: "card table-wrap", children: _jsxs("table", { children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "CIDR" }), _jsx("th", { children: "Label" }), _jsx("th", {})] }) }), _jsxs("tbody", { children: [allowlist.entries.length === 0 && (_jsx("tr", { children: _jsx("td", { colSpan: 3, className: "muted-text", children: "No allowlist entries yet." }) })), allowlist.entries.map((entry) => (_jsxs("tr", { children: [_jsx("td", { children: _jsx("code", { children: entry.cidr }) }), _jsx("td", { children: entry.label || "—" }), _jsx("td", { children: _jsx("button", { type: "button", className: "btn btn-ghost", disabled: !canWrite, onClick: () => removeEntry(entry.id), children: "Remove" }) })] }, entry.id)))] })] }) }), _jsxs("p", { className: "muted-text", children: ["Break-glass: ", _jsx("code", { children: "docker compose exec alpha-router python -m app.security_breakglass --disable-admin-ip-restriction" })] })] }))] }));
}
