import { FormEvent, useEffect, useState } from "react";
import Modal from "../Modal";

export type PlanFormValues = {
  name: string;
  monthly_budget_usd: number;
};

export type PlanInitial = {
  id: number;
  name: string;
  monthly_budget_usd: number;
};

type Props = {
  open: boolean;
  mode: "create" | "edit";
  initial?: PlanInitial | null;
  onClose: () => void;
  onSubmit: (values: PlanFormValues) => Promise<void>;
};

const emptyValues: PlanFormValues = {
  name: "",
  monthly_budget_usd: 5,
};

function toFormValues(initial?: PlanInitial | null): PlanFormValues {
  if (!initial) return emptyValues;
  return {
    name: initial.name,
    monthly_budget_usd: initial.monthly_budget_usd,
  };
}

export default function PlanFormModal({ open, mode, initial, onClose, onSubmit }: Props) {
  const [form, setForm] = useState<PlanFormValues>(emptyValues);
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
      setErr("Plan name is required.");
      return;
    }
    if (!Number.isFinite(form.monthly_budget_usd) || form.monthly_budget_usd < 0) {
      setErr("Monthly budget must be zero or greater.");
      return;
    }
    setSaving(true);
    setErr("");
    try {
      await onSubmit({
        name: form.name.trim(),
        monthly_budget_usd: form.monthly_budget_usd,
      });
      onClose();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setSaving(false);
    }
  }

  const title = mode === "create" ? "New plan" : "Edit plan";
  const submitLabel = mode === "create" ? "Create" : "Save";
  const savingLabel = mode === "create" ? "Creating…" : "Saving…";

  return (
    <Modal open={open} title={title} onClose={onClose}>
      <form onSubmit={handleSubmit}>
        {mode === "edit" && initial ? (
          <p className="muted-text" style={{ marginTop: 0 }}>
            Plan · <strong>{initial.name}</strong>
          </p>
        ) : null}
        <label>Plan name</label>
        <input
          className="input-block"
          value={form.name}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          required
        />
        <label>Monthly budget (USD)</label>
        <input
          type="number"
          step="0.01"
          min={0}
          className="input-block"
          value={form.monthly_budget_usd}
          onChange={(e) => setForm((f) => ({ ...f, monthly_budget_usd: Number(e.target.value) }))}
          required
        />
        {err && <p className="alert alert-error">{err}</p>}
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
