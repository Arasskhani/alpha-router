import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import AdminPage from "../../components/AdminPage";
import { api, formatApiError } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";
import { useReadOnly } from "../../context/ReadOnlyContext";

type DeploymentValue = { value: number | null; env: string };

type SettingsPayload = {
  policy: {
    enabled: boolean;
    max_concurrent_turns: number;
    max_per_subject: number;
    retry_after_seconds: number;
  };
  workspace: {
    max_workspace_files: number;
    max_workspace_total_mb: number;
  };
  deployment: {
    hard_max_concurrent_turns: DeploymentValue;
    lease_ttl_seconds: DeploymentValue;
    heartbeat_seconds: DeploymentValue;
    execution_timeout_seconds: DeploymentValue;
    broker_max_concurrent: DeploymentValue;
  };
  effective: {
    max_concurrent_turns: number;
    available: number;
    utilization_percent: number;
    limited_by: "app" | "broker" | "both";
    mismatch: boolean;
    app_max_concurrent_turns: number;
    broker_max_concurrent: number | null;
  };
  broker: { status: string; active_jobs?: number };
};

const SETTINGS_PATH = "/api/admin/operations/code-interpreter-settings";
const POLICY_PATH = "/api/admin/operations/code-interpreter-capacity";
const WORKSPACE_PATH = "/api/admin/operations/code-interpreter-workspace";

const DEPLOYMENT_LABELS: Record<keyof SettingsPayload["deployment"], string> = {
  hard_max_concurrent_turns: "Hard ceiling on concurrent turns",
  lease_ttl_seconds: "Turn lease TTL",
  heartbeat_seconds: "Lease heartbeat",
  execution_timeout_seconds: "Execution timeout",
  broker_max_concurrent: "Broker concurrent sandboxes",
};

/**
 * Everything that governs Code Interpreter, in one place.
 *
 * The settings used to be split across three pages under two permissions —
 * concurrency on Operations, workspace limits on Storage Management, and the
 * deployment ceilings nowhere at all — so tuning the feature meant knowing
 * which page held which half. Operations keeps the live chart and links here.
 *
 * The three families are kept visibly apart because they have different
 * owners: policy an administrator changes at any time, workspace limits the
 * same, and deployment values only a redeploy.
 */
