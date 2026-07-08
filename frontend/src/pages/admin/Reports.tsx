import { FormEvent, useEffect, useMemo, useState } from "react";
import AdminPage from "../../components/AdminPage";
import UserOwnerSelect from "../../components/apiKeys/UserOwnerSelect";
import { api, formatApiError } from "../../api";

type ReportDef = {
  id: string;
  category: string;
  title: string;
  description: string;
  needs_date: boolean;
  params: string[];
};

type ReportOptions = {
  plans: { id: number; name: string }[];
  groups: { id: number; name: string; source: string }[];
  departments: string[];
  offices: string[];
  apps: string[];
  providers: string[];
  models: string[];
  nitro_api_keys: { id: number; name: string }[];
  auth_providers: string[];
  group_by_options: { value: string; label: string }[];
};

type Preview = { columns: string[]; rows: Record<string, unknown>[]; row_count: number };

type ParamState = {
  user_id: number | null;
  plan_id: string;
  department: string;
  office: string;
  group_id: string;
  nitro_api_key_id: string;
  app: string;
  model_id: string;
  provider: string;
  top_n: number;
  threshold_pct: number;
  latency_ms: number;
  inactive_days: number;
  auth_provider: string;
  group_by: string;
};

const emptyParams: ParamState = {
  user_id: null,
  plan_id: "",
  department: "",
  office: "",
  group_id: "",
  nitro_api_key_id: "",
  app: "",
  model_id: "",
  provider: "",
  top_n: 10,
  threshold_pct: 80,
  latency_ms: 10000,
  inactive_days: 30,
  auth_provider: "",
  group_by: "model",
};

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

const DATE_PRESETS = [
  { value: "7", label: "Last 7 days", days: 7 },
  { value: "14", label: "Last 14 days", days: 14 },
  { value: "30", label: "Last 30 days", days: 30 },
  { value: "60", label: "Last 60 days", days: 60 },
  { value: "90", label: "Last 90 days", days: 90 },
  { value: "custom", label: "Custom range", days: null },
] as const;

function applyPresetDays(days: number): { start: string; end: string } {
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - days);
  return { start: isoDate(start), end: isoDate(end) };
}

function applyPreset(preset: string): { start: string; end: string } {
  const entry = DATE_PRESETS.find((p) => p.value === preset);
  if (entry?.days) return applyPresetDays(entry.days);
  return applyPresetDays(30);
}

function presetLabel(preset: string): string {
  return DATE_PRESETS.find((p) => p.value === preset)?.label ?? "Custom range";
}

const token = () => localStorage.getItem("nitro_token");

