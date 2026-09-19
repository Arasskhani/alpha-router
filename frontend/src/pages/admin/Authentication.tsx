import { FormEvent, useEffect, useRef, useState } from "react";

import AdminPage from "../../components/AdminPage";
import { api } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";
import Tabs, { TabPanel } from "../../components/Tabs";

const LDAPS_PORT = 636;
const SAML_METADATA_MAX_BYTES = 1024 * 1024;

type LdapSimple = {
  enabled: boolean;
  dc_host: string;
  bind_username: string;
  bind_password: string;
  port: number;
  use_ssl: boolean;
  trust_untrusted_cert: boolean;
  sync_ous: string;
  sync_ous_prune: boolean;
  sync_schedule_enabled: boolean;
  sync_schedule_hour: number;
  sync_schedule_minute: number;
};

type SamlCfg = {
  enabled: boolean;
  idp_metadata_url: string;
  idp_metadata_xml: string;
  entity_id: string;
  acs_url: string;
  metadata_url: string;
  attr_username: string;
  attr_email: string;
  attr_display_name: string;
  strict: boolean;
  want_assertions_signed: boolean;
  /** Server-enforced: both flags are locked to true unless ALLOW_INSECURE_SAML. */
  security_locked?: boolean;
};

type OidcCfg = {
  enabled: boolean;
  issuer: string;
  client_id: string;
  client_secret: string;
  redirect_uri: string;
  scopes: string;
  claim_username: string;
  claim_email: string;
  claim_display_name: string;
};

