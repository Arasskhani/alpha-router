/**
 * Pure helpers behind the SMTP Server page.
 *
 * SMTP has two incompatible ways of using TLS, and the page used to offer one
 * "Use TLS" switch that meant the one port 587 does not speak. The server now
 * takes an explicit mode; these helpers keep the port, the hints and the
 * test report in line with it.
 */

export type SmtpSecurity = "starttls" | "ssl" | "none";

export const SMTP_SECURITY_OPTIONS: ReadonlyArray<{ value: SmtpSecurity; label: string }> = [
  { value: "starttls", label: "STARTTLS — usually port 587 (recommended)" },
  { value: "ssl", label: "SSL/TLS — usually port 465" },
  { value: "none", label: "None — no encryption (trusted internal relay only)" },
];

/** The port each mode normally uses. */
export const STANDARD_PORTS: Record<SmtpSecurity, number> = { starttls: 587, ssl: 465, none: 25 };

/** What the server sends instead of a saved password, and accepts back as "keep it". */
export const PASSWORD_MASK = "********";

const SECURITY_NAMES: Record<SmtpSecurity, string> = { starttls: "STARTTLS", ssl: "SSL/TLS", none: "no encryption" };

/**
 * The port to show after the mode changes. A port that is empty or one of the
 * standard ones follows the mode; one the administrator typed (2525, say)
 * stays where it is.
 */
export function portAfterSecurityChange(port: string, next: SmtpSecurity): string {
  const current = Number(port);
  const standard = Object.values(STANDARD_PORTS);
  if (!port.trim() || standard.includes(current)) return String(STANDARD_PORTS[next]);
  return port;
}

/** A hint when the port is the one another mode normally uses. Never blocks saving. */
export function portHint(security: SmtpSecurity, port: number): string | null {
  if (security === "starttls" && port === 465) {
    return "Port 465 normally expects SSL/TLS from the first byte; STARTTLS there usually times out.";
  }
  if (security === "ssl" && port === 587) {
    return "Port 587 normally uses STARTTLS; SSL/TLS there fails with “wrong version number”.";
  }
  if (security === "ssl" && port === 25) return "Port 25 normally uses STARTTLS or no encryption.";
  if (security === "none" && port === 465) return "Port 465 expects SSL/TLS; without encryption it will not answer.";
  if (security === "none" && port === 587) return "Port 587 normally requires STARTTLS before logging in.";
  return null;
}

/** Same rule as the server: case and trailing dots do not make another server. */
export function sameServer(a: string | null | undefined, b: string | null | undefined): boolean {
  const canonical = (host: string | null | undefined) => (host ?? "").trim().toLowerCase().replace(/\.+$/, "");
  return canonical(a) === canonical(b);
}

/** 2: TLS with a verified certificate, 1: TLS without verification, 0: plain text. */
export function protectionLevel(security: SmtpSecurity, verifyCertificate: boolean): number {
  if (security === "none") return 0;
  return verifyCertificate ? 2 : 1;
}

/** Why a saved password is not used with other values; the server's `login_skipped` uses the same words. */
export type PasswordReuseProblem = "saved_for_another_server" | "less_secure_connection";

type ConnectionValues = { host: string; username: string | null; security: SmtpSecurity; verify_certificate: boolean };

/**
 * Why the saved password would not be used with the values on the form, or
 * null. The server's rule: it stays with its server and username, and is never
 * sent over a less secure connection than the one it was saved with.
 */
export function passwordReuseProblem(saved: ConnectionValues, next: ConnectionValues): PasswordReuseProblem | null {
  if (!sameServer(next.host, saved.host) || (next.username ?? "").trim() !== (saved.username ?? "").trim()) {
    return "saved_for_another_server";
  }
  if (
    protectionLevel(next.security, next.verify_certificate) < protectionLevel(saved.security, saved.verify_certificate)
  ) {
    return "less_secure_connection";
  }
  return null;
}

/** What the server says when Save leaves the password alone but may not reuse it. */
export const PASSWORD_AGAIN: Record<PasswordReuseProblem, string> = {
  saved_for_another_server:
    "Enter the password again: a saved password is only used with the server and username it was saved for.",
  less_secure_connection:
    "Enter the password again: a saved password is never sent over a less secure connection than the one it was saved for.",
};

export type SmtpFormValues = { host: string; port: string; from_address: string };

// One address, without the characters that mean something else in an address
// header ("reports@[" or "a@b;c"): the server refuses what the email package
// cannot put in a header, and this keeps its message from arriving as JSON.
const PLAIN_ADDRESS = /^[^@\s<>()[\]\\,;:"]+@[^@\s<>()[\]\\,;:"]+$/;

/** The first reason the form cannot be saved as it stands, or null. Mirrors the server's checks. */
export function validateSmtpForm(form: SmtpFormValues): string | null {
  const host = form.host.trim();
  if (!host) return "Enter the SMTP server's host name.";
  if (host.includes("://") || host.includes("/") || /\s/.test(host)) {
    return "Enter the server's host name only, for example mail.example.com.";
  }
  const port = Number(form.port);
  if (!Number.isInteger(port) || port < 1 || port > 65535) return "The port must be a number from 1 to 65535.";
  if (!PLAIN_ADDRESS.test(form.from_address.trim())) {
    return "The From address must be an email address, for example reports@example.com.";
  }
  return null;
}

export type SmtpTestResult = {
  ok: boolean;
  error?: string;
  security?: SmtpSecurity;
  tls_version?: string | null;
  certificate_verified?: boolean;
  login_tested?: boolean;
  login_skipped?: "no_password" | PasswordReuseProblem | null;
};

/** One or two sentences for the result of "Test connection". */
export function describeTestResult(result: SmtpTestResult): string {
  if (!result.ok) return result.error || "The connection failed.";
  const security = result.security ?? "starttls";
  let connected = `Connected with ${SECURITY_NAMES[security]}`;
  if (result.tls_version) connected += ` (${result.tls_version})`;
  if (security !== "none" && result.certificate_verified === false) connected += ", certificate not verified";
  let login: string;
  if (result.login_tested) login = "Login succeeded.";
  else if (result.login_skipped === "saved_for_another_server") {
    login = "Login not tested: the saved password belongs to another server or username. Type the password to test it.";
  } else if (result.login_skipped === "less_secure_connection") {
    login =
      "Login not tested: the saved password is not sent over a less secure connection than the saved one. Type the password to test it.";
  } else if (result.login_skipped === "no_password") login = "Login not tested: there is no password to try.";
  else login = "No login configured.";
  return `${connected}. ${login}`;
}
