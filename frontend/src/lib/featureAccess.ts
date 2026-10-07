/** Types and wording for the Feature Access admin page (`/api/admin/feature-access`). */

export type FeatureKey = "chat" | "projects" | "project_create" | "api_keys" | "extension";
export type RuleTarget = "user" | "group" | "department";

export type FeatureRule = {
  id: number;
  feature: FeatureKey;
  target_type: RuleTarget;
  target: number | string;
  label: string;
  sublabel: string | null;
  effect: "deny" | "allow";
  note: string | null;
  created_at: string | null;
  created_by: string | null;
};

export type FeatureOverview = {
  key: FeatureKey;
  title: string;
  rules: FeatureRule[];
  deny_count: number;
  allow_count: number;
};

export type TargetOptions = {
  groups: { id: number; name: string; source: string; member_count: number }[];
  departments: { name: string; user_count: number }[];
};

export type FeatureDecision = {
  feature: FeatureKey;
  title: string;
  allowed: boolean;
  reason:
    | "default"
    | "admin"
    | "user_allow"
    | "user_deny"
    | "group_deny"
    | "department_deny"
    | "projects_closed"
    | "chat_closed";
  rule_id: number | null;
  via: string | null;
};

export type FeatureCheck = {
  user: { id: number; label: string; department: string | null };
  features: FeatureDecision[];
};

export function targetTypeLabel(kind: RuleTarget): string {
  return kind === "user" ? "User" : kind === "group" ? "Group" : "Department";
}

/** One line under a section's title: who it is closed for at a glance. */
export function featureSummary(feature: Pick<FeatureOverview, "deny_count" | "allow_count">): string {
  if (feature.deny_count === 0 && feature.allow_count === 0) return "Open to everyone.";
  const parts = [`Denied by ${feature.deny_count} ${feature.deny_count === 1 ? "rule" : "rules"}`];
  if (feature.allow_count > 0) {
    parts.push(`given back to ${feature.allow_count} ${feature.allow_count === 1 ? "person" : "people"}`);
  }
  return `Open to everyone else. ${parts.join(", ")}.`;
}

/** What a section covers beyond its title, for the line under it on the admin page; empty for none. */
export function featureNote(key: FeatureKey): string {
  switch (key) {
    case "chat":
      return (
        "Closing Chat also closes Create projects, unless the person has an Allow there, and the chat of " +
        "projects that only they are in."
      );
    case "project_create":
      return (
        "Closed whenever Projects is, and whenever Chat is unless the person has an Allow here. Projects the " +
        "person is invited to keep working."
      );
    case "api_keys":
      return "Keys issued on the API Keys page are not affected.";
    case "extension":
      return "Downloading and connecting the browser extension, and every call it makes. Chat Tools applies on top.";
    default:
      return "";
  }
}

/** Why one person gets what they get, in the words of the check tool. */
export function decisionText(decision: Pick<FeatureDecision, "reason" | "via">): string {
  switch (decision.reason) {
    case "admin":
      return "Administrators always have access.";
    case "user_allow":
      return "Allowed for this person.";
    case "user_deny":
      return "Denied for this person.";
    case "group_deny":
      return `Denied for the group “${decision.via ?? ""}”.`;
    case "department_deny":
      return `Denied for the department “${decision.via ?? ""}”.`;
    case "projects_closed":
      return "Closed because Projects is closed for this person.";
    case "chat_closed":
      return "Closed because Chat is closed for this person. An Allow here gives it back.";
    default:
      return "No rule applies.";
  }
}
