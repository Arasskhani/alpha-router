/**
 * Admin › Exchange EWS: the checks and wording the page needs beside the API
 * calls in `exchangeMail.ts`.
 *
 * The server checks every setting again on Save (`validate_settings`); these
 * checks only say what is wrong next to the field before a round trip, and
 * `fieldForServerMessage` puts the server's own refusal next to the field it
 * is about.
 */

import {
  SETTING_BOUNDS,
  type ConnectionStatus,
  type ExchangeSettings,
  type ExchangeSettingsResponse,
  type LoginFormat,
} from "./exchangeMail";

export type SettingsField = keyof ExchangeSettings;
export type SettingsErrors = Partial<Record<SettingsField, string>>;
type BoundedField = keyof typeof SETTING_BOUNDS;

export const EWS_URL_EXAMPLE = "https://mail.corp.example/EWS/Exchange.asmx";
/** The Admin Guide section the page links to (`pages/admin/docs/sections.tsx`). */
export const GUIDE_HREF = "/admin/docs#admin-exchange-ews";

export const LOGIN_FORMAT_OPTIONS: { value: LoginFormat; label: string; hint: string }[] = [
  { value: "netbios", label: "Domain and user name", hint: "CORP\\s.karimi, the usual Windows sign-in" },
  { value: "upn", label: "User principal name", hint: "s.karimi@corp.example" },
  { value: "email", label: "Email address", hint: "The account's email from the directory" },
];

export const STATUS_FILTERS: { value: ConnectionStatus | ""; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "connected", label: "Connected" },
  { value: "needs_password", label: "Password needed" },
  { value: "error", label: "Error" },
];

/**
 * Changing any of these makes every stored password unusable as it stands (another server or certificate
 * check, or another login made from the account), so the server sets every connection to "password needed"
 * on Save. The first four say where passwords are sent: only a Super Admin may change them (403
 * `super_admin_only` otherwise).
 */
const PASSWORD_RESET_FIELDS: readonly SettingsField[] = [
  "ews_url",
  "autodiscover_url",
  "verify_tls",
  "ca_bundle_pem",
  "login_format",
  "netbios_domain",
  "upn_suffix",
];
export const ONLY_SUPER_ADMIN_TEXT = "Only a Super Admin can change where Exchange passwords are sent.";
export const PASSWORDS_RESET_TEXT = "Everyone who connected a mailbox will have to type their password again.";

/** Whether saving `form` over `saved` makes everyone type their password again. */
export function resetsPasswords(saved: ExchangeSettings, form: ExchangeSettings): boolean {
  return PASSWORD_RESET_FIELDS.some((key) => saved[key] !== form[key]);
}

const NETBIOS = /^[A-Za-z0-9][A-Za-z0-9._-]{0,14}$/;
const DNS = /^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z0-9-]{2,63}$/;
const PEM_CERT = /-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----/g;

/** An https address with a host and no user name in it, as the server accepts. */
function isHttpsUrl(value: string): boolean {
  try {
    const url = new URL(value.trim());
    return url.protocol === "https:" && Boolean(url.hostname) && !url.username && !url.password;
  } catch {
    return false;
  }
}

/** How many PEM certificates the text holds (the server reads each one again). */
export function countCertificates(pem: string): number {
  return pem.match(PEM_CERT)?.length ?? 0;
}

function boundError(form: ExchangeSettings, key: BoundedField): string | undefined {
  const [low, high] = SETTING_BOUNDS[key];
  const value = form[key];
  return Number.isInteger(value) && value >= low && value <= high
    ? undefined
    : `Enter a whole number from ${low} to ${high}.`;
}

