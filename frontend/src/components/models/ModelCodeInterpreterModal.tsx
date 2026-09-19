import { useCallback, useEffect, useState } from "react";

import { api } from "../../api";
import Modal from "../Modal";
import type { CodeInterpreterCompatibility } from "../../lib/chatCodeInterpreterModels";

type CompatibilityEvent = {
  id: number;
  source: string;
  success: boolean;
  reason_code: string | null;
  detail: string | null;
  requested_model_id: string | null;
  created_at: string | null;
};

type CompatibilityDetail = {
  model_id: number;
  external_id: string;
  compatibility: CodeInterpreterCompatibility;
  events: CompatibilityEvent[];
};

type ProbeResponse = {
  ok: boolean;
  reason_code: string | null;
  detail: string | null;
  selected_model_id: string | null;
  compatibility: CodeInterpreterCompatibility;
};

type OverrideChoice = "auto" | "compatible" | "incompatible";

type Props = {
  open: boolean;
  modelId: number | null;
  modelLabel: string;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
};

function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export default function ModelCodeInterpreterModal({
  open,
  modelId,
  modelLabel,
  onClose,
  onSaved,
}: Props) {
  const [detail, setDetail] = useState<CompatibilityDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    if (modelId == null) return;
    setLoading(true);
    setErr("");
    try {
      setDetail(
        await api<CompatibilityDetail>(
          `/api/admin/models/${modelId}/code-interpreter-compatibility`,
        ),
      );
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }, [modelId]);

  useEffect(() => {
    if (!open || modelId == null) return;
    setMsg("");
    void load();
  }, [open, modelId, load]);

  async function applyOverride(override: OverrideChoice) {
    if (modelId == null) return;
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      await api(`/api/admin/models/${modelId}/code-interpreter-compatibility`, {
        method: "PUT",
        body: JSON.stringify({ override }),
      });
      await load();
      await onSaved();
      setMsg(
        override === "auto"
          ? "Automatic detection restored."
          : `Pinned as ${override}.`,
      );
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runProbe() {
    if (modelId == null) return;
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const result = await api<ProbeResponse>(
        `/api/admin/models/${modelId}/code-interpreter-probe`,
        { method: "POST" },
      );
      await load();
      await onSaved();
      setMsg(
        result.ok
          ? `Probe passed${result.selected_model_id ? ` via ${result.selected_model_id}` : ""}.`
          : `Probe failed: ${result.reason_code || "unknown"}`,
      );
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  const compat = detail?.compatibility;
  const override = (compat?.manual_override || "auto") as OverrideChoice;

  return (
    <Modal open={open} title={`Code Interpreter — ${modelLabel}`} onClose={onClose}>
      {err ? <p className="error" role="alert">{err}</p> : null}
      {msg ? <p className="muted-text">{msg}</p> : null}
      {loading ? (
        <p className="muted-text">Loading…</p>
      ) : (
        <>
          <div className="model-compat__summary">
            <div>
              <span className="muted-text">Status</span>
              <strong>{compat?.status || "unknown"}</strong>
            </div>
            <div>
              <span className="muted-text">Health score</span>
              <strong>{compat?.score == null ? "—" : compat.score.toFixed(2)}</strong>
            </div>
            <div>
              <span className="muted-text">Reason</span>
              <strong>{compat?.reason_detail || compat?.reason_code || "—"}</strong>
            </div>
            <div>
              <span className="muted-text">Last probe</span>
              <strong>{formatTime(compat?.last_probe_at)}</strong>
            </div>
            <div>
              <span className="muted-text">Last success</span>
              <strong>{formatTime(compat?.last_success_at)}</strong>
            </div>
            <div>
              <span className="muted-text">Last failure</span>
              <strong>{formatTime(compat?.last_failure_at)}</strong>
            </div>
            <div>
              <span className="muted-text">Next probe</span>
              <strong>{formatTime(compat?.next_probe_at)}</strong>
            </div>
            <div>
              <span className="muted-text">Quarantine until</span>
              <strong>{formatTime(compat?.quarantine_until)}</strong>
            </div>
          </div>

          <p className="muted-text">
            Compatibility is measured automatically. Pin a value only to override the
            measured result for this model.
          </p>
          <div className="dialog-actions" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
            <button type="button" className="btn" disabled={busy} onClick={runProbe}>
              {busy ? "…" : "Run probe now"}
            </button>
            <button
              type="button"
              className={`btn btn-ghost model-compat__choice${
                override === "auto" ? " model-compat__choice--on" : ""
              }`}
              disabled={busy}
              onClick={() => applyOverride("auto")}
            >
              Automatic
            </button>
            <button
              type="button"
              className={`btn btn-ghost model-compat__choice${
                override === "compatible" ? " model-compat__choice--on" : ""
              }`}
              disabled={busy}
              onClick={() => applyOverride("compatible")}
            >
              Force allow
            </button>
            <button
              type="button"
              className={`btn btn-ghost model-compat__choice${
                override === "incompatible" ? " model-compat__choice--on" : ""
              }`}
              disabled={busy}
              onClick={() => applyOverride("incompatible")}
            >
              Force block
            </button>
          </div>

          <h4>Recent evidence</h4>
          {detail?.events?.length ? (
            <div className="table-wrap">
              <table className="card data-table">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Source</th>
                    <th>Result</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.events.map((event) => (
                    <tr key={event.id}>
                      <td>{formatTime(event.created_at)}</td>
                        <td>{event.source}</td>
                        <td>
                          {event.source === "admin"
                            ? "override"
                            : event.success
                              ? "pass"
                              : "fail"}
                        </td>
                      <td>{event.reason_code || event.detail || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted-text">No probe or runtime evidence recorded yet.</p>
          )}
        </>
      )}
    </Modal>
  );
}
