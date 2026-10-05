import { FormEvent, useEffect, useState } from "react";

import { cleanCode } from "../../lib/emailAuth";

type Props = {
  email: string;
  codeLength: number;
  /** Seconds before another code may be asked for, counted from when this step opened. */
  resendIn: number;
  busy: boolean;
  error: string;
  onVerify: (code: string) => void;
  onResend: () => void;
  onBack: () => void;
  idBase: string;
};

/**
 * The emailed code: typed or pasted, with a resend that waits its turn.
 * The parent keys it by the code's token, so a new code starts it afresh.
 */
export default function CodeStep({ email, codeLength, resendIn, busy, error, onVerify, onResend, onBack, idBase }: Props) {
  const [code, setCode] = useState("");
  const [wait, setWait] = useState(resendIn);

  useEffect(() => {
    if (wait <= 0) return;
    const timer = window.setTimeout(() => setWait((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [wait]);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (code.length === codeLength && !busy) onVerify(code);
  }

  return (
    <form className="login-form" onSubmit={submit}>
      <p className="login-panel__hint">
        We sent a {codeLength}-digit code to <strong>{email}</strong>. It works for 10 minutes.
      </p>
      <label className="login-form__label" htmlFor={`${idBase}-code`}>
        Verification code
      </label>
      <input
        id={`${idBase}-code`}
        value={code}
        onChange={(e) => setCode(cleanCode(e.target.value, codeLength))}
        autoComplete="one-time-code"
        inputMode="numeric"
        className="login-form__input login-form__input--code"
        placeholder={"0".repeat(codeLength)}
        // eslint-disable-next-line jsx-a11y/no-autofocus -- the step the person just reached by asking for the code; the field is the only thing to do
        autoFocus
        aria-invalid={!!error}
      />
      {error && (
        <p className="login-form__error" role="alert">
          {error}
        </p>
      )}
      <button className="btn login-form__submit" type="submit" disabled={busy || code.length !== codeLength} aria-busy={busy}>
        {busy ? "Checking…" : "Verify"}
      </button>
      <div className="login-panel__links">
        <button type="button" className="login-panel__link" onClick={onBack} disabled={busy}>
          Use another email
        </button>
        <button
          type="button"
          className="login-panel__link"
          onClick={() => {
            setCode("");
            onResend();
          }}
          disabled={busy || wait > 0}
        >
          {wait > 0 ? `Send a new code in ${wait}s` : "Send a new code"}
        </button>
      </div>
    </form>
  );
}
