import { useCallback, useEffect, useMemo, useState } from "react";

import Modal from "../Modal";
import RowActionsMenu from "../RowActionsMenu";
import ResourceAccessEditor from "../admin/ResourceAccessEditor";
import { api, formatApiError } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";
import { useReadOnly } from "../../context/ReadOnlyContext";
import { useTableCards } from "../../hooks/useTableCards";
import {
  ACTION_LABELS,
  GUARDRAILS_BASE,
  MODE_LABELS,
  channelsSummary,
  type GuardrailsMeta,
  type Overview,
  type Rule,
  type RuleDraft,
  type RuleMode,
} from "../../lib/guardrails";
import RuleModal from "./RuleModal";
import StatCards from "./StatCards";
import TestTextModal from "./TestTextModal";

type Props = {
  meta: GuardrailsMeta | null;
  overview: Overview | null;
  onChanged: () => Promise<void> | void;
};

function appliesTo(rule: Rule): string {
  if (rule.access_type === "private") return rule.allow_count ? `Only ${rule.allow_count} named` : "No one yet";
  return rule.deny_count ? `Everyone except ${rule.deny_count}` : "Everyone";
}

/** The rules, in the order they are applied; when several match, the strictest action wins. */
export default function RulesTab({ meta, overview, onChanged }: Props) {
  const readOnly = useReadOnly();
  const { confirm } = useConfirm();
  const tableRef = useTableCards<HTMLTableElement>();
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<Rule | "new" | null>(null);
  const [scoping, setScoping] = useState<Rule | null>(null);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    try {
      setRules(await api<Rule[]>(`${GUARDRAILS_BASE}/rules`));
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

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!rules || !q) return rules ?? [];
    return rules.filter((r) => `${r.name} ${r.pattern_names.join(" ")}`.toLowerCase().includes(q));
  }, [rules, query]);

  async function save(draft: RuleDraft) {
    if (editing === "new") {
      await api(`${GUARDRAILS_BASE}/rules`, { method: "POST", body: JSON.stringify(draft) });
      await changed(`Rule "${draft.name}" created.`);
    } else if (editing) {
      await api(`${GUARDRAILS_BASE}/rules/${editing.id}`, { method: "PUT", body: JSON.stringify(draft) });
      await changed(`Rule "${draft.name}" saved.`);
    }
    setEditing(null);
  }

  async function setMode(rule: Rule, mode: RuleMode) {
    await api(`${GUARDRAILS_BASE}/rules/${rule.id}/mode`, { method: "PATCH", body: JSON.stringify({ mode }) });
    await changed(`"${rule.name}" is now ${MODE_LABELS[mode].toLowerCase()}.`);
  }

  async function move(rule: Rule, direction: "up" | "down") {
    await api(`${GUARDRAILS_BASE}/rules/${rule.id}/move`, { method: "POST", body: JSON.stringify({ direction }) });
    await changed(`"${rule.name}" moved ${direction}.`);
  }

  async function remove(rule: Rule) {
    const ok = await confirm({
      title: "Delete rule",
      message: `Delete "${rule.name}"? It stops applying at once. Its events are kept.`,
      danger: true,
    });
    if (!ok) return;
    await api(`${GUARDRAILS_BASE}/rules/${rule.id}`, { method: "DELETE" });
    await changed(`Rule "${rule.name}" deleted.`);
  }

  return (
    <div className="guardrails-rules">
      <StatCards overview={overview} />
      {error ? <p className="alert alert-error" role="alert">{error}</p> : null}
      {notice ? <p className="alert alert-success">{notice}</p> : null}
      <div className="guardrails-toolbar">
        <input
          type="search"
          className="input-block guardrails-search"
          placeholder="Search rules…"
          aria-label="Search rules"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {readOnly ? null : (
          <div className="guardrails-toolbar__actions">
            <button type="button" className="btn btn-ghost" onClick={() => setTesting(true)}>
              Test a text
            </button>
            <button type="button" className="btn" onClick={() => setEditing("new")}>
              + New rule
            </button>
          </div>
        )}
      </div>
      <div className="table-wrap">
        <table ref={tableRef} className="card data-table data-table--cards guardrails-table">
          <thead>
            <tr>
              <th>Rule</th>
              <th className="col-md">Detects</th>
              <th className="col-md">Channels → destinations</th>
              <th className="col-sm">Applies to</th>
              <th className="col-sm">Action</th>
              <th className="col-sm">Mode</th>
              <th className="col-sm">Hits 7d</th>
              <th className="col-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rules === null ? (
              <tr>
                <td colSpan={8} className="muted-text">
                  Loading…
                </td>
              </tr>
            ) : shown.length === 0 ? (
              <tr>
                <td colSpan={8} className="muted-text">
                  {rules.length
                    ? "No rule matches this search."
                    : "No rules yet. Nothing is checked until you add one with + New rule and turn it on."}
                </td>
              </tr>
            ) : (
              shown.map((rule, index) => {
                const where = channelsSummary(rule, meta);
                return (
                  <tr key={rule.id} className={rule.mode === "off" ? "guardrails-row--off" : ""}>
                    <td>
                      <div className="guardrails-rule-name">{rule.name}</div>
                      <div className="muted-text guardrails-rule-sub">
                        v{rule.version}
                        {rule.description ? ` · ${rule.description}` : ""}
                        {rule.missing_patterns.length ? " · a pattern it names is gone: it is not applied" : ""}
                      </div>
                    </td>
                    <td>
                      {rule.pattern_names.map((name) => (
                        <span key={name} className="guardrails-chip">
                          {name}
                        </span>
                      ))}
                    </td>
                    <td>
                      {where.channels.map((c) => (
                        <span key={c} className="guardrails-chip">
                          {c}
                        </span>
                      ))}
                      <span aria-hidden> → </span>
                      <span className="sr-only">to</span>
                      {where.destinations.map((d) => (
                        <span key={d} className="guardrails-chip">
                          {d}
                        </span>
                      ))}
                    </td>
                    <td>{appliesTo(rule)}</td>
                    <td>
                      <span className={`guardrails-action guardrails-action--${rule.action}`}>
                        {rule.action === "route" ? `Route → ${rule.route_model_label ?? "?"}` : ACTION_LABELS[rule.action]}
                      </span>
                    </td>
                    <td>
                      <span className="guardrails-mode">
                        <span className={`guardrails-dot guardrails-dot--${rule.mode}`} aria-hidden />
                        {MODE_LABELS[rule.mode]}
                      </span>
                    </td>
                    <td className="guardrails-hits">{rule.hits_7d}</td>
                    <td className="col-actions">
                      <RowActionsMenu
                        onError={setError}
                        actions={[
                          { label: "Edit", onClick: () => setEditing(rule) },
                          { label: "Who it applies to", onClick: () => setScoping(rule) },
                          ...(["enforce", "monitor", "off"] as RuleMode[])
                            .filter((mode) => mode !== rule.mode)
                            .map((mode) => ({
                              label: mode === "enforce" ? "Enforce" : mode === "monitor" ? "Monitor only" : "Turn off",
                              onClick: () => setMode(rule, mode),
                            })),
                          ...(index > 0 && !query ? [{ label: "Move up", onClick: () => move(rule, "up") }] : []),
                          ...(index < shown.length - 1 && !query
                            ? [{ label: "Move down", onClick: () => move(rule, "down") }]
                            : []),
                          { label: "Delete", onClick: () => remove(rule), danger: true },
                        ]}
                      />
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      <p className="muted-text guardrails-foot">
        Rules apply top to bottom; when several match, the strictest action wins (block, then route, then redact).
        Values found are never stored — only their kind and a masked hint.
      </p>
      {editing ? (
        <RuleModal
          title={editing === "new" ? "New rule" : "Edit rule"}
          initial={editing === "new" ? undefined : editing}
          meta={meta}
          onClose={() => setEditing(null)}
          onSubmit={save}
        />
      ) : null}
      <Modal open={scoping !== null} title={scoping ? `Who "${scoping.name}" applies to` : ""} onClose={() => setScoping(null)}>
        {scoping ? (
          <>
            <p className="muted-text">
              Public: everyone except those denied. Private: only those allowed. A denial always wins, and there is no
              exception for a Super Admin unless you add one.
            </p>
            <ResourceAccessEditor
              title="Applies to"
              loadPath={`${GUARDRAILS_BASE}/rules/${scoping.id}/access`}
              savePath={`${GUARDRAILS_BASE}/rules/${scoping.id}/access`}
              disabled={readOnly}
              onError={setError}
              onSaved={() => {
                setScoping(null);
                void changed(`Who "${scoping.name}" applies to was saved.`);
              }}
            />
          </>
        ) : null}
      </Modal>
      {testing ? <TestTextModal meta={meta} onClose={() => setTesting(false)} /> : null}
    </div>
  );
}
