import { FormEvent, useEffect, useState } from "react";

import { api } from "../../api";
import Modal from "../Modal";
import AccessSubjectPicker, { type AccessGroup, type AccessUser } from "./AccessSubjectPicker";
import type { ModelAccessType } from "../../lib/modelCatalog";

type AccessDetail = {
  model_id: number;
  access_type: ModelAccessType;
  users: AccessUser[];
  groups: AccessGroup[];
};

type Props = {
  open: boolean;
  modelId: number | null;
  modelLabel: string;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
};

export default function ModelAccessModal({ open, modelId, modelLabel, onClose, onSaved }: Props) {
  const [accessType, setAccessType] = useState<ModelAccessType>("public");
  const [users, setUsers] = useState<AccessUser[]>([]);
  const [groups, setGroups] = useState<AccessGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open || modelId == null) return;
    setErr("");
    setLoading(true);
    api<AccessDetail>(`/api/admin/models/${modelId}/access`)
      .then((detail) => {
        setAccessType(detail.access_type === "private" ? "private" : "public");
        setUsers(detail.users || []);
        setGroups(detail.groups || []);
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }, [open, modelId]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (modelId == null) return;
    setSaving(true);
    setErr("");
    try {
      await api(`/api/admin/models/${modelId}/access`, {
        method: "PUT",
        body: JSON.stringify({
          access_type: accessType,
          user_ids: accessType === "private" ? users.map((u) => u.id) : [],
          group_ids: accessType === "private" ? groups.map((g) => g.id) : [],
        }),
      });
      await onSaved();
      onClose();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} title="Model access" onClose={() => !saving && onClose()}>
      <form className="model-access-form" onSubmit={handleSubmit}>
        <p className="muted-text model-access-form__label">{modelLabel}</p>
        {loading ? <p className="muted-text">Loading…</p> : null}
        {err ? <p className="alert alert-error">{err}</p> : null}

        <fieldset className="model-access-form__type" disabled={loading || saving}>
          <legend>Access type</legend>
          <label className="model-access-form__radio">
            <input
              type="radio"
              name="access_type"
              checked={accessType === "public"}
              onChange={() => setAccessType("public")}
            />
            <span>
              <strong>Public</strong>
              <span className="muted-text"> — all logged-in users</span>
            </span>
          </label>
          <label className="model-access-form__radio">
            <input
              type="radio"
              name="access_type"
              checked={accessType === "private"}
              onChange={() => setAccessType("private")}
            />
            <span>
              <strong>Private</strong>
              <span className="muted-text"> — selected users/groups only</span>
            </span>
          </label>
        </fieldset>

        {accessType === "private" ? (
          <div className="model-access-form__private">
            <p className="muted-text model-access-form__hint">
              Leave empty to allow Super Admins only.
            </p>

            <AccessSubjectPicker
              users={users}
              groups={groups}
              onChangeUsers={setUsers}
              onChangeGroups={setGroups}
              disabled={saving || loading}
            />
          </div>
        ) : null}

        <div className="dialog-actions">
          <button type="submit" className="btn" disabled={loading || saving}>
            {saving ? "…" : "Save"}
          </button>
          <button type="button" className="btn btn-ghost" disabled={saving} onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
}
