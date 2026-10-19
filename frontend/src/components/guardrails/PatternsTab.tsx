import { type ChangeEvent, useCallback, useEffect, useRef, useState } from "react";

import RowActionsMenu from "../RowActionsMenu";
import { api, formatApiError } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";
import { useReadOnly } from "../../context/ReadOnlyContext";
import { useTableCards } from "../../hooks/useTableCards";
import {
  GUARDRAILS_BASE,
  type CustomPattern,
  type GuardrailsMeta,
  type LibraryPattern,
  type PatternDraft,
  type PatternsResponse,
} from "../../lib/guardrails";
import PatternModal from "./PatternModal";

type Editing = { title: string; initial?: Partial<PatternDraft>; id?: number } | null;

function fromLibrary(p: LibraryPattern): Partial<PatternDraft> {
  return {
    name: `${p.name} (copy)`,
    description: p.description,
    kind: p.kind,
    expression: p.expression,
    validator: p.validator,
    redact_label: p.redact_label,
    case_sensitive: p.case_sensitive,
    normalize: p.normalize,
    must_match: p.must_match,
    must_not_match: p.must_not_match,
  };
}

/** The library (built in, used as it is or copied) and the administrator's own patterns. */
export default function PatternsTab({ meta, onChanged }: { meta: GuardrailsMeta | null; onChanged: () => Promise<void> | void }) {
  const readOnly = useReadOnly();
  const { confirm } = useConfirm();
  const tableRef = useTableCards<HTMLTableElement>();
  const fileRef = useRef<HTMLInputElement>(null);
  const [data, setData] = useState<PatternsResponse | null>(null);
  const [view, setView] = useState<"library" | "custom">("custom");
  const [editing, setEditing] = useState<Editing>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    try {
      const next = await api<PatternsResponse>(`${GUARDRAILS_BASE}/patterns`);
      setData(next);
    } catch (err) {
      setError(formatApiError(err));
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the tab's first load
    void load();
  }, [load]);

  const changed = async (message: string) => {
    setNotice(message);
    setError("");
    await load();
    await onChanged();
  };

  async function save(draft: PatternDraft) {
    if (editing?.id) {
      await api(`${GUARDRAILS_BASE}/patterns/${editing.id}`, { method: "PUT", body: JSON.stringify(draft) });
      await changed(`Pattern "${draft.name}" saved.`);
    } else {
      await api(`${GUARDRAILS_BASE}/patterns`, { method: "POST", body: JSON.stringify(draft) });
      await changed(`Pattern "${draft.name}" created.`);
      setView("custom");
    }
    setEditing(null);
  }

  async function remove(p: CustomPattern) {
    const ok = await confirm({ title: "Delete pattern", message: `Delete "${p.name}"? This cannot be undone.`, danger: true });
    if (!ok) return;
    await api(`${GUARDRAILS_BASE}/patterns/${p.id}`, { method: "DELETE" });
    await changed(`Pattern "${p.name}" deleted.`);
  }

  async function exportJson() {
    try {
      const body = await api<unknown>(`${GUARDRAILS_BASE}/patterns/export`);
      const url = URL.createObjectURL(new Blob([JSON.stringify(body, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "guardrail-patterns.json";
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  async function importJson(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text()) as { patterns?: unknown };
      const result = await api<{ imported: number }>(`${GUARDRAILS_BASE}/patterns/import`, {
        method: "POST",
        body: JSON.stringify({ patterns: parsed.patterns ?? [] }),
      });
      await changed(`${result.imported} pattern(s) imported.`);
    } catch (err) {
      setError(err instanceof SyntaxError ? "That file is not JSON." : formatApiError(err));
    }
  }

  const rows = view === "custom" ? (data?.custom ?? []) : (data?.library ?? []);
  return (
    <div className="guardrails-patterns">
      {error ? <p className="alert alert-error">{error}</p> : null}
      {notice ? <p className="alert alert-success">{notice}</p> : null}
      <div className="guardrails-toolbar">
        <div className="activity-segmented" role="group" aria-label="Which patterns">
          {(["custom", "library"] as const).map((key) => (
            <button
              key={key}
              type="button"
              aria-pressed={view === key}
              className={`activity-segmented__btn${view === key ? " activity-segmented__btn--active" : ""}`}
              onClick={() => setView(key)}
            >
              {key === "custom" ? `Custom (${data?.custom.length ?? 0})` : `Library (${data?.library.length ?? 0})`}
            </button>
          ))}
        </div>
        <div className="guardrails-toolbar__actions">
          <button type="button" className="btn btn-ghost" onClick={() => void exportJson()}>
            Export JSON
          </button>
          {readOnly ? null : (
            <>
              <button type="button" className="btn btn-ghost" onClick={() => fileRef.current?.click()}>
                Import JSON
              </button>
              <input ref={fileRef} type="file" accept="application/json,.json" hidden onChange={(e) => void importJson(e)} />
              <button type="button" className="btn" onClick={() => setEditing({ title: "New pattern" })}>
                + New pattern
              </button>
            </>
          )}
        </div>
      </div>
      <div className="table-wrap">
        <table ref={tableRef} className="card data-table data-table--cards guardrails-table">
          <thead>
            <tr>
              <th>Pattern</th>
              <th className="col-sm">Kind</th>
              <th className="col-md">Used by</th>
              <th className="col-sm">Hits 7d</th>
              <th className="col-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {data === null ? (
              <tr>
                <td colSpan={5} className="muted-text">
                  Loading…
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="muted-text">
                  No patterns of your own yet. Copy one from the library or add one with + New pattern.
                </td>
              </tr>
            ) : (
              rows.map((p) => (
                <tr key={p.ref}>
                  <td>
                    <div className="guardrails-rule-name">{p.name}</div>
                    {p.description ? <div className="muted-text guardrails-rule-sub">{p.description}</div> : null}
                  </td>
                  <td>{p.kind === "regex" ? "Regex" : p.kind === "words" ? "Word list" : "Domains"}</td>
                  <td>{p.used_by?.length ? p.used_by.join(", ") : "—"}</td>
                  <td className="guardrails-hits">{p.hits_7d ?? 0}</td>
                  <td className="col-actions">
                    <RowActionsMenu
                      onError={setError}
                      actions={
                        "id" in p
                          ? [
                              {
                                label: "Edit",
                                onClick: () => setEditing({ title: "Edit pattern", initial: p, id: (p as CustomPattern).id }),
                              },
                              { label: "Delete", onClick: () => remove(p as CustomPattern), danger: true },
                            ]
                          : [{ label: "Copy as my own", onClick: () => setEditing({ title: "New pattern", initial: fromLibrary(p) }) }]
                      }
                    />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {editing ? (
        <PatternModal title={editing.title} initial={editing.initial} meta={meta} onClose={() => setEditing(null)} onSubmit={save} />
      ) : null}
    </div>
  );
}
