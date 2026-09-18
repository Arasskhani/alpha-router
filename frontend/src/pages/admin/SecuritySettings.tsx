import { FormEvent, useEffect, useMemo, useState } from "react";
import AdminPage from "../../components/AdminPage";
import { api } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";
import { useAdminWriteLock } from "../../lib/adminWriteLock";
import { userHasSuperAdminAccess, type SessionRbac } from "../../lib/rbac";
import {
  canEnableEnforce,
  expiryBannerLevel,
  httpsHealthUrl,
  isReservedHttpsPort,
  parseCidrInput,
  type AdminIpMode,
  type AllowlistEntry,
} from "../../lib/securitySettings";

type AllowlistResponse = {
  mode: AdminIpMode;
  allow_loopback: boolean;
  entries: AllowlistEntry[];
  detected_client_ip: string | null;
  kill_switch: boolean;
  http_bind: string;
};

type TlsCertificate = {
  id: number;
  label: string;
  subject: string;
  issuer: string;
  sans: string[];
  not_after: string | null;
  days_remaining: number | null;
  sha256_fingerprint: string;
  key_algorithm: string;
  key_bits: number;
  is_active: boolean;
  warnings?: string[];
};

type TlsStatus = {
  enabled: boolean;
  https_port: number | null;
  http_mode: "redirect" | "loopback_only";
  hsts: boolean;
  fingerprint?: string | null;
  certificate_id?: number | null;
  days_remaining: number | null;
  http_bind: string;
  http_published_on_all_interfaces: boolean;
  apply_status: { generation?: number; ok?: boolean; error?: string; applied_at?: string } | null;
};

