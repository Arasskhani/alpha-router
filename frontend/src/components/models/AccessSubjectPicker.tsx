import { useEffect, useMemo, useState } from "react";

import { api } from "../../api";

export type AccessUser = {
  id: number;
  username: string;
  email: string;
  display_name: string | null;
};

export type AccessGroup = {
  id: number;
  name: string;
  source: string;
};

type Props = {
  users: AccessUser[];
  groups: AccessGroup[];
  onChangeUsers: (next: AccessUser[]) => void;
  onChangeGroups: (next: AccessGroup[]) => void;
  disabled?: boolean;
  /**
   * Optional line under a chosen subject. The bulk dialog uses it to say how
   * many of the selected models a subject currently covers, so a group that
   * only holds twelve of forty is visible before it is replaced.
   */
  noteFor?: (kind: "user" | "group", id: number) => string | null;
};

/**
 * The users-and-groups picker shared by the single-model and bulk access
 * dialogs. It was written once inside the single-model modal; the bulk dialog
 * needs exactly the same control, and two copies of a permissions picker is
 * two places for them to drift apart.
 */
export default function AccessSubjectPicker({
  users,
  groups,
  onChangeUsers,
  onChangeGroups,
  disabled = false,
  noteFor,
}: Props) {
  const [allGroups, setAllGroups] = useState<AccessGroup[]>([]);
  const [userQuery, setUserQuery] = useState("");
  const [groupQuery, setGroupQuery] = useState("");
  const [userHits, setUserHits] = useState<AccessUser[]>([]);

  useEffect(() => {
    api<AccessGroup[]>("/api/admin/groups")
      .then((rows) =>
        setAllGroups((rows || []).map((g) => ({ id: g.id, name: g.name, source: g.source || "local" }))),
      )
      .catch(() => setAllGroups([]));
  }, []);

  useEffect(() => {
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
  }, [userQuery]);

  const groupHits = useMemo(() => {
    const term = groupQuery.trim().toLowerCase();
    if (term.length < 1) return [];
    const chosen = new Set(groups.map((g) => g.id));
    return allGroups
      .filter((g) => !chosen.has(g.id))
      .filter((g) => {
        const name = (g.name || "").toLowerCase();
        const source = (g.source || "").toLowerCase();
        return name.includes(term) || source.includes(term);
      })
      .slice(0, 25);
  }, [allGroups, groups, groupQuery]);

  function addUser(u: AccessUser) {
    if (!users.some((x) => x.id === u.id)) onChangeUsers([...users, u]);
    setUserQuery("");
    setUserHits([]);
  }

  function addGroup(g: AccessGroup) {
    if (!groups.some((x) => x.id === g.id)) onChangeGroups([...groups, g]);
    setGroupQuery("");
  }

  return (
    <>
      <p className="model-access-form__section-title">Users</p>
      <div className="model-access-chips">
        {users.map((u) => {
          const note = noteFor?.("user", u.id) || null;
          return (
            <button
              key={u.id}
              type="button"
              className="model-access-chip"
              onClick={() => onChangeUsers(users.filter((x) => x.id !== u.id))}
              title="Remove"
              disabled={disabled}
            >
              {u.display_name || u.username}
              {note ? <span className="muted-text">{note}</span> : null}
              <span aria-hidden>×</span>
            </button>
          );
        })}
      </div>
      <input
        className="input-block"
        placeholder="Search users (2+ characters)…"
        value={userQuery}
        onChange={(e) => setUserQuery(e.target.value)}
        disabled={disabled}
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

      <p className="model-access-form__section-title">Groups</p>
      <div className="model-access-chips">
        {groups.map((g) => {
          const note = noteFor?.("group", g.id) || null;
          return (
            <button
              key={g.id}
              type="button"
              className="model-access-chip"
              onClick={() => onChangeGroups(groups.filter((x) => x.id !== g.id))}
              title="Remove"
              disabled={disabled}
            >
              {g.name}
              <span className="muted-text">({g.source})</span>
              {note ? <span className="muted-text">{note}</span> : null}
              <span aria-hidden>×</span>
            </button>
          );
        })}
      </div>
      <input
        className="input-block"
        placeholder="Search groups…"
        value={groupQuery}
        onChange={(e) => setGroupQuery(e.target.value)}
        disabled={disabled}
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
    </>
  );
}
