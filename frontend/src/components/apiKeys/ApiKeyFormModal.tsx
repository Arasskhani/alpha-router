import { FormEvent, ReactNode, useEffect, useState } from "react";

import Modal from "../Modal";

import ConnectionAllowlistField from "./ConnectionAllowlistField";
import ModelAllowlistField from "./ModelAllowlistField";
import UserOwnerSelect, { type OwnerUser } from "./UserOwnerSelect";

export type ApiKeyFormValues = {
  name: string;
  owner_user_id: number;
  credit_limit_usd: number | null;
  /** Explicit opt-out from the credit limit; required when the limit is empty/0. */
  unlimited_budget: boolean;
  reset_period: "daily" | "weekly" | "monthly";
  expiration_days: number | null;
  expiration_never: boolean;
  restrict_connections: boolean;
  allowed_connection_ids: number[];
  restrict_models: boolean;
  allowed_model_ids: number[];
};

type Props = {
  open: boolean;
  title: string;
  initial?: Partial<ApiKeyFormValues> & { owner_user_id?: number };
  onClose: () => void;
  onSubmit: (values: ApiKeyFormValues) => Promise<void>;
  headerActions?: ReactNode;
};

const defaultValues: ApiKeyFormValues = {
  name: "",
  owner_user_id: 0,
  credit_limit_usd: null,
  unlimited_budget: false,
  reset_period: "monthly",
  expiration_days: null,
  expiration_never: false,
  restrict_connections: false,
  allowed_connection_ids: [],
  restrict_models: false,
  allowed_model_ids: [],
};

export default function ApiKeyFormModal({ open, title, initial, onClose, onSubmit, headerActions }: Props) {
  const [form, setForm] = useState<ApiKeyFormValues>(defaultValues);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open) return;
    setErr("");
    setForm({
      name: initial?.name ?? "",
      owner_user_id: initial?.owner_user_id ?? 0,
      credit_limit_usd: initial?.credit_limit_usd ?? null,
      unlimited_budget: initial?.unlimited_budget ?? false,
      reset_period: initial?.reset_period ?? "monthly",
      expiration_days: initial?.expiration_days ?? null,
      expiration_never: initial?.expiration_never ?? false,
      restrict_connections: initial?.restrict_connections ?? false,
      allowed_connection_ids: initial?.allowed_connection_ids ?? [],
      restrict_models: initial?.restrict_models ?? false,
      allowed_model_ids: initial?.allowed_model_ids ?? [],
    });
  }, [open, initial]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!form.owner_user_id) {
      setErr("Select an owner.");
      return;
    }
    if (!form.name.trim()) {
      setErr("Name is required.");
      return;
    }
    if (!form.expiration_never && (form.expiration_days == null || form.expiration_days < 1)) {
      setErr("Enter expiration days or choose Never.");
      return;
    }
    setSaving(true);
    setErr("");
    try {
      await onSubmit(form);
      onClose();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} title={title} onClose={onClose} headerActions={headerActions}>
      <form className="api-key-form" onSubmit={handleSubmit}>
        <label className="api-key-form__label" htmlFor="api-key-form-owner">
          Owner
          <UserOwnerSelect
            inputId="api-key-form-owner"
            value={form.owner_user_id || null}
            onChange={(u: OwnerUser | null) =>
              setForm((f) => ({ ...f, owner_user_id: u?.id ?? 0 }))
            }
            disabled={saving}
          />
        </label>
        <label className="api-key-form__label">
          Name
          <input
            className="input-block"
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            required
          />
        </label>
        <label className="api-key-form__label">
          Credit limit (USD, optional)
          <input
            type="number"
            min={0}
            step={0.01}
            className="input-block"
            value={form.credit_limit_usd ?? ""}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                credit_limit_usd: e.target.value === "" ? null : Number(e.target.value),
              }))
            }
          />
          <span className="muted-text api-key-form__hint">
            A key without a positive limit is blocked unless you mark it unlimited below.
          </span>
        </label>
        <label className="api-key-form__label" style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <input
            type="checkbox"
            checked={form.unlimited_budget}
            onChange={(e) => setForm((f) => ({ ...f, unlimited_budget: e.target.checked }))}
          />
          <span>Unlimited budget (no credit cap)</span>
        </label>
        {form.unlimited_budget ? (
          <p className="form-hint form-hint--warning">
            This key can spend without any per-period ceiling. Every request is still billed to the
            owner&apos;s account.
          </p>
        ) : null}
        <label className="api-key-form__label">
          Reset limit every…
          <select
            className="input-block"
            value={form.reset_period}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                reset_period: e.target.value as ApiKeyFormValues["reset_period"],
              }))
            }
          >
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
          </select>
        </label>
        <label className="api-key-form__label">
          Expiration
          <div className="api-key-form__expiration">
            <label className="api-key-form__never">
              <input
                type="checkbox"
                checked={form.expiration_never}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    expiration_never: e.target.checked,
                    expiration_days: e.target.checked ? null : f.expiration_days,
                  }))
                }
              />
              Never
            </label>
            {!form.expiration_never ? (
              <input
                type="number"
                min={1}
                className="input-block"
                placeholder="Days active"
                value={form.expiration_days ?? ""}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    expiration_days: e.target.value ? Number(e.target.value) : null,
                  }))
                }
              />
            ) : null}
          </div>
          <span className="muted-text api-key-form__hint">
            After N days the key is deactivated automatically
          </span>
        </label>
        <fieldset className="api-key-form__connections">
          <legend className="api-key-form__label">Allowed connections</legend>
          <label className="api-key-form__never">
            <input
              type="checkbox"
              checked={form.restrict_connections}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  restrict_connections: e.target.checked,
                }))
              }
              disabled={saving}
            />
            Limit this key to specific connections
          </label>
          {form.restrict_connections ? (
            <ConnectionAllowlistField
              selectedIds={form.allowed_connection_ids}
              onChange={(ids) => setForm((f) => ({ ...f, allowed_connection_ids: ids }))}
              disabled={saving}
            />
          ) : (
            <span className="muted-text api-key-form__hint">
              Unchecked: the key can use models from all active connections (still subject to model access).
            </span>
          )}
        </fieldset>
        <fieldset className="api-key-form__connections">
          <legend className="api-key-form__label">Allowed models</legend>
          <label className="api-key-form__never">
            <input
              type="checkbox"
              checked={form.restrict_models}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  restrict_models: e.target.checked,
                }))
              }
              disabled={saving}
            />
            Limit this key to specific models
          </label>
          {form.restrict_models ? (
            <ModelAllowlistField
              ownerUserId={form.owner_user_id}
              connectionIds={form.restrict_connections ? form.allowed_connection_ids : []}
              restrictConnections={form.restrict_connections}
              selectedIds={form.allowed_model_ids}
              onChange={(ids) => setForm((f) => ({ ...f, allowed_model_ids: ids }))}
              disabled={saving}
            />
          ) : (
            <span className="muted-text api-key-form__hint">
              Unchecked: all models allowed by connection policy and the owner&apos;s catalog access.
            </span>
          )}
        </fieldset>
        {err && <p className="alert alert-error">{err}</p>}
        <div className="dialog-actions">
          <button type="submit" className="btn" disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
          <button type="button" className="btn btn-ghost dialog-actions-cancel" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
}