const defaultLdap = (): LdapSimple => ({
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

function normalizeLdap(r: Partial<LdapSimple>): LdapSimple {
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

const defaultSaml = (): SamlCfg => ({
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

const defaultOidc = (): OidcCfg => ({
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
  const [tab, setTab] = useState<"ldap" | "saml" | "oidc">("ldap");
  const [ldap, setLdap] = useState<LdapSimple>(defaultLdap);
  const { confirm } = useConfirm();
  const [saml, setSaml] = useState<SamlCfg>(defaultSaml);
  const [oidc, setOidc] = useState<OidcCfg>(defaultOidc);
  const [msg, setMsg] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [idpXmlFileName, setIdpXmlFileName] = useState("");
  const [loadFailed, setLoadFailed] = useState<string[]>([]);
  const idpXmlInputRef = useRef<HTMLInputElement>(null);

  // Save PUTs the whole form object, so a failed load is not a cosmetic
  // problem: the form would sit on its defaults, look plausible, and write an
  // empty host, empty bind DN and enabled:false over a working directory
  // configuration the moment the admin changed one field. Saving is blocked
  // until every provider has actually been read.
  useEffect(() => {
    let cancelled = false;
    const failures: string[] = [];

    async function load() {
      try {
        const r = await api<LdapSimple>("/api/admin/authentication/ldap");
        if (!cancelled) setLdap(normalizeLdap(r));
      } catch {
        failures.push("Active Directory");
      }
      try {
        const r = await api<SamlCfg>("/api/admin/authentication/saml");
        if (!cancelled) {
          setSaml({
            ...defaultSaml(),
            ...r,
            enabled: Boolean(r.enabled),
            strict: r.strict !== false,
            want_assertions_signed: r.want_assertions_signed !== false,
          });
          setIdpXmlFileName(r.idp_metadata_xml?.trim() ? "Stored IdP metadata XML" : "");
        }
      } catch {
        failures.push("SAML");
      }
      try {
        const r = await api<OidcCfg>("/api/admin/authentication/oidc");
        if (!cancelled) {
          setOidc({
            ...defaultOidc(),
            ...r,
            enabled: Boolean(r.enabled),
            client_secret: r.client_secret || "",
          });
        }
      } catch {
        failures.push("OIDC");
      }
      if (!cancelled) setLoadFailed(failures);
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  async function onIdpMetadataFile(file: File | null) {
    if (!file) return;
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
    } catch {
      setMsg("Could not read the metadata file.");
    }
  }

  function clearIdpMetadataXml() {
    setSaml({ ...saml, idp_metadata_xml: "" });
    setIdpXmlFileName("");
    if (idpXmlInputRef.current) idpXmlInputRef.current.value = "";
  }

  function ldapPayload(): LdapSimple {
    return { ...ldap, port: LDAPS_PORT, use_ssl: true };
  }

  async function saveLdap(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setMsg("");
    try {
      await api("/api/admin/authentication/ldap", {
        method: "PUT",
        body: JSON.stringify(ldapPayload()),
      });
      setMsg("Active Directory settings saved.");
      const refreshed = await api<LdapSimple>("/api/admin/authentication/ldap");
      setLdap(normalizeLdap({ ...refreshed, bind_password: refreshed.bind_password || "********" }));
    } catch (err) {
      setMsg(String(err));
    } finally {
      setSaving(false);
    }
  }

  async function runLdapTest() {
    setTesting(true);
    setMsg("");
    try {
      const res = await api<{ ok: boolean; status: string; encryption?: string; port?: number }>(
        "/api/admin/authentication/ldap/test",
        {
          method: "POST",
          body: JSON.stringify(ldapPayload()),
        },
      );
      const via = res.encryption ? ` via ${res.encryption}` : " via LDAPS";
      const portNote = res.port ? ` (port ${res.port})` : ` (port ${LDAPS_PORT})`;
      setMsg(`Success${via}${portNote}`);
    } catch (e) {
      const text = String(e);
      setMsg(text.toLowerCase().includes("failed") ? text : `Failed: ${text}`);
    } finally {
      setTesting(false);
    }
  }

  async function syncAd() {
    setSyncing(true);
    setMsg("");
    try {
      const r = await api<{ users_synced: number; groups_synced: number }>(
        "/api/admin/authentication/ldap/sync",
        { method: "POST" },
      );
      setMsg(`${r.users_synced} users synced, ${r.groups_synced} groups synced.`);
    } catch (e) {
      setMsg(String(e));
    } finally {
      setSyncing(false);
    }
  }

  function renderSyncSchedule(
    enabled: boolean,
    hour: number,
    minute: number,
    onChange: (patch: { enabled?: boolean; hour?: number; minute?: number }) => void,
  ) {
    return (
      <div className="auth-sync-schedule" style={{ marginTop: 16 }}>
        <h3>Sync schedule</h3>
        <p className="muted-text" style={{ marginTop: 0 }}>
          Automatically sync users and groups on a daily schedule. Manual sync remains available.
        </p>
        <div className="auth-sync-schedule__row">
          <button
            aria-label="Enable scheduled sync"
            type="button"
            className={`alpha-router-toggle${enabled ? " on" : ""}`}
            aria-pressed={enabled}
            onClick={() => onChange({ enabled: !enabled })}
          />
          <span>Enable scheduled sync</span>
        </div>
        <div className="auth-sync-schedule__time">
          <label>
            Hour (0–23)
            <input
              type="number"
              min={0}
              max={23}
              value={hour}
              disabled={!enabled}
              onChange={(e) => onChange({ hour: Math.min(23, Math.max(0, Number(e.target.value || 0))) })}
            />
          </label>
          <label>
            Minute (0–59)
            <input
              type="number"
              min={0}
              max={59}
              value={minute}
              disabled={!enabled}
              onChange={(e) => onChange({ minute: Math.min(59, Math.max(0, Number(e.target.value || 0))) })}
            />
          </label>
        </div>
      </div>
    );
  }

  async function saveSaml(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setMsg("");
    try {
      const res = await api<SamlCfg & { ok?: boolean }>("/api/admin/authentication/saml", {
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
    } catch (err) {
      setMsg(String(err));
    } finally {
      setSaving(false);
    }
  }

  async function saveOidc(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setMsg("");
    try {
      const res = await api<OidcCfg & { ok?: boolean }>("/api/admin/authentication/oidc", {
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
    } catch (err) {
      setMsg(String(err));
    } finally {
      setSaving(false);
    }
  }

  const canTry = ldap.dc_host.trim() && ldap.bind_username.trim();

  return (
    <AdminPage title="Authentication">
      <p style={{ color: "var(--muted)" }}>
        Connect Alpharouter to your corporate directory with a domain controller and service account. Active Directory uses{" "}
        <strong>LDAPS on port 636</strong> only — the Alpharouter container must be able to reach the DC on that port.
      </p>

      {loadFailed.length > 0 && (
        <p className="alert alert-error" role="alert">
          Could not load the current {loadFailed.join(", ")} settings. Saving is disabled so the
          form cannot overwrite them with blanks &mdash; reload the page to try again.
        </p>
      )}
      {msg && <p className="card">{msg}</p>}

      <Tabs
        idBase="auth"
        ariaLabel="Identity providers"
        items={[
          { id: "ldap", label: "Active Directory" },
          { id: "saml", label: "SAML" },
          { id: "oidc", label: "OIDC" },
        ]}
        value={tab}
        onChange={setTab}
      />

      {tab === "ldap" && (
        <TabPanel idBase="auth" id="ldap">
        <form className="card" onSubmit={saveLdap}>
          <label>
            <input
              type="checkbox"
              checked={ldap.enabled}
              onChange={(e) => setLdap({ ...ldap, enabled: e.target.checked })}
            />{" "}
            Enable Active Directory sign-in
          </label>

          <label className="input-block" style={{ marginTop: 12 }}>
            <span className="muted-text">Domain Controller (hostname or IP)</span>
            <input
              value={ldap.dc_host}
              onChange={(e) => setLdap({ ...ldap, dc_host: e.target.value })}
              placeholder="dc01.corp.example.com"
              style={{ width: "100%" }}
              required
            />
          </label>

          <label className="input-block">
            <span className="muted-text">Port</span>
            <input type="text" value={String(LDAPS_PORT)} readOnly disabled style={{ width: "100%" }} />
          </label>

          <label
            className="input-block"
            style={{ display: "flex", alignItems: "center", gap: "0.5rem", opacity: 0.85 }}
          >
            <input type="checkbox" checked disabled readOnly />
            <span className="muted-text">Use LDAPS (port 636)</span>
          </label>

          <label className="input-block" style={{ display: "flex", alignItems: "flex-start", gap: "0.5rem" }}>
            <input
              type="checkbox"
              checked={ldap.trust_untrusted_cert}
              onChange={(e) => setLdap({ ...ldap, trust_untrusted_cert: e.target.checked })}
            />
            <span>
              <span className="muted-text">Support Untrusted Certificate</span>
              <br />
              <span className="muted-text" style={{ fontSize: "0.85rem" }}>
                Accept self-signed or non-CA LDAPS certificates (hostname should still match the directory server).
              </span>
            </span>
          </label>

          <div className="card" style={{ marginTop: 12, background: "var(--surface-2)" }}>
            <h3 style={{ marginTop: 0 }}>LDAPS certificate on the directory server</h3>
            <p className="muted-text" style={{ marginTop: 0 }}>
              Alpharouter connects with LDAPS only. Issue a TLS certificate whose subject or SAN matches the
              directory server FQDN, install it so the directory service can present it on port 636, and ensure
              Alpharouter trusts that certificate (or enable trust for untrusted certificates only for lab use).
            </p>
            <ol className="muted-text" style={{ paddingLeft: "1.25rem", marginBottom: 0 }}>
              <li>
                Create or obtain a certificate for the directory server FQDN using your organization&apos;s CA
                process.
              </li>
              <li>Install the certificate where the directory service expects TLS credentials for LDAPS.</li>
              <li>
                Ensure Alpharouter can validate the certificate chain, or use the untrusted-certificate option
                only in non-production environments.
              </li>
              <li>Confirm LDAPS connectivity on port 636, then use Test in Alpharouter.</li>
            </ol>
          </div>

          <label className="input-block">
            <span className="muted-text">Username (service account)</span>
            <input
              value={ldap.bind_username}
              onChange={(e) => setLdap({ ...ldap, bind_username: e.target.value })}
              placeholder="Administrator or CORP\\Administrator"
              style={{ width: "100%" }}
              autoComplete="off"
              required
            />
            <span className="muted-text" style={{ fontSize: "0.85rem" }}>
              Examples: short name, <strong>DOMAIN\user</strong>, or <strong>user@corp.example.com</strong>
            </span>
          </label>

          <label className="input-block">
            <span className="muted-text">Password</span>
            <input
              type="password"
              value={ldap.bind_password}
              onChange={(e) => setLdap({ ...ldap, bind_password: e.target.value })}
              placeholder={ldap.bind_password === "********" ? "Saved (leave or replace)" : ""}
              style={{ width: "100%" }}
              autoComplete="new-password"
            />
          </label>

          <label className="input-block">
            <span className="muted-text">Sync OUs (optional)</span>
            <textarea
              value={ldap.sync_ous}
              onChange={(e) => setLdap({ ...ldap, sync_ous: e.target.value })}
              placeholder={"OU=Staff,DC=corp,DC=local\nOU=Contractors,DC=corp,DC=local"}
              rows={4}
              style={{ width: "100%", resize: "vertical" }}
            />
            <span className="muted-text" style={{ fontSize: "0.85rem" }}>
              One OU per line. Limits user and group sync to these OUs. Leave empty for the whole domain.
            </span>
          </label>

          <label className="input-block" style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 8 }}>
            <input
              type="checkbox"
              checked={ldap.sync_ous_prune}
              onChange={async (e) => {
                const next = e.target.checked;
                if (next) {
                  const ok = await confirm({
                    title: "Remove users outside Sync OUs?",
                    message:
                      "When enabled, users and groups outside the Sync OUs filter will be removed from Users and Groups on the next sync. Removed users cannot sign in. Users who have signed in to Alpharouter at least once will be moved to Deleted Users (their data stays on the server).",
                    confirmLabel: "Enable removal",
                    cancelLabel: "Cancel",
                    danger: true,
                  });
                  if (!ok) return;
                }
                setLdap({ ...ldap, sync_ous_prune: next });
              }}
            />
            <span>
              Remove users and groups outside Sync OUs on sync
              <br />
              <span className="muted-text" style={{ fontSize: "0.85rem" }}>
                LDAP groups with an assigned budget plan are never auto-removed.
              </span>
            </span>
          </label>

          {renderSyncSchedule(ldap.sync_schedule_enabled, ldap.sync_schedule_hour, ldap.sync_schedule_minute, (patch) =>
            setLdap({
              ...ldap,
              sync_schedule_enabled: patch.enabled ?? ldap.sync_schedule_enabled,
              sync_schedule_hour: patch.hour ?? ldap.sync_schedule_hour,
              sync_schedule_minute: patch.minute ?? ldap.sync_schedule_minute,
            }),
          )}

          <div className="dialog-actions" style={{ marginTop: 12 }}>
            <button className="btn" type="submit" disabled={saving || !canTry || loadFailed.length > 0}>
              {saving ? "Saving…" : "Save"}
            </button>
            <button className="btn btn-ghost" type="button" disabled={!canTry || testing} onClick={() => void runLdapTest()}>
              {testing ? "Testing…" : "Test"}
            </button>
            <button className="btn btn-ghost" type="button" disabled={!ldap.enabled || syncing} onClick={() => void syncAd()}>
              {syncing ? "Syncing…" : "Sync AD"}
            </button>
          </div>
        </form>
        </TabPanel>
      )}

      {tab === "saml" && (
        <TabPanel idBase="auth" id="saml">
        <form className="card" onSubmit={(e) => void saveSaml(e)}>
          <p className="muted-text" style={{ marginTop: 0 }}>
            Alpharouter is a SAML 2.0 Service Provider. Users are created or updated on first successful SSO login (no
            directory sync). Register the ACS URL and SP metadata with your Identity Provider.
          </p>
          <label>
            <input
              type="checkbox"
              checked={saml.enabled}
              onChange={(e) => setSaml({ ...saml, enabled: e.target.checked })}
            />{" "}
            Enable SAML
          </label>

          <label className="input-block" style={{ marginTop: 12 }}>
            <span className="muted-text">IdP Metadata URL (public IdPs only)</span>
            <input
              value={saml.idp_metadata_url}
              onChange={(e) => setSaml({ ...saml, idp_metadata_url: e.target.value })}
              placeholder="https://idp.example.com/metadata"
              style={{ width: "100%" }}
            />
            <span className="muted-text" style={{ fontSize: "0.85rem", display: "block", marginTop: 4 }}>
              Private/loopback hosts are blocked (SSRF protection). For an internal IdP, upload Metadata XML below.
            </span>
          </label>

          <div className="input-block" style={{ marginTop: 8 }}>
            <span className="muted-text">IdP Metadata XML file (recommended for internal IdPs)</span>
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "0.5rem", marginTop: 6 }}>
              <input
                ref={idpXmlInputRef}
                type="file"
                accept=".xml,text/xml,application/xml"
                style={{ display: "none" }}
                onChange={(e) => void onIdpMetadataFile(e.target.files?.[0] ?? null)}
              />
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => idpXmlInputRef.current?.click()}
              >
                Upload metadata XML
              </button>
              {saml.idp_metadata_xml.trim() ? (
                <>
                  <span className="muted-text" style={{ fontSize: "0.9rem" }}>
                    {idpXmlFileName || "XML stored"}
                  </span>
                  <button type="button" className="btn btn-ghost" onClick={clearIdpMetadataXml}>
                    Clear
                  </button>
                </>
              ) : (
                <span className="muted-text" style={{ fontSize: "0.9rem" }}>
                  No file uploaded
                </span>
              )}
            </div>
            <span className="muted-text" style={{ fontSize: "0.85rem", display: "block", marginTop: 4 }}>
              If both URL and file are set, the uploaded XML is used (no outbound fetch).
            </span>
          </div>

          <label className="input-block" style={{ marginTop: 8 }}>
            <span className="muted-text">SP Entity ID</span>
            <input
              value={saml.entity_id}
              onChange={(e) => setSaml({ ...saml, entity_id: e.target.value })}
              placeholder="https://alpha-router.example.com/api/auth/saml/metadata"
              style={{ width: "100%" }}
            />
          </label>

          <label className="input-block" style={{ marginTop: 8 }}>
            <span className="muted-text">ACS URL (fixed)</span>
            <input type="text" value={saml.acs_url || "/api/auth/saml/acs"} readOnly disabled style={{ width: "100%" }} />
          </label>

          <p className="muted-text" style={{ marginTop: 8 }}>
            SP Metadata (public only while SAML is enabled):{" "}
            <a href={saml.metadata_url || "/api/auth/saml/metadata"} target="_blank" rel="noreferrer">
              {saml.metadata_url || "/api/auth/saml/metadata"}
            </a>
          </p>

          <h3 style={{ marginTop: 16 }}>Attribute mapping</h3>
          <label className="input-block">
            <span className="muted-text">Username attribute</span>
            <input
              value={saml.attr_username}
              onChange={(e) => setSaml({ ...saml, attr_username: e.target.value })}
              style={{ width: "100%" }}
            />
          </label>
          <label className="input-block" style={{ marginTop: 8 }}>
            <span className="muted-text">Email attribute</span>
            <input
              value={saml.attr_email}
              onChange={(e) => setSaml({ ...saml, attr_email: e.target.value })}
              style={{ width: "100%" }}
            />
          </label>
          <label className="input-block" style={{ marginTop: 8 }}>
            <span className="muted-text">Display name attribute</span>
            <input
              value={saml.attr_display_name}
              onChange={(e) => setSaml({ ...saml, attr_display_name: e.target.value })}
              style={{ width: "100%" }}
            />
          </label>

          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginTop: 12 }}>
            <input
              type="checkbox"
              checked={saml.want_assertions_signed}
              disabled={saml.security_locked !== false}
              onChange={(e) => setSaml({ ...saml, want_assertions_signed: e.target.checked })}
            />
            <span className="muted-text">Require signed assertions</span>
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginTop: 8 }}>
            <input
              type="checkbox"
              checked={saml.strict}
              disabled={saml.security_locked !== false}
              onChange={(e) => setSaml({ ...saml, strict: e.target.checked })}
            />
            <span className="muted-text">Strict SAML validation</span>
          </label>
          {saml.security_locked !== false && (
            <p className="muted-text" style={{ marginTop: 6, fontSize: "0.85em" }}>
              Signed assertions and strict validation are always on. Only a lab deployment with
              ALLOW_INSECURE_SAML=true can change them.
            </p>
          )}

          <div className="dialog-actions" style={{ marginTop: 12 }}>
            <button className="btn" type="submit" disabled={saving || loadFailed.length > 0}>
              {saving ? "Saving…" : "Save SAML"}
            </button>
          </div>
        </form>
        </TabPanel>
      )}

      {tab === "oidc" && (
        <TabPanel idBase="auth" id="oidc">
        <form className="card" onSubmit={saveOidc}>
          <p className="muted-text">
            Generic OpenID Connect (Authorization Code + PKCE). Users are created or updated on first successful SSO
            login (no directory sync). Redirect URI is fixed by the server — register it exactly on your IdP.
          </p>
          <label>
            <input
              type="checkbox"
              checked={oidc.enabled}
              onChange={(e) => setOidc({ ...oidc, enabled: e.target.checked })}
            />{" "}
            Enable OIDC
          </label>

          <label className="input-block" style={{ marginTop: 12 }}>
            <span className="muted-text">Issuer URL</span>
            <input
              value={oidc.issuer}
              onChange={(e) => setOidc({ ...oidc, issuer: e.target.value })}
              placeholder="https://idp.example.com/realms/alpha-router"
              style={{ width: "100%" }}
            />
            <span className="muted-text" style={{ display: "block", marginTop: 4 }}>
              Discovery: {"{issuer}"}/.well-known/openid-configuration — HTTPS required in production
            </span>
          </label>

          <label className="input-block" style={{ marginTop: 8 }}>
            <span className="muted-text">Client ID</span>
            <input
              value={oidc.client_id}
              onChange={(e) => setOidc({ ...oidc, client_id: e.target.value })}
              style={{ width: "100%" }}
            />
          </label>

          <label className="input-block" style={{ marginTop: 8 }}>
            <span className="muted-text">Client Secret</span>
            <input
              type="password"
              value={oidc.client_secret}
              onChange={(e) => setOidc({ ...oidc, client_secret: e.target.value })}
              placeholder={oidc.client_secret === "********" ? "******** (unchanged)" : ""}
              style={{ width: "100%" }}
              autoComplete="new-password"
            />
            <span className="muted-text" style={{ display: "block", marginTop: 4 }}>
              Stored encrypted. Leave as ******** to keep the existing secret.
            </span>
          </label>

          <label className="input-block" style={{ marginTop: 8 }}>
            <span className="muted-text">Redirect URI (fixed)</span>
            <input
              type="text"
              value={oidc.redirect_uri || "/api/auth/oidc/callback"}
              readOnly
              disabled
              style={{ width: "100%" }}
            />
          </label>

          <label className="input-block" style={{ marginTop: 8 }}>
            <span className="muted-text">Scopes</span>
            <input
              value={oidc.scopes}
              onChange={(e) => setOidc({ ...oidc, scopes: e.target.value })}
              style={{ width: "100%" }}
            />
          </label>

          <h3 style={{ marginTop: 16 }}>Claim mapping</h3>
          <label className="input-block">
            <span className="muted-text">Username claim</span>
            <input
              value={oidc.claim_username}
              onChange={(e) => setOidc({ ...oidc, claim_username: e.target.value })}
              style={{ width: "100%" }}
            />
          </label>
          <label className="input-block" style={{ marginTop: 8 }}>
            <span className="muted-text">Email claim</span>
            <input
              value={oidc.claim_email}
              onChange={(e) => setOidc({ ...oidc, claim_email: e.target.value })}
              style={{ width: "100%" }}
            />
          </label>
          <label className="input-block" style={{ marginTop: 8 }}>
            <span className="muted-text">Display name claim</span>
            <input
              value={oidc.claim_display_name}
              onChange={(e) => setOidc({ ...oidc, claim_display_name: e.target.value })}
              style={{ width: "100%" }}
            />
          </label>

          <div className="dialog-actions" style={{ marginTop: 12 }}>
            <button className="btn" type="submit" disabled={saving || loadFailed.length > 0}>
              {saving ? "Saving…" : "Save OIDC"}
            </button>
          </div>
        </form>
        </TabPanel>
      )}
    </AdminPage>
  );
}
