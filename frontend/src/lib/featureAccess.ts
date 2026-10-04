/** Types and wording for the Feature Access admin page (`/api/admin/feature-access`). */

export type FeatureKey = "chat" | "projects" | "api_keys";
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
  reason: "default" | "admin" | "user_allow" | "user_deny" | "group_deny" | "department_deny";
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
    default:
      return "No rule applies.";
  }
}
