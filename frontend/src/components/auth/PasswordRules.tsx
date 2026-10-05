import { useEffect, useState } from "react";

import { authFetch } from "../../api";
import {
  DEFAULT_PASSWORD_POLICY,
  loadPasswordPolicy,
  unmetPasswordRules,
  type PasswordPolicy,
} from "../../lib/passwordRules";

type Props = {
  password: string;
  username?: string;
  email?: string;
  /** id of the list, for the password field's aria-describedby. */
  id?: string;
};

/**
 * The password rules, each ticked as the typed password meets it. The server
 * checks them again; this only saves a round trip and says what is missing.
 */
export default function PasswordRules({ password, username, email, id }: Props) {
  const [policy, setPolicy] = useState<PasswordPolicy>(DEFAULT_PASSWORD_POLICY);
  useEffect(() => {
    let cancelled = false;
    void loadPasswordPolicy((path) => authFetch(path)).then((value) => {
      if (!cancelled) setPolicy(value);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const unmet = new Set(
    unmetPasswordRules(password, { minLength: policy.min_length, username, email, common: policy.common }),
  );
  return (
    <ul className="password-rules" id={id} aria-label="Password requirements">
      {policy.rules.map((rule) => {
        const met = password.length > 0 && !unmet.has(rule.key);
        return (
          <li key={rule.key} className={met ? "password-rules__rule password-rules__rule--met" : "password-rules__rule"}>
            <span aria-hidden>{met ? "✓" : "○"}</span> {rule.label}
            <span className="sr-only">{met ? " (met)" : " (not met yet)"}</span>
          </li>
        );
      })}
    </ul>
  );
}