export default function CodeInterpreter() {
  const readOnly = useReadOnly();
  const { confirm } = useConfirm();
  const [data, setData] = useState<SettingsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [maxTurns, setMaxTurns] = useState(200);
  const [perSubject, setPerSubject] = useState(2);
  const [retryAfter, setRetryAfter] = useState(30);
  const [savingPolicy, setSavingPolicy] = useState(false);

  const [workspaceFiles, setWorkspaceFiles] = useState(10);
  const [workspaceMb, setWorkspaceMb] = useState(10);
  const [savingWorkspace, setSavingWorkspace] = useState(false);
  const [togglingSwitch, setTogglingSwitch] = useState(false);

  const apply = useCallback((payload: SettingsPayload) => {
    setData(payload);
    setMaxTurns(payload.policy.max_concurrent_turns);
    setPerSubject(payload.policy.max_per_subject);
    setRetryAfter(payload.policy.retry_after_seconds);
    setWorkspaceFiles(payload.workspace.max_workspace_files);
    setWorkspaceMb(payload.workspace.max_workspace_total_mb);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      apply(await api<SettingsPayload>(SETTINGS_PATH));
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, [apply]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the effect's job is the fetch
    void load();
  }, [load]);

  async function savePolicy(e: FormEvent) {
    e.preventDefault();
    setSavingPolicy(true);
    setError("");
    setNotice("");
    try {
      await api(POLICY_PATH, {
        method: "PATCH",
        body: JSON.stringify({
          max_concurrent_turns: maxTurns,
          max_per_subject: perSubject,
          retry_after_seconds: retryAfter,
        }),
      });
      apply(await api<SettingsPayload>(SETTINGS_PATH));
      setNotice("Concurrency limits saved.");
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setSavingPolicy(false);
    }
  }

  async function saveWorkspace(e: FormEvent) {
    e.preventDefault();
    setSavingWorkspace(true);
    setError("");
    setNotice("");
    try {
      apply(
        await api<SettingsPayload>(WORKSPACE_PATH, {
          method: "PATCH",
          body: JSON.stringify({
            max_workspace_files: workspaceFiles,
            max_workspace_total_mb: workspaceMb,
          }),
        }),
      );
      setNotice("Workspace limits saved.");
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setSavingWorkspace(false);
    }
  }

  async function toggleEnabled() {
    if (!data) return;
    const turningOff = data.policy.enabled;
    if (turningOff) {
      const ok = await confirm({
        title: "Turn off Code Interpreter?",
        message:
          "New turns will be refused for everyone until it is turned back on. Turns already running keep going and finish normally.",
        confirmLabel: "Turn off",
        cancelLabel: "Cancel",
        danger: true,
      });
      if (ok !== true) return;
    }
    setTogglingSwitch(true);
    setError("");
    setNotice("");
    try {
      await api(POLICY_PATH, { method: "PATCH", body: JSON.stringify({ enabled: !data.policy.enabled }) });
      apply(await api<SettingsPayload>(SETTINGS_PATH));
      setNotice(turningOff ? "Code Interpreter is off." : "Code Interpreter is on.");
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setTogglingSwitch(false);
    }
  }

  const busy = savingPolicy || savingWorkspace || togglingSwitch;

  return (
    <AdminPage
      title="Code Interpreter"
      actions={
        <button type="button" className="btn btn-ghost" onClick={() => void load()} disabled={loading || busy}>
          {loading ? "…" : "Refresh"}
        </button>
      }
    >
      <p className="muted-text">
        Who may run code, how much of it may run at once, and what a turn may carry into the sandbox. Live
        utilisation and the refusal history are on <Link to="/admin/operations">Operations</Link>; model-by-model
        compatibility is on <Link to="/admin/models">Models</Link>.
      </p>

      {error ? (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="alert alert-success" role="status">
          {notice}
        </p>
      ) : null}

      {data ? (
        <>
          <h3 className="admin-section-title">Availability</h3>
          <div className="card code-interpreter-switch">
            <div>
              <strong>{data.policy.enabled ? "On" : "Off"}</strong>
              <p className="muted-text">
                {data.policy.enabled
                  ? "Turns are being admitted. Turning this off refuses new turns with a clear message and lets the ones already running finish."
                  : "New turns are refused for everyone. Nothing else about the configuration has changed."}
              </p>
            </div>
            <button
              type="button"
              className={data.policy.enabled ? "btn btn-danger" : "btn"}
              onClick={() => void toggleEnabled()}
              disabled={readOnly || busy}
            >
              {togglingSwitch ? "…" : data.policy.enabled ? "Turn off" : "Turn on"}
            </button>
          </div>

          <h3 className="admin-section-title">Concurrency</h3>
          {data.effective.mismatch ? (
            <p className="alert alert-warning">
              Two ceilings guard this and the smaller one decides:{" "}
              <strong>{data.effective.max_concurrent_turns}</strong> concurrent turns. The operational limit below
              is {data.effective.app_max_concurrent_turns}; the broker is built with{" "}
              <code>SANDBOX_MAX_CONCURRENT={String(data.effective.broker_max_concurrent)}</code>. Raising the number
              below past the broker&apos;s does nothing.
            </p>
          ) : null}
          <form className="card code-interpreter-form" onSubmit={savePolicy}>
            <label htmlFor="ci-max-turns">
              Concurrent turns
              <input
                id="ci-max-turns"
                type="number"
                min={1}
                max={data.deployment.hard_max_concurrent_turns.value ?? 200}
                value={maxTurns}
                onChange={(e) => setMaxTurns(Number(e.target.value))}
                disabled={readOnly || busy}
              />
            </label>
            <label htmlFor="ci-per-subject">
              Per user / API key
              <input
                id="ci-per-subject"
                type="number"
                min={1}
                max={maxTurns}
                value={perSubject}
                onChange={(e) => setPerSubject(Number(e.target.value))}
                disabled={readOnly || busy}
              />
            </label>
            <label htmlFor="ci-retry-after">
              Retry-After (seconds)
              <input
                id="ci-retry-after"
                type="number"
                min={1}
                max={300}
                value={retryAfter}
                onChange={(e) => setRetryAfter(Number(e.target.value))}
                disabled={readOnly || busy}
              />
            </label>
            <button className="btn" disabled={readOnly || busy}>
              {savingPolicy ? "Saving…" : "Save concurrency"}
            </button>
          </form>
          <p className="muted-text">
            Requests above the limit are refused at once with HTTP 429 and the Retry-After above — there is no
            queue. Set the ceiling from a load test, not from the number of signed-in users; each turn is a
            container.
          </p>

          <h3 className="admin-section-title">Workspace</h3>
          <form className="card code-interpreter-form" onSubmit={saveWorkspace}>
            <label htmlFor="ci-workspace-files">
              Files per turn
              <input
                id="ci-workspace-files"
                type="number"
                min={1}
                max={1000}
                value={workspaceFiles}
                onChange={(e) => setWorkspaceFiles(Number(e.target.value))}
                disabled={readOnly || busy}
              />
            </label>
            <label htmlFor="ci-workspace-mb">
              Total size (MB)
              <input
                id="ci-workspace-mb"
                type="number"
                min={1}
                max={1024}
                value={workspaceMb}
                onChange={(e) => setWorkspaceMb(Number(e.target.value))}
                disabled={readOnly || busy}
              />
            </label>
            <button className="btn" disabled={readOnly || busy}>
              {savingWorkspace ? "Saving…" : "Save workspace"}
            </button>
          </form>
          <p className="muted-text">
            The same two limits appear on <Link to="/admin/storage-management">Storage Management</Link> beside the
            other transfer ceilings; saving in either place changes the same setting.
          </p>

          <h3 className="admin-section-title">Set at deploy</h3>
          <p className="muted-text">
            Fixed when the containers are built. Change them in <code>.env</code> and redeploy.
          </p>
          <div className="table-wrap">
            <table className="card data-table">
              <thead>
                <tr>
                  <th>Setting</th>
                  <th>Value</th>
                  <th>Environment variable</th>
                </tr>
              </thead>
              <tbody>
                {(Object.keys(DEPLOYMENT_LABELS) as (keyof SettingsPayload["deployment"])[]).map((key) => (
                  <tr key={key}>
                    <td>{DEPLOYMENT_LABELS[key]}</td>
                    <td>{data.deployment[key].value ?? "—"}</td>
                    <td>
                      <code>{data.deployment[key].env}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </AdminPage>
  );
}
