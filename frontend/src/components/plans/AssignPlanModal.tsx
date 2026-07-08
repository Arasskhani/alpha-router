import { FormEvent, useEffect, useState } from "react";
import { api } from "../../api";
import UserOwnerSelect from "../apiKeys/UserOwnerSelect";
import Modal from "../Modal";

export type AssignPlanTarget = "group" | "user" | "department";

export type AssignPlanValues = {
  plan_id: number;
  target: AssignPlanTarget;
  group_id: number | null;
  user_id: number | null;
  department: string;
};

type PlanOption = { id: number; name: string; monthly_budget_usd: number };
type GroupOption = { id: number; name: string; source: string };
type DepartmentOption = { name: string; user_count: number };

const DEPARTMENT_OTHER = "__other__";

type Props = {
  open: boolean;
  plans: PlanOption[];
  groups: GroupOption[];
  initialPlanId?: number | null;
  onClose: () => void;
  onSubmit: (values: AssignPlanValues) => Promise<void>;
};

export default function AssignPlanModal({
  open,
  plans,
  groups,
  initialPlanId,
  onClose,
  onSubmit,
}: Props) {
  const [planId, setPlanId] = useState("");
  const [target, setTarget] = useState<AssignPlanTarget>("group");
  const [groupId, setGroupId] = useState("");
  const [userId, setUserId] = useState<number | null>(null);
  const [departmentKey, setDepartmentKey] = useState("");
  const [departmentOther, setDepartmentOther] = useState("");
  const [departments, setDepartments] = useState<DepartmentOption[]>([]);
  const [departmentsLoading, setDepartmentsLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open) return;
    setErr("");
    setTarget("group");
    setGroupId("");
    setUserId(null);
    setDepartmentKey("");
    setDepartmentOther("");
    setPlanId(initialPlanId ? String(initialPlanId) : "");
    setDepartmentsLoading(true);
    void api<DepartmentOption[]>("/api/admin/plans/departments")
      .then(setDepartments)
      .catch(() => setDepartments([]))
      .finally(() => setDepartmentsLoading(false));
  }, [open, initialPlanId]);

  function resolvedDepartment(): string {
    if (departmentKey === DEPARTMENT_OTHER) return departmentOther.trim();
    return departmentKey.trim();
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!planId) {
      setErr("Select a plan.");
      return;
    }
    if (target === "group" && !groupId) {
      setErr("Select a group.");
      return;
    }
    if (target === "user" && !userId) {
      setErr("Select a user.");
      return;
    }
    if (target === "department") {
      const dept = resolvedDepartment();
      if (!departmentKey) {
        setErr("Select a department.");
        return;
      }
      if (departmentKey === DEPARTMENT_OTHER && !dept) {
        setErr("Enter a department name.");
        return;
      }
    }
    setSaving(true);
    setErr("");
    try {
      await onSubmit({
        plan_id: Number(planId),
        target,
        group_id: target === "group" ? Number(groupId) : null,
        user_id: target === "user" ? userId : null,
        department: target === "department" ? resolvedDepartment() : "",
      });
      onClose();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setSaving(false);
    }
  }

  const selectedPlan = plans.find((p) => String(p.id) === planId);

  return (
    <Modal open={open} title="Assign plan" onClose={onClose}>
      <form onSubmit={handleSubmit}>
        <label>Plan</label>
        <select
          className="input-block"
          value={planId}
          onChange={(e) => setPlanId(e.target.value)}
          required
        >
          <option value="">Select plan…</option>
          {plans.map((p) => (
            <option key={p.id} value={String(p.id)}>
              {p.name} (${p.monthly_budget_usd}/mo)
            </option>
          ))}
        </select>
        {selectedPlan ? (
          <p className="muted-text" style={{ marginTop: "-0.35rem", marginBottom: "0.75rem" }}>
            Monthly budget: ${selectedPlan.monthly_budget_usd}
          </p>
        ) : null}

        <label>Assign to</label>
        <select
          className="input-block"
          value={target}
          onChange={(e) => setTarget(e.target.value as AssignPlanTarget)}
        >
          <option value="group">Group</option>
          <option value="user">User</option>
          <option value="department">Department</option>
        </select>

        {target === "group" ? (
          <>
            <label>Group</label>
            <select
              className="input-block"
              value={groupId}
              onChange={(e) => setGroupId(e.target.value)}
            >
              <option value="">Select group…</option>
              {groups.map((g) => (
                <option key={g.id} value={String(g.id)}>
                  {g.name} ({g.source})
                </option>
              ))}
            </select>
            <p className="muted-text" style={{ marginTop: "-0.35rem", marginBottom: "0.75rem" }}>
              Group members with «From group» budget inherit this plan unless they have a direct user plan.
            </p>
          </>
        ) : null}

        {target === "user" ? (
          <>
            <label>User</label>
            <UserOwnerSelect value={userId} onChange={(u) => setUserId(u?.id ?? null)} />
            <p className="muted-text" style={{ marginTop: "-0.35rem", marginBottom: "0.75rem" }}>
              Assigns the plan directly to the user, overriding group and department inheritance.
            </p>
          </>
        ) : null}

        {target === "department" ? (
          <>
            <label>Department</label>
            <select
              className="input-block"
              value={departmentKey}
              onChange={(e) => setDepartmentKey(e.target.value)}
              disabled={departmentsLoading}
            >
              <option value="">
                {departmentsLoading ? "Loading departments…" : "Select department…"}
              </option>
              {departments.map((d) => (
                <option key={d.name} value={d.name}>
                  {d.name}
                  {d.user_count > 0
                    ? ` (${d.user_count} user${d.user_count === 1 ? "" : "s"})`
                    : " (assigned, no users)"}
                </option>
              ))}
              <option value={DEPARTMENT_OTHER}>Other…</option>
            </select>
            {departmentKey === DEPARTMENT_OTHER ? (
              <>
                <label>Department name</label>
                <input
                  className="input-block"
                  value={departmentOther}
                  onChange={(e) => setDepartmentOther(e.target.value)}
                  placeholder="New department name"
                />
              </>
            ) : null}
            <p className="muted-text" style={{ marginTop: "-0.35rem", marginBottom: "0.75rem" }}>
              Lists departments from user profiles and existing plan assignments. Matching is exact — it must match
              each user&apos;s Department field.
            </p>
          </>
        ) : null}

        {err && <p className="alert alert-error">{err}</p>}
        <div className="dialog-actions">
          <button type="submit" className="btn" disabled={saving}>
            {saving ? "Assigning…" : "Assign"}
          </button>
          <button type="button" className="btn btn-ghost dialog-actions-cancel" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
}
