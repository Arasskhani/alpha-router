import { FormEvent, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import AdminPage from "../../components/AdminPage";
import LocalGroupFormModal, {
  type LocalGroupFormValues,
  type LocalGroupInitial,
} from "../../components/groups/LocalGroupFormModal";
import Modal from "../../components/Modal";
import RowActionsMenu, { RowAction } from "../../components/RowActionsMenu";
import { api } from "../../api";
import { useDebounced } from "../../hooks/useDebounced";
import { useConfirm } from "../../context/ConfirmContext";
import { USAGE_AND_ACTIVITY_LABEL } from "../../lib/usageActivityLabel";

type Group = { id: number; name: string; description: string | null; source: string; plan_id: number | null };
type Plan = { id: number; name: string };

function buildPlanBody(budgetPlan: string): Record<string, unknown> {
  if (budgetPlan === "__none__") return { clear_plan: true };
  return { plan_id: Number(budgetPlan) };
}

export default function Groups() {
  const navigate = useNavigate();
  const { confirm } = useConfirm();
  const [groups, setGroups] = useState<Group[]>([]);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [search, setSearch] = useState("");
  const debounced = useDebounced(search, 280);
  const [source, setSource] = useState("");
  const [flash, setFlash] = useState("");
  const [err, setErr] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [editGroup, setEditGroup] = useState<LocalGroupInitial | null>(null);
  const [budgetGroup, setBudgetGroup] = useState<Group | null>(null);
  const [budgetPlanId, setBudgetPlanId] = useState("");
  const [budgetSaving, setBudgetSaving] = useState(false);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkPlanId, setBulkPlanId] = useState("");

  const load = () => {
    const q = new URLSearchParams();
    if (debounced.trim()) q.set("q", debounced.trim());
    if (source) q.set("source", source);
    api<Group[]>(`/api/admin/groups?${q}`).then(setGroups).catch((e) => setErr(String(e)));
    api<Plan[]>("/api/admin/plans").then((p) => setPlans(p.map((x) => ({ id: x.id, name: x.name })))).catch(() => {});
  };

  useEffect(() => {
    load();
  }, [debounced, source]);

  async function createLocalGroup(values: LocalGroupFormValues) {
    setErr("");
    const body: Record<string, unknown> = {
      name: values.name,
      description: values.description || undefined,
    };
    if (values.budget_plan !== "__none__") {
      body.plan_id = Number(values.budget_plan);
    }
    await api("/api/admin/groups", {
      method: "POST",
      body: JSON.stringify(body),
    });
    setFlash("Group created.");
    load();
  }

  async function updateLocalGroup(values: LocalGroupFormValues) {
    if (!editGroup) return;
    setErr("");
    await api(`/api/admin/groups/${editGroup.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        name: values.name,
        description: values.description,
        ...buildPlanBody(values.budget_plan),
      }),
    });
    setFlash("Group updated.");
    load();
  }

  async function syncLdap() {
    await api("/api/admin/groups/sync/ldap", { method: "POST" });
    setFlash("LDAP groups synced.");
    load();
  }

  async function assignPlan(groupId: number, planId: string) {
    setErr("");
    try {
      const body = planId ? { plan_id: Number(planId) } : { clear_plan: true };
      const res = await api<{ users_assigned: number }>(`/api/admin/groups/${groupId}/plan`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      const g = groups.find((x) => x.id === groupId);
      setFlash(
        planId
          ? `Budget plan assigned to "${g?.name ?? groupId}" and ${res.users_assigned ?? 0} member(s).`
          : `Budget plan removed from "${g?.name ?? groupId}".`,
      );
      load();
    } catch (e) {
      setErr(String(e));
    }
  }

  function openAssignBudget(g: Group) {
    setBudgetGroup(g);
    setBudgetPlanId(g.plan_id ? String(g.plan_id) : "");
  }

  async function saveAssignBudget(e: FormEvent) {
    e.preventDefault();
    if (!budgetGroup) return;
    setBudgetSaving(true);
    try {
      await assignPlan(budgetGroup.id, budgetPlanId);
      setBudgetGroup(null);
    } finally {
      setBudgetSaving(false);
    }
  }

  async function deleteGroup(g: Group) {
    const ok = await confirm({
      title: "Delete group",
      message: `Delete group "${g.name}"? Members stay in Users; only membership and group plan assignment are removed.`,
      confirmLabel: "Delete",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!ok) return;
    setErr("");
    try {
      await api(`/api/admin/groups/${g.id}`, { method: "DELETE" });
      setFlash(`Group "${g.name}" deleted.`);
      load();
    } catch (e) {
      setErr(String(e));
    }
  }

  async function deactiveGroupMembers(g: Group) {
    const ok = await confirm({
      title: "Deactive all members",
      message: `Set all non-admin members of "${g.name}" to Deactive? They can still sign in and browse chat history and media, but cannot send new messages.`,
      confirmLabel: "Deactive all members",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!ok) return;
    setErr("");
    try {
      const res = await api<{ disabled: number; skipped_admins: number }>(
        `/api/admin/groups/${g.id}/disable-members`,
        { method: "POST" },
      );
      setFlash(
        `Deactivated ${res.disabled ?? 0} user(s) in "${g.name}"` +
          (res.skipped_admins ? ` (${res.skipped_admins} admin(s) skipped).` : "."),
      );
    } catch (e) {
      setErr(String(e));
    }
  }

  function showGroupMembers(g: Group) {
    navigate(`/admin/users?group_id=${g.id}&group_name=${encodeURIComponent(g.name)}`);
  }

  function openEditGroup(g: Group) {
    setEditGroup({
      id: g.id,
      name: g.name,
      description: g.description,
      plan_id: g.plan_id,
    });
  }

  function groupRowActions(g: Group): RowAction[] {
    const actions: RowAction[] = [
      {
        label: USAGE_AND_ACTIVITY_LABEL,
        menuWrap: true,
        onClick: () => navigate(`/admin/groups/${g.id}/activity`),
      },
      { label: "Show Members", onClick: () => showGroupMembers(g) },
    ];
    if (g.source === "local") {
      actions.push({ label: "Edit group", onClick: () => openEditGroup(g) });
    } else {
      actions.push({ label: "Budget plan", onClick: () => openAssignBudget(g) });
    }
    actions.push(
      { label: "Deactive all Members", onClick: () => void deactiveGroupMembers(g), danger: true },
      { label: "Delete Group", onClick: () => void deleteGroup(g), danger: true },
    );
    return actions;
  }

  const allVisibleSelected = useMemo(
    () => groups.length > 0 && groups.every((g) => selectedIds.includes(g.id)),
    [groups, selectedIds],
  );

  function toggleSelection(groupId: number) {
    setSelectedIds((prev) =>
      prev.includes(groupId) ? prev.filter((id) => id !== groupId) : [...prev, groupId],
    );
  }

  function toggleSelectAllVisible() {
    setSelectedIds((prev) => {
      if (allVisibleSelected) {
        return prev.filter((id) => !groups.some((g) => g.id === id));
      }
      const merged = new Set(prev);
      for (const g of groups) merged.add(g.id);
      return Array.from(merged);
    });
  }

  async function runBulk(action: "assign_plan" | "delete" | "disable_members") {
    if (!selectedIds.length) return;
    if (action === "delete") {
      const ok = await confirm({
        title: "Delete groups",
        message: `Delete ${selectedIds.length} selected group(s)? Members stay in Users; group plan assignments are removed.`,
        confirmLabel: "Delete Group",
        cancelLabel: "Cancel",
        danger: true,
      });
      if (!ok) return;
    }
    if (action === "disable_members") {
      const ok = await confirm({
        title: "Deactive all Members",
        message: `Set all non-admin members in ${selectedIds.length} selected group(s) to Deactive?`,
        confirmLabel: "Deactive all Members",
        cancelLabel: "Cancel",
        danger: true,
      });
      if (!ok) return;
    }
    if (action === "assign_plan" && !bulkPlanId) {
      setErr("Select a plan for bulk assign.");
      return;
    }
    setBulkBusy(true);
    setErr("");
    try {
      const res = await api<{ deleted?: number; disabled?: number; groups?: number }>("/api/admin/groups/bulk", {
        method: "POST",
        body: JSON.stringify({
          group_ids: selectedIds,
          action: action === "assign_plan" ? "assign_plan" : action === "delete" ? "delete" : "disable_members",
          plan_id: action === "assign_plan" ? Number(bulkPlanId) : undefined,
        }),
      });
      if (action === "delete") setFlash(`Deleted ${res.deleted ?? 0} group(s).`);
      else if (action === "disable_members")
        setFlash(`Deactivated ${res.disabled ?? 0} member(s) across selected groups.`);
      else setFlash(`Assigned budget plan to ${res.groups ?? 0} group(s).`);
      setBulkOpen(false);
      setSelectedIds([]);
      load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBulkBusy(false);
    }
  }

  const badge = (s: string) => `badge badge-${s}`;
  const planName = (planId: number | null) => plans.find((p) => p.id === planId)?.name;

  return (
    <AdminPage title="Groups">
      {flash && <p className="alert alert-success">{flash}</p>}
      {err && <p className="alert alert-error">{err}</p>}
      <div className="search-bar">
        <input placeholder="Search groups…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <select value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">All sources</option>
          <option value="local">Local</option>
          <option value="ldap">LDAP</option>
          <option value="saml">SAML</option>
        </select>
        <button className="btn btn-ghost" type="button" onClick={syncLdap}>
          Sync LDAP
        </button>
        <button
          className="btn btn-ghost"
          type="button"
          disabled={selectedIds.length === 0}
          onClick={() => {
            setBulkPlanId("");
            setBulkOpen(true);
          }}
        >
          Bulk Edit{selectedIds.length > 0 ? ` (${selectedIds.length})` : ""}
        </button>
        <button className="btn" type="button" onClick={() => setCreateOpen(true)}>
          + Local group
        </button>
      </div>

      <div className="table-wrap">
        <table className="card data-table">
          <thead>
            <tr>
              <th style={{ width: 36 }}>
                <input type="checkbox" checked={allVisibleSelected} onChange={toggleSelectAllVisible} aria-label="Select all" />
              </th>
              <th>Name</th>
              <th>Source</th>
              <th>Budget plan</th>
              <th className="col-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => (
              <tr key={g.id}>
                <td>
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(g.id)}
                    onChange={() => toggleSelection(g.id)}
                    aria-label={`Select ${g.name}`}
                  />
                </td>
                <td>
                  {g.name}
                  <br />
                  <small>{g.description}</small>
                </td>
                <td>
                  <span className={badge(g.source)}>{g.source}</span>
                </td>
                <td>
                  <select
                    value={g.plan_id ? String(g.plan_id) : ""}
                    onChange={(e) => void assignPlan(g.id, e.target.value)}
                    title="Synced with Plans page"
                  >
                    <option value="">No plan</option>
                    {plans.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                  {g.plan_id ? <small className="muted-text"> · {planName(g.plan_id)}</small> : null}
                </td>
                <td className="col-actions">
                  <RowActionsMenu actions={groupRowActions(g)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <LocalGroupFormModal
        open={createOpen}
        mode="create"
        plans={plans}
        onClose={() => setCreateOpen(false)}
        onSubmit={createLocalGroup}
      />

      <LocalGroupFormModal
        open={!!editGroup}
        mode="edit"
        initial={editGroup}
        plans={plans}
        onClose={() => setEditGroup(null)}
        onSubmit={updateLocalGroup}
      />

      <Modal open={!!budgetGroup} title="Budget plan" onClose={() => setBudgetGroup(null)}>
        {budgetGroup && (
          <form onSubmit={saveAssignBudget}>
            <p className="muted-text">
              Assign a budget plan to <strong>{budgetGroup.name}</strong>. Updates Plans assignments for this group and
              all members.
            </p>
            <label>Budget plan</label>
            <select
              className="input-block"
              value={budgetPlanId}
              onChange={(e) => setBudgetPlanId(e.target.value)}
            >
              <option value="">No plan</option>
              {plans.map((p) => (
                <option key={p.id} value={String(p.id)}>
                  {p.name}
                </option>
              ))}
            </select>
            <div className="dialog-actions">
              <button type="submit" className="btn" disabled={budgetSaving}>
                {budgetSaving ? "Saving…" : "Save"}
              </button>
              <button type="button" className="btn btn-ghost dialog-actions-cancel" onClick={() => setBudgetGroup(null)}>
                Cancel
              </button>
            </div>
          </form>
        )}
      </Modal>

      <Modal open={bulkOpen} title={`Bulk Edit (${selectedIds.length} groups)`} onClose={() => !bulkBusy && setBulkOpen(false)}>
        <p className="muted-text">Apply an action to all selected groups.</p>
        <label>Budget plan (optional)</label>
        <select className="input-block" value={bulkPlanId} onChange={(e) => setBulkPlanId(e.target.value)}>
          <option value="">Select plan for bulk assign…</option>
          {plans.map((p) => (
            <option key={p.id} value={String(p.id)}>
              {p.name}
            </option>
          ))}
        </select>
        <div className="dialog-actions dialog-actions-grid" style={{ marginTop: 12 }}>
          <button type="button" className="btn" disabled={bulkBusy || !bulkPlanId} onClick={() => void runBulk("assign_plan")}>
            Assign budget plan
          </button>
          <button type="button" className="btn btn-danger" disabled={bulkBusy} onClick={() => void runBulk("delete")}>
            Delete Group
          </button>
          <button type="button" className="btn btn-ghost" disabled={bulkBusy} onClick={() => void runBulk("disable_members")}>
            Deactive all Members
          </button>
          <button type="button" className="btn btn-ghost dialog-actions-cancel" disabled={bulkBusy} onClick={() => setBulkOpen(false)}>
            Cancel
          </button>
        </div>
      </Modal>
    </AdminPage>
  );
}
