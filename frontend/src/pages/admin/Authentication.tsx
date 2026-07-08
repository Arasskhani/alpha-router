import { FormEvent, useEffect, useRef, useState } from "react";

import AdminPage from "../../components/AdminPage";

import { api } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";



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



type KcCfg = {
  enabled: boolean;
  server_url: string;
  realm: string;
  client_id: string;
  client_secret: string;
  redirect_uri: string;
  admin_client_id: string;
  admin_client_secret: string;
  sync_schedule_enabled: boolean;
  sync_schedule_hour: number;
  sync_schedule_minute: number;
};



function parsePortInput(raw: string): number {
  const digits = raw.replace(/\D/g, "");
  if (!digits) return 0;
  const n = Number.parseInt(digits, 10);
  if (!Number.isFinite(n)) return 0;
  return Math.min(65535, Math.max(0, n));
}

function effectivePort(port: number): number {
  return port > 0 && port <= 65535 ? port : 389;
}

function portFieldValue(port: number): string {
  return port > 0 ? String(port) : "";
}

const PLAIN_LDAP_PORT = 389;
const LDAPS_PORT = 636;

function applyLdapSslToggle(prev: LdapSimple, enabled: boolean, lastPlainPort: number): LdapSimple {
  if (enabled) {
    return { ...prev, use_ssl: true, port: LDAPS_PORT };
  }
  const restore =
    lastPlainPort > 0 && lastPlainPort !== LDAPS_PORT ? lastPlainPort : PLAIN_LDAP_PORT;
  return {
    ...prev,
    use_ssl: false,
    port: prev.port === LDAPS_PORT ? restore : prev.port,
  };
}

function applyLdapPortChange(prev: LdapSimple, port: number, lastPlainPort: number): {
  next: LdapSimple;
  lastPlainPort: number;
} {
  if (port === LDAPS_PORT) {
    return { next: { ...prev, port, use_ssl: true }, lastPlainPort };
  }
  if (port > 0 && port !== LDAPS_PORT) {
    return { next: { ...prev, port, use_ssl: false }, lastPlainPort: port };
  }
  return { next: { ...prev, port }, lastPlainPort };
}

const defaultLdap = (): LdapSimple => ({
  enabled: false,
  dc_host: "",
  bind_username: "",
  bind_password: "",
  port: 389,
  use_ssl: false,
  trust_untrusted_cert: false,
  sync_ous: "",
  sync_ous_prune: false,
  sync_schedule_enabled: false,
  sync_schedule_hour: 3,
  sync_schedule_minute: 0,
});



