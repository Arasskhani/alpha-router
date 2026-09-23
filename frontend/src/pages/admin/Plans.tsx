import { useEffect, useState } from "react";
import AdminPage from "../../components/AdminPage";
import AssignPlanModal, { type AssignPlanValues } from "../../components/plans/AssignPlanModal";
import PlanFormModal, { type PlanFormValues, type PlanInitial } from "../../components/plans/PlanFormModal";
import Modal from "../../components/Modal";
import RowActionsMenu from "../../components/RowActionsMenu";
import { api } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";
import { useTableCards } from "../../hooks/useTableCards";

type GroupOption = { id: number; name: string; source: string };
type Plan = {
  id: number;
  name: string;
  monthly_budget_usd: number;
};
type PlanMembers = {
  plan: { id: number; name: string; monthly_budget_usd: number };
  users: { id: number; username: string; display_name: string | null; email: string | null }[];
  groups: { id: number; name: string; source: string; member_count: number }[];
  departments: string[];
};

export default function Plans() {
  // On a phone the table is drawn as a list of cards (styles.css).
  const tableCardsRef = useTableCards<HTMLTableElement>();
  const { confirm } = useConfirm();
  const [plans, setPlans] = useState<Plan[]>([]);
  const [groups, setGroups] = useState<GroupOption[]>([]);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [editPlan, setEditPlan] = useState<PlanInitial | null>(null);
  const [assignOpen, setAssignOpen] = useState(false);
  const [assignPlanId, setAssignPlanId] = useState<number | null>(null);
  const [planSearch, setPlanSearch] = useState("");
  const [sortBy, setSortBy] = useState<"name" | "budget">("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(1);
  const [membersPlan, setMembersPlan] = useState<Plan | null>(null);
  const [membersData, setMembersData] = useState<PlanMembers | null>(null);
  const [membersLoading, setMembersLoading] = useState(false);
  const pageSize = 8;

  const load = async () => {
    try {
      const [p, g] = await Promise.all([
        api<Plan[]>("/api/admin/plans"),
        api<GroupOption[]>("/api/admin/groups"),
      ]);
      setPlans(p);
      setGroups(g);
    } catch (e) {
      setErr(String(e));
    }
  };

  useEffect(() => {
    void load();
  }, []);

  async function createPlan(values: PlanFormValues) {
    setErr("");
    await api("/api/admin/plans", {
      method: "POST",
      body: JSON.stringify(values),
    });
    setMsg(`Plan "${values.name}" created.`);
    await load();
  }

  async function updatePlan(values: PlanFormValues) {
    if (!editPlan) return;
    setErr("");
    await api(`/api/admin/plans/${editPlan.id}`, {
      method: "PATCH",
      body: JSON.stringify(values),
    });
    setMsg(`Plan "${values.name}" updated.`);
    await load();
  }

  async function assignPlan(values: AssignPlanValues) {
    setErr("");
    if (values.target === "group" && values.group_id) {
      const g = groups.find((x) => x.id === values.group_id);
      const res = await api<{ users_assigned: number }>("/api/admin/plans/assign", {
        method: "POST",
        body: JSON.stringify({ plan_id: values.plan_id, group_id: values.group_id }),
      });
      setMsg(
        `Plan assigned to group "${g?.name ?? values.group_id}" and ${res.users_assigned ?? 0} member user(s).`,
      );
    } else if (values.target === "user" && values.user_id) {
      await api("/api/admin/plans/assign", {
        method: "POST",
        body: JSON.stringify({ plan_id: values.plan_id, user_id: values.user_id }),
      });
      setMsg("Plan assigned to user.");
    } else if (values.target === "department") {
      await api("/api/admin/plans/assign-department", {
        method: "POST",
        body: JSON.stringify({ plan_id: values.plan_id, department: values.department }),
      });
      setMsg(`Plan assigned to department "${values.department}".`);
    }
    await load();
  }

  function openAssign(planId?: number) {
    setAssignPlanId(planId ?? null);
    setAssignOpen(true);
  }

  function openEdit(plan: Plan) {
    setEditPlan({
      id: plan.id,
      name: plan.name,
      monthly_budget_usd: plan.monthly_budget_usd,
    });
  }

  async function deletePlan(plan: Plan) {
    const ok = await confirm({
      title: "Delete plan",
      message: `Delete plan "${plan.name}"? Its assignments will be removed.`,
      confirmLabel: "Delete",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!ok) return;
    setErr("");
    try {
      await api(`/api/admin/plans/${plan.id}`, { method: "DELETE" });
      setMsg(`Plan "${plan.name}" deleted.`);
      await load();
    } catch (e2) {
      setErr(String(e2));
    }
  }

  async function showMembers(plan: Plan) {
    setMembersPlan(plan);
    setMembersData(null);
    setMembersLoading(true);
    try {
      const data = await api<PlanMembers>(`/api/admin/plans/${plan.id}/members`);
      setMembersData(data);
    } catch (e) {
      setErr(String(e));
      setMembersPlan(null);
    } finally {
      setMembersLoading(false);
    }
  }

  const visiblePlans = plans
    .filter((p) => {
      const q = planSearch.trim().toLowerCase();
      if (!q) return true;
      return p.name.toLowerCase().includes(q);
    })
    .sort((a, b) => {
      const dir = sortDir === "asc" ? 1 : -1;
      if (sortBy === "name") return a.name.localeCompare(b.name) * dir;
      return (a.monthly_budget_usd - b.monthly_budget_usd) * dir;
    });

  const totalPages = Math.max(1, Math.ceil(visiblePlans.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const pagedPlans = visiblePlans.slice((safePage - 1) * pageSize, safePage * pageSize);

  function setSort(next: "name" | "budget") {
    if (sortBy === next) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortBy(next);
      setSortDir("asc");
    }
  }

  return (
    <AdminPage title="Plans">
      {msg && <p className="alert alert-success">{msg}</p>}
      {err && <p className="alert alert-error" role="alert">{err}</p>}

      <div className="search-bar">
        <input
          placeholder="Search plan name…"
          value={planSearch}
          onChange={(e) => {
            setPlanSearch(e.target.value);
            setPage(1);
          }}
        />
        <select value={sortBy} onChange={(e) => setSort(e.target.value as "name" | "budget")}>
          <option value="name">Sort: Name</option>
          <option value="budget">Sort: Budget</option>
        </select>
        <button className="btn btn-ghost" type="button" onClick={() => setSort(sortBy)}>
          {sortDir === "asc" ? "Asc" : "Desc"}
        </button>
        <button className="btn btn-ghost" type="button" onClick={() => openAssign()} disabled={plans.length === 0}>
          Assign plan
        </button>
        <button className="btn" type="button" onClick={() => setCreateOpen(true)}>
          + New plan
        </button>
      </div>

      <div className="table-wrap">
        <table ref={tableCardsRef} className="card data-table data-table--cards">
          <thead>
            <tr>
              <th>Name</th>
              <th>Monthly budget</th>
              <th className="col-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {pagedPlans.map((p) => (
              <tr key={p.id}>
                <td><strong>{p.name}</strong></td>
                <td>${p.monthly_budget_usd}</td>
                <td className="col-actions">
                  <RowActionsMenu
                    label="Actions"
                    actions={[
                      { label: "Show Members", onClick: () => void showMembers(p) },
                      { label: "Assign plan", onClick: () => openAssign(p.id) },
                      { label: "Edit", onClick: () => openEdit(p) },
                      { label: "Delete", onClick: () => void deletePlan(p), danger: true },
                    ]}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <span className="muted-text">
          {visiblePlans.length} plan(s) · page {safePage} / {totalPages}
        </span>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn btn-ghost" type="button" disabled={safePage <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
            Prev
          </button>
          <button className="btn btn-ghost" type="button" disabled={safePage >= totalPages} onClick={() => setPage((p) => Math.min(totalPages, p + 1))}>
            Next
          </button>
        </div>
      </div>

      <PlanFormModal
        open={createOpen}
        mode="create"
        onClose={() => setCreateOpen(false)}
        onSubmit={createPlan}
      />

      <PlanFormModal
        open={!!editPlan}
        mode="edit"
        initial={editPlan}
        onClose={() => setEditPlan(null)}
        onSubmit={updatePlan}
      />

      <AssignPlanModal
        open={assignOpen}
        plans={plans}
        groups={groups}
        initialPlanId={assignPlanId}
        onClose={() => {
          setAssignOpen(false);
          setAssignPlanId(null);
        }}
        onSubmit={assignPlan}
      />

      <Modal open={!!membersPlan} title={membersPlan ? `Show Members — ${membersPlan.name}` : "Show Members"} onClose={() => setMembersPlan(null)}>
        {membersLoading && <p className="muted-text">Loading…</p>}
        {!membersLoading && membersData && (
          <>
            <h4 style={{ marginTop: 0 }}>Users</h4>
            {membersData.users.length === 0 ? (
              <p className="muted-text">No users assigned directly.</p>
            ) : (
              <ul style={{ marginTop: 0 }}>
                {membersData.users.map((u) => (
                  <li key={u.id}>
                    {u.display_name || u.username}
                    <span className="muted-text"> · {u.username}{u.email ? ` · ${u.email}` : ""}</span>
                  </li>
                ))}
              </ul>
            )}
            <h4>Groups</h4>
            {membersData.groups.length === 0 ? (
              <p className="muted-text">No groups assigned.</p>
            ) : (
              <ul style={{ marginTop: 0 }}>
                {membersData.groups.map((g) => (
                  <li key={g.id}>
                    {g.name}
                    <span className="muted-text"> · {g.source} · {g.member_count} member(s)</span>
                  </li>
                ))}
              </ul>
            )}
            {membersData.departments.length > 0 && (
              <>
                <h4>Departments</h4>
                <ul style={{ marginTop: 0 }}>
                  {membersData.departments.map((d) => (
                    <li key={d}>{d}</li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </Modal>
    </AdminPage>
  );
}
