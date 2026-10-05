import { FormEvent, useState } from "react";

import { EmailAuthError, resetComplete, resetStart, resetVerify, type CodeStarted } from "../../lib/emailAuth";
import CodeStep from "./CodeStep";
import PasswordRules from "./PasswordRules";

type Props = {
  /** Filled in when the person came from sign-up with an address that has an account. */
  initialEmail?: string;
  /** The password is changed: back to sign in, as this username. */
  onDone: (username: string) => void;
};

function messageOf(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Reset a forgotten password: email, the emailed code, then the new password. */
export default function PasswordResetFlow({ initialEmail = "", onDone }: Props) {
  const [step, setStep] = useState<"email" | "code" | "password">("email");
  const [email, setEmail] = useState(initialEmail);
  const [started, setStarted] = useState<CodeStarted | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function sendCode() {
    setBusy(true);
    setError("");
    try {
      const result = await resetStart(email.trim());
      setStarted(result);
      setEmail(result.email);
      setStep("code");
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  }

  async function verify(code: string) {
    if (!started) return;
    setBusy(true);
    setError("");
    try {
      const result = await resetVerify(started.token, code);
      setUsername(result.username ?? "");
      setStep("password");
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  }

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
      const result = await resetComplete(started.token, password);
      onDone(result.username);
    } catch (err) {
      setError(messageOf(err));
      if (err instanceof EmailAuthError && (err.code === "code_invalid" || err.code === "code_expired")) {
        setStep("email");
        setStarted(null);
      }
    } finally {
      setBusy(false);
    }
  }

  if (step === "code" && started) {
    return (
      <CodeStep
        key={started.token}
        idBase="reset"
        email={started.email}
        codeLength={started.code_length}
        resendIn={started.resend_in}
        busy={busy}
        error={error}
        onVerify={(code) => void verify(code)}
        onResend={() => void sendCode()}
        onBack={() => {
          setStep("email");
          setStarted(null);
          setError("");
        }}
      />
    );
  }

  if (step === "password" && started) {
    return (
      <form className="login-form" onSubmit={finish}>
        <p className="login-panel__hint">
          Choose a new password{username ? (
            <>
              {" "}
              for <strong>{username}</strong>
            </>
          ) : null}
          . Every device signed in to this account will be signed out.
        </p>
        <label className="login-form__label" htmlFor="reset-password">
          New password
        </label>
        <input
          id="reset-password"
          maxLength={256}
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="new-password"
          className="login-form__input"
          aria-describedby="reset-password-rules"
          required
        />
        <PasswordRules id="reset-password-rules" password={password} username={username} email={started.email} />
        <label className="login-form__label" htmlFor="reset-confirm">
          Confirm new password
        </label>
        <input
          id="reset-confirm"
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
        <button className="btn login-form__submit" type="submit" disabled={busy} aria-busy={busy}>
          {busy ? "Saving…" : "Set new password"}
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
      <p className="login-panel__hint">Enter the email address of your account. We will send you a code.</p>
      <label className="login-form__label" htmlFor="reset-email">
        Email
      </label>
      <input
        id="reset-email"
        maxLength={320}
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        autoComplete="email"
        className="login-form__input"
        placeholder="you@example.com"
        // eslint-disable-next-line jsx-a11y/no-autofocus -- the person just chose to reset their password; the email is the only field
        autoFocus
        aria-invalid={!!error}
        required
      />
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
