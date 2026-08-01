import { FormEvent, useEffect, useMemo, useState } from "react";

import { api } from "../../api";
import Modal from "../Modal";
import type { ModelAccessType } from "../../lib/modelCatalog";

type AccessUser = {
  id: number;
  username: string;
  email: string;
  display_name: string | null;
};

type AccessGroup = {
  id: number;
  name: string;
  source: string;
};

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
  const [allGroups, setAllGroups] = useState<AccessGroup[]>([]);
  const [userQuery, setUserQuery] = useState("");
  const [groupQuery, setGroupQuery] = useState("");
  const [userHits, setUserHits] = useState<AccessUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open || modelId == null) return;
    setErr("");
    setUserQuery("");
    setGroupQuery("");
    setUserHits([]);
    setLoading(true);
    Promise.all([
      api<AccessDetail>(`/api/admin/models/${modelId}/access`),
      api<AccessGroup[]>("/api/admin/groups"),
    ])
      .then(([detail, groupRows]) => {
        setAccessType(detail.access_type === "private" ? "private" : "public");
        setUsers(detail.users || []);
        setGroups(detail.groups || []);
        setAllGroups(
          (groupRows || []).map((g) => ({
            id: g.id,
            name: g.name,
            source: g.source || "local",
          })),
        );
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }, [open, modelId]);

  useEffect(() => {
    if (!open || accessType !== "private") return;
    const term = userQuery.trim();
    if (term.length < 2) {
      setUserHits([]);
      return;
    }
    const t = window.setTimeout(() => {
      const qs = new URLSearchParams({ picker: "true", q: term });
      api<AccessUser[]>(`/api/admin/users?${qs}`)
        .then(setUserHits)
        .catch(() => setUserHits([]));
    }, 200);
    return () => window.clearTimeout(t);
  }, [userQuery, open, accessType]);

  const groupHits = useMemo(() => {
    const term = groupQuery.trim().toLowerCase();
    if (term.length < 1) return [];
    const selected = new Set(groups.map((g) => g.id));
    return allGroups
      .filter((g) => !selected.has(g.id))
      .filter((g) => {
        const name = (g.name || "").toLowerCase();
        const source = (g.source || "").toLowerCase();
        return name.includes(term) || source.includes(term);
      })
      .slice(0, 25);
  }, [allGroups, groups, groupQuery]);

  function addUser(u: AccessUser) {
    setUsers((prev) => (prev.some((x) => x.id === u.id) ? prev : [...prev, u]));
    setUserQuery("");
    setUserHits([]);
  }

  function removeUser(id: number) {
    setUsers((prev) => prev.filter((u) => u.id !== id));
  }

  function addGroup(g: AccessGroup) {
    setGroups((prev) => (prev.some((x) => x.id === g.id) ? prev : [...prev, g]));
    setGroupQuery("");
  }

  function removeGroup(id: number) {
    setGroups((prev) => prev.filter((g) => g.id !== id));
  }

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

            <label className="model-access-form__section-title">Users</label>
            <div className="model-access-chips">
              {users.map((u) => (
                <button
                  key={u.id}
                  type="button"
                  className="model-access-chip"
                  onClick={() => removeUser(u.id)}
                  title="Remove"
                >
                  {u.display_name || u.username}
                  <span aria-hidden>×</span>
                </button>
              ))}
            </div>
            <input
              className="input-block"
              placeholder="Search users (2+ characters)…"
              value={userQuery}
              onChange={(e) => setUserQuery(e.target.value)}
              disabled={saving}
            />
            {userHits.length > 0 ? (
              <ul className="model-access-hits">
                {userHits
                  .filter((u) => !users.some((x) => x.id === u.id))
                  .map((u) => (
                    <li key={u.id}>
                      <button type="button" onClick={() => addUser(u)}>
                        <strong>{u.display_name || u.username}</strong>
                        <span className="muted-text">{u.email}</span>
                      </button>
                    </li>
                  ))}
              </ul>
            ) : null}

            <label className="model-access-form__section-title">Groups</label>
            <div className="model-access-chips">
              {groups.map((g) => (
                <button
                  key={g.id}
                  type="button"
                  className="model-access-chip"
                  onClick={() => removeGroup(g.id)}
                  title="Remove"
                >
                  {g.name}
                  <span className="muted-text">({g.source})</span>
                  <span aria-hidden>×</span>
                </button>
              ))}
            </div>
            <input
              className="input-block"
              placeholder="Search groups…"
              value={groupQuery}
              onChange={(e) => setGroupQuery(e.target.value)}
              disabled={saving || loading}
            />
            {groupQuery.trim() && groupHits.length === 0 ? (
              <p className="muted-text model-access-form__empty-hits">No groups found</p>
            ) : null}
            {groupHits.length > 0 ? (
              <ul className="model-access-hits">
                {groupHits.map((g) => (
                  <li key={g.id}>
                    <button type="button" onClick={() => addGroup(g)}>
                      <strong>{g.name}</strong>
                      <span className="muted-text">{g.source}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
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
