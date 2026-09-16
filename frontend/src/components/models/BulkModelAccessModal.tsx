import { FormEvent, useEffect, useMemo, useState } from "react";

import { api } from "../../api";
import Modal from "../Modal";
import AccessSubjectPicker, { type AccessGroup, type AccessUser } from "./AccessSubjectPicker";

type SummaryUser = AccessUser & { model_count: number };
type SummaryGroup = AccessGroup & { model_count: number };

type AccessSummary = {
  model_count: number;
  private_count: number;
  public_count: number;
  users: SummaryUser[];
  groups: SummaryGroup[];
};

type Props = {
  open: boolean;
  modelIds: number[];
  onClose: () => void;
  onSaved: (message: string) => Promise<void> | void;
};

/**
 * Make a set of models private to one audience.
 *
 * Bulk edit could set the access type and nothing else, so an administrator
 * could privatise forty models and then had no way to say who they were
 * private *to* except opening each model in turn. It also left each model's
 * existing assignments alone, which meant one action could give the selected
 * models different audiences depending on what they already had.
 *
 * This dialog opens on the audience the selection currently has and writes
 * back exactly what is on screen: the last change is the source of truth.
 * Removing a chip removes that access from every selected model; adding one
 * grants it to all of them.
 */
export default function BulkModelAccessModal({ open, modelIds, onClose, onSaved }: Props) {
  const [summary, setSummary] = useState<AccessSummary | null>(null);
  const [users, setUsers] = useState<AccessUser[]>([]);
  const [groups, setGroups] = useState<AccessGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmedEmpty, setConfirmedEmpty] = useState(false);
  const [err, setErr] = useState("");

  const count = modelIds.length;

  useEffect(() => {
    if (!open || count === 0) return;
    setErr("");
    setConfirmedEmpty(false);
    setLoading(true);
    api<AccessSummary>("/api/admin/models/access-summary", {
      method: "POST",
      body: JSON.stringify({ ids: modelIds }),
    })
      .then((data) => {
        setSummary(data);
        setUsers(data.users || []);
        setGroups(data.groups || []);
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
    // modelIds is a fresh array each render; the selection size and the open
    // flag are what actually decide when to reload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, count]);

  /** "on 12 of 40" — only when a subject does not already cover every model. */
  const noteFor = useMemo(() => {
    const userCounts = new Map((summary?.users || []).map((u) => [u.id, u.model_count]));
    const groupCounts = new Map((summary?.groups || []).map((g) => [g.id, g.model_count]));
    return (kind: "user" | "group", id: number): string | null => {
      const held = (kind === "user" ? userCounts : groupCounts).get(id);
      if (held == null || held >= count) return null;
      return `on ${held} of ${count}`;
    };
  }, [summary, count]);

  const partialCount = useMemo(() => {
    const all = [...(summary?.users || []), ...(summary?.groups || [])];
    return all.filter((s) => s.model_count < count).length;
  }, [summary, count]);

  const willBeEmpty = users.length === 0 && groups.length === 0;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!count || saving) return;
    if (willBeEmpty && !confirmedEmpty) {
      setConfirmedEmpty(true);
      return;
    }
    setSaving(true);
    setErr("");
    try {
      await api("/api/admin/models/access", {
        method: "PUT",
        body: JSON.stringify({
          ids: modelIds,
          access_type: "private",
          user_ids: users.map((u) => u.id),
          group_ids: groups.map((g) => g.id),
        }),
      });
      const audience =
        users.length + groups.length === 0
          ? "Super Admins only"
          : `${users.length} user(s) and ${groups.length} group(s)`;
      await onSaved(`Set ${count} model(s) to Private for ${audience}.`);
      onClose();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} title="Private — who can use these?" onClose={() => !saving && onClose()}>
      <form className="model-access-form" onSubmit={handleSubmit}>
        <p className="muted-text model-access-form__label">
          {count} model(s) selected
          {summary && summary.private_count > 0 ? ` · ${summary.private_count} already private` : ""}
        </p>
        {loading ? <p className="muted-text">Loading current access…</p> : null}
        {err ? <p className="alert alert-error">{err}</p> : null}

        <p className="muted-text model-access-form__hint">
          This list becomes the access for <strong>every</strong> selected model. Remove someone and
          they lose access to all of them; add someone and they gain it on all of them.
        </p>

        {partialCount > 0 ? (
          <p className="alert alert-warning">
            {partialCount} of the entries below currently applies to only some of the selected
            models (marked “on N of {count}”). Keeping one grants it on all {count}; removing it
            revokes it everywhere.
          </p>
        ) : null}

        <div className="model-access-form__private">
          <AccessSubjectPicker
            users={users}
            groups={groups}
            onChangeUsers={setUsers}
            onChangeGroups={setGroups}
            disabled={saving || loading}
            noteFor={noteFor}
          />
        </div>

        {willBeEmpty ? (
          <p className={confirmedEmpty ? "alert alert-warning" : "muted-text"}>
            {confirmedEmpty
              ? `No one is selected. These ${count} model(s) will be usable by Super Admins only. Press Apply again to confirm.`
              : `With no one selected, these ${count} model(s) become usable by Super Admins only.`}
          </p>
        ) : null}

        <div className="dialog-actions">
          <button type="submit" className="btn" disabled={loading || saving || count === 0}>
            {saving ? "…" : confirmedEmpty && willBeEmpty ? "Apply anyway" : "Apply"}
          </button>
          <button type="button" className="btn btn-ghost" disabled={saving} onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
}
