import { type FormEvent, useState } from "react";

import Modal from "../Modal";
import { api, formatApiError } from "../../api";
import { ACTION_LABELS, GUARDRAILS_BASE, type Channel, type GuardrailsMeta, type TrustLevel } from "../../lib/guardrails";

type TestResult = {
  action: string | null;
  message: string | null;
  masked: string | null;
  rules: {
    id: number;
    name: string;
    mode: string;
    action: string;
    applied: boolean;
    count: number;
    matches: { start: number; end: number; value: string; pattern: string }[];
  }[];
};

/** The text with every find marked, from the matches' offsets. */
function Highlighted({ text, spans }: { text: string; spans: { start: number; end: number }[] }) {
  const sorted = [...spans].sort((a, b) => a.start - b.start);
  const out: React.ReactNode[] = [];
  let cursor = 0;
  sorted.forEach((span, i) => {
    if (span.start < cursor) return;
    out.push(text.slice(cursor, span.start));
    out.push(<mark key={i}>{text.slice(span.start, span.end)}</mark>);
    cursor = span.end;
  });
  out.push(text.slice(cursor));
  return <p className="guardrails-highlight" dir="auto">{out}</p>;
}

/** What the rules would do to a text: monitored rules are tried as if they enforced; nothing is recorded. */
export default function TestTextModal({ meta, onClose }: { meta: GuardrailsMeta | null; onClose: () => void }) {
  const [text, setText] = useState("");
  const [channel, setChannel] = useState<Channel>("chat");
  const [trust, setTrust] = useState<TrustLevel>("public");
  const [result, setResult] = useState<TestResult | null>(null);
  const [tried, setTried] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function run(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      setResult(
        await api<TestResult>(`${GUARDRAILS_BASE}/test`, {
          method: "POST",
          body: JSON.stringify({ text, channel, trust_level: trust }),
        }),
      );
      setTried(text);
    } catch (e2) {
      setErr(formatApiError(e2));
    } finally {
      setBusy(false);
    }
  }

  const spans = result?.rules.flatMap((r) => r.matches) ?? [];
  return (
    <Modal open title="Test a text" onClose={onClose} panelClassName="modal-panel--lg">
      <form className="connection-form guardrails-form" onSubmit={run}>
        <label className="connection-form__label">
          Text
          <textarea className="input-block" rows={5} dir="auto" value={text} onChange={(e) => setText(e.target.value)} />
        </label>
        <div className="guardrails-inline-row">
          <label className="guardrails-inline">
            Channel{" "}
            <select value={channel} onChange={(e) => setChannel(e.target.value as Channel)}>
              {(meta?.channels ?? []).map((c) => (
                <option key={c.key} value={c.key}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          <label className="guardrails-inline">
            Sent to{" "}
            <select value={trust} onChange={(e) => setTrust(e.target.value as TrustLevel)}>
              {(meta?.trust_levels ?? []).map((t) => (
                <option key={t.key} value={t.key}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <span className="muted-text">As a person no rule names: rules for everyone apply.</span>
        </div>
        {err ? <p className="alert alert-error">{err}</p> : null}
        {result ? (
          <div className="guardrails-test-result" data-testid="guardrails-test-result">
            <p>
              <strong>Result:</strong>{" "}
              {result.action ? (
                <span className={`guardrails-action guardrails-action--${result.action}`}>{ACTION_LABELS[result.action]}</span>
              ) : (
                "Nothing would happen: no rule matches."
              )}
            </p>
            {spans.length ? <Highlighted text={tried} spans={spans} /> : null}
            {result.message ? <p className="muted-text">The person would see: {result.message}</p> : null}
            {result.masked ? (
              <p className="muted-text">
                Sent as: <code dir="auto">{result.masked}</code>
              </p>
            ) : null}
            <ul className="guardrails-list">
              {result.rules.map((r) => (
                <li key={r.id}>
                  <span>
                    {r.name} — {ACTION_LABELS[r.action]}
                    {r.mode === "monitor" ? " (monitor only)" : ""}
                    {r.applied ? "" : " (outranked)"}
                  </span>
                  <strong>{r.count}</strong>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <div className="dialog-actions">
          <button type="submit" className="btn" disabled={busy || !text.trim()}>
            {busy ? "Testing…" : "Test"}
          </button>
          <button type="button" className="btn btn-ghost dialog-actions-cancel" onClick={onClose}>
            Close
          </button>
        </div>
      </form>
    </Modal>
  );
}
