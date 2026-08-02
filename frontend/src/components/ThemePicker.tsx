import {
  colorModeOf,
  composeTheme,
  namedThemeLabel,
  namedThemeOf,
  type CachedTheme,
  type ColorMode,
  type NamedTheme,
} from "../lib/themeCache";
import ThemeSegmentedControl from "./ThemeSegmentedControl";

type Props = {
  value: CachedTheme;
  onChange: (theme: CachedTheme) => void;
  className?: string;
  /** Compact layout for the user-profile menu. */
  compact?: boolean;
};

const NAMED_OPTIONS: NamedTheme[] = ["default", "mint", "dark-mint"];

export default function ThemePicker({ value, onChange, className = "", compact = false }: Props) {
  const named = namedThemeOf(value);
  const mode = colorModeOf(value);

  const setNamed = (next: NamedTheme) => {
    if (next === "dark-mint") {
      onChange("dark-mint");
      return;
    }
    if (next === "mint") {
      onChange(mode === "system" ? "mint-system" : "mint");
      return;
    }
    onChange(mode);
  };

  const setMode = (next: ColorMode) => {
    if (named === "default") {
      onChange(composeTheme("default", next));
      return;
    }
    onChange(composeTheme("mint", next));
  };

  return (
    <div className={`theme-picker${compact ? " theme-picker--compact" : ""}${className ? ` ${className}` : ""}`}>
      <label className="theme-picker__named">
        <select
          className="theme-picker__select settings-input"
          value={named}
          aria-label="Theme"
          onChange={(e) => setNamed(e.target.value as NamedTheme)}
        >
          {NAMED_OPTIONS.map((opt) => (
            <option key={opt} value={opt}>
              {namedThemeLabel(opt)}
            </option>
          ))}
        </select>
      </label>
      <ThemeSegmentedControl value={mode} onChange={setMode} className="theme-picker__modes" />
    </div>
  );
}