export default function SecuritySettings() {
  const { confirm } = useConfirm();
  const { readOnly, writeLockProps } = useAdminWriteLock();
  const [tab, setTab] = useState<"https" | "ip">("https");
  const [session, setSession] = useState<SessionRbac | null>(null);
  const [msg, setMsg] = useState("");
  const [allowlist, setAllowlist] = useState<AllowlistResponse | null>(null);
  const [cidr, setCidr] = useState("");
  const [label, setLabel] = useState("");
  const [certs, setCerts] = useState<TlsCertificate[]>([]);
  const [tls, setTls] = useState<TlsStatus | null>(null);
  const [httpsPort, setHttpsPort] = useState(443);
  const [httpMode, setHttpMode] = useState<"redirect" | "loopback_only">("loopback_only");
  const [hsts, setHsts] = useState(false);
  const [selectedCertId, setSelectedCertId] = useState<number | null>(null);
  const [certLabel, setCertLabel] = useState("");
  const [certPassword, setCertPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const canWrite = useMemo(
    () => !readOnly && userHasSuperAdminAccess(session?.roles, session?.role),
    [readOnly, session],
  );

  async function load() {
    const [sessionRow, allow, certList, status] = await Promise.all([
      api<SessionRbac>("/api/auth/session"),
      api<AllowlistResponse>("/api/admin/security/ip-allowlist"),
      api<{ items: TlsCertificate[] }>("/api/admin/security/tls/certificates"),
      api<TlsStatus>("/api/admin/security/tls/status"),
    ]);
    setSession(sessionRow);
    setAllowlist(allow);
    setCerts(certList.items);
    setTls(status);
    if (status.https_port) setHttpsPort(status.https_port);
    if (status.http_mode) setHttpMode(status.http_mode);
    setHsts(Boolean(status.hsts));
    const active = certList.items.find((item) => item.is_active) || certList.items[0];
    if (active) setSelectedCertId(active.id);
  }

  useEffect(() => {
    load().catch((err) => setMsg(String(err)));
  }, []);

  async function addCidr(e: FormEvent) {
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
    } catch (err) {
      setMsg(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function addCurrentIp() {
    if (!allowlist?.detected_client_ip) return;
    setCidr(allowlist.detected_client_ip);
    setLabel("This browser");
  }

  async function changeMode(mode: AdminIpMode) {
    if (!allowlist) return;
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
        message:
          "Admin pages and /api/admin will only accept listed IP addresses. If you lose access, use the break-glass CLI on the host.",
        danger: true,
        confirmLabel: "Enforce",
      });
      if (!ok) return;
    }
    setBusy(true);
    try {
      await api("/api/admin/security/ip-allowlist/mode", {
        method: "PUT",
        body: JSON.stringify({ mode }),
      });
      setMsg(`IP restriction mode set to ${mode}.`);
      await load();
    } catch (err) {
      setMsg(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function removeEntry(id: number) {
    const ok = await confirm({
      title: "Remove allowlist entry",
      message: "This IP or CIDR will no longer be allowed when restriction is enforced.",
      danger: true,
      confirmLabel: "Remove",
    });
    if (!ok) return;
    try {
      await api(`/api/admin/security/ip-allowlist/${id}`, { method: "DELETE" });
      await load();
    } catch (e) {
      setMsg(`Could not remove the allowlist entry: ${String(e)}`);
    }
  }

  async function uploadCertificate(e: FormEvent) {
    e.preventDefault();
    const input = document.getElementById("tls-cert-file") as HTMLInputElement | null;
    const file = input?.files?.[0];
    const body = new FormData();
    body.append("label", certLabel);
    body.append("password", certPassword);
    if (file) body.append("file", file);
    setBusy(true);
    try {
      const stored = await api<TlsCertificate>("/api/admin/security/tls/certificates", { method: "POST", body });
      setSelectedCertId(stored.id);
      setCertLabel("");
      setCertPassword("");
      if (input) input.value = "";
      const uploaded = `Certificate uploaded (${stored.sha256_fingerprint.slice(0, 12)}…).`;
      setMsg(stored.warnings?.length ? `${uploaded} ${stored.warnings.join(" ")}` : uploaded);
      await load();
    } catch (err) {
      setMsg(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function activateHttps(e: FormEvent) {
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
    if (!ok) return;
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
      let verified: { ok: boolean; error?: string } = { ok: false, error: "not ready yet" };
      for (let attempt = 0; attempt < 6; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 2500));
        verified = await api<{ ok: boolean; error?: string }>("/api/admin/security/tls/verify", {
          method: "POST",
          body: JSON.stringify({ https_port: httpsPort }),
        });
        if (verified.ok) break;
      }
      setMsg(
        verified.ok
          ? `HTTPS is listening on port ${httpsPort}. Update FRONTEND_URL / API_PUBLIC_URL and bind HTTP to 127.0.0.1 after you confirm.`
          : `HTTPS was requested. Listener check: ${verified.error || "not ready yet"}. Use Revert to HTTP if needed.`,
      );
      await load();
    } catch (err) {
      setMsg(String(err));
    } finally {
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
    if (!ok) return;
    setBusy(true);
    try {
      await api("/api/admin/security/tls/active", { method: "DELETE" });
      setMsg("HTTPS deactivated.");
      await load();
    } catch (err) {
      setMsg(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function deleteCert(id: number) {
    const ok = await confirm({
      title: "Delete certificate",
      message: "The stored certificate and encrypted private key will be removed.",
      danger: true,
      confirmLabel: "Delete",
    });
    if (!ok) return;
    try {
      await api(`/api/admin/security/tls/certificates/${id}`, { method: "DELETE" });
      await load();
    } catch (e) {
      setMsg(`Could not delete the certificate: ${String(e)}`);
    }
  }

  const expiry = expiryBannerLevel(tls?.days_remaining ?? certs.find((c) => c.is_active)?.days_remaining ?? null);
  const health = httpsHealthUrl(window.location.hostname, httpsPort);

  return (
    <AdminPage title="Security Settings">
      <p className="muted-text">
        TLS termination and admin IP restrictions. Write access is Super Admin only. Private keys never leave the
        server.
      </p>
      {msg && <p className="card">{msg}</p>}
      {expiry !== "none" && (
        <p className={expiry === "expired" || expiry === "critical" ? "alert-error" : "alert-warning"}>
          {expiry === "expired"
            ? "The active TLS certificate has expired. HTTPS clients will fail until you replace it."
            : `The active TLS certificate expires in ${tls?.days_remaining ?? "a few"} days. Upload a replacement soon.`}
        </p>
      )}

      <div className="tabs">
        <button type="button" className={`tab ${tab === "https" ? "active" : ""}`} onClick={() => setTab("https")}>
          HTTPS
        </button>
        <button type="button" className={`tab ${tab === "ip" ? "active" : ""}`} onClick={() => setTab("ip")}>
          Admin IP Restrictions
        </button>
      </div>

      {tab === "https" && (
        <>
          <form className="card" onSubmit={uploadCertificate}>
            <h3 style={{ marginTop: 0 }}>Upload certificate</h3>
            <p className="muted-text">PEM (certificate + key, optional chain) or PKCS#12 (.pfx / .p12).</p>
            <label className="input-block">
              <span className="muted-text">Label</span>
              <input value={certLabel} onChange={(e) => setCertLabel(e.target.value)} style={{ width: "100%" }} />
            </label>
            <label className="input-block" style={{ marginTop: 8 }}>
              <span className="muted-text">Certificate file</span>
              <input id="tls-cert-file" type="file" accept=".pem,.crt,.cer,.key,.p12,.pfx,.xml" />
            </label>
            <label className="input-block" style={{ marginTop: 8 }}>
              <span className="muted-text">Passphrase (if the key or PFX is encrypted)</span>
              <input
                type="password"
                value={certPassword}
                onChange={(e) => setCertPassword(e.target.value)}
                style={{ width: "100%" }}
              />
            </label>
            <div className="dialog-actions">
              <button className="btn" type="submit" {...writeLockProps} disabled={!canWrite || busy}>
                Upload
              </button>
            </div>
          </form>

          <div className="card table-wrap">
            <h3 style={{ marginTop: 0 }}>Stored certificates</h3>
            <table>
              <thead>
                <tr>
                  <th></th>
                  <th>Label</th>
                  <th>Subject</th>
                  <th>Expires</th>
                  <th>Fingerprint</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {certs.length === 0 && (
                  <tr>
                    <td colSpan={6} className="muted-text">
                      No certificates uploaded.
                    </td>
                  </tr>
                )}
                {certs.map((cert) => (
                  <tr key={cert.id}>
                    <td>
                      <input
                        type="radio"
                        name="tls-cert"
                        checked={selectedCertId === cert.id}
                        onChange={() => setSelectedCertId(cert.id)}
                        disabled={!canWrite}
                      />
                    </td>
                    <td>
                      {cert.label}
                      {cert.is_active ? " (active)" : ""}
                    </td>
                    <td>{cert.subject}</td>
                    <td>{cert.not_after || "—"}</td>
                    <td>
                      <code>{cert.sha256_fingerprint.slice(0, 16)}…</code>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-ghost"
                        disabled={!canWrite || cert.is_active}
                        onClick={() => deleteCert(cert.id)}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <form className="card" onSubmit={activateHttps}>
            <h3 style={{ marginTop: 0 }}>Activate HTTPS</h3>
            <label className="input-block">
              <span className="muted-text">HTTPS port</span>
              <input
                type="number"
                min={1}
                max={65535}
                value={httpsPort}
                onChange={(e) => setHttpsPort(Number(e.target.value))}
                disabled={!canWrite}
              />
            </label>
            <label className="input-block" style={{ marginTop: 8 }}>
              <span className="muted-text">HTTP mode</span>
              <select
                value={httpMode}
                onChange={(e) => setHttpMode(e.target.value as "redirect" | "loopback_only")}
                disabled={!canWrite}
              >
                <option value="loopback_only">Keep HTTP on 8080 (recommended during cutover)</option>
                <option value="redirect">Also listen on port 80 and redirect to HTTPS</option>
              </select>
            </label>
            <label style={{ display: "block", marginTop: 8 }}>
              <input type="checkbox" checked={hsts} onChange={(e) => setHsts(e.target.checked)} disabled={!canWrite} />{" "}
              Send HSTS from the edge proxy
            </label>
            <p className="muted-text">
              After activation, open <a href={health}>{health}</a> and then set{" "}
              <code>ALPHAROUTER_HTTP_BIND=127.0.0.1</code> so clients cannot skip TLS.
            </p>
            {tls?.http_published_on_all_interfaces && tls.enabled && (
              <p className="alert-warning">
                HTTP is still published on all interfaces ({tls.http_bind}:8080). Bind it to 127.0.0.1 after you confirm
                HTTPS.
              </p>
            )}
            {tls?.apply_status && tls.apply_status.ok === false && (
              <p className="alert-error">Edge proxy failed: {tls.apply_status.error || "unknown error"}</p>
            )}
            <div className="dialog-actions">
              <button className="btn" type="submit" {...writeLockProps} disabled={!canWrite || busy}>
                Activate HTTPS
              </button>
              <button type="button" className="btn btn-ghost dialog-actions-end" disabled={!canWrite || busy} onClick={revertHttp}>
                Revert to HTTP
              </button>
            </div>
          </form>
        </>
      )}

      {tab === "ip" && allowlist && (
        <>
          {allowlist.kill_switch && (
            <p className="alert-warning">
              <code>ADMIN_IP_RESTRICTION_DISABLED</code> is set. The allowlist is not enforced.
            </p>
          )}
          {allowlist.mode === "enforce" && allowlist.http_bind === "0.0.0.0" && (
            <p className="alert-warning">
              HTTP is published on 0.0.0.0:8080. Attackers who can reach that port may bypass an upstream proxy. Bind
              HTTP to 127.0.0.1 after HTTPS is active.
            </p>
          )}
          <div className="card">
            <h3 style={{ marginTop: 0 }}>Restriction mode</h3>
            <p className="muted-text">
              Applies to <code>/admin</code> and <code>/api/admin</code> only. Login and end-user routes stay open.
              Detected IP: <strong>{allowlist.detected_client_ip || "unknown"}</strong>
            </p>
            <div className="dialog-actions">
              {(["off", "monitor", "enforce"] as AdminIpMode[]).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  className={`btn ${allowlist.mode === mode ? "" : "btn-ghost"}`}
                  disabled={!canWrite || busy}
                  onClick={() => changeMode(mode)}
                >
                  {mode}
                </button>
              ))}
            </div>
          </div>
          <form className="card" onSubmit={addCidr}>
            <h3 style={{ marginTop: 0 }}>Add IP or CIDR</h3>
            <input
              placeholder="192.168.1.10 or 10.0.0.0/8"
              value={cidr}
              onChange={(e) => setCidr(e.target.value)}
              style={{ width: "100%", marginBottom: 8 }}
            />
            <input
              placeholder="Label (optional)"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              style={{ width: "100%", marginBottom: 8 }}
            />
            <div className="dialog-actions">
              <button className="btn" type="submit" {...writeLockProps} disabled={!canWrite || busy}>
                Add
              </button>
              <button type="button" className="btn btn-ghost" disabled={!canWrite || !allowlist.detected_client_ip} onClick={addCurrentIp}>
                Add my current IP{allowlist.detected_client_ip ? ` (${allowlist.detected_client_ip})` : ""}
              </button>
            </div>
          </form>
          <div className="card table-wrap">
            <table>
              <thead>
                <tr>
                  <th>CIDR</th>
                  <th>Label</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {allowlist.entries.length === 0 && (
                  <tr>
                    <td colSpan={3} className="muted-text">
                      No allowlist entries yet.
                    </td>
                  </tr>
                )}
                {allowlist.entries.map((entry) => (
                  <tr key={entry.id}>
                    <td>
                      <code>{entry.cidr}</code>
                    </td>
                    <td>{entry.label || "—"}</td>
                    <td>
                      <button type="button" className="btn btn-ghost" disabled={!canWrite} onClick={() => removeEntry(entry.id)}>
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted-text">
            Break-glass: <code>docker compose exec alpha-router python -m app.security_breakglass --disable-admin-ip-restriction</code>
          </p>
        </>
      )}
    </AdminPage>
  );
}
