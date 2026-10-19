import { type FormEvent, useEffect, useState } from "react";

import Modal from "../Modal";
import { api, formatApiError } from "../../api";
import {
  EMPTY_RULE,
  GUARDRAILS_BASE,
  ruleProblem,
  type Channel,
  type GuardrailsMeta,
  type PatternsResponse,
  type Rule,
  type RuleAction,
  type RuleDraft,
  type RuleMode,
  type TrustLevel,
} from "../../lib/guardrails";

type Props = {
  title: string;
  initial?: Rule;
  meta: GuardrailsMeta | null;
  onClose: () => void;
  onSubmit: (draft: RuleDraft) => Promise<void>;
};

function draftOf(rule: Rule | undefined): RuleDraft {
  if (!rule) return { ...EMPTY_RULE };
  return {
    name: rule.name,
    description: rule.description ?? "",
    mode: rule.mode,
    patterns: [...rule.patterns],
    match_mode: rule.match_mode,
    min_matches: rule.min_matches,
    channels: [...rule.channels],
    destinations: [...rule.destinations],
    action: rule.action,
    route_model_id: rule.route_model_id,
    user_message: rule.user_message ?? "",
  };
}

function toggle<T>(list: T[], value: T, on: boolean): T[] {
  return on ? [...list.filter((v) => v !== value), value] : list.filter((v) => v !== value);
}

