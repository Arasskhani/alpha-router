import { FormEvent, KeyboardEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, formatApiError } from "../../api";
import { useReadOnly } from "../../context/ReadOnlyContext";

type PlanOption = { id: number; name: string; monthly_budget_usd: number };

export type EmailSignupView = {
  enabled: boolean;
  allowed_domains: string[];
  default_plan_id: number | null;
  reset_enabled: boolean;
  smtp_configured: boolean;
  plans: PlanOption[];
  signups_last_30_days: number;
};

const PATH = "/api/admin/authentication/email-signup";

/**
 * Admin -> Authentication -> Email sign-up: whether people may create their
 * own account with a code sent by email, from which domains, with which
 * plan; and whether people with a local account may reset a forgotten
 * password the same way.
 */
export default function EmailSignupSettings() {
  const readOnly = useReadOnly();
  const [view, setView] = useState<EmailSignupView | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [domains, setDomains] = useState<string[]>([]);
  const [domainDraft, setDomainDraft] = useState("");
  const [planId, setPlanId] = useState("");
  const [resetEnabled, setResetEnabled] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  function apply(data: EmailSignupView) {
    setView(data);
    setEnabled(data.enabled);
    setDomains(data.allowed_domains);
    // A plan deleted since it was chosen shows as "No plan", and saving sends that, not the old id.
    const planKnown = data.plans.some((plan) => plan.id === data.default_plan_id);
    setPlanId(planKnown ? String(data.default_plan_id) : "");
    setResetEnabled(data.reset_enabled);
  }

  useEffect(() => {
    let cancelled = false;
    api<EmailSignupView>(PATH)
      .then((data) => {
        if (!cancelled) apply(data);
      })
      .catch((err) => {
        if (!cancelled) setError(formatApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function addDomains(raw: string) {
    const parts = raw
      .split(/[\s,;]+/)
      .map((part) => part.trim().toLowerCase().replace(/^@/, ""))
      .filter(Boolean);
    if (parts.length === 0) return;
    setDomains((current) => [...current, ...parts.filter((part) => !current.includes(part))]);
    setDomainDraft("");
  }

  function onDomainKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addDomains(domainDraft);
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    setNotice("");
    const pending = domainDraft.trim() ? [...domains, domainDraft.trim().toLowerCase().replace(/^@/, "")] : domains;
    try {
      const data = await api<EmailSignupView>(PATH, {
        method: "PUT",
        body: JSON.stringify({
          enabled,
          allowed_domains: pending,
          default_plan_id: planId ? Number(planId) : null,
          reset_enabled: resetEnabled,
        }),
      });
      apply(data);
      setDomainDraft("");
      setNotice("Email sign-up settings saved.");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setSaving(false);
    }
  }

  if (!view) {
    return error ? (
      <p className="alert alert-error" role="alert">
        {error}
      </p>
    ) : (
      <p className="muted-text" aria-busy="true">
        Loading…
      </p>
    );
  }

  const selectedPlan = view.plans.find((plan) => String(plan.id) === planId);
  return (
    <form className="card email-signup-settings" onSubmit={save}>
      <p className="muted-text">
        Let people create their own account: they enter their email address, type the 6-digit code we send to it, then
        choose a username nobody has and a password that meets the policy. The account is active at once. The same
        codes can let people with a local account reset a forgotten password.
      </p>

      {!view.smtp_configured && (
        <p className="alert alert-error" role="alert">
          The codes are sent by email, and no SMTP server is set up. Set it up first on{" "}
          <Link to="/admin/smtp">SMTP Server</Link>.
        </p>
      )}

      <label className="email-signup-settings__switch">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
          disabled={readOnly}
        />{" "}
        Allow people to create an account with their email
      </label>

      <fieldset className="email-signup-settings__group" disabled={readOnly}>
        <legend>Allowed email domains</legend>
        <p className="muted-text">
          Only addresses at these domains may create an account, for example <code>example.com</code>. Leave the list
          empty to allow any address.
        </p>
        {domains.length > 0 && (
          <ul className="email-signup-settings__chips" aria-label="Allowed domains">
            {domains.map((domain) => (
              <li key={domain} className="email-signup-settings__chip">
                {domain}
                {!readOnly && (
                  <button
                    type="button"
                    className="email-signup-settings__chip-remove"
                    aria-label={`Remove ${domain}`}
                    onClick={() => setDomains((current) => current.filter((d) => d !== domain))}
                  >
                    ×
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        <div className="email-signup-settings__add">
          <label htmlFor="email-signup-domain" className="sr-only">
            Add a domain
          </label>
          <input
            id="email-signup-domain"
            className="input-block"
            value={domainDraft}
            onChange={(e) => setDomainDraft(e.target.value)}
            onKeyDown={onDomainKey}
            placeholder="example.com"
          />
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => addDomains(domainDraft)}>
            Add
          </button>
        </div>
        {enabled && domains.length === 0 && !domainDraft.trim() && (
          <p className="alert alert-warning" role="status">
            With no domains, anyone with an email address can create an account
            {planId ? " and spend from the default plan" : ""}.
          </p>
        )}
      </fieldset>

      <label htmlFor="email-signup-plan">Plan for new accounts</label>
      <select
        id="email-signup-plan"
        className="input-block"
        value={planId}
        onChange={(e) => setPlanId(e.target.value)}
        disabled={readOnly}
      >
        <option value="">No plan (an administrator assigns one later)</option>
        {view.plans.map((plan) => (
          <option key={plan.id} value={String(plan.id)}>
            {plan.name} (${plan.monthly_budget_usd}/month)
          </option>
        ))}
      </select>
      <p className="muted-text email-signup-settings__hint">
        {selectedPlan
          ? `New accounts get ${selectedPlan.name} and can use Alpharouter at once.`
          : "Without a plan a new account can sign in but cannot spend until an administrator assigns one."}
      </p>

      <label className="email-signup-settings__switch">
        <input
          type="checkbox"
          checked={resetEnabled}
          onChange={(e) => setResetEnabled(e.target.checked)}
          disabled={readOnly}
        />{" "}
        Allow people with a local account to reset a forgotten password by email
      </label>
      <p className="muted-text email-signup-settings__hint">
        Directory (LDAP) and single sign-on accounts reset their password where it is kept. A reset signs the account
        out everywhere; two-factor authentication still applies.
      </p>

      <p className="muted-text">
        Accounts created in the last 30 days: <strong>{view.signups_last_30_days}</strong>. Each sign-up and reset is
        in <Link to="/admin/sign-in-activity">Sign-in Activity</Link>; changes to these settings are in{" "}
        <Link to="/admin/admin-logs">Admin Logs</Link>.
      </p>

      {error && (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="alert alert-success" role="status">
          {notice}
        </p>
      )}
      {!readOnly && (
        <div className="dialog-actions">
          <button className="btn" type="submit" disabled={saving}>
            {saving ? "Saving…" : "Save email sign-up"}
          </button>
        </div>
      )}
    </form>
  );
}