export default function Authentication() {

  const [tab, setTab] = useState<"ldap" | "keycloak">("ldap");

  const [ldap, setLdap] = useState<LdapSimple>(defaultLdap);
  const { confirm } = useConfirm();
  const lastPlainPortRef = useRef(PLAIN_LDAP_PORT);

  const [kc, setKc] = useState<KcCfg>({
    enabled: false,
    server_url: "",
    realm: "",
    client_id: "",
    client_secret: "",
    redirect_uri: "http://localhost:8080/api/auth/keycloak/callback",
    admin_client_id: "",
    admin_client_secret: "",
    sync_schedule_enabled: false,
    sync_schedule_hour: 3,
    sync_schedule_minute: 0,
  });
  const [msg, setMsg] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [kcSyncing, setKcSyncing] = useState(false);

  const [saving, setSaving] = useState(false);

  const [testing, setTesting] = useState(false);



  useEffect(() => {

    api<LdapSimple>("/api/admin/authentication/ldap").then((r) => {
      const port = r.port && r.port > 0 ? r.port : PLAIN_LDAP_PORT;
      if (port !== LDAPS_PORT) {
        lastPlainPortRef.current = port;
      }
      setLdap({
        enabled: r.enabled,
        dc_host: r.dc_host || "",
        bind_username: r.bind_username || "",
        bind_password: r.bind_password || "",
        port,
        use_ssl: Boolean(r.use_ssl),
        trust_untrusted_cert: Boolean(r.trust_untrusted_cert),
        sync_ous: r.sync_ous || "",
        sync_ous_prune: Boolean(r.sync_ous_prune),
        sync_schedule_enabled: Boolean(r.sync_schedule_enabled),
        sync_schedule_hour: Number.isFinite(r.sync_schedule_hour) ? r.sync_schedule_hour : 3,
        sync_schedule_minute: Number.isFinite(r.sync_schedule_minute) ? r.sync_schedule_minute : 0,
      });
    });
    api<KcCfg>("/api/admin/authentication/keycloak").then((r) =>
      setKc({
        enabled: r.enabled,
        server_url: r.server_url || "",
        realm: r.realm || "",
        client_id: r.client_id || "",
        client_secret: r.client_secret || "",
        redirect_uri: r.redirect_uri || "http://localhost:8080/api/auth/keycloak/callback",
        admin_client_id: r.admin_client_id || "",
        admin_client_secret: r.admin_client_secret || "",
        sync_schedule_enabled: Boolean(r.sync_schedule_enabled),
        sync_schedule_hour: Number.isFinite(r.sync_schedule_hour) ? r.sync_schedule_hour : 3,
        sync_schedule_minute: Number.isFinite(r.sync_schedule_minute) ? r.sync_schedule_minute : 0,
      }),
    );

  }, []);



  function ldapPayload(): LdapSimple {

    return { ...ldap, port: effectivePort(ldap.port) };

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

      const port = refreshed.port && refreshed.port > 0 ? refreshed.port : PLAIN_LDAP_PORT;
      if (port !== LDAPS_PORT) {
        lastPlainPortRef.current = port;
      }
      setLdap({
        enabled: refreshed.enabled,
        dc_host: refreshed.dc_host,
        bind_username: refreshed.bind_username,
        bind_password: refreshed.bind_password || "********",
        port,
        use_ssl: Boolean(refreshed.use_ssl),
        trust_untrusted_cert: Boolean(refreshed.trust_untrusted_cert),
        sync_ous: refreshed.sync_ous || "",
        sync_ous_prune: Boolean(refreshed.sync_ous_prune),
        sync_schedule_enabled: Boolean(refreshed.sync_schedule_enabled),
        sync_schedule_hour: refreshed.sync_schedule_hour ?? 3,
        sync_schedule_minute: refreshed.sync_schedule_minute ?? 0,
      });

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

      const via = res.encryption ? ` via ${res.encryption}` : "";
      const portNote = res.port ? ` (port ${res.port})` : "";
      setMsg(`Success${via}${portNote}`);
      if (res.port && res.port !== ldap.port) {
        setLdap((prev) => ({ ...prev, port: res.port!, use_ssl: res.port === 636 || prev.use_ssl }));
      }

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



  async function syncKc() {
    setKcSyncing(true);
    setMsg("");
    try {
      const r = await api<{ users_synced: number; groups_synced: number; members_linked?: number }>(
        "/api/admin/authentication/keycloak/sync",
        { method: "POST" },
      );
      setMsg(
        `${r.users_synced} users synced, ${r.groups_synced} groups synced` +
          (r.members_linked != null ? `, ${r.members_linked} memberships linked.` : "."),
      );
    } catch (e) {
      setMsg(String(e));
    } finally {
      setKcSyncing(false);
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
        <label className="auth-sync-schedule__row">
          <button
            type="button"
            className={`cgpt-toggle${enabled ? " on" : ""}`}
            aria-pressed={enabled}
            onClick={() => onChange({ enabled: !enabled })}
          />
          <span>Enable scheduled sync</span>
        </label>
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

  async function saveKc(e: FormEvent) {

    e.preventDefault();

    await api("/api/admin/authentication/keycloak", { method: "PUT", body: JSON.stringify(kc) });

    setMsg("Keycloak settings saved.");

  }



  const canTry = ldap.dc_host.trim() && ldap.bind_username.trim();



  return (

    <AdminPage title="Authentication">

      <p style={{ color: "var(--muted)" }}>

        Connect Alpha Router to your corporate directory. For Active Directory you only need the domain controller and a

        service account — encryption and LDAP paths are configured automatically.

      </p>

      {msg && <p className="card">{msg}</p>}



      <div className="tabs">

        <button type="button" className={`tab ${tab === "ldap" ? "active" : ""}`} onClick={() => setTab("ldap")}>

          Active Directory

        </button>

        <button type="button" className={`tab ${tab === "keycloak" ? "active" : ""}`} onClick={() => setTab("keycloak")}>

          Keycloak

        </button>

      </div>



      {tab === "ldap" && (

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

            <input

              type="text"

              inputMode="numeric"

              autoComplete="off"

              value={portFieldValue(ldap.port)}

              onChange={(e) => {
                const parsed = parsePortInput(e.target.value);
                if (parsed > 0 && parsed !== LDAPS_PORT) {
                  lastPlainPortRef.current = parsed;
                }
                const { next } = applyLdapPortChange(ldap, parsed, lastPlainPortRef.current);
                setLdap(next);
              }}

              placeholder="389"

              style={{ width: "100%" }}

            />

            <span className="muted-text" style={{ fontSize: "0.85rem" }}>

              Use <strong>389</strong> for plain LDAP or <strong>636</strong> for LDAPS. If the DC requires LDAP signing,
              Alpha Router will try LDAPS automatically when testing from Docker/Linux.

            </span>

          </label>



          <label className="input-block" style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>

            <input

              type="checkbox"

              checked={ldap.use_ssl}

              onChange={(e) => {
                if (e.target.checked && ldap.port > 0 && ldap.port !== LDAPS_PORT) {
                  lastPlainPortRef.current = ldap.port;
                }
                setLdap(applyLdapSslToggle(ldap, e.target.checked, lastPlainPortRef.current));
              }}

            />

            <span className="muted-text">Use LDAPS (port 636)</span>

          </label>



          {ldap.use_ssl && (

          <label className="input-block" style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>

            <input

              type="checkbox"

              checked={ldap.trust_untrusted_cert}

              onChange={(e) => setLdap({ ...ldap, trust_untrusted_cert: e.target.checked })}

            />

            <span className="muted-text">Support Untrusted Certificate</span>

            <span className="muted-text" style={{ fontSize: "0.85rem" }}>

              Accept self-signed or non-CA LDAPS certificates (hostname should still match the DC).

            </span>

          </label>

          )}



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

              One OU per line. Limits user and group sync when prune is enabled. Leave empty for all users.

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
                      "When enabled, users and groups outside the Sync OUs filter will be removed from Users and Groups on the next sync. Removed users cannot sign in. Users who have signed in to Alpha Router at least once will be moved to Deleted Users (their data stays on the server).",
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

            <button className="btn" type="submit" disabled={saving || !canTry}>

              {saving ? "Saving…" : "Save"}

            </button>

            <button

              className="btn btn-ghost"

              type="button"

              disabled={!canTry || testing}

              onClick={() => void runLdapTest()}

            >

              {testing ? "Testing…" : "Test"}

            </button>

            <button

              className="btn btn-ghost"

              type="button"

              disabled={!ldap.enabled || syncing}

              onClick={() => void syncAd()}

            >

              {syncing ? "Syncing…" : "Sync AD"}

            </button>

          </div>

        </form>

      )}



      {tab === "keycloak" && (

        <form className="card" onSubmit={saveKc}>

          <label>

            <input type="checkbox" checked={kc.enabled} onChange={(e) => setKc({ ...kc, enabled: e.target.checked })} />{" "}

            Enable Keycloak

          </label>

          <input

            placeholder="Server URL"

            value={kc.server_url}

            onChange={(e) => setKc({ ...kc, server_url: e.target.value })}

            style={{ width: "100%", marginTop: 8 }}

          />

          <input

            placeholder="Realm"

            value={kc.realm}

            onChange={(e) => setKc({ ...kc, realm: e.target.value })}

            style={{ width: "100%", marginTop: 8 }}

          />

          <input

            placeholder="Client ID"

            value={kc.client_id}

            onChange={(e) => setKc({ ...kc, client_id: e.target.value })}

            style={{ width: "100%", marginTop: 8 }}

          />

          <input

            type="password"

            placeholder="Client secret"

            value={kc.client_secret}

            onChange={(e) => setKc({ ...kc, client_secret: e.target.value })}

            style={{ width: "100%", marginTop: 8 }}

          />

          <input

            placeholder="Redirect URI"

            value={kc.redirect_uri}

            onChange={(e) => setKc({ ...kc, redirect_uri: e.target.value })}

            style={{ width: "100%", marginTop: 8 }}

          />

          <h3>Admin API (group sync)</h3>

          <input

            placeholder="Admin client ID"

            value={kc.admin_client_id}

            onChange={(e) => setKc({ ...kc, admin_client_id: e.target.value })}

            style={{ width: "100%", marginTop: 8 }}

          />

          <input

            type="password"

            placeholder="Admin client secret"

            value={kc.admin_client_secret}

            onChange={(e) => setKc({ ...kc, admin_client_secret: e.target.value })}

            style={{ width: "100%", marginTop: 8 }}

          />

          {renderSyncSchedule(kc.sync_schedule_enabled, kc.sync_schedule_hour, kc.sync_schedule_minute, (patch) =>
            setKc({
              ...kc,
              sync_schedule_enabled: patch.enabled ?? kc.sync_schedule_enabled,
              sync_schedule_hour: patch.hour ?? kc.sync_schedule_hour,
              sync_schedule_minute: patch.minute ?? kc.sync_schedule_minute,
            }),
          )}

          <div className="dialog-actions" style={{ marginTop: 12 }}>
            <button className="btn" type="submit">
              Save Keycloak
            </button>
            <button
              className="btn btn-ghost"
              type="button"
              disabled={!kc.enabled || kcSyncing}
              onClick={() => void syncKc()}
            >
              {kcSyncing ? "Syncing…" : "Sync Keycloak"}
            </button>
          </div>
        </form>

      )}

    </AdminPage>

  );

}


