/**
 * The password policy, as the forms that set a password show it while the
 * person types. The server (`app.services.password_policy`) is the authority:
 * it checks every rule again, and serves the labels and the minimum length at
 * `/api/auth/password-policy`, so a changed minimum reaches the forms.
 */

export type PasswordRuleKey = "length" | "upper" | "lower" | "digit" | "symbol" | "personal" | "common";

export type PasswordPolicy = {
  min_length: number;
  rules: { key: PasswordRuleKey; label: string }[];
  /** The server's list of passwords too common to use, lowercase. */
  common?: string[];
};

export const DEFAULT_PASSWORD_POLICY: PasswordPolicy = {
  min_length: 8,
  rules: [
    { key: "length", label: "At least 8 characters" },
    { key: "upper", label: "An uppercase letter (A-Z)" },
    { key: "lower", label: "A lowercase letter (a-z)" },
    { key: "digit", label: "A digit (0-9)" },
    { key: "symbol", label: "A symbol, such as ! @ # $ % - _" },
    { key: "personal", label: "Not your username or the name in your email" },
  ],
};

/** A personal word shorter than this is not looked for, as on the server. */
const PERSONAL_MIN_CHARS = 3;

function personalWords(username?: string, email?: string): string[] {
  const local = email ? email.split("@", 1)[0] : "";
  return [username ?? "", local]
    .map((word) => word.trim().toLowerCase())
    .filter((word) => word.length >= PERSONAL_MIN_CHARS);
}

/**
 * The rules `password` does not meet yet, in rule order. The tests are the
 * server's: Unicode categories for the character classes (a digit is a decimal
 * digit, Nd), and lowercase comparison for the personal words and the list.
 */
export function unmetPasswordRules(
  password: string,
  {
    minLength = 8,
    username,
    email,
    common = [],
  }: { minLength?: number; username?: string; email?: string; common?: string[] } = {},
): PasswordRuleKey[] {
  const pwd = password.trim();
  const unmet: PasswordRuleKey[] = [];
  if ([...pwd].length < minLength) unmet.push("length");
  if (!/\p{Lu}/u.test(pwd)) unmet.push("upper");
  if (!/\p{Ll}/u.test(pwd)) unmet.push("lower");
  if (!/\p{Nd}/u.test(pwd)) unmet.push("digit");
  if (!/[^\p{L}\p{N}\s]/u.test(pwd)) unmet.push("symbol");
  const folded = pwd.toLowerCase();
  if (personalWords(username, email).some((word) => folded.includes(word))) unmet.push("personal");
  if (common.includes(folded)) unmet.push("common");
  return unmet;
}

let cached: Promise<PasswordPolicy> | null = null;

/** The server's policy, read once per page load; the defaults when it cannot be read. */
export function loadPasswordPolicy(fetcher: (path: string) => Promise<Response>): Promise<PasswordPolicy> {
  if (!cached) {
    cached = fetcher("/api/auth/password-policy")
      .then((res) => (res.ok ? (res.json() as Promise<PasswordPolicy>) : DEFAULT_PASSWORD_POLICY))
      .catch(() => DEFAULT_PASSWORD_POLICY);
  }
  return cached;
}

/** For tests: forget the policy read so far. */
export function resetPasswordPolicyCache(): void {
  cached = null;
}
