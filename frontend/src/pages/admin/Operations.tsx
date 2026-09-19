import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import AdminPage from "../../components/AdminPage";
import OperationsMetricCard, { type OpsSegment } from "../../components/operations/OperationsMetricCard";
import OperationsSlowModelsTable, { type SlowModelRow } from "../../components/operations/OperationsSlowModelsTable";
import OperationsTimeRangeMenu, {
  DEFAULT_OPS_RANGE,
  type OpsRangeKey,
} from "../../components/operations/OperationsTimeRangeMenu";
import { api } from "../../api";
import { formatLocalDateTime } from "../../lib/dateTime";

type OpsFooter = {
  label: string;
  value: number;
  suffix?: string;
};

type OpsCard = {
  title: string;
  total: number;
  unit: string;
  change_pct?: number | null;
  segments: OpsSegment[];
  chart: Record<string, string | number>[];
  footer?: OpsFooter;
};

type OpsTimeRangeInfo = {
  key: string;
  label: string;
  short_badge: string;
  period_short: string;
};

type DashboardPayload = {
  last_checked_at: string | null;
  auto_refresh_interval_seconds: number;
  chart_hours: number;
  time_range: OpsTimeRangeInfo;
  db_engine: string | null;
  cards: {
    cpu: OpsCard;
    memory: OpsCard;
    database: OpsCard;
    errors: OpsCard;
    latency: OpsCard;
    throughput: OpsCard;
    slow_requests: OpsCard;
    p95_vs_prior: OpsCard;
    models_p95: OpsCard;
    code_interpreter: OpsCard;
  };
  model_experience: {
    slow_request_threshold_ms: number;
    slowest_models: SlowModelRow[];
  };
  snapshot_count: number;
  request_log_count: number;
};

type CodeInterpreterCapacityPayload = {
  settings: {
    max_concurrent_turns: number;
    max_per_subject: number;
    retry_after_seconds: number;
    lease_ttl_seconds: number;
    heartbeat_seconds: number;
    hard_max_concurrent_turns: number;
  };
  runtime: {
    active: number;
    available: number;
    limit: number;
    utilization_percent: number;
  };
  /** The ceiling a turn actually meets, across both admission gates. */
  effective: {
    max_concurrent_turns: number;
    available: number;
    utilization_percent: number;
    limited_by: "app" | "broker" | "both";
    mismatch: boolean;
    app_max_concurrent_turns: number;
    broker_max_concurrent: number | null;
  };
  broker: {
    status: string;
    max_concurrent?: number;
    in_use?: number;
    available?: number;
    active_jobs?: number;
    tracked_jobs?: number;
  };
};

