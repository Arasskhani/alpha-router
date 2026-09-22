/**
 * The words the Sign-in Activity page uses for the codes the server stores.
 *
 * The server keeps stable codes (`app.models.auth_event`); this file owns the
 * human labels, so a wording change is a frontend change and a new code the
 * page has not learned yet still shows *something* rather than nothing.
 */

type SignInEventType = "login_success" | "login_failed" | "login_rate_limited" | "logout" | "session_revoked";

export type SignInEvent = {
  id: number;
  occurred_at: string | null;
  user_id: number | null;
  username: string | null;
  event_type: SignInEventType | string;
  outcome: "success" | "failure" | "n/a" | string;
  scope: string | null;
  reason_code: string | null;
  reason_detail: string | null;
  auth_method: string | null;
  ip: string | null;
  user_agent: string | null;
  session_id: string | null;
  correlation_id: string | null;
  backfilled: boolean;
};

type SignInEventAccount = {
  id: number;
  username: string;
  display_name: string | null;
  auth_provider: string | null;
  is_active: boolean;
  deleted_at: string | null;
  purged_at: string | null;
};

export type SignInEventDetail = SignInEvent & {
  user: SignInEventAccount | null;
};

export type SignInFilterOptions = {
  event_types: string[];
  outcomes: string[];
  reason_codes: string[];
  auth_methods: string[];
};

const EVENT_LABELS: Record<string, string> = {
  login_success: "Signed in",
  login_failed: "Sign-in failed",
  login_rate_limited: "Rate limited",
  logout: "Signed out",
  session_revoked: "Sessions revoked",
};

const OUTCOME_LABELS: Record<string, string> = {
  success: "Success",
  failure: "Failure",
  "n/a": "—",
};

const METHOD_LABELS: Record<string, string> = {
  local: "Local",
  ldap: "LDAP",
  saml: "SAML",
  oidc: "OIDC",
};

/**
 * Why a sign-in failed, or why every session ended, as a sentence fragment.
 * Kept short enough for a table cell; the detail modal shows the provider's
 * own message beside it when one was recorded.
 */
export const REASON_LABELS: Record<string, string> = {
  bad_password: "Wrong password",
  no_such_user: "No such account",
  account_inactive: "Account deactivated",
  account_deleted: "Account deleted",
  twofa_required: "Two-factor code required",
  twofa_failed: "Two-factor code rejected",
  ldap_unavailable: "Directory unreachable",
  ldap_rejected: "Directory rejected the credentials",
  saml_rejected: "SAML response rejected",
  oidc_rejected: "OIDC callback rejected",
  sso_code_invalid: "Sign-on code invalid or expired",
  unknown: "Reason not recorded",
  rate_limited: "Too many attempts",
  password_changed: "Password changed",
  admin_password_reset: "Password reset by an administrator",
  admin_2fa_disabled: "Two-factor disabled by an administrator",
  user_deactivated: "Account deactivated by an administrator",
  user_deleted: "Account deleted",
};

function humanCode(value: string): string {
  const spaced = value.replace(/_/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function eventLabel(type: string): string {
  return EVENT_LABELS[type] ?? humanCode(type);
}

export function outcomeLabel(outcome: string): string {
  return OUTCOME_LABELS[outcome] ?? humanCode(outcome);
}

export function methodLabel(method: string | null): string {
  if (!method) return "—";
  return METHOD_LABELS[method] ?? method.toUpperCase();
}

export function reasonLabel(code: string | null): string {
  if (!code) return "—";
  return REASON_LABELS[code] ?? humanCode(code);
}

/**
 * The badge colour is the outcome, not the event type: green for a sign-in
 * that worked, red for one that did not (including being rate-limited), and
 * grey for a sign-out or revocation, which is neither.
 */
export function outcomeBadgeClass(event: Pick<SignInEvent, "outcome">): string {
  if (event.outcome === "success") return "status-badge status-badge--active";
  if (event.outcome === "failure") return "status-badge status-badge--failed";
  return "status-badge status-badge--neutral";
}

/**
 * A sign-out in this product bumps the account's token version, which ends
 * every session on every device — so a revocation row is described as
 * "signed out everywhere", and never paired with one sign-in as a duration.
 */
export function scopeSentence(event: Pick<SignInEvent, "event_type" | "scope" | "reason_code">): string | null {
  if (event.event_type === "session_revoked") {
    const why = event.reason_code ? reasonLabel(event.reason_code).toLowerCase() : "an administrative action";
    return `Signed out everywhere: ${why}.`;
  }
  if (event.event_type === "logout" && event.scope === "all_sessions") {
    return "Signing out ends every session for the account, on every device.";
  }
  return null;
}

/**
 * True for accounts that sign in through an identity provider. Their sign-out
 * is not recorded here — the provider's own log is the record of it — so the
 * page says so rather than showing a gap.
 */
export function signOutIsRecordedByIdp(method: string | null): boolean {
  return method === "saml" || method === "oidc";
}

export const IDP_SIGN_OUT_NOTE = "Sign-out for this account is recorded by your identity provider, not here.";

export type SignInFilters = {
  userId: string;
  username: string;
  eventType: string;
  outcome: string;
  reasonCode: string;
  authMethod: string;
  ip: string;
  start: string;
  end: string;
};

export const EMPTY_FILTERS: SignInFilters = {
  userId: "",
  username: "",
  eventType: "",
  outcome: "",
  reasonCode: "",
  authMethod: "",
  ip: "",
  start: "",
  end: "",
};

/**
 * The same query for the list and the export, so the file always carries the
 * page's rows. `limit`/`offset` are added only when paging.
 */
export function buildSignInQuery(filters: SignInFilters, paging?: { limit: number; offset: number }): URLSearchParams {
  const q = new URLSearchParams();
  if (paging) {
    q.set("limit", String(paging.limit));
    q.set("offset", String(paging.offset));
  }
  const userId = Number(filters.userId);
  if (Number.isInteger(userId) && userId > 0) q.set("user_id", String(userId));
  if (filters.username.trim()) q.set("username", filters.username.trim());
  if (filters.eventType) q.set("event_type", filters.eventType);
  if (filters.outcome) q.set("outcome", filters.outcome);
  if (filters.reasonCode) q.set("reason_code", filters.reasonCode);
  if (filters.authMethod) q.set("auth_method", filters.authMethod);
  if (filters.ip.trim()) q.set("ip", filters.ip.trim());
  if (filters.start) q.set("start_date", filters.start);
  if (filters.end) q.set("end_date", filters.end);
  return q;
}

/** `?user=<id>` from the Users page row action; anything else is ignored. */
export function userIdFromSearch(params: URLSearchParams): string {
  const raw = params.get("user") ?? "";
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? String(id) : "";
}

export function signInActivityPathForUser(userId: number): string {
  return `/admin/sign-in-activity?user=${userId}`;
}