/** A rule: what to detect, where, for which destinations, and what to do; who it applies to is set apart. */
export default function RuleModal({ title, initial, meta, onClose, onSubmit }: Props) {
  // Mounted afresh for each opening, so it starts from its props.
  const [form, setForm] = useState<RuleDraft>(() => draftOf(initial));
  const [patterns, setPatterns] = useState<PatternsResponse | null>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api<PatternsResponse>(`${GUARDRAILS_BASE}/patterns`)
      .then(setPatterns)
      .catch((e) => setErr(formatApiError(e)));
  }, []);

  const set = <K extends keyof RuleDraft>(key: K, value: RuleDraft[K]) => setForm((f) => ({ ...f, [key]: value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    const problem = ruleProblem(form, meta);
    if (problem) {
      setErr(problem);
      return;
    }
    setSaving(true);
    setErr("");
    try {
      await onSubmit({ ...form, name: form.name.trim(), user_message: form.user_message.trim() });
    } catch (e2) {
      setErr(formatApiError(e2));
    } finally {
      setSaving(false);
    }
  }

  const patternOptions = [
    ...(patterns?.library ?? []).map((p) => ({ ref: p.ref, name: p.name, source: "Library" })),
    ...(patterns?.custom ?? []).map((p) => ({ ref: p.ref, name: p.name, source: "Custom" })),
  ];
  const defaultMessage = meta?.default_messages[form.action] ?? "";

  return (
    <Modal open title={title} onClose={onClose} panelClassName="modal-panel--lg">
      <form className="connection-form guardrails-form" onSubmit={submit}>
        <label className="connection-form__label">
          Name
          <input className="input-block" value={form.name} onChange={(e) => set("name", e.target.value)} required />
        </label>
        <fieldset className="guardrails-fieldset">
          <legend>Mode</legend>
          {(["off", "monitor", "enforce"] as RuleMode[]).map((mode) => (
            <label key={mode} className="guardrails-inline">
              <input type="radio" name="rule-mode" value={mode} checked={form.mode === mode} onChange={() => set("mode", mode)} />{" "}
              {mode === "off" ? "Off" : mode === "monitor" ? "Monitor (record only)" : "Enforce"}
            </label>
          ))}
        </fieldset>

        <fieldset className="guardrails-fieldset">
          <legend>What to detect</legend>
          <div className="guardrails-checklist" role="group" aria-label="Patterns">
            {patternOptions.length === 0 ? <p className="muted-text">Loading patterns…</p> : null}
            {patternOptions.map((p) => (
              <label key={p.ref} className="guardrails-check">
                <input
                  type="checkbox"
                  value={p.ref}
                  checked={form.patterns.includes(p.ref)}
                  onChange={(e) => set("patterns", toggle(form.patterns, p.ref, e.target.checked))}
                />{" "}
                {p.name} <span className="muted-text">· {p.source}</span>
              </label>
            ))}
          </div>
          <div className="guardrails-inline-row">
            <span>Trigger when</span>
            <label className="guardrails-inline">
              <input type="radio" name="match-mode" checked={form.match_mode === "any"} onChange={() => set("match_mode", "any")} /> any
              pattern
            </label>
            <label className="guardrails-inline">
              <input type="radio" name="match-mode" checked={form.match_mode === "all"} onChange={() => set("match_mode", "all")} /> all
              of them
            </label>
            <label className="guardrails-inline">
              at least{" "}
              <input
                type="number"
                min={1}
                max={1000}
                className="guardrails-number"
                aria-label="At least this many matches"
                value={form.min_matches}
                onChange={(e) => set("min_matches", Number(e.target.value))}
              />{" "}
              match(es)
            </label>
          </div>
        </fieldset>

        <fieldset className="guardrails-fieldset">
          <legend>Where</legend>
          <div className="guardrails-checklist guardrails-checklist--columns" role="group" aria-label="Channels">
            {(meta?.channels ?? []).map((c) => (
              <label key={c.key} className="guardrails-check">
                <input
                  type="checkbox"
                  value={c.key}
                  checked={form.channels.includes(c.key)}
                  onChange={(e) => set("channels", toggle<Channel>(form.channels, c.key, e.target.checked))}
                />{" "}
                {c.label}
              </label>
            ))}
          </div>
          <div className="guardrails-inline-row" role="group" aria-label="Destinations">
            <span>Sent to</span>
            {(meta?.trust_levels ?? []).map((t) => (
              <label key={t.key} className="guardrails-inline">
                <input
                  type="checkbox"
                  value={t.key}
                  checked={form.destinations.includes(t.key)}
                  onChange={(e) => set("destinations", toggle<TrustLevel>(form.destinations, t.key, e.target.checked))}
                />{" "}
                {t.label}
              </label>
            ))}
            <span className="muted-text">{form.destinations.length ? "" : "(none ticked: every destination)"}</span>
          </div>
        </fieldset>

        <fieldset className="guardrails-fieldset">
          <legend>Action</legend>
          <div className="guardrails-inline-row">
            {(["redact", "route", "block"] as RuleAction[]).map((action) => (
              <label key={action} className="guardrails-inline">
                <input type="radio" name="rule-action" value={action} checked={form.action === action} onChange={() => set("action", action)} />{" "}
                {action === "redact" ? "Redact (mask the values)" : action === "route" ? "Route to a model" : "Block"}
              </label>
            ))}
          </div>
          {form.action === "route" ? (
            <label className="connection-form__label">
              Model to route to
              <select
                className="input-block"
                value={form.route_model_id ?? ""}
                onChange={(e) => set("route_model_id", e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">Choose a model…</option>
                {(meta?.route_models ?? []).map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label} ({m.trust_level})
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <label className="connection-form__label">
            Message shown to the person
            <textarea
              className="input-block"
              rows={2}
              maxLength={500}
              placeholder={defaultMessage}
              value={form.user_message}
              onChange={(e) => set("user_message", e.target.value)}
            />
            <span className="muted-text connection-form__hint">
              Empty: the default above.{form.action === "route" ? " {model} is replaced by the model's name." : ""}
            </span>
          </label>
        </fieldset>
        <label className="connection-form__label">
          Description (optional)
          <input className="input-block" maxLength={500} value={form.description} onChange={(e) => set("description", e.target.value)} />
        </label>
        {err ? (
          <p className="alert alert-error" role="alert">
            {err}
          </p>
        ) : null}
        <div className="dialog-actions">
          <button type="submit" className="btn" disabled={saving}>
            {saving ? "Saving…" : "Save rule"}
          </button>
          <button type="button" className="btn btn-ghost dialog-actions-cancel" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
}
