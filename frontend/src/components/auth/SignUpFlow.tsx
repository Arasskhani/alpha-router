import { FormEvent, useEffect, useState } from "react";

import {
  EmailAuthError,
  signupComplete,
  signupStart,
  signupUsernameAvailable,
  signupVerify,
  type CodeStarted,
} from "../../lib/emailAuth";
import { clearEmailFlow, loadEmailFlow, saveEmailFlow, type EmailFlow } from "../../lib/emailFlowStore";
import CodeStep from "./CodeStep";
import PasswordRules from "./PasswordRules";

type Props = {
  /** The account is made and the session set: go on as after signing in. */
  onSignedIn: () => void | Promise<void>;
  /** Back to the sign-in form, with the email when the address already has an account. */
  onSignIn: () => void;
  /** The address has a local account whose password can be reset by email. */
  onResetPassword: (email: string) => void;
};

type Taken = { message: string; resetAvailable: boolean };
type NameState = { status: "idle" | "checking" | "free" | "bad"; message?: string };

function messageOf(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Seconds left of the resend wait for a step picked up after a reload. */
function waitLeft(flow: EmailFlow): number {
  return Math.max(0, Math.ceil(flow.started.resend_in - (Date.now() - flow.at) / 1000));
}

/** Create an account: email, the emailed code, then a username and a password. */
export default function SignUpFlow({ onSignedIn, onSignIn, onResetPassword }: Props) {
  // A sign-up left by a reload (the mail app opened for the code) picks up where it was.
  const [resumed] = useState(() => {
    const flow = loadEmailFlow();
    return flow?.flow === "signup" ? { flow, resendIn: waitLeft(flow) } : null;
  });
  const [step, setStep] = useState<"email" | "code" | "details">(
    resumed ? (resumed.flow.step === "details" ? "details" : "code") : "email",
  );
  const [email, setEmail] = useState(resumed?.flow.started.email ?? "");
  const [started, setStarted] = useState<CodeStarted | null>(resumed?.flow.started ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [taken, setTaken] = useState<Taken | null>(null);
  const [username, setUsername] = useState(resumed?.flow.username ?? "");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [name, setName] = useState<NameState>({ status: "idle" });

  async function sendCode() {
    setBusy(true);
    setError("");
    setTaken(null);
    try {
      const result = await signupStart(email.trim());
      setStarted(result);
      setEmail(result.email);
      setStep("code");
      saveEmailFlow({ flow: "signup", step: "code", started: result });
    } catch (err) {
      if (err instanceof EmailAuthError && err.code === "email_taken") {
        setTaken({ message: err.message, resetAvailable: err.extra.reset_available === true });
      } else {
        setError(messageOf(err));
      }
    } finally {
      setBusy(false);
    }
  }

  async function verify(code: string) {
    if (!started) return;
    setBusy(true);
    setError("");
    try {
      const result = await signupVerify(started.token, code);
      setUsername(result.suggested_username);
      setStep("details");
      saveEmailFlow({ flow: "signup", step: "details", started, username: result.suggested_username });
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  }

  // The username is checked as it is typed, a moment after typing stops.
  const token = started?.token ?? "";
  useEffect(() => {
    if (step !== "details" || !token) return;
    const wanted = username.trim();
    if (!wanted) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setName({ status: "checking" });
      signupUsernameAvailable(token, wanted)
        .then((result) => {
          if (cancelled) return;
          setName(result.available ? { status: "free" } : { status: "bad", message: result.message ?? undefined });
        })
        .catch(() => {
          if (!cancelled) setName({ status: "idle" });
        });
    }, 400);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [step, token, username]);

  async function finish(e: FormEvent) {
    e.preventDefault();
    if (!started || busy) return;
    if (password !== confirm) {
      setError("The two passwords are not the same.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await signupComplete(started.token, username.trim(), password, displayName.trim());
      clearEmailFlow();
      await onSignedIn();
    } catch (err) {
      setError(messageOf(err));
      if (err instanceof EmailAuthError && (err.code === "code_invalid" || err.code === "code_expired")) {
        setStep("email");
        setStarted(null);
        clearEmailFlow();
      }
    } finally {
      setBusy(false);
    }
  }

  if (step === "code" && started) {
    return (
      <CodeStep
        key={started.token}
        idBase="signup"
        email={started.email}
        codeLength={started.code_length}
        resendIn={resumed && started === resumed.flow.started ? resumed.resendIn : started.resend_in}
        busy={busy}
        error={error}
        onVerify={(code) => void verify(code)}
        onResend={() => void sendCode()}
        onBack={() => {
          setStep("email");
          setStarted(null);
          setError("");
          clearEmailFlow();
        }}
      />
    );
  }

  if (step === "details" && started) {
    return (
      <form className="login-form" onSubmit={finish}>
        <p className="login-panel__hint">
          <strong>{started.email}</strong> is confirmed. Choose how you will sign in.
        </p>
        <label className="login-form__label" htmlFor="signup-username">
          Username
        </label>
        <input
          id="signup-username"
          maxLength={64}
          value={username}
          onChange={(e) => {
            setUsername(e.target.value);
            setName({ status: "idle" });
          }}
          autoComplete="username"
          className="login-form__input"
          // eslint-disable-next-line jsx-a11y/no-autofocus -- the step the person just reached by entering the code; without it focus fell to the page
          autoFocus
          aria-describedby="signup-username-status"
          aria-invalid={name.status === "bad"}
          required
        />
        <p id="signup-username-status" className="login-form__field-note" aria-live="polite">
          {name.status === "checking" && "Checking…"}
          {name.status === "free" && <span className="login-form__ok">Available</span>}
          {name.status === "bad" && <span className="login-form__bad">{name.message}</span>}
        </p>
        <label className="login-form__label" htmlFor="signup-display-name">
          Your name (optional)
        </label>
        <input
          id="signup-display-name"
          maxLength={255}
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          autoComplete="name"
          className="login-form__input"
          placeholder="As others will see it"
        />
        <label className="login-form__label" htmlFor="signup-password">
          Password
        </label>
        <input
          id="signup-password"
          maxLength={256}
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="new-password"
          className="login-form__input"
          aria-describedby="signup-password-rules"
          required
        />
        <PasswordRules id="signup-password-rules" password={password} username={username.trim()} email={started.email} />
        <label className="login-form__label" htmlFor="signup-confirm">
          Confirm password
        </label>
        <input
          id="signup-confirm"
          maxLength={256}
          type="password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          autoComplete="new-password"
          className="login-form__input"
          aria-invalid={confirm.length > 0 && confirm !== password}
          required
        />
        {error && (
          <p className="login-form__error" role="alert">
            {error}
          </p>
        )}
        <button className="btn login-form__submit" type="submit" disabled={busy || name.status === "bad"} aria-busy={busy}>
          {busy ? "Creating your account…" : "Create account"}
        </button>
      </form>
    );
  }

  return (
    <form
      className="login-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (!busy) void sendCode();
      }}
    >
      <p className="login-panel__hint">Enter your email address. We will send you a code to confirm it.</p>
      <label className="login-form__label" htmlFor="signup-email">
        Email
      </label>
      <input
        id="signup-email"
        maxLength={320}
        type="email"
        value={email}
        onChange={(e) => {
          setEmail(e.target.value);
          setTaken(null);
        }}
        autoComplete="email"
        className="login-form__input"
        placeholder="you@example.com"
        // eslint-disable-next-line jsx-a11y/no-autofocus -- the person just chose to create an account; the email is the first and only field
        autoFocus
        aria-invalid={!!error || !!taken}
        required
      />
      {taken && (
        <div className="login-form__notice" role="alert">
          <p>{taken.message}</p>
          <div className="login-panel__links">
            <button type="button" className="login-panel__link" onClick={onSignIn}>
              Sign in
            </button>
            {taken.resetAvailable && (
              <button type="button" className="login-panel__link" onClick={() => onResetPassword(email.trim())}>
                Reset password
              </button>
            )}
          </div>
        </div>
      )}
      {error && (
        <p className="login-form__error" role="alert">
          {error}
        </p>
      )}
      <button className="btn login-form__submit" type="submit" disabled={busy} aria-busy={busy}>
        {busy ? "Sending…" : "Send code"}
      </button>
    </form>
  );
}
