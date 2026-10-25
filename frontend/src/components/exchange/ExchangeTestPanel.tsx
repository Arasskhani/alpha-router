import { useState, type FormEvent } from "react";

import { Field, StepIcon, describedBy, errorText } from "./ExchangeControls";
import { exchangeAdminApi, type ExchangeSettingsResponse, type TestResult, type TestStep } from "../../lib/exchangeMail";

type Props = {
  /** The saved settings: the test runs with them, never with the form. */
  saved: ExchangeSettingsResponse;
  /** The form differs from the saved settings. */
  dirty: boolean;
  /** Read-only administrators read the panel but cannot run a test (it signs in to Exchange). */
  canRun: boolean;
  onPassed: () => void;
};

type StepState = "ok" | "fail" | "warn";

const STATE_WORDS: Record<StepState, string> = { ok: "Passed", fail: "Failed", warn: "Warning" };

/** A failed Autodiscover step does not fail the test: Full Access mailboxes are only not listed. */
function stepState(step: TestStep, result: TestResult): StepState {
  if (step.ok) return "ok";
  return result.ok || step.key === "autodiscover" ? "warn" : "fail";
}

/**
 * Settings › Test connection: signs in to Exchange with an account the
 * administrator types, with the saved settings, and lists each step the way a
 * person's Connect would go. Nothing is stored, and the password field is
 * emptied after every run.
 */
export default function ExchangeTestPanel({ saved, dirty, canRun, onPassed }: Props) {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);
  const [error, setError] = useState("");

  const blocked = !saved.settings.ews_url
    ? "Save the EWS address first: the test uses the saved settings."
    : dirty
      ? "Save your changes first: the test uses the saved settings, not the form."
      : "";

  async function run(event: FormEvent) {
    event.preventDefault();
    if (!canRun || blocked || running || !login.trim() || !password) return;
    setRunning(true);
    setResult(null);
    setError("");
    try {
      const next = await exchangeAdminApi.test({
        login: login.trim(),
        password,
        ...(email.trim() ? { email: email.trim() } : {}),
      });
      setResult(next);
      if (next.ok) onPassed();
    } catch (err) {
      setError(errorText(err));
    } finally {
      // The password is typed for one run only.
      setPassword("");
      setRunning(false);
    }
  }

  const autodiscoverRan = result?.steps.some((step) => step.key === "autodiscover") ?? false;
  return (
    <section className="ews-admin-card ews-admin-test" id="ews-admin-test" aria-labelledby="ews-admin-test-title">
      <h3 id="ews-admin-test-title">Test connection</h3>
      <p className="muted-text">
        Signs in to Exchange with an account you type here, using the <strong>saved</strong> settings, and shows each
        step a person&apos;s Connect goes through. Nothing is stored: the password is used for this test only and the
        field is emptied afterwards.
      </p>
      <form className="ews-admin-test__form" onSubmit={(e) => void run(e)} aria-label="Test connection" noValidate>
        <Field
          id="ews-test-login"
          label="Login"
          hint="An AD account in the login format above. Your own account is the simplest test."
        >
          {/* Not a sign-in form: a name and autocomplete that keep the browser from filling in the administrator's
              own saved user name and password. */}
          <input
            id="ews-test-login"
            name="ews-test-account"
            className="input-block"
            dir="ltr"
            value={login}
            placeholder={saved.example_login || "CORP\\username"}
            autoComplete="off"
            spellCheck={false}
            disabled={!canRun}
            aria-describedby={describedBy("ews-test-login", true)}
            onChange={(e) => setLogin(e.target.value)}
          />
        </Field>
        <Field id="ews-test-password" label="Password">
          <input
            id="ews-test-password"
            name="ews-test-secret"
            className="input-block"
            type="password"
            dir="ltr"
            value={password}
            autoComplete="new-password"
            disabled={!canRun}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <Field
          id="ews-test-email"
          label={
            <>
              Email <span className="muted-text">(optional)</span>
            </>
          }
          hint="The account's email address: also checks that this password opens that person's own mailbox, as Connect does."
        >
          <input
            id="ews-test-email"
            className="input-block"
            type="text"
            inputMode="email"
            dir="ltr"
            value={email}
            placeholder="s.karimi@corp.example"
            autoComplete="off"
            spellCheck={false}
            disabled={!canRun}
            aria-describedby={describedBy("ews-test-email", true)}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>
        {canRun ? (
          <div className="ews-admin-test__actions">
            {blocked ? <p className="ews-admin-hint ews-admin-hint--warn">{blocked}</p> : null}
            <button
              type="submit"
              className="btn"
              disabled={running || Boolean(blocked) || !login.trim() || !password}
            >
              {running ? "Testing…" : "Run test"}
            </button>
          </div>
        ) : (
          <p className="ews-admin-hint">Your role can read this page but cannot run a test.</p>
        )}
      </form>

      {error ? (
        <p className="alert alert-error ews-admin-test__error" role="alert">
          {error}
        </p>
      ) : null}

      {result ? (
        <div className="ews-admin-test__result" data-testid="ews-test-result">
          <p className={`alert ${result.ok ? "alert-success" : "alert-error"}`} role={result.ok ? "status" : "alert"}>
            {result.ok
              ? "The test passed: these settings reach Exchange and open the mailbox."
              : "The test stopped at the step marked with a cross."}
          </p>
          <ol className="ews-admin-steps">
            {result.steps.map((step) => {
              const state = stepState(step, result);
              return (
                <li key={step.key} className={`ews-admin-step ews-admin-step--${state}`}>
                  <span className="ews-admin-step__icon">
                    <StepIcon state={state} />
                  </span>
                  <span className="ews-admin-step__text">
                    <span className="ews-admin-step__label">
                      {step.label}
                      <span className="sr-only">: {STATE_WORDS[state]}</span>
                    </span>
                    {step.detail ? <span className="ews-admin-step__detail">{step.detail}</span> : null}
                  </span>
                </li>
              );
            })}
          </ol>
          {result.mailbox ? (
            <div className="ews-admin-test__found">
              <h4>Mailbox found</h4>
              <p>
                <bdi>{result.mailbox.display_name || result.mailbox.smtp}</bdi>{" "}
                <span className="muted-text" dir="ltr">
                  {result.mailbox.smtp}
                </span>
              </p>
            </div>
          ) : null}
          {autodiscoverRan ? (
            <div className="ews-admin-test__found">
              <h4>Full Access mailboxes · {result.full_access.length} found</h4>
              {result.full_access.length ? (
                <ul className="ews-admin-test__mailboxes">
                  {result.full_access.map((box) => (
                    <li key={box.smtp}>
                      <bdi>{box.display_name || box.smtp}</bdi>{" "}
                      <span className="muted-text" dir="ltr">
                        {box.smtp}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted-text">
                  Autodiscover lists none for this account. Mailboxes given with -AutoMapping $false can still be added
                  by hand.
                </p>
              )}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
