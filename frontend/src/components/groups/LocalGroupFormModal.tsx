import { FormEvent, useEffect, useState } from "react";
import Modal from "../Modal";

export type LocalGroupFormValues = {
  name: string;
  description: string;
  budget_plan: string;
};

export type LocalGroupInitial = {
  id: number;
  name: string;
  description: string | null;
  plan_id: number | null;
};

type PlanOption = { id: number; name: string };

type Props = {
  open: boolean;
  mode: "create" | "edit";
  initial?: LocalGroupInitial | null;
  plans: PlanOption[];
  onClose: () => void;
  onSubmit: (values: LocalGroupFormValues) => Promise<void>;
};

const emptyValues: LocalGroupFormValues = {
  name: "",
  description: "",
  budget_plan: "__none__",
};

function toFormValues(initial?: LocalGroupInitial | null): LocalGroupFormValues {
  if (!initial) return emptyValues;
  return {
    name: initial.name,
    description: initial.description ?? "",
    budget_plan: initial.plan_id ? String(initial.plan_id) : "__none__",
  };
}

export default function LocalGroupFormModal({ open, mode, initial, plans, onClose, onSubmit }: Props) {
  const [form, setForm] = useState<LocalGroupFormValues>(emptyValues);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open) return;
    setErr("");
    setForm(toFormValues(mode === "edit" ? initial : null));
  }, [open, mode, initial]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) {
      setErr("Name is required.");
      return;
    }
    setSaving(true);
    setErr("");
    try {
      await onSubmit({
        name: form.name.trim(),
        description: form.description.trim(),
        budget_plan: form.budget_plan,
      });
      onClose();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setSaving(false);
    }
  }

  const title = mode === "create" ? "Create local group" : "Edit local group";
  const submitLabel = mode === "create" ? "Create" : "Save";
  const savingLabel = mode === "create" ? "Creating…" : "Saving…";

  return (
    <Modal open={open} title={title} onClose={onClose}>
      <form onSubmit={handleSubmit}>
        {mode === "edit" && initial ? (
          <p className="muted-text" style={{ marginTop: 0 }}>
            Local group · <strong>{initial.name}</strong>
          </p>
        ) : null}
        <label htmlFor="local-group-form-modal-name">Name</label>
        <input id="local-group-form-modal-name"
          className="input-block"
          value={form.name}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          required
        />
        <label htmlFor="local-group-form-modal-description">Description</label>
        <textarea id="local-group-form-modal-description"
          className="input-block"
          rows={3}
          value={form.description}
          onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
        />
        <label htmlFor="local-group-form-modal-budget-plan">Budget plan</label>
        <select id="local-group-form-modal-budget-plan"
          className="input-block"
          value={form.budget_plan}
          onChange={(e) => setForm((f) => ({ ...f, budget_plan: e.target.value }))}
        >
          <option value="__none__">No plan</option>
          {plans.map((p) => (
            <option key={p.id} value={String(p.id)}>
              {p.name}
            </option>
          ))}
        </select>
        <p className="muted-text" style={{ marginTop: "-0.35rem", marginBottom: "0.75rem" }}>
          Members with «From group» budget inherit this plan when assigned to the group.
        </p>
        {err && <p className="alert alert-error" role="alert">{err}</p>}
        <div className="dialog-actions">
          <button type="submit" className="btn" disabled={saving}>
            {saving ? savingLabel : submitLabel}
          </button>
          <button type="button" className="btn btn-ghost dialog-actions-cancel" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
}
