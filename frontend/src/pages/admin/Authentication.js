import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import AdminPage from "../../components/AdminPage";
import { api } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";
const LDAPS_PORT = 636;
const SAML_METADATA_MAX_BYTES = 1024 * 1024;
const defaultLdap = () => ({
    enabled: false,
    dc_host: "",
    bind_username: "",
    bind_password: "",
    port: LDAPS_PORT,
    use_ssl: true,
    trust_untrusted_cert: false,
    sync_ous: "",
    sync_ous_prune: false,
    sync_schedule_enabled: false,
    sync_schedule_hour: 3,
    sync_schedule_minute: 0,
});
function normalizeLdap(r) {
    return {
        enabled: Boolean(r.enabled),
        dc_host: r.dc_host || "",
        bind_username: r.bind_username || "",
        bind_password: r.bind_password || "",
        port: LDAPS_PORT,
        use_ssl: true,
        trust_untrusted_cert: Boolean(r.trust_untrusted_cert),
        sync_ous: r.sync_ous || "",
        sync_ous_prune: Boolean(r.sync_ous_prune),
        sync_schedule_enabled: Boolean(r.sync_schedule_enabled),
        sync_schedule_hour: Number.isFinite(r.sync_schedule_hour) ? Number(r.sync_schedule_hour) : 3,
        sync_schedule_minute: Number.isFinite(r.sync_schedule_minute) ? Number(r.sync_schedule_minute) : 0,
    };
}
const defaultSaml = () => ({
    enabled: false,
    idp_metadata_url: "",
    idp_metadata_xml: "",
    entity_id: "",
    acs_url: "/api/auth/saml/acs",
    metadata_url: "/api/auth/saml/metadata",
    attr_username: "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
    attr_email: "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
    attr_display_name: "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname",
    strict: true,
    want_assertions_signed: true,
});
const defaultOidc = () => ({
    enabled: false,
    issuer: "",
    client_id: "",
    client_secret: "",
    redirect_uri: "/api/auth/oidc/callback",
    scopes: "openid profile email",
    claim_username: "preferred_username",
    claim_email: "email",
    claim_display_name: "name",
});
export default function Authentication() {
    const [tab, setTab] = useState("ldap");
    const [ldap, setLdap] = useState(defaultLdap);
    const { confirm } = useConfirm();
    const [saml, setSaml] = useState(defaultSaml);
    const [oidc, setOidc] = useState(defaultOidc);
    const [msg, setMsg] = useState("");
    const [syncing, setSyncing] = useState(false);
    const [saving, setSaving] = useState(false);
    const [testing, setTesting] = useState(false);
    const [idpXmlFileName, setIdpXmlFileName] = useState("");
    const idpXmlInputRef = useRef(null);
    useEffect(() => {
        api("/api/admin/authentication/ldap").then((r) => setLdap(normalizeLdap(r)));
        api("/api/admin/authentication/saml").then((r) => {
            setSaml({
                ...defaultSaml(),
                ...r,
                enabled: Boolean(r.enabled),
                strict: r.strict !== false,
                want_assertions_signed: r.want_assertions_signed !== false,
            });
            setIdpXmlFileName(r.idp_metadata_xml?.trim() ? "Stored IdP metadata XML" : "");
        });
        api("/api/admin/authentication/oidc").then((r) => {
            setOidc({
                ...defaultOidc(),
                ...r,
                enabled: Boolean(r.enabled),
                client_secret: r.client_secret || "",
            });
        });
    }, []);
    async function onIdpMetadataFile(file) {
        if (!file)
            return;
        const lower = file.name.toLowerCase();
        if (!lower.endsWith(".xml") && file.type !== "text/xml" && file.type !== "application/xml") {
            setMsg("Please upload an .xml metadata file.");
            return;
        }
        if (file.size > SAML_METADATA_MAX_BYTES) {
            setMsg("Metadata file is too large (max 1 MB).");
            return;
        }
        try {
            const text = await file.text();
            const trimmed = text.trim();
            if (!trimmed.startsWith("<") || !/EntityDescriptor/i.test(trimmed)) {
                setMsg("File does not look like SAML IdP metadata XML.");
                return;
            }
            setSaml({ ...saml, idp_metadata_xml: trimmed });
            setIdpXmlFileName(file.name);
            setMsg("");
        }
        catch {
            setMsg("Could not read the metadata file.");
        }
    }
    function clearIdpMetadataXml() {
        setSaml({ ...saml, idp_metadata_xml: "" });
        setIdpXmlFileName("");
        if (idpXmlInputRef.current)
            idpXmlInputRef.current.value = "";
    }
    function ldapPayload() {
        return { ...ldap, port: LDAPS_PORT, use_ssl: true };
    }
    async function saveLdap(e) {
        e.preventDefault();
        setSaving(true);
        setMsg("");
        try {
            await api("/api/admin/authentication/ldap", {
                method: "PUT",
                body: JSON.stringify(ldapPayload()),
            });
            setMsg("Active Directory settings saved.");
            const refreshed = await api("/api/admin/authentication/ldap");
            setLdap(normalizeLdap({ ...refreshed, bind_password: refreshed.bind_password || "********" }));
        }
        catch (err) {
            setMsg(String(err));
        }
        finally {
            setSaving(false);
        }
    }
    async function runLdapTest() {
        setTesting(true);
        setMsg("");
        try {
            const res = await api("/api/admin/authentication/ldap/test", {
                method: "POST",
                body: JSON.stringify(ldapPayload()),
            });
            const via = res.encryption ? ` via ${res.encryption}` : " via LDAPS";
            const portNote = res.port ? ` (port ${res.port})` : ` (port ${LDAPS_PORT})`;
            setMsg(`Success${via}${portNote}`);
        }
        catch (e) {
            const text = String(e);
            setMsg(text.toLowerCase().includes("failed") ? text : `Failed: ${text}`);
        }
        finally {
            setTesting(false);
        }
    }
    async function syncAd() {
        setSyncing(true);
        setMsg("");
        try {
            const r = await api("/api/admin/authentication/ldap/sync", { method: "POST" });
            setMsg(`${r.users_synced} users synced, ${r.groups_synced} groups synced.`);
        }
        catch (e) {
            setMsg(String(e));
        }
        finally {
            setSyncing(false);
        }
    }
    function renderSyncSchedule(enabled, hour, minute, onChange) {
        return (_jsxs("div", { className: "auth-sync-schedule", style: { marginTop: 16 }, children: [_jsx("h3", { children: "Sync schedule" }), _jsx("p", { className: "muted-text", style: { marginTop: 0 }, children: "Automatically sync users and groups on a daily schedule. Manual sync remains available." }), _jsxs("label", { className: "auth-sync-schedule__row", children: [_jsx("button", { type: "button", className: `alpha-router-toggle${enabled ? " on" : ""}`, "aria-pressed": enabled, onClick: () => onChange({ enabled: !enabled }) }), _jsx("span", { children: "Enable scheduled sync" })] }), _jsxs("div", { className: "auth-sync-schedule__time", children: [_jsxs("label", { children: ["Hour (0\u201323)", _jsx("input", { type: "number", min: 0, max: 23, value: hour, disabled: !enabled, onChange: (e) => onChange({ hour: Math.min(23, Math.max(0, Number(e.target.value || 0))) }) })] }), _jsxs("label", { children: ["Minute (0\u201359)", _jsx("input", { type: "number", min: 0, max: 59, value: minute, disabled: !enabled, onChange: (e) => onChange({ minute: Math.min(59, Math.max(0, Number(e.target.value || 0))) }) })] })] })] }));
    }
    async function saveSaml(e) {
        e.preventDefault();
        setSaving(true);
        setMsg("");
        try {
            const res = await api("/api/admin/authentication/saml", {
                method: "PUT",
                body: JSON.stringify({
                    enabled: saml.enabled,
                    idp_metadata_url: saml.idp_metadata_url,
                    idp_metadata_xml: saml.idp_metadata_xml,
                    entity_id: saml.entity_id,
                    attr_username: saml.attr_username,
                    attr_email: saml.attr_email,
                    attr_display_name: saml.attr_display_name,
                    strict: saml.strict,
                    want_assertions_signed: saml.want_assertions_signed,
                }),
            });
            setSaml({
                ...defaultSaml(),
                ...res,
                enabled: Boolean(res.enabled),
                strict: res.strict !== false,
                want_assertions_signed: res.want_assertions_signed !== false,
            });
            setIdpXmlFileName(res.idp_metadata_xml?.trim() ? idpXmlFileName || "Stored IdP metadata XML" : "");
            setMsg("SAML settings saved.");
        }
        catch (err) {
            setMsg(String(err));
        }
        finally {
            setSaving(false);
        }
    }
    async function saveOidc(e) {
        e.preventDefault();
        setSaving(true);
        setMsg("");
        try {
            const res = await api("/api/admin/authentication/oidc", {
                method: "PUT",
                body: JSON.stringify({
                    enabled: oidc.enabled,
                    issuer: oidc.issuer,
                    client_id: oidc.client_id,
                    client_secret: oidc.client_secret || "********",
                    scopes: oidc.scopes,
                    claim_username: oidc.claim_username,
                    claim_email: oidc.claim_email,
                    claim_display_name: oidc.claim_display_name,
                }),
            });
            setOidc({
                ...defaultOidc(),
                ...res,
                enabled: Boolean(res.enabled),
                client_secret: res.client_secret || "",
            });
            setMsg("OIDC settings saved.");
        }
        catch (err) {
            setMsg(String(err));
        }
        finally {
            setSaving(false);
        }
    }
    const canTry = ldap.dc_host.trim() && ldap.bind_username.trim();
    return (_jsxs(AdminPage, { title: "Authentication", children: [_jsxs("p", { style: { color: "var(--muted)" }, children: ["Connect Alpharouter to your corporate directory with a domain controller and service account. Active Directory uses", " ", _jsx("strong", { children: "LDAPS on port 636" }), " only \u2014 the Alpharouter container must be able to reach the DC on that port."] }), msg && _jsx("p", { className: "card", children: msg }), _jsxs("div", { className: "tabs", children: [_jsx("button", { type: "button", className: `tab ${tab === "ldap" ? "active" : ""}`, onClick: () => setTab("ldap"), children: "Active Directory" }), _jsx("button", { type: "button", className: `tab ${tab === "saml" ? "active" : ""}`, onClick: () => setTab("saml"), children: "SAML" }), _jsx("button", { type: "button", className: `tab ${tab === "oidc" ? "active" : ""}`, onClick: () => setTab("oidc"), children: "OIDC" })] }), tab === "ldap" && (_jsxs("form", { className: "card", onSubmit: saveLdap, children: [_jsxs("label", { children: [_jsx("input", { type: "checkbox", checked: ldap.enabled, onChange: (e) => setLdap({ ...ldap, enabled: e.target.checked }) }), " ", "Enable Active Directory sign-in"] }), _jsxs("label", { className: "input-block", style: { marginTop: 12 }, children: [_jsx("span", { className: "muted-text", children: "Domain Controller (hostname or IP)" }), _jsx("input", { value: ldap.dc_host, onChange: (e) => setLdap({ ...ldap, dc_host: e.target.value }), placeholder: "dc01.corp.example.com", style: { width: "100%" }, required: true })] }), _jsxs("label", { className: "input-block", children: [_jsx("span", { className: "muted-text", children: "Port" }), _jsx("input", { type: "text", value: String(LDAPS_PORT), readOnly: true, disabled: true, style: { width: "100%" } })] }), _jsxs("label", { className: "input-block", style: { display: "flex", alignItems: "center", gap: "0.5rem", opacity: 0.85 }, children: [_jsx("input", { type: "checkbox", checked: true, disabled: true, readOnly: true }), _jsx("span", { className: "muted-text", children: "Use LDAPS (port 636)" })] }), _jsxs("label", { className: "input-block", style: { display: "flex", alignItems: "flex-start", gap: "0.5rem" }, children: [_jsx("input", { type: "checkbox", checked: ldap.trust_untrusted_cert, onChange: (e) => setLdap({ ...ldap, trust_untrusted_cert: e.target.checked }) }), _jsxs("span", { children: [_jsx("span", { className: "muted-text", children: "Support Untrusted Certificate" }), _jsx("br", {}), _jsx("span", { className: "muted-text", style: { fontSize: "0.85rem" }, children: "Accept self-signed or non-CA LDAPS certificates (hostname should still match the directory server)." })] })] }), _jsxs("div", { className: "card", style: { marginTop: 12, background: "var(--surface-2, transparent)" }, children: [_jsx("h3", { style: { marginTop: 0 }, children: "LDAPS certificate on the directory server" }), _jsx("p", { className: "muted-text", style: { marginTop: 0 }, children: "Alpharouter connects with LDAPS only. Issue a TLS certificate whose subject or SAN matches the directory server FQDN, install it so the directory service can present it on port 636, and ensure Alpharouter trusts that certificate (or enable trust for untrusted certificates only for lab use)." }), _jsxs("ol", { className: "muted-text", style: { paddingLeft: "1.25rem", marginBottom: 0 }, children: [_jsx("li", { children: "Create or obtain a certificate for the directory server FQDN using your organization's CA process." }), _jsx("li", { children: "Install the certificate where the directory service expects TLS credentials for LDAPS." }), _jsx("li", { children: "Ensure Alpharouter can validate the certificate chain, or use the untrusted-certificate option only in non-production environments." }), _jsx("li", { children: "Confirm LDAPS connectivity on port 636, then use Test in Alpharouter." })] })] }), _jsxs("label", { className: "input-block", children: [_jsx("span", { className: "muted-text", children: "Username (service account)" }), _jsx("input", { value: ldap.bind_username, onChange: (e) => setLdap({ ...ldap, bind_username: e.target.value }), placeholder: "Administrator or CORP\\\\Administrator", style: { width: "100%" }, autoComplete: "off", required: true }), _jsxs("span", { className: "muted-text", style: { fontSize: "0.85rem" }, children: ["Examples: short name, ", _jsx("strong", { children: "DOMAIN\\user" }), ", or ", _jsx("strong", { children: "user@corp.example.com" })] })] }), _jsxs("label", { className: "input-block", children: [_jsx("span", { className: "muted-text", children: "Password" }), _jsx("input", { type: "password", value: ldap.bind_password, onChange: (e) => setLdap({ ...ldap, bind_password: e.target.value }), placeholder: ldap.bind_password === "********" ? "Saved (leave or replace)" : "", style: { width: "100%" }, autoComplete: "new-password" })] }), _jsxs("label", { className: "input-block", children: [_jsx("span", { className: "muted-text", children: "Sync OUs (optional)" }), _jsx("textarea", { value: ldap.sync_ous, onChange: (e) => setLdap({ ...ldap, sync_ous: e.target.value }), placeholder: "OU=Staff,DC=corp,DC=local\nOU=Contractors,DC=corp,DC=local", rows: 4, style: { width: "100%", resize: "vertical" } }), _jsx("span", { className: "muted-text", style: { fontSize: "0.85rem" }, children: "One OU per line. Limits user and group sync to these OUs. Leave empty for the whole domain." })] }), _jsxs("label", { className: "input-block", style: { display: "flex", gap: 8, alignItems: "flex-start", marginTop: 8 }, children: [_jsx("input", { type: "checkbox", checked: ldap.sync_ous_prune, onChange: async (e) => {
                                    const next = e.target.checked;
                                    if (next) {
                                        const ok = await confirm({
                                            title: "Remove users outside Sync OUs?",
                                            message: "When enabled, users and groups outside the Sync OUs filter will be removed from Users and Groups on the next sync. Removed users cannot sign in. Users who have signed in to Alpharouter at least once will be moved to Deleted Users (their data stays on the server).",
                                            confirmLabel: "Enable removal",
                                            cancelLabel: "Cancel",
                                            danger: true,
                                        });
                                        if (!ok)
                                            return;
                                    }
                                    setLdap({ ...ldap, sync_ous_prune: next });
                                } }), _jsxs("span", { children: ["Remove users and groups outside Sync OUs on sync", _jsx("br", {}), _jsx("span", { className: "muted-text", style: { fontSize: "0.85rem" }, children: "LDAP groups with an assigned budget plan are never auto-removed." })] })] }), renderSyncSchedule(ldap.sync_schedule_enabled, ldap.sync_schedule_hour, ldap.sync_schedule_minute, (patch) => setLdap({
                        ...ldap,
                        sync_schedule_enabled: patch.enabled ?? ldap.sync_schedule_enabled,
                        sync_schedule_hour: patch.hour ?? ldap.sync_schedule_hour,
                        sync_schedule_minute: patch.minute ?? ldap.sync_schedule_minute,
                    })), _jsxs("div", { className: "dialog-actions", style: { marginTop: 12 }, children: [_jsx("button", { className: "btn", type: "submit", disabled: saving || !canTry, children: saving ? "Saving…" : "Save" }), _jsx("button", { className: "btn btn-ghost", type: "button", disabled: !canTry || testing, onClick: () => void runLdapTest(), children: testing ? "Testing…" : "Test" }), _jsx("button", { className: "btn btn-ghost", type: "button", disabled: !ldap.enabled || syncing, onClick: () => void syncAd(), children: syncing ? "Syncing…" : "Sync AD" })] })] })), tab === "saml" && (_jsxs("form", { className: "card", onSubmit: (e) => void saveSaml(e), children: [_jsx("p", { className: "muted-text", style: { marginTop: 0 }, children: "Alpharouter is a SAML 2.0 Service Provider. Users are created or updated on first successful SSO login (no directory sync). Register the ACS URL and SP metadata with your Identity Provider." }), _jsxs("label", { children: [_jsx("input", { type: "checkbox", checked: saml.enabled, onChange: (e) => setSaml({ ...saml, enabled: e.target.checked }) }), " ", "Enable SAML"] }), _jsxs("label", { className: "input-block", style: { marginTop: 12 }, children: [_jsx("span", { className: "muted-text", children: "IdP Metadata URL (public IdPs only)" }), _jsx("input", { value: saml.idp_metadata_url, onChange: (e) => setSaml({ ...saml, idp_metadata_url: e.target.value }), placeholder: "https://idp.example.com/metadata", style: { width: "100%" } }), _jsx("span", { className: "muted-text", style: { fontSize: "0.85rem", display: "block", marginTop: 4 }, children: "Private/loopback hosts are blocked (SSRF protection). For an internal IdP, upload Metadata XML below." })] }), _jsxs("div", { className: "input-block", style: { marginTop: 8 }, children: [_jsx("span", { className: "muted-text", children: "IdP Metadata XML file (recommended for internal IdPs)" }), _jsxs("div", { style: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: "0.5rem", marginTop: 6 }, children: [_jsx("input", { ref: idpXmlInputRef, type: "file", accept: ".xml,text/xml,application/xml", style: { display: "none" }, onChange: (e) => void onIdpMetadataFile(e.target.files?.[0] ?? null) }), _jsx("button", { type: "button", className: "btn btn-ghost", onClick: () => idpXmlInputRef.current?.click(), children: "Upload metadata XML" }), saml.idp_metadata_xml.trim() ? (_jsxs(_Fragment, { children: [_jsx("span", { className: "muted-text", style: { fontSize: "0.9rem" }, children: idpXmlFileName || "XML stored" }), _jsx("button", { type: "button", className: "btn btn-ghost", onClick: clearIdpMetadataXml, children: "Clear" })] })) : (_jsx("span", { className: "muted-text", style: { fontSize: "0.9rem" }, children: "No file uploaded" }))] }), _jsx("span", { className: "muted-text", style: { fontSize: "0.85rem", display: "block", marginTop: 4 }, children: "If both URL and file are set, the uploaded XML is used (no outbound fetch)." })] }), _jsxs("label", { className: "input-block", style: { marginTop: 8 }, children: [_jsx("span", { className: "muted-text", children: "SP Entity ID" }), _jsx("input", { value: saml.entity_id, onChange: (e) => setSaml({ ...saml, entity_id: e.target.value }), placeholder: "https://alpha-router.example.com/api/auth/saml/metadata", style: { width: "100%" } })] }), _jsxs("label", { className: "input-block", style: { marginTop: 8 }, children: [_jsx("span", { className: "muted-text", children: "ACS URL (fixed)" }), _jsx("input", { type: "text", value: saml.acs_url || "/api/auth/saml/acs", readOnly: true, disabled: true, style: { width: "100%" } })] }), _jsxs("p", { className: "muted-text", style: { marginTop: 8 }, children: ["SP Metadata (public only while SAML is enabled):", " ", _jsx("a", { href: saml.metadata_url || "/api/auth/saml/metadata", target: "_blank", rel: "noreferrer", children: saml.metadata_url || "/api/auth/saml/metadata" })] }), _jsx("h3", { style: { marginTop: 16 }, children: "Attribute mapping" }), _jsxs("label", { className: "input-block", children: [_jsx("span", { className: "muted-text", children: "Username attribute" }), _jsx("input", { value: saml.attr_username, onChange: (e) => setSaml({ ...saml, attr_username: e.target.value }), style: { width: "100%" } })] }), _jsxs("label", { className: "input-block", style: { marginTop: 8 }, children: [_jsx("span", { className: "muted-text", children: "Email attribute" }), _jsx("input", { value: saml.attr_email, onChange: (e) => setSaml({ ...saml, attr_email: e.target.value }), style: { width: "100%" } })] }), _jsxs("label", { className: "input-block", style: { marginTop: 8 }, children: [_jsx("span", { className: "muted-text", children: "Display name attribute" }), _jsx("input", { value: saml.attr_display_name, onChange: (e) => setSaml({ ...saml, attr_display_name: e.target.value }), style: { width: "100%" } })] }), _jsxs("label", { style: { display: "flex", alignItems: "center", gap: "0.5rem", marginTop: 12 }, children: [_jsx("input", { type: "checkbox", checked: saml.want_assertions_signed, onChange: (e) => setSaml({ ...saml, want_assertions_signed: e.target.checked }) }), _jsx("span", { className: "muted-text", children: "Require signed assertions" })] }), _jsxs("label", { style: { display: "flex", alignItems: "center", gap: "0.5rem", marginTop: 8 }, children: [_jsx("input", { type: "checkbox", checked: saml.strict, onChange: (e) => setSaml({ ...saml, strict: e.target.checked }) }), _jsx("span", { className: "muted-text", children: "Strict SAML validation" })] }), _jsx("div", { className: "dialog-actions", style: { marginTop: 12 }, children: _jsx("button", { className: "btn", type: "submit", disabled: saving, children: saving ? "Saving…" : "Save SAML" }) })] })), tab === "oidc" && (_jsxs("form", { className: "card", onSubmit: saveOidc, children: [_jsx("p", { className: "muted-text", children: "Generic OpenID Connect (Authorization Code + PKCE). Users are created or updated on first successful SSO login (no directory sync). Redirect URI is fixed by the server \u2014 register it exactly on your IdP." }), _jsxs("label", { children: [_jsx("input", { type: "checkbox", checked: oidc.enabled, onChange: (e) => setOidc({ ...oidc, enabled: e.target.checked }) }), " ", "Enable OIDC"] }), _jsxs("label", { className: "input-block", style: { marginTop: 12 }, children: [_jsx("span", { className: "muted-text", children: "Issuer URL" }), _jsx("input", { value: oidc.issuer, onChange: (e) => setOidc({ ...oidc, issuer: e.target.value }), placeholder: "https://idp.example.com/realms/alpha-router", style: { width: "100%" } }), _jsxs("span", { className: "muted-text", style: { display: "block", marginTop: 4 }, children: ["Discovery: ", "{issuer}", "/.well-known/openid-configuration \u2014 HTTPS required in production"] })] }), _jsxs("label", { className: "input-block", style: { marginTop: 8 }, children: [_jsx("span", { className: "muted-text", children: "Client ID" }), _jsx("input", { value: oidc.client_id, onChange: (e) => setOidc({ ...oidc, client_id: e.target.value }), style: { width: "100%" } })] }), _jsxs("label", { className: "input-block", style: { marginTop: 8 }, children: [_jsx("span", { className: "muted-text", children: "Client Secret" }), _jsx("input", { type: "password", value: oidc.client_secret, onChange: (e) => setOidc({ ...oidc, client_secret: e.target.value }), placeholder: oidc.client_secret === "********" ? "******** (unchanged)" : "", style: { width: "100%" }, autoComplete: "new-password" }), _jsx("span", { className: "muted-text", style: { display: "block", marginTop: 4 }, children: "Stored encrypted. Leave as ******** to keep the existing secret." })] }), _jsxs("label", { className: "input-block", style: { marginTop: 8 }, children: [_jsx("span", { className: "muted-text", children: "Redirect URI (fixed)" }), _jsx("input", { type: "text", value: oidc.redirect_uri || "/api/auth/oidc/callback", readOnly: true, disabled: true, style: { width: "100%" } })] }), _jsxs("label", { className: "input-block", style: { marginTop: 8 }, children: [_jsx("span", { className: "muted-text", children: "Scopes" }), _jsx("input", { value: oidc.scopes, onChange: (e) => setOidc({ ...oidc, scopes: e.target.value }), style: { width: "100%" } })] }), _jsx("h3", { style: { marginTop: 16 }, children: "Claim mapping" }), _jsxs("label", { className: "input-block", children: [_jsx("span", { className: "muted-text", children: "Username claim" }), _jsx("input", { value: oidc.claim_username, onChange: (e) => setOidc({ ...oidc, claim_username: e.target.value }), style: { width: "100%" } })] }), _jsxs("label", { className: "input-block", style: { marginTop: 8 }, children: [_jsx("span", { className: "muted-text", children: "Email claim" }), _jsx("input", { value: oidc.claim_email, onChange: (e) => setOidc({ ...oidc, claim_email: e.target.value }), style: { width: "100%" } })] }), _jsxs("label", { className: "input-block", style: { marginTop: 8 }, children: [_jsx("span", { className: "muted-text", children: "Display name claim" }), _jsx("input", { value: oidc.claim_display_name, onChange: (e) => setOidc({ ...oidc, claim_display_name: e.target.value }), style: { width: "100%" } })] }), _jsx("div", { className: "dialog-actions", style: { marginTop: 12 }, children: _jsx("button", { className: "btn", type: "submit", disabled: saving, children: saving ? "Saving…" : "Save OIDC" }) })] }))] }));
}
