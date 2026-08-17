import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import {
  AccessGrantInput,
  ResourceAccessRecord,
} from "../../lib/agentPlatform";

type GroupRow = { id: number; name: string; source?: string };
type RoleRow = { slug: string; name: string };

type Props = {
  title?: string;
  loadPath: string;
  savePath: string;
  disabled?: boolean;
  onSaved?: (access: ResourceAccessRecord) => void;
  onError?: (message: string) => void;
};

export default function ResourceAccessEditor({
  title = "Access control",
  loadPath,
  savePath,
  disabled,
  onSaved,
  onError,
}: Props) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [accessType, setAccessType] = useState<"public" | "private">("private");
  const [aclVersion, setAclVersion] = useState(0);
  const [grants, setGrants] = useState<AccessGrantInput[]>([]);
  const [groups, setGroups] = useState<GroupRow[]>([]);
  const [roles, setRoles] = useState<RoleRow[]>([]);
  const [targetType, setTargetType] = useState<AccessGrantInput["target_type"]>("group");
  const [target, setTarget] = useState("");
  const [effect, setEffect] = useState<"allow" | "deny">("allow");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api<ResourceAccessRecord>(loadPath)
      .then((row) => {
        if (cancelled) return;
        setAccessType(row.access_type);
        setAclVersion(row.acl_version);
        setGrants(
          (row.grants || []).map((grant) => ({
            target_type: grant.target_type,
            target: grant.target,
            effect: grant.effect,
          })),
        );
      })
      .catch((err) => {
        if (!cancelled) onError?.(String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload only when resource path changes
  }, [loadPath]);

  useEffect(() => {
    api<GroupRow[]>("/api/admin/groups")
      .then(setGroups)
      .catch(() => setGroups([]));
    api<RoleRow[]>("/api/admin/roles")
      .then((rows) => setRoles(rows.map((row) => ({ slug: row.slug, name: row.name }))))
      .catch(() => setRoles([]));
  }, []);

  const grantLabels = useMemo(() => {
    const groupNames = new Map(groups.map((group) => [String(group.id), group.name]));
    const roleNames = new Map(roles.map((role) => [role.slug, role.name]));
    return grants.map((grant) => {
      if (grant.target_type === "group") {
        return groupNames.get(String(grant.target)) || `Group #${grant.target}`;
      }
      if (grant.target_type === "role") {
        return roleNames.get(String(grant.target)) || String(grant.target);
      }
      if (grant.target_type === "user") return `User #${grant.target}`;
      return String(grant.target);
    });
  }, [grants, groups, roles]);

  function addGrant(e: FormEvent) {
    e.preventDefault();
    const raw = target.trim();
    if (!raw) return;
    const normalizedTarget =
      targetType === "user" || targetType === "group" ? Number(raw) : raw;
    if (
      (targetType === "user" || targetType === "group")
      && (!Number.isFinite(normalizedTarget) || Number(normalizedTarget) <= 0)
    ) {
      onError?.("User/Group target must be a positive numeric id.");
      return;
    }
    const next: AccessGrantInput = {
      target_type: targetType,
      target: normalizedTarget,
      effect,
    };
    const key = `${next.target_type}:${next.target}:${next.effect}`;
    if (
      grants.some(
        (grant) => `${grant.target_type}:${grant.target}:${grant.effect}` === key,
      )
    ) {
      return;
    }
    setGrants((current) => [...current, next]);
    setTarget("");
  }

  async function saveAccess() {
    setSaving(true);
    try {
      const saved = await api<ResourceAccessRecord>(savePath, {
        method: "PUT",
        body: JSON.stringify({
          access_type: accessType,
          grants,
        }),
      });
      setAccessType(saved.access_type);
      setAclVersion(saved.acl_version);
      setGrants(
        (saved.grants || []).map((grant) => ({
          target_type: grant.target_type,
          target: grant.target,
          effect: grant.effect,
        })),
      );
      onSaved?.(saved);
    } catch (err) {
      onError?.(String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="agent-section-card">
      <div className="agent-section-card__head">
        <div>
          <h3>{title}</h3>
          <p>
            Private resources require an allow grant. Deny always wins. ACL v{aclVersion || 0}.
          </p>
        </div>
        <button
          type="button"
          className="btn"
          disabled={disabled || loading || saving}
          onClick={() => void saveAccess()}
        >
          {saving ? "Saving…" : "Save access"}
        </button>
      </div>

      <label>
        Visibility
        <select
          value={accessType}
          disabled={disabled || loading}
          onChange={(e) => setAccessType(e.target.value as "public" | "private")}
        >
          <option value="private">Private</option>
          <option value="public">Public</option>
        </select>
      </label>

      <form className="agent-inline-form resource-access-form" onSubmit={addGrant}>
        <select
          value={targetType}
          disabled={disabled || loading}
          onChange={(e) => {
            setTargetType(e.target.value as AccessGrantInput["target_type"]);
            setTarget("");
          }}
        >
          <option value="group">Group</option>
          <option value="role">Role</option>
          <option value="department">Department</option>
          <option value="user">User ID</option>
        </select>
        {targetType === "group" && groups.length > 0 ? (
          <select
            value={target}
            disabled={disabled || loading}
            onChange={(e) => setTarget(e.target.value)}
          >
            <option value="">Select group…</option>
            {groups.map((group) => (
              <option key={group.id} value={String(group.id)}>
                {group.name}
              </option>
            ))}
          </select>
        ) : null}
        {targetType === "role" && roles.length > 0 ? (
          <select
            value={target}
            disabled={disabled || loading}
            onChange={(e) => setTarget(e.target.value)}
          >
            <option value="">Select role…</option>
            {roles.map((role) => (
              <option key={role.slug} value={role.slug}>
                {role.name}
              </option>
            ))}
          </select>
        ) : null}
        {targetType === "user" || targetType === "department" || (targetType === "group" && groups.length === 0) || (targetType === "role" && roles.length === 0) ? (
          <input
            value={target}
            disabled={disabled || loading}
            placeholder={
              targetType === "user"
                ? "User id"
                : targetType === "department"
                  ? "Department name"
                  : "Target"
            }
            onChange={(e) => setTarget(e.target.value)}
          />
        ) : null}
        <select
          value={effect}
          disabled={disabled || loading}
          onChange={(e) => setEffect(e.target.value as "allow" | "deny")}
        >
          <option value="allow">Allow</option>
          <option value="deny">Deny</option>
        </select>
        <button type="submit" className="btn btn-ghost" disabled={disabled || loading || !target.trim()}>
          Add grant
        </button>
      </form>

      <div className="agent-chip-list">
        {grants.map((grant, index) => (
          <span className="agent-binding-chip" key={`${grant.target_type}-${grant.target}-${grant.effect}-${index}`}>
            <strong>{grant.effect}</strong>
            <em>{grant.target_type}</em>
            {grantLabels[index]}
            <button
              type="button"
              disabled={disabled || loading}
              onClick={() => setGrants((current) => current.filter((_, i) => i !== index))}
            >
              Remove
            </button>
          </span>
        ))}
        {!loading && grants.length === 0 ? (
          <p className="agent-empty">
            {accessType === "private"
              ? "No grants yet — private means nobody can use this until you allow a target."
              : "No explicit grants. Public access is open unless a deny grant matches."}
          </p>
        ) : null}
      </div>
    </section>
  );
}
