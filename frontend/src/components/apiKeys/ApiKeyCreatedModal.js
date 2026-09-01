import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { api } from "../../api";
import Modal from "../Modal";
async function copyText(text) {
    try {
        await navigator.clipboard.writeText(text);
        return true;
    }
    catch {
        try {
            const ta = document.createElement("textarea");
            ta.value = text;
            ta.style.position = "fixed";
            ta.style.left = "-9999px";
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            document.body.removeChild(ta);
            return true;
        }
        catch {
            return false;
        }
    }
}
function CopyButton({ value, label }) {
    const [copied, setCopied] = useState(false);
    async function handleCopy() {
        const ok = await copyText(value);
        if (ok) {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 2000);
        }
    }
    return (_jsx("button", { type: "button", className: "api-key-created__copy", onClick: () => void handleCopy(), title: label, "aria-label": label, children: copied ? (_jsx("span", { className: "api-key-created__copy-done", children: "\u2713" })) : (_jsxs("svg", { viewBox: "0 0 24 24", width: "18", height: "18", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": true, children: [_jsx("rect", { x: "9", y: "9", width: "13", height: "13", rx: "2" }), _jsx("path", { d: "M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" })] })) }));
}
function SecretRow({ label, value }) {
    return (_jsxs("div", { className: "api-key-created__block", children: [_jsx("p", { className: "api-key-created__field-label", children: label }), _jsxs("div", { className: "api-key-created__row", children: [_jsx("input", { readOnly: true, value: value, className: "api-key-created__field mono", "aria-label": label }), _jsx(CopyButton, { value: value, label: `Copy ${label}` })] })] }));
}
export default function ApiKeyCreatedModal({ open, apiKey, url, name, ownerUserId, ownerEmail, onClose, }) {
    const [emailBusy, setEmailBusy] = useState(false);
    const [emailMsg, setEmailMsg] = useState("");
    const [emailErr, setEmailErr] = useState("");
    const [copyToMe, setCopyToMe] = useState(false);
    const [emailSent, setEmailSent] = useState(false);
    const canDismissFreely = emailSent;
    async function sendToOwner() {
        setEmailBusy(true);
        setEmailMsg("");
        setEmailErr("");
        try {
            const res = await api("/api/admin/api-keys/email-credentials", {
                method: "POST",
                body: JSON.stringify({
                    owner_user_id: ownerUserId,
                    name: name ?? "API key",
                    api_key: apiKey,
                    url,
                    copy_to_admin: copyToMe,
                }),
            });
            setEmailMsg(res.cc ? `Sent to ${res.to} (copy to ${res.cc})` : `Sent to ${res.to}`);
            setEmailSent(true);
        }
        catch (ex) {
            setEmailErr(String(ex));
        }
        finally {
            setEmailBusy(false);
        }
    }
    return (_jsx(Modal, { open: open, title: "", onClose: onClose, compactHeader: true, closeOnBackdrop: canDismissFreely, closeOnEscape: canDismissFreely, children: _jsxs("div", { className: "api-key-created", children: [name ? _jsx("p", { className: "api-key-created__name muted-text", children: name }) : null, _jsx(SecretRow, { label: "Your new key:", value: apiKey }), _jsx(SecretRow, { label: "Base URL (OpenAI-compatible):", value: url }), _jsxs("div", { className: "api-key-created__email", children: [_jsxs("div", { className: "api-key-created__email-actions", children: [_jsx("button", { type: "button", className: "btn btn-ghost api-key-created__email-btn", disabled: emailBusy || !ownerEmail, onClick: () => void sendToOwner(), title: ownerEmail ? `Send credentials to ${ownerEmail}` : "Owner has no email", children: emailBusy ? "Sending…" : "Email to owner" }), _jsxs("label", { className: "api-key-created__email-copy", children: [_jsx("input", { type: "checkbox", checked: copyToMe, disabled: emailBusy, onChange: (e) => setCopyToMe(e.target.checked) }), "Send me a copy"] })] }), ownerEmail ? (_jsx("span", { className: "muted-text api-key-created__email-hint", children: ownerEmail })) : (_jsx("span", { className: "muted-text api-key-created__email-hint", children: "No owner email on file" }))] }), emailMsg && _jsx("p", { className: "alert alert-success api-key-created__email-status", children: emailMsg }), emailErr && _jsx("p", { className: "alert alert-error api-key-created__email-status", children: emailErr }), _jsxs("p", { className: "api-key-created__warn", children: ["Please copy it now and write it down somewhere safe.", " ", _jsx("strong", { children: "You will not be able to see it again." })] }), _jsxs("p", { className: "api-key-created__footer muted-text", children: ["You can use it with OpenAI-compatible apps (Open WebUI, Kilo Code, scripts), or", " ", _jsx("a", { href: "/admin/docs#platform-api", target: "_blank", rel: "noopener noreferrer", children: "read the setup guide in Docs" }), " ", "(opens in a new tab)."] })] }) }));
}
