import { FormEvent, useEffect, useState } from "react";
import AdminPage from "../../components/AdminPage";
import { api } from "../../api";

type Smtp = {
  host: string;
  port: number;
  username: string;
  password: string;
  from_address: string;
  use_tls: boolean;
};

export default function SmtpServer() {
  const [cfg, setCfg] = useState<Smtp>({
    host: "",
    port: 587,
    username: "",
    password: "",
    from_address: "",
    use_tls: true,
  });
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api<Smtp | null>("/api/admin/smtp").then((d) => d && setCfg({ ...cfg, ...d, password: d.password || "" }));
  }, []);

  async function save(e: FormEvent) {
    e.preventDefault();
    await api("/api/admin/smtp", { method: "PUT", body: JSON.stringify(cfg) });
    setMsg("SMTP settings saved.");
  }

  async function testConn(e: FormEvent) {
    e.preventDefault();
    const r = await api<{ ok: boolean; error?: string }>("/api/admin/smtp/test", { method: "POST", body: JSON.stringify(cfg) });
    setMsg(r.ok ? "Connection successful." : `Failed: ${r.error}`);
  }

  return (
    <AdminPage title="SMTP Server">
      <p className="muted-text">Used for scheduled report emails. Only admins configure this; users can only receive reports.</p>
      {msg && <p className="card">{msg}</p>}
      <form className="card" onSubmit={save}>
        <input placeholder="SMTP host" value={cfg.host} onChange={(e) => setCfg({ ...cfg, host: e.target.value })} required style={{ width: "100%", marginBottom: 8 }} />
        <input type="number" placeholder="Port" value={cfg.port} onChange={(e) => setCfg({ ...cfg, port: Number(e.target.value) })} style={{ width: "100%", marginBottom: 8 }} />
        <input placeholder="Username" value={cfg.username} onChange={(e) => setCfg({ ...cfg, username: e.target.value })} style={{ width: "100%", marginBottom: 8 }} />
        <input type="password" placeholder="Password" value={cfg.password} onChange={(e) => setCfg({ ...cfg, password: e.target.value })} style={{ width: "100%", marginBottom: 8 }} />
        <input placeholder="From address" value={cfg.from_address} onChange={(e) => setCfg({ ...cfg, from_address: e.target.value })} required style={{ width: "100%", marginBottom: 8 }} />
        <label><input type="checkbox" checked={cfg.use_tls} onChange={(e) => setCfg({ ...cfg, use_tls: e.target.checked })} /> Use TLS</label>
        <div className="dialog-actions">
          <button className="btn" type="submit">Save</button>
          <button type="button" className="btn btn-ghost dialog-actions-end" onClick={testConn}>
            Test connection
          </button>
        </div>
      </form>
    </AdminPage>
  );
}
