import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import AdminPage from "../../components/AdminPage";
import Modal from "../../components/Modal";
import UserOwnerSelect from "../../components/apiKeys/UserOwnerSelect";
import { api, formatApiError } from "../../api";
import { useReadOnly } from "../../context/ReadOnlyContext";
import { useTableCards } from "../../hooks/useTableCards";
import {
  type FeatureCheck,
  type FeatureKey,
  type FeatureOverview,
  type FeatureRule,
  type RuleTarget,
  type TargetOptions,
  decisionText,
  featureSummary,
  targetTypeLabel,
} from "../../lib/featureAccess";

const BASE = "/api/admin/feature-access";
const USER_OPTIONS_PATH = `${BASE}/user-options`;
const DEPARTMENT_OTHER = "__other__";

function when(value: string | null): string {
  if (!value) return "—";
  const at = new Date(value);
  return Number.isNaN(at.getTime()) ? "—" : at.toLocaleString();
}

function RulesTable({
  feature,
  readOnly,
  onRemove,
}: {
  feature: FeatureOverview;
  readOnly: boolean;
  onRemove: (rule: FeatureRule) => void;
}) {
  // On a phone the rules are drawn as a list of cards (styles.css).
  const tableCardsRef = useTableCards<HTMLTableElement>();
  if (feature.rules.length === 0) {
    return <p className="muted-text">No rules yet.</p>;
  }
  return (
    <div className="table-wrap">
      <table ref={tableCardsRef} className="table data-table data-table--cards feature-access-table">
        <thead>
          <tr>
            <th scope="col">Who</th>
            <th scope="col">Access</th>
            <th scope="col">Note</th>
            <th scope="col">Added</th>
            <th scope="col" className="feature-access-table__actions">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {feature.rules.map((rule) => (
            <tr key={rule.id}>
              <td>
                <strong>{rule.label}</strong>
                <span className="muted-text feature-access-table__kind">
                  {targetTypeLabel(rule.target_type)}
                  {rule.sublabel ? ` · ${rule.sublabel}` : ""}
                </span>
              </td>
              <td>
                <span className={`badge ${rule.effect === "deny" ? "badge-denied" : "badge-allowed"}`}>
                  {rule.effect === "deny" ? "Denied" : "Allowed"}
                </span>
              </td>
              <td className="muted-text">{rule.note || "—"}</td>
              <td className="muted-text">
                {when(rule.created_at)}
                {rule.created_by ? ` · ${rule.created_by}` : ""}
              </td>
              <td className="feature-access-table__actions">
                {readOnly ? null : (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => onRemove(rule)}
                    aria-label={`Remove the rule for ${rule.label} on ${feature.title}`}
                  >
                    Remove
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AddRuleModal({
  open,
  feature,
  features,
  onClose,
  onSaved,
}: {
  open: boolean;
  feature: FeatureKey;
  features: FeatureOverview[];
  onClose: () => void;
  onSaved: (rule: FeatureRule) => void;
}) {
  const [section, setSection] = useState<FeatureKey>(feature);
  const [targetType, setTargetType] = useState<RuleTarget>("user");
  const [userId, setUserId] = useState<number | null>(null);
  const [groupId, setGroupId] = useState("");
  const [departmentKey, setDepartmentKey] = useState("");
  const [departmentOther, setDepartmentOther] = useState("");
  const [effect, setEffect] = useState<"deny" | "allow">("deny");
  const [note, setNote] = useState("");
  const [options, setOptions] = useState<TargetOptions | null>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  // Reset each time the dialog opens, for the section it was opened from.
  const [openedFor, setOpenedFor] = useState<string | null>(null);
  const key = open ? feature : null;
  if (openedFor !== key) {
    setOpenedFor(key);
    if (open) {
      setSection(feature);
      setTargetType("user");
      setUserId(null);
      setGroupId("");
      setDepartmentKey("");
      setDepartmentOther("");
      setEffect("deny");
      setNote("");
      setErr("");
    }
  }

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    api<TargetOptions>(`${BASE}/options`)
      .then((data) => {
        if (!cancelled) setOptions(data);
      })
      .catch(() => {
        if (!cancelled) setOptions({ groups: [], departments: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const allowPossible = targetType === "user";
  const shownEffect = allowPossible ? effect : "deny";

  async function submit(e: FormEvent) {
    e.preventDefault();
    let target: number | string;
    if (targetType === "user") {
      if (!userId) return setErr("Choose a user.");
      target = userId;
    } else if (targetType === "group") {
      if (!groupId) return setErr("Choose a group.");
      target = Number(groupId);
    } else {
      const name = (departmentKey === DEPARTMENT_OTHER ? departmentOther : departmentKey).trim();
      if (!name) return setErr("Choose or enter a department.");
      target = name;
    }
    setSaving(true);
    setErr("");
    try {
      const saved = await api<FeatureRule>(`${BASE}/rules`, {
        method: "POST",
        body: JSON.stringify({
          feature: section,
          target_type: targetType,
          target,
          effect: shownEffect,
          note: note.trim() || null,
        }),
      });
      onSaved(saved);
    } catch (ex) {
      setErr(formatApiError(ex));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} title="Add a rule" onClose={onClose} panelClassName="modal-panel--md">
      <form onSubmit={submit} className="feature-access-form">
        <p className="muted-text feature-access-form__intro">
          One rule per section and subject: if this user, group or department already has one here, saving replaces
          it.
        </p>
        <label htmlFor="feature-access-section">Section</label>
        <select
          id="feature-access-section"
          className="input-block"
          value={section}
          onChange={(e) => setSection(e.target.value as FeatureKey)}
        >
          {features.map((f) => (
            <option key={f.key} value={f.key}>
              {f.title}
            </option>
          ))}
        </select>

        <label htmlFor="feature-access-target-type">Applies to</label>
        <select
          id="feature-access-target-type"
          className="input-block"
          value={targetType}
          onChange={(e) => setTargetType(e.target.value as RuleTarget)}
        >
          <option value="user">A user</option>
          <option value="group">A group</option>
          <option value="department">A department</option>
        </select>

        {targetType === "user" ? (
          <>
            <label htmlFor="feature-access-user">User</label>
            <UserOwnerSelect
              inputId="feature-access-user"
              value={userId}
              onChange={(u) => setUserId(u?.id ?? null)}
              searchPath={USER_OPTIONS_PATH}
            />
          </>
        ) : null}

        {targetType === "group" ? (
          <>
            <label htmlFor="feature-access-group">Group</label>
            <select
              id="feature-access-group"
              className="input-block"
              value={groupId}
              onChange={(e) => setGroupId(e.target.value)}
              disabled={!options}
            >
              <option value="">{options ? "Choose a group…" : "Loading groups…"}</option>
              {options?.groups.map((g) => (
                <option key={g.id} value={String(g.id)}>
                  {g.name} ({g.member_count} {g.member_count === 1 ? "member" : "members"})
                </option>
              ))}
            </select>
          </>
        ) : null}

        {targetType === "department" ? (
          <>
            <label htmlFor="feature-access-department">Department</label>
            <select
              id="feature-access-department"
              className="input-block"
              value={departmentKey}
              onChange={(e) => setDepartmentKey(e.target.value)}
              disabled={!options}
            >
              <option value="">{options ? "Choose a department…" : "Loading departments…"}</option>
              {options?.departments.map((d) => (
                <option key={d.name} value={d.name}>
                  {d.name} ({d.user_count} {d.user_count === 1 ? "user" : "users"})
                </option>
              ))}
              <option value={DEPARTMENT_OTHER}>Other…</option>
            </select>
            {departmentKey === DEPARTMENT_OTHER ? (
              <>
                <label htmlFor="feature-access-department-name">Department name</label>
                <input
                  id="feature-access-department-name"
                  className="input-block"
                  value={departmentOther}
                  onChange={(e) => setDepartmentOther(e.target.value)}
                  placeholder="As it appears on user profiles"
                />
              </>
            ) : null}
            <p className="muted-text feature-access-form__hint">
              Matches each user&apos;s Department field, whatever its case or spacing.
            </p>
          </>
        ) : null}

        <fieldset className="feature-access-form__effect">
          <legend>Access</legend>
          <label>
            <input
              type="radio"
              name="feature-access-effect"
              value="deny"
              checked={shownEffect === "deny"}
              onChange={() => setEffect("deny")}
            />{" "}
            Deny — turn the section off
          </label>
          <label>
            <input
              type="radio"
              name="feature-access-effect"
              value="allow"
              checked={shownEffect === "allow"}
              disabled={!allowPossible}
              onChange={() => setEffect("allow")}
            />{" "}
            Allow — give it back to this person inside a denied group or department
          </label>
          {!allowPossible ? (
            <p className="muted-text feature-access-form__hint">
              Allow is for one person: a section is open unless a rule closes it.
            </p>
          ) : null}
        </fieldset>

        <label htmlFor="feature-access-note">Note (optional)</label>
        <input
          id="feature-access-note"
          className="input-block"
          value={note}
          maxLength={500}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Why, for whoever reads this later"
        />

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

function CheckUser({ version }: { version: number }) {
  const [userId, setUserId] = useState<number | null>(null);
  const [result, setResult] = useState<FeatureCheck | null>(null);
  const [err, setErr] = useState("");

  // Asked again when the person changes and whenever a rule is saved or removed (`version`).
  useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    api<FeatureCheck>(`${BASE}/check?user_id=${userId}`)
      .then((data) => {
        if (cancelled) return;
        setResult(data);
        setErr("");
      })
      .catch((ex) => {
        if (cancelled) return;
        setResult(null);
        setErr(formatApiError(ex));
      });
    return () => {
      cancelled = true;
    };
  }, [userId, version]);

  return (
    <section className="settings-section" aria-labelledby="feature-access-check-title">
      <h2 id="feature-access-check-title">Check a user</h2>
      <p className="settings-section-desc">What one person gets, and which rule decided it.</p>
      <label htmlFor="feature-access-check-user" className="sr-only">
        User to check
      </label>
      <UserOwnerSelect
        inputId="feature-access-check-user"
        value={userId}
        onChange={(u) => {
          // Never show one person's answer under another's name while the new one loads.
          setUserId(u?.id ?? null);
          setResult(null);
          setErr("");
        }}
        searchPath={USER_OPTIONS_PATH}
      />
      {err ? (
        <p className="alert alert-error" role="alert">
          {err}
        </p>
      ) : null}
      {userId && result && result.user.id === userId ? (
        <ul className="feature-access-check" aria-live="polite">
          {result.features.map((decision) => (
            <li key={decision.feature}>
              <strong>{decision.title}</strong>
              <span className={`badge ${decision.allowed ? "badge-allowed" : "badge-denied"}`}>
                {decision.allowed ? "Open" : "Closed"}
              </span>
              <span className="muted-text">{decisionText(decision)}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

/**
 * Feature Access: turn the web Chat or Projects off for a user, a group or a
 * department, the way a plan is assigned. Both are open until a rule closes
 * them. A rule on a person beats their groups and department; among groups
 * and departments a deny wins; administrators always have both.
 */
export default function FeatureAccess() {
  const readOnly = useReadOnly();
  const [features, setFeatures] = useState<FeatureOverview[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [adding, setAdding] = useState<FeatureKey | null>(null);
  const [removing, setRemoving] = useState<FeatureRule | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [version, setVersion] = useState(0);

  const load = useCallback(async (message?: string) => {
    try {
      const data = await api<{ features: FeatureOverview[] }>(BASE);
      setFeatures(data.features);
      setVersion((v) => v + 1);
      setError("");
      if (message) setNotice(message);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await api<{ features: FeatureOverview[] }>(BASE);
        if (cancelled) return;
        setFeatures(data.features);
        setError("");
      } catch (err) {
        if (!cancelled) setError(formatApiError(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function confirmRemove() {
    if (!removing) return;
    setRemoveBusy(true);
    try {
      await api(`${BASE}/rules/${removing.id}`, { method: "DELETE" });
      const label = removing.label;
      setRemoving(null);
      await load(`Rule for ${label} removed.`);
    } catch (err) {
      setNotice("");
      setError(formatApiError(err));
      setRemoving(null);
    } finally {
      setRemoveBusy(false);
    }
  }

  return (
    <AdminPage
      title="Feature Access"
      actions={
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => {
            setLoading(true);
            void load();
          }}
          disabled={loading}
        >
          {loading ? "…" : "Refresh"}
        </button>
      }
    >
      <p className="muted-text">
        Who may use the web Chat and Projects. Both are open to everyone until you add a rule. Deny turns a section off
        for a user, a group or a department; Allow gives it back to one person inside a denied group or department. A
        rule on a person beats their groups and department, a deny on any group or department wins over the rest, and
        administrators always have both. Project chats follow Projects, so a person without Chat keeps them. The browser
        extension and API keys are not affected — the extension&apos;s access is on{" "}
        <Link to="/admin/chat-tools">Chat Tools</Link>. Nothing is deleted when a section is turned off, and changes are
        recorded in <Link to="/admin/admin-logs">Admin Logs</Link>.
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

      {features === null && loading ? (
        <p className="muted-text" aria-busy="true">
          Loading…
        </p>
      ) : null}

      {features?.map((feature) => (
        <section key={feature.key} className="settings-section" aria-labelledby={`feature-access-${feature.key}`}>
          <div className="feature-access-section__head">
            <div>
              <h2 id={`feature-access-${feature.key}`}>{feature.title}</h2>
              <p className="settings-section-desc">{featureSummary(feature)}</p>
            </div>
            {readOnly ? null : (
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => {
                  setNotice("");
                  setAdding(feature.key);
                }}
              >
                Add rule
              </button>
            )}
          </div>
          <RulesTable feature={feature} readOnly={readOnly} onRemove={setRemoving} />
        </section>
      ))}

      <CheckUser version={version} />

      {features ? (
        <AddRuleModal
          open={adding !== null}
          feature={adding ?? "chat"}
          features={features}
          onClose={() => setAdding(null)}
          onSaved={(rule) => {
            setAdding(null);
            const section = features.find((f) => f.key === rule.feature)?.title ?? rule.feature;
            void load(`${section}: ${rule.effect === "deny" ? "denied" : "allowed"} for ${rule.label}.`);
          }}
        />
      ) : null}

      <Modal open={removing !== null} title="Remove rule" onClose={() => (removeBusy ? undefined : setRemoving(null))}>
        {removing ? (
          <>
            <p>
              Remove the rule that {removing.effect === "deny" ? "denies" : "allows"}{" "}
              {features?.find((f) => f.key === removing.feature)?.title ?? removing.feature} for{" "}
              <strong>{removing.label}</strong>?
            </p>
            <div className="dialog-actions">
              <button type="button" className="btn btn-danger" onClick={confirmRemove} disabled={removeBusy}>
                {removeBusy ? "Removing…" : "Remove"}
              </button>
              <button type="button" className="btn btn-ghost dialog-actions-cancel" onClick={() => setRemoving(null)}>
                Cancel
              </button>
            </div>
          </>
        ) : null}
      </Modal>
    </AdminPage>
  );
}
