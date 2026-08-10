import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { type RoleRecord } from "../../lib/rbac";
import Modal from "../Modal";

export type CreateLocalUserValues = {
  username: string;
  email: string;
  password: string;
  display_name: string;
  company: string;
  department: string;
  office: string;
  job_title: string;
  reporting_to: string;
  role: string;
  group_id: number | null;
  budget_plan: string;
};

type LocalGroup = { id: number; name: string };
type PlanOption = { id: number; name: string };

type Props = {
  open: boolean;
  roles: RoleRecord[];
  plans: PlanOption[];
  onClose: () => void;
  onSubmit: (values: CreateLocalUserValues) => Promise<void>;
};

const defaultValues: CreateLocalUserValues = {
  username: "",
  email: "",
  password: "",
  display_name: "",
  company: "",
  department: "",
  office: "",
  job_title: "",
  reporting_to: "",
  role: "user",
  group_id: null,
  budget_plan: "__inherit__",
};

export default function CreateLocalUserModal({ open, roles, plans, onClose, onSubmit }: Props) {
  const [form, setForm] = useState<CreateLocalUserValues>(defaultValues);
  const [localGroups, setLocalGroups] = useState<LocalGroup[]>([]);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open) return;
    setErr("");
    setForm(defaultValues);
    void api<LocalGroup[]>("/api/admin/groups?source=local")
      .then(setLocalGroups)
      .catch(() => setLocalGroups([]));
  }, [open]);

  const roleOptions = useMemo(
    () =>
      [...roles]
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((role) => (
          <option key={role.slug} value={role.slug}>
            {role.name}
          </option>
        )),
    [roles],
  );

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!form.username.trim()) {
      setErr("Username is required.");
      return;
    }
    if (!form.email.trim()) {
      setErr("Email is required.");
      return;
    }
    if (!form.password) {
      setErr("Password is required.");
      return;
    }
    setSaving(true);
    setErr("");
    try {
      await onSubmit({
        ...form,
        username: form.username.trim(),
        email: form.email.trim(),
        display_name: form.display_name.trim(),
        company: form.company.trim(),
        department: form.department.trim(),
        office: form.office.trim(),
        job_title: form.job_title.trim(),
        reporting_to: form.reporting_to.trim(),
      });
      onClose();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} title="Create local user" onClose={onClose}>
      <form onSubmit={handleSubmit}>
        <label>Username</label>
        <input
          className="input-block"
          value={form.username}
          onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
          autoComplete="off"
          required
        />
        <label>Email</label>
        <input
          type="email"
          className="input-block"
          value={form.email}
          onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
          autoComplete="off"
          required
        />
        <label>Password</label>
        <input
          type="password"
          className="input-block"
          value={form.password}
          onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
          autoComplete="new-password"
          required
        />
        <label>Display name</label>
        <input
          className="input-block"
          value={form.display_name}
          onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))}
        />
        <label>Company</label>
        <input
          className="input-block"
          value={form.company}
          onChange={(e) => setForm((f) => ({ ...f, company: e.target.value }))}
        />
        <label>Department</label>
        <input
          className="input-block"
          value={form.department}
          onChange={(e) => setForm((f) => ({ ...f, department: e.target.value }))}
        />
        <label>Office</label>
        <input
          className="input-block"
          value={form.office}
          onChange={(e) => setForm((f) => ({ ...f, office: e.target.value }))}
        />
        <label>Job title</label>
        <input
          className="input-block"
          value={form.job_title}
          onChange={(e) => setForm((f) => ({ ...f, job_title: e.target.value }))}
        />
        <label>Report to</label>
        <input
          className="input-block"
          value={form.reporting_to}
          onChange={(e) => setForm((f) => ({ ...f, reporting_to: e.target.value }))}
        />
        <label>Role</label>
        <select
          className="input-block"
          value={form.role}
          onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
        >
          {roleOptions}
        </select>
        <label>Group</label>
        <select
          className="input-block"
          value={form.group_id ?? ""}
          onChange={(e) =>
            setForm((f) => ({
              ...f,
              group_id: e.target.value ? Number(e.target.value) : null,
            }))
          }
        >
          <option value="">No group</option>
          {localGroups.map((g) => (
            <option key={g.id} value={String(g.id)}>
              {g.name}
            </option>
          ))}
        </select>
        {localGroups.length === 0 ? (
          <p className="muted-text" style={{ marginTop: "-0.35rem", marginBottom: "0.75rem" }}>
            No local groups yet.{" "}
            <Link to="/admin/groups" onClick={onClose}>
              Create one on Groups
            </Link>
            .
          </p>
        ) : (
          <p className="muted-text" style={{ marginTop: "-0.35rem", marginBottom: "0.75rem" }}>
            Only local groups are listed. LDAP membership is managed by directory sync; SAML users are provisioned on login.
          </p>
        )}
        <label>Budget plan</label>
        <select
          className="input-block"
          value={form.budget_plan}
          onChange={(e) => setForm((f) => ({ ...f, budget_plan: e.target.value }))}
        >
          <option value="__inherit__">From group</option>
          <option value="__none__">No Plan</option>
          {plans.map((p) => (
            <option key={p.id} value={String(p.id)}>
              {p.name}
            </option>
          ))}
        </select>
        {err && <p className="error">{err}</p>}
        <div className="modal-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button type="submit" className="btn" disabled={saving}>
            {saving ? "Creating…" : "Create user"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