function humanSize(bytes: number) {
  if (!bytes) return "0 B";
  let v = bytes;
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(1)} ${units[i]}`;
}

function formatFooter(f?: OpsFooter) {
  if (!f) return undefined;
  const suffix = f.suffix ?? "";
  const val = Number.isInteger(f.value) ? String(f.value) : String(f.value);
  return { label: f.label, value: `${val}${suffix}` };
}

function formatCount(v: number) {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1000) return `${Math.round(v / 1000)}K`;
  return String(Math.round(v));
}

function formatCheckedAt(iso: string | null) {
  if (!iso) return "Never";
  return formatLocalDateTime(iso);
}

function OpsCardView({
  card,
  formatValue,
  footer,
}: {
  card: OpsCard;
  formatValue: (v: number) => string;
  footer?: { label: string; value: string };
}) {
  return (
    <OperationsMetricCard
      title={card.title}
      total={card.total}
      unit={card.unit}
      changePct={card.change_pct}
      segments={card.segments}
      chartRows={card.chart}
      formatValue={formatValue}
      footer={footer}
    />
  );
}

export default function Operations() {
  const [data, setData] = useState<DashboardPayload | null>(null);
  const [capacity, setCapacity] = useState<CodeInterpreterCapacityPayload | null>(null);
  const [build, setBuild] = useState<{ version: string; revision: string } | null>(null);
  const [rangeKey, setRangeKey] = useState<OpsRangeKey>(DEFAULT_OPS_RANGE);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const intervalRef = useRef<number | null>(null);

  const loadCapacity = useCallback(async () => {
    try {
      const payload = await api<CodeInterpreterCapacityPayload>(
        "/api/admin/operations/code-interpreter-capacity",
      );
      setCapacity(payload);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  const load = useCallback(
    async (record: boolean, range: OpsRangeKey) => {
      if (record) setChecking(true);
      else setLoading(true);
      setError("");
      const qs = new URLSearchParams({ range });
      if (record) qs.set("record", "true");
      try {
        const path = record
          ? `/api/admin/operations/check-now?${qs}`
          : `/api/admin/operations/dashboard?${qs}`;
        const payload = record
          ? await api<DashboardPayload>(path, { method: "POST" })
          : await api<DashboardPayload>(path);
        setData(payload);
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
        setChecking(false);
      }
    },
    [],
  );

  useEffect(() => {
    // The running build cannot change while the page is open, so this is not
    // part of the hourly refresh below.
    api<{ version: string; revision: string }>("/api/admin/version")
      .then(setBuild)
      .catch(() => {});
    void load(false, rangeKey);
    void loadCapacity();
    intervalRef.current = window.setInterval(() => {
      void load(false, rangeKey);
      void loadCapacity();
    }, 3600_000);
    return () => {
      if (intervalRef.current) window.clearInterval(intervalRef.current);
    };
  }, [load, loadCapacity, rangeKey]);

  const c = data?.cards;

  return (
    <AdminPage
      title="Operations"
      actions={
        <div className="operations-header-actions">
          <OperationsTimeRangeMenu
            value={rangeKey}
            onChange={setRangeKey}
            disabled={loading || checking}
          />
          <button
            type="button"
            className="btn"
            disabled={checking || loading}
            onClick={() => {
              void load(true, rangeKey);
              void loadCapacity();
            }}
          >
            {checking ? "Checking…" : "Check Now"}
          </button>
        </div>
      }
    >
      <p className="muted-text">
        Infrastructure snapshots (CPU, memory, DB) plus API traffic from <code>request_logs</code> for{" "}
        <strong>{data?.time_range?.label ?? "Past 1 Day"}</strong>. Auto-refreshes every 1 hour. Live DB detail:{" "}
        <Link to="/admin/database">Database</Link> · Usage & cost: <Link to="/admin">Dashboard</Link>.
      </p>
      {data && (
        <p className="operations-meta muted-text">
          Last checked: <strong>{formatCheckedAt(data.last_checked_at)}</strong>
          {data.db_engine && (
            <>
              {" "}
              · Engine: <strong>{data.db_engine}</strong>
            </>
          )}
          {data.snapshot_count > 0 && <> · {data.snapshot_count} infra samples</>}
          {data.request_log_count >= 0 && <> · {formatCount(data.request_log_count)} API log rows</>}
          {build && (
            <>
              {" "}
              · Version:{" "}
              <strong title={build.revision ? `commit ${build.revision}` : undefined}>{build.version}</strong>
            </>
          )}
        </p>
      )}
      {error && <p className="alert alert-error" role="alert">{error}</p>}

      {c && (
        <>
          <h3 className="operations-section-title">Infrastructure</h3>
          <div className="activity-metrics-grid operations-metrics-grid">
            <OpsCardView
              card={c.cpu}
              formatValue={(v) => `${v.toFixed(1)}`}
            />
            <OpsCardView
              card={c.memory}
              formatValue={(v) => `${v.toFixed(1)}`}
              footer={
                c.memory.footer
                  ? { label: c.memory.footer.label, value: humanSize(c.memory.footer.value) }
                  : undefined
              }
            />
            <OpsCardView
              card={c.database}
              formatValue={(v) => `${v.toFixed(2)}`}
              footer={
                c.database.footer
                  ? { label: c.database.footer.label, value: humanSize(c.database.footer.value) }
                  : undefined
              }
            />
          </div>

          <h3 className="operations-section-title">API traffic (request logs)</h3>
          <div className="activity-metrics-grid operations-metrics-grid">
            <OpsCardView card={c.errors} formatValue={(v) => formatCount(v)} footer={formatFooter(c.errors.footer)} />
            <OpsCardView card={c.latency} formatValue={(v) => `${Math.round(v)}`} footer={formatFooter(c.latency.footer)} />
            <OpsCardView
              card={c.throughput}
              formatValue={(v) => formatCount(v)}
              footer={formatFooter(c.throughput.footer)}
            />
          </div>

          <h3 className="operations-section-title">Code Interpreter</h3>
          <p className="muted-text operations-section-lead">
            Turns running and turns refused over the window. The number to set the ceiling from is the peak, not
            what is running at this second.{" "}
            <Link to="/admin/code-interpreter">Limits and workspace settings</Link>.
          </p>
          <div className="activity-metrics-grid operations-metrics-grid">
            <OpsCardView
              card={c.code_interpreter}
              formatValue={(v) => formatCount(v)}
              footer={formatFooter(c.code_interpreter.footer)}
            />
            {capacity && (
              <div className="card operations-capacity-card">
                <div className="operations-capacity-summary">
                  <span>
                    <strong>{capacity.runtime.active}</strong> active
                  </span>
                  <span>
                    <strong>{capacity.effective.available}</strong> available
                  </span>
                  <span>
                    <strong>{capacity.effective.utilization_percent.toFixed(1)}%</strong> utilized
                  </span>
                  <span>
                    <strong>
                      {capacity.broker.status === "ok" ? (capacity.broker.active_jobs ?? 0) : "—"}
                    </strong>{" "}
                    broker jobs
                  </span>
                </div>
                <div className="operations-capacity-track" aria-label="Code Interpreter capacity utilization">
                  <span style={{ width: `${Math.min(100, capacity.effective.utilization_percent)}%` }} />
                </div>
                {capacity.effective.mismatch ? (
                  <p className="alert alert-warning operations-capacity-mismatch">
                    Two ceilings disagree, and the smaller one decides:{" "}
                    <strong>{capacity.effective.max_concurrent_turns}</strong> concurrent turns. The operational
                    limit is {capacity.effective.app_max_concurrent_turns}; the broker is built with{" "}
                    <code>SANDBOX_MAX_CONCURRENT={capacity.effective.broker_max_concurrent}</code>, which only a
                    redeploy changes.
                  </p>
                ) : null}
                <p className="muted-text">
                  Limits: {capacity.settings.max_concurrent_turns} concurrent ·{" "}
                  {capacity.settings.max_per_subject} per user · Retry-After {capacity.settings.retry_after_seconds}s
                  · <Link to="/admin/code-interpreter">edit</Link>
                </p>
              </div>
            )}
          </div>

          <h3 className="operations-section-title">Model experience</h3>
          <p className="muted-text operations-section-lead">
            When users say models feel slow — P95 by model, slow requests (≥{" "}
            {(data.model_experience.slow_request_threshold_ms / 1000).toFixed(0)}s), and comparison to the prior{" "}
            {data.time_range?.period_short ?? "period"}.
          </p>
          <div className="activity-metrics-grid operations-metrics-grid">
            <OpsCardView
              card={c.slow_requests}
              formatValue={(v) => formatCount(v)}
              footer={formatFooter(c.slow_requests.footer)}
            />
            <OpsCardView
              card={c.p95_vs_prior}
              formatValue={(v) => `${Math.round(v)}`}
              footer={formatFooter(c.p95_vs_prior.footer)}
            />
            <OpsCardView
              card={c.models_p95}
              formatValue={(v) => `${Math.round(v)}`}
              footer={formatFooter(c.models_p95.footer)}
            />
          </div>
          <OperationsSlowModelsTable
            rows={data.model_experience.slowest_models}
            thresholdMs={data.model_experience.slow_request_threshold_ms}
          />
        </>
      )}

      {loading && !data && <p className="muted-text">Loading operations dashboard…</p>}
    </AdminPage>
  );
}
