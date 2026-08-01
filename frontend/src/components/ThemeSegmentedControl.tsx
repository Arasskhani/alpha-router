import type { ReactNode } from "react";
import type { ColorMode } from "../lib/themeCache";

type Props = {
  value: ColorMode;
  onChange: (mode: ColorMode) => void;
  className?: string;
};

function IconSun() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
  );
}

function IconMoon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

function IconSystem() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <rect x="2" y="3" width="20" height="14" rx="2" />
      <path d="M8 21h8M12 17v4" />
    </svg>
  );
}

const OPTIONS: { value: ColorMode; label: string; icon: ReactNode }[] = [
  { value: "light", label: "Light", icon: <IconSun /> },
  { value: "dark", label: "Dark", icon: <IconMoon /> },
  { value: "system", label: "System", icon: <IconSystem /> },
];

/** Light / Dark / System segmented control. */
export default function ThemeSegmentedControl({ value, onChange, className = "" }: Props) {
  return (
    <div className={`theme-segment${className ? ` ${className}` : ""}`} role="group" aria-label="Color mode">
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          className={`theme-segment__btn${value === opt.value ? " is-active" : ""}`}
          aria-label={opt.label}
          aria-pressed={value === opt.value}
          title={opt.label}
          onClick={() => onChange(opt.value)}
        >
          {opt.icon}
        </button>
      ))}
    </div>
  );
}
