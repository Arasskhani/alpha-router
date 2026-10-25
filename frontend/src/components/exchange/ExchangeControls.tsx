import type { ReactNode } from "react";

import { CONNECTION_STATUS_LABELS, type ConnectionStatus } from "../../lib/exchangeMail";

/** An on/off switch beside a card's heading, as on Tickets › Settings. */
export function Switch({
  on,
  label,
  disabled,
  onChange,
}: {
  on: boolean;
  label: string;
  disabled: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      className={`ews-admin-switch${on ? " is-on" : ""}`}
      disabled={disabled}
      onClick={() => onChange(!on)}
    >
      <span className="ews-admin-switch__knob" aria-hidden />
    </button>
  );
}

export function FieldError({ id, text }: { id?: string; text?: string }) {
  return text ? (
    <p id={id} className="ews-admin-field-error" role="alert">
      {text}
    </p>
  ) : null;
}

/** A label above its control, a hint under it, and the error under both. */
export function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: ReactNode;
  hint?: ReactNode;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="ews-admin-field">
      <label htmlFor={id}>{label}</label>
      {children}
      {hint ? (
        <p id={`${id}-hint`} className="ews-admin-hint">
          {hint}
        </p>
      ) : null}
      <FieldError id={`${id}-error`} text={error} />
    </div>
  );
}

/** The ids a control inside `Field` points at for its hint and error. */
export function describedBy(id: string, hint: boolean, error?: string): string | undefined {
  const ids = [hint ? `${id}-hint` : "", error ? `${id}-error` : ""].filter(Boolean);
  return ids.length ? ids.join(" ") : undefined;
}

/** "Keep action items (days)" with its number box on the right and its error under. */
export function NumberField({
  id,
  label,
  hint,
  value,
  error,
  bounds,
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  hint?: string;
  value: number;
  error?: string;
  bounds: [number, number];
  disabled: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <div className="ews-admin-number">
      <div className="ews-admin-number__row">
        <label htmlFor={id}>
          {label}
          {hint ? <span className="ews-admin-hint">{hint}</span> : null}
        </label>
        <input
          id={id}
          type="number"
          inputMode="numeric"
          className={`input-block${error ? " is-invalid" : ""}`}
          min={bounds[0]}
          max={bounds[1]}
          step={1}
          value={Number.isNaN(value) ? "" : value}
          disabled={disabled}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${id}-error` : undefined}
          onChange={(e) => onChange(e.target.value === "" ? Number.NaN : Number(e.target.value))}
        />
      </div>
      <FieldError id={`${id}-error`} text={error} />
    </div>
  );
}

/** A checkbox with a title and a line saying what it does. */
export function CheckField({
  checked,
  title,
  hint,
  disabled,
  onChange,
}: {
  checked: boolean;
  title: string;
  hint?: ReactNode;
  disabled: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className={`ews-admin-check${disabled ? " is-disabled" : ""}`}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span>
        <span className="ews-admin-check__title">{title}</span>
        {hint ? <span className="ews-admin-hint">{hint}</span> : null}
      </span>
    </label>
  );
}

/** Connected · Password needed · Error, as a pill with a dot. */
export function ConnectionBadge({ status }: { status: ConnectionStatus }) {
  return (
    <span className={`ews-admin-badge ews-admin-badge--${status}`}>
      <i aria-hidden />
      {CONNECTION_STATUS_LABELS[status] ?? status}
    </span>
  );
}

/** A tick, a cross or a warning sign, 16 px, in the step's colour. */
export function StepIcon({ state }: { state: "ok" | "fail" | "warn" }) {
  const common = {
    width: 16,
    height: 16,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  if (state === "ok") {
    return (
      <svg {...common}>
        <polyline points="20 6 9 17 4 12" />
      </svg>
    );
  }
  if (state === "warn") {
    return (
      <svg {...common}>
        <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

export function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
