import { type FormEvent, useEffect, useState } from "react";

import Modal from "../Modal";
import { api, formatApiError } from "../../api";
import { EMPTY_PATTERN, GUARDRAILS_BASE, lines, words, type GuardrailsMeta, type PatternDraft } from "../../lib/guardrails";

type TestResponse = {
  ok: boolean;
  error: string | null;
  matches: { start: number; end: number; value: string }[];
  problems: string[];
};

type Props = {
  title: string;
  initial?: Partial<PatternDraft>;
  meta: GuardrailsMeta | null;
  onClose: () => void;
  onSubmit: (draft: PatternDraft) => Promise<void>;
};

const LIVE_TEST_DELAY_MS = 400;

/** An administrator's pattern, tried on the server as it is written (RE2 there, not the browser's engine). */
export default function PatternModal({ title, initial, meta, onClose, onSubmit }: Props) {
  // Mounted afresh for each opening, so it starts from its props. Lists are edited as text.
  const start = { ...EMPTY_PATTERN, ...initial };
  const [form, setForm] = useState<PatternDraft>(start);
  const [entries, setEntries] = useState(start.entries.join("\n"));
  const [context, setContext] = useState(start.context_words.join(", "));
  const [never, setNever] = useState(start.never_match.join("\n"));
  const [mustMatch, setMustMatch] = useState(start.must_match.join("\n"));
  const [mustNot, setMustNot] = useState(start.must_not_match.join("\n"));
  const [sample, setSample] = useState(start.must_match[0] ?? "");
  const [test, setTest] = useState<TestResponse | null>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const draft: PatternDraft = {
    ...form,
    entries: lines(entries),
    context_words: words(context),
    never_match: lines(never),
    must_match: lines(mustMatch),
    must_not_match: lines(mustNot),
    redact_label: form.redact_label.trim().toUpperCase(),
  };
  const draftKey = JSON.stringify(draft);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      api<TestResponse>(`${GUARDRAILS_BASE}/patterns/test`, {
        method: "POST",
        body: JSON.stringify({ pattern: { ...JSON.parse(draftKey), name: form.name || "draft" }, text: sample }),
      })
        .then(setTest)
        .catch(() => setTest(null));
    }, LIVE_TEST_DELAY_MS);
    return () => window.clearTimeout(handle);
  }, [draftKey, sample, form.name]);

  const set = <K extends keyof PatternDraft>(key: K, value: PatternDraft[K]) => setForm((f) => ({ ...f, [key]: value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!draft.name.trim()) {
      setErr("Name the pattern.");
      return;
    }
    setSaving(true);
    setErr("");
    try {
      await onSubmit(draft);
    } catch (e2) {
      setErr(formatApiError(e2));
    } finally {
      setSaving(false);
    }
  }

  const invalid = test && !test.ok;
  return (
    <Modal open title={title} onClose={onClose} panelClassName="modal-panel--lg">
      <form className="connection-form guardrails-form" onSubmit={submit}>
        <label className="connection-form__label">
          Name
          <input className="input-block" value={form.name} onChange={(e) => set("name", e.target.value)} required />
        </label>
        <div className="guardrails-inline-row" role="radiogroup" aria-label="Kind">
          <span>Kind</span>
          {(["regex", "words", "domains"] as const).map((kind) => (
            <label key={kind} className="guardrails-inline">
              <input type="radio" name="pattern-kind" value={kind} checked={form.kind === kind} onChange={() => set("kind", kind)} />{" "}
              {kind === "regex" ? "Regex" : kind === "words" ? "Word list" : "Domains"}
            </label>
          ))}
        </div>
        {form.kind === "regex" ? (
          <label className="connection-form__label">
            Expression
            <input
              className="input-block guardrails-code"
              dir="ltr"
              spellCheck={false}
              value={form.expression}
              onChange={(e) => set("expression", e.target.value)}
              aria-invalid={invalid ? true : undefined}
            />
            {invalid ? (
              <span className="guardrails-invalid" role="alert">
                Rejected: {test?.error}
              </span>
            ) : (
              <span className="muted-text connection-form__hint">
                RE2 syntax: no back-references or look-arounds. \b knows only Latin letters; use a word list for Persian
                words.
              </span>
            )}
          </label>
        ) : (
          <label className="connection-form__label">
            {form.kind === "words" ? "Words or phrases, one per line" : "Domains, one per line (subdomains and addresses at them count)"}
            <textarea className="input-block" rows={4} dir="auto" value={entries} onChange={(e) => setEntries(e.target.value)} />
          </label>
        )}
        <div className="guardrails-inline-row">
          <label className="guardrails-inline">
            <input type="checkbox" checked={form.normalize} onChange={(e) => set("normalize", e.target.checked)} /> Normalise
            Persian
          </label>
          <label className="guardrails-inline">
            <input type="checkbox" checked={form.case_sensitive} onChange={(e) => set("case_sensitive", e.target.checked)} />{" "}
            Case-sensitive
          </label>
        </div>
        <div className="guardrails-grid2">
          <label className="connection-form__label">
            Context words (optional)
            <input className="input-block" dir="auto" value={context} onChange={(e) => setContext(e.target.value)} />
            <span className="muted-text connection-form__hint">Only a find with one of these nearby counts.</span>
          </label>
          <label className="connection-form__label">
            within (characters)
            <input
              type="number"
              min={0}
              max={500}
              className="input-block"
              value={form.context_window}
              onChange={(e) => set("context_window", Number(e.target.value))}
            />
          </label>
          <label className="connection-form__label">
            Validator
            <select className="input-block" value={form.validator ?? ""} onChange={(e) => set("validator", e.target.value || null)}>
              <option value="">None</option>
              {(meta?.validators ?? []).map((v) => (
                <option key={v.key} value={v.key}>
                  {v.label}
                </option>
              ))}
            </select>
          </label>
          <label className="connection-form__label">
            Redact as
            <input
              className="input-block guardrails-code"
              dir="ltr"
              value={form.redact_label}
              onChange={(e) => set("redact_label", e.target.value)}
            />
            <span className="muted-text connection-form__hint">Masked as [{draft.redact_label || "LABEL"}_1], [{draft.redact_label || "LABEL"}_2]…</span>
          </label>
        </div>
        <label className="connection-form__label">
          Never match (one value per line)
          <textarea className="input-block" rows={2} dir="auto" value={never} onChange={(e) => setNever(e.target.value)} />
        </label>
        <div className="guardrails-grid2">
          <label className="connection-form__label">
            Must match (test samples, one per line)
            <textarea className="input-block" rows={2} dir="auto" value={mustMatch} onChange={(e) => setMustMatch(e.target.value)} />
          </label>
          <label className="connection-form__label">
            Must not match
            <textarea className="input-block" rows={2} dir="auto" value={mustNot} onChange={(e) => setMustNot(e.target.value)} />
          </label>
        </div>
        <div className="card guardrails-live">
          <label className="connection-form__label">
            Live test
            <textarea className="input-block" rows={3} dir="auto" value={sample} onChange={(e) => setSample(e.target.value)} />
          </label>
          {test?.ok ? (
            <>
              {test.matches.length ? (
                <p className="guardrails-highlight" dir="auto" data-testid="guardrails-live-matches">
                  {test.matches.map((m) => (
                    <mark key={`${m.start}-${m.end}`}>{m.value}</mark>
                  ))}
                </p>
              ) : null}
              <p className="muted-text">
                {test.matches.length} {test.matches.length === 1 ? "match" : "matches"}
                {test.problems.length ? "" : draft.must_match.length || draft.must_not_match.length ? " · samples ✓" : ""}
              </p>
              {test.problems.map((p) => (
                <p key={p} className="guardrails-invalid">
                  {p}
                </p>
              ))}
            </>
          ) : null}
        </div>
        {err ? (
          <p className="alert alert-error" role="alert">
            {err}
          </p>
        ) : null}
        <div className="dialog-actions">
          <button type="submit" className="btn" disabled={saving || Boolean(invalid)}>
            {saving ? "Saving…" : "Save pattern"}
          </button>
          <button type="button" className="btn btn-ghost dialog-actions-cancel" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
}