export default function Reports() {
  const [catalog, setCatalog] = useState<ReportDef[]>([]);
  const [categories, setCategories] = useState<Record<string, string>>({});
  const [options, setOptions] = useState<ReportOptions | null>(null);
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [params, setParams] = useState<ParamState>(emptyParams);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [datePreset, setDatePreset] = useState("30");
  const [format, setFormat] = useState("csv");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api<{ reports: ReportDef[]; categories: Record<string, string>; default_dates: { start_date: string; end_date: string } }>(
      "/api/admin/reports/catalog",
    ).then((data) => {
      setCatalog(data.reports);
      setCategories(data.categories);
      const d = applyPreset("30");
      setStart(d.start);
      setEnd(d.end);
    });
    void api<ReportOptions>("/api/admin/reports/options").then(setOptions).catch(() => {});
  }, []);

  const selected = useMemo(
    () => catalog.find((r) => r.id === selectedId) ?? null,
    [catalog, selectedId],
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return catalog;
    return catalog.filter(
      (r) =>
        r.title.toLowerCase().includes(q) ||
        r.description.toLowerCase().includes(q) ||
        r.id.toLowerCase().includes(q),
    );
  }, [catalog, search]);

  const grouped = useMemo(() => {
    const map = new Map<string, ReportDef[]>();
    for (const r of filtered) {
      const list = map.get(r.category) ?? [];
      list.push(r);
      map.set(r.category, list);
    }
    return map;
  }, [filtered]);

  function buildBody(): Record<string, unknown> {
    if (!selected) return {};
    const body: Record<string, unknown> = {
      report_type: selected.id,
      format,
    };
    if (selected.needs_date || selected.id === "users_no_recent_login") {
      body.start_date = start;
      body.end_date = end;
    }
    if (params.user_id) body.user_id = params.user_id;
    if (params.plan_id) body.plan_id = Number(params.plan_id);
    if (params.department) body.department = params.department;
    if (params.office) body.office = params.office;
    if (params.group_id) body.group_id = Number(params.group_id);
    if (params.nitro_api_key_id) body.nitro_api_key_id = Number(params.nitro_api_key_id);
    if (params.app) body.app = params.app;
    if (params.model_id) body.model_id = params.model_id;
    if (params.provider) body.provider = params.provider;
    if (params.auth_provider) body.auth_provider = params.auth_provider;
    body.top_n = params.top_n;
    body.threshold_pct = params.threshold_pct;
    body.latency_ms = params.latency_ms;
    body.inactive_days = params.inactive_days;
    body.group_by = params.group_by;
    return body;
  }

  function selectReport(id: string) {
    setSelectedId(id);
    setParams(emptyParams);
    setPreview(null);
    setErr("");
  }

  function onPresetChange(preset: string) {
    setDatePreset(preset);
    if (preset !== "custom") {
      const d = applyPreset(preset);
      setStart(d.start);
      setEnd(d.end);
    }
  }

  async function runPreview(e: FormEvent) {
    e.preventDefault();
    if (!selected) return;
    setBusy(true);
    setErr("");
    try {
      const data = await api<Preview>("/api/admin/reports/preview", {
        method: "POST",
        body: JSON.stringify(buildBody()),
      });
      setPreview(data);
    } catch (ex) {
      setErr(formatApiError(ex));
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }

  async function runExport() {
    if (!selected) return;
    setBusy(true);
    setErr("");
    try {
      const res = await fetch("/api/admin/reports/export", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token() ? { Authorization: `Bearer ${token()}` } : {}),
        },
        body: JSON.stringify(buildBody()),
      });
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      const ext = format === "xls" ? "xlsx" : format;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${selected.id}.${ext}`;
      a.click();
    } catch (ex) {
      setErr(formatApiError(ex));
    } finally {
      setBusy(false);
    }
  }

  function renderParam(name: string) {
    if (!options) return null;
    switch (name) {
      case "user":
        return (
          <div key={name}>
            <label>User (optional)</label>
            <UserOwnerSelect
              value={params.user_id}
              onChange={(u) => setParams((p) => ({ ...p, user_id: u?.id ?? null }))}
            />
          </div>
        );
      case "plan":
        return (
          <div key={name}>
            <label>Plan{selected?.id === "plan_usage" ? " *" : " (optional)"}</label>
            <select
              className="input-block"
              value={params.plan_id}
              onChange={(e) => setParams((p) => ({ ...p, plan_id: e.target.value }))}
              required={selected?.id === "plan_usage"}
            >
              {selected?.id !== "plan_usage" && <option value="">All plans</option>}
              {selected?.id === "plan_usage" && <option value="">Select plan…</option>}
              {options.plans.map((p) => (
                <option key={p.id} value={String(p.id)}>{p.name}</option>
              ))}
            </select>
          </div>
        );
      case "department":
        return (
          <div key={name}>
            <label>Department</label>
            <select className="input-block" value={params.department} onChange={(e) => setParams((p) => ({ ...p, department: e.target.value }))}>
              <option value="">Select department…</option>
              {options.departments.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </div>
        );
      case "office":
        return (
          <div key={name}>
            <label>Office (optional)</label>
            <select className="input-block" value={params.office} onChange={(e) => setParams((p) => ({ ...p, office: e.target.value }))}>
              <option value="">All offices</option>
              {options.offices.map((o) => (
                <option key={o} value={o}>{o}</option>
              ))}
            </select>
          </div>
        );
      case "group":
        return (
          <div key={name}>
            <label>Group</label>
            <select className="input-block" value={params.group_id} onChange={(e) => setParams((p) => ({ ...p, group_id: e.target.value }))}>
              <option value="">Select group…</option>
              {options.groups.map((g) => (
                <option key={g.id} value={String(g.id)}>{g.name} ({g.source})</option>
              ))}
            </select>
          </div>
        );
      case "nitro_api_key":
        return (
          <div key={name}>
            <label>API key (optional)</label>
            <select className="input-block" value={params.nitro_api_key_id} onChange={(e) => setParams((p) => ({ ...p, nitro_api_key_id: e.target.value }))}>
              <option value="">All keys</option>
              {options.nitro_api_keys.map((k) => (
                <option key={k.id} value={String(k.id)}>{k.name}</option>
              ))}
            </select>
          </div>
        );
      case "app":
        return (
          <div key={name}>
            <label>Application (optional)</label>
            <select className="input-block" value={params.app} onChange={(e) => setParams((p) => ({ ...p, app: e.target.value }))}>
              <option value="">All apps</option>
              {options.apps.map((a) => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>
          </div>
        );
      case "model":
        return (
          <div key={name}>
            <label>Model (optional)</label>
            <select className="input-block" value={params.model_id} onChange={(e) => setParams((p) => ({ ...p, model_id: e.target.value }))}>
              <option value="">All models</option>
              {options.models.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>
        );
      case "provider":
        return (
          <div key={name}>
            <label>Provider (optional)</label>
            <select className="input-block" value={params.provider} onChange={(e) => setParams((p) => ({ ...p, provider: e.target.value }))}>
              <option value="">All providers</option>
              {options.providers.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
        );
      case "top_n":
        return (
          <div key={name}>
            <label>Top N</label>
            <input type="number" min={1} max={100} className="input-block" value={params.top_n} onChange={(e) => setParams((p) => ({ ...p, top_n: Number(e.target.value) }))} />
          </div>
        );
      case "threshold_pct":
        return (
          <div key={name}>
            <label>Threshold (%)</label>
            <input type="number" min={1} max={100} className="input-block" value={params.threshold_pct} onChange={(e) => setParams((p) => ({ ...p, threshold_pct: Number(e.target.value) }))} />
          </div>
        );
      case "latency_ms":
        return (
          <div key={name}>
            <label>Slow threshold (ms)</label>
            <input type="number" min={1} className="input-block" value={params.latency_ms} onChange={(e) => setParams((p) => ({ ...p, latency_ms: Number(e.target.value) }))} />
          </div>
        );
      case "inactive_days":
        return (
          <div key={name}>
            <label>Inactive days</label>
            <input type="number" min={1} max={365} className="input-block" value={params.inactive_days} onChange={(e) => setParams((p) => ({ ...p, inactive_days: Number(e.target.value) }))} />
          </div>
        );
      case "auth_provider":
        return (
          <div key={name}>
            <label>Auth provider (optional)</label>
            <select className="input-block" value={params.auth_provider} onChange={(e) => setParams((p) => ({ ...p, auth_provider: e.target.value }))}>
              <option value="">All</option>
              {options.auth_providers.map((a) => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>
          </div>
        );
      case "group_by":
        return (
          <div key={name}>
            <label>Group by</label>
            <select className="input-block" value={params.group_by} onChange={(e) => setParams((p) => ({ ...p, group_by: e.target.value }))}>
              {options.group_by_options.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
        );
      default:
        return null;
    }
  }

  return (
    <AdminPage title="Reports">
      {err && <p className="alert alert-error">{err}</p>}

      <div className="search-bar">
        <input placeholder="Search reports…" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      <div className="reports-layout">
        <div className="reports-catalog card">
          {Array.from(grouped.entries()).map(([cat, items]) => (
            <section key={cat} className="reports-catalog__section">
              <h3 className="reports-catalog__heading">{categories[cat] ?? cat}</h3>
              <ul className="reports-catalog__list">
                {items.map((r) => (
                  <li key={r.id}>
                    <button
                      type="button"
                      className={`reports-catalog__item${selectedId === r.id ? " reports-catalog__item--active" : ""}`}
                      onClick={() => selectReport(r.id)}
                    >
                      <strong>{r.title}</strong>
                      <span className="muted-text">{r.description}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>

        <div className="reports-runner card">
          {!selected ? (
            <p className="muted-text">Select a report from the catalog.</p>
          ) : (
            <form onSubmit={runPreview}>
              <h3 style={{ marginTop: 0 }}>{selected.title}</h3>
              <p className="muted-text">{selected.description}</p>

              {selected.needs_date ? (
                <>
                  <label>Period preset</label>
                  <select className="input-block" value={datePreset} onChange={(e) => onPresetChange(e.target.value)}>
                    {DATE_PRESETS.map((p) => (
                      <option key={p.value} value={p.value}>{p.label}</option>
                    ))}
                  </select>
                  {datePreset !== "custom" && start && end ? (
                    <p className="muted-text reports-runner__period">
                      Period: {start} → {end} ({presetLabel(datePreset)})
                    </p>
                  ) : null}
                  {datePreset === "custom" ? (
                    <>
                      <label>Start date</label>
                      <input
                        type="date"
                        className="input-block"
                        value={start}
                        onChange={(e) => setStart(e.target.value)}
                      />
                      <label>End date</label>
                      <input
                        type="date"
                        className="input-block"
                        value={end}
                        onChange={(e) => setEnd(e.target.value)}
                      />
                    </>
                  ) : null}
                </>
              ) : (
                <p className="muted-text reports-runner__snapshot">Snapshot report — date range does not apply.</p>
              )}

              {selected.params.map((p) => renderParam(p))}

              <label>Export format</label>
              <select className="input-block" value={format} onChange={(e) => setFormat(e.target.value)}>
                <option value="csv">CSV</option>
                <option value="xls">Excel</option>
                <option value="pdf">PDF</option>
              </select>

              <div className="dialog-actions">
                <button type="submit" className="btn" disabled={busy}>
                  {busy ? "Loading…" : "Preview"}
                </button>
                <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => void runExport()}>
                  Download
                </button>
              </div>
            </form>
          )}

          {preview && (
            <div className="reports-preview">
              <h4>Preview ({preview.row_count} rows)</h4>
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>{preview.columns.map((c) => <th key={c}>{c}</th>)}</tr>
                  </thead>
                  <tbody>
                    {preview.rows.slice(0, 200).map((row, i) => (
                      <tr key={i}>
                        {preview.columns.map((c) => (
                          <td key={c}>{String(row[c] ?? "")}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {preview.row_count > 200 && (
                <p className="muted-text">Showing first 200 rows in preview.</p>
              )}
            </div>
          )}
        </div>
      </div>
    </AdminPage>
  );
}