/** What is wrong with the form, by field; empty when it can be saved. */
export function validateExchangeSettings(form: ExchangeSettings): SettingsErrors {
  const errors: SettingsErrors = {};
  for (const key of Object.keys(SETTING_BOUNDS) as BoundedField[]) {
    const error = boundError(form, key);
    if (error) errors[key] = error;
  }
  const ews = form.ews_url.trim();
  if (ews && !isHttpsUrl(ews)) {
    errors.ews_url = `Enter an https address, such as ${EWS_URL_EXAMPLE}.`;
  } else if (form.enabled && !ews) {
    errors.ews_url = "Give the EWS address before turning Exchange EWS on.";
  }
  const autodiscover = form.autodiscover_url.trim();
  if (autodiscover && !isHttpsUrl(autodiscover)) {
    errors.autodiscover_url = "Enter an https address, or leave it blank.";
  }
  const netbios = form.netbios_domain.trim();
  if (netbios && !NETBIOS.test(netbios)) {
    errors.netbios_domain = "A short name such as CORP: up to 15 letters, digits, '-' or '.'.";
  }
  const suffix = form.upn_suffix.trim().replace(/^@/, "");
  if (suffix && !DNS.test(suffix)) {
    errors.upn_suffix = "A domain such as corp.example.";
  }
  if (form.ca_bundle_pem.trim() && countCertificates(form.ca_bundle_pem) === 0) {
    errors.ca_bundle_pem = "Paste PEM certificates (-----BEGIN CERTIFICATE----- …).";
  }
  if (form.detection === "model" && !form.detection_model.trim()) {
    errors.detection_model = "Choose a model, or use the rules.";
  }
  return errors;
}

const MESSAGE_FIELDS: [RegExp, SettingsField][] = [
  [/turning exchange ews on/i, "ews_url"],
  [/\bEWS address\b/i, "ews_url"],
  [/autodiscover/i, "autodiscover_url"],
  [/netbios/i, "netbios_domain"],
  [/\bUPN\b/i, "upn_suffix"],
  [/CA certificate/i, "ca_bundle_pem"],
  [/\bmodel\b/i, "detection_model"],
];

/**
 * The field a server refusal (422 `invalid_settings`) is about, read from its
 * message: either the setting's own name ("poll_minutes must be …") or the
 * words the server uses for it ("The EWS address must be …"). Null: show it
 * above the form.
 */
export function fieldForServerMessage(message: string, fields: readonly SettingsField[]): SettingsField | null {
  const named = fields.find((key) => new RegExp(`\\b${key}\\b`).test(message));
  if (named) return named;
  return MESSAGE_FIELDS.find(([pattern]) => pattern.test(message))?.[1] ?? null;
}

/** The sign-in name part of a login, whatever its format: `CORP\\s.karimi` and `s.karimi@corp.example` → `s.karimi`. */
function bareUser(login: string): string {
  const text = login.trim();
  if (text.includes("\\")) return text.split("\\").slice(1).join("\\");
  if (text.includes("@")) return text.split("@")[0];
  return text;
}

/**
 * The login NTLM would be given for the reading administrator under the
 * form's login settings (as `login_for` makes it on the server).
 *
 * The server's `example_login` is exact for the saved settings; for a format
 * or domain changed on the form, it is rebuilt from the same user name. Null
 * when no login can be made (no domain known), or the format is the email,
 * which only the server knows.
 */
export function exampleLogin(
  form: Pick<ExchangeSettings, "login_format" | "netbios_domain" | "upn_suffix">,
  saved: Pick<ExchangeSettingsResponse, "settings" | "directory" | "example_login">,
): { login: string | null; saved: boolean } {
  const s = saved.settings;
  const unchanged =
    form.login_format === s.login_format &&
    form.netbios_domain.trim().toUpperCase() === s.netbios_domain.toUpperCase() &&
    form.upn_suffix.trim().replace(/^@/, "").toLowerCase() === s.upn_suffix.toLowerCase();
  if (unchanged) return { login: saved.example_login || null, saved: true };
  const user = bareUser(saved.example_login) || "username";
  if (form.login_format === "netbios") {
    const domain = form.netbios_domain.trim().toUpperCase() || saved.directory.netbios_domain.toUpperCase();
    return { login: domain ? `${domain}\\${user}` : null, saved: false };
  }
  if (form.login_format === "upn") {
    const suffix = form.upn_suffix.trim().replace(/^@/, "").toLowerCase() || saved.directory.dns_domain.toLowerCase();
    return { login: suffix ? `${user}@${suffix}` : null, saved: false };
  }
  return { login: null, saved: false };
}

/** "just now", "8 min ago", "3 h ago", "yesterday", "4 days ago", then the date. */
export function ago(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "Never";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "—";
  const minutes = Math.max(0, Math.round((now.getTime() - then.getTime()) / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  return then.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/** The full local date and time, for a tooltip beside `ago`. */
export function fullTime(iso: string | null | undefined): string | undefined {
  if (!iso) return undefined;
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? undefined : at.toLocaleString();
}

export function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}
