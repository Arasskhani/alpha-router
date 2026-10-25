/** An on/off switch in the app's toggle style, announced as a switch. */
export default function MailSwitch({
  on,
  label,
  disabled = false,
  onChange,
}: {
  on: boolean;
  label: string;
  disabled?: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      className={`alpha-router-toggle${on ? " on" : ""}`}
      disabled={disabled}
      onClick={() => onChange(!on)}
    >
      <span className="alpha-router-toggle-knob" aria-hidden />
    </button>
  );
}
