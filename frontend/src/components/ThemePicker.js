import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { colorModeOf, composeTheme, namedThemeLabel, namedThemeOf, } from "../lib/themeCache";
import ThemeSegmentedControl from "./ThemeSegmentedControl";
const NAMED_OPTIONS = ["default", "mint", "dark-mint"];
export default function ThemePicker({ value, onChange, className = "", compact = false }) {
    const named = namedThemeOf(value);
    const mode = colorModeOf(value);
    const setNamed = (next) => {
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
    const setMode = (next) => {
        if (named === "default") {
            onChange(composeTheme("default", next));
            return;
        }
        onChange(composeTheme("mint", next));
    };
    return (_jsxs("div", { className: `theme-picker${compact ? " theme-picker--compact" : ""}${className ? ` ${className}` : ""}`, children: [_jsx("label", { className: "theme-picker__named", children: _jsx("select", { className: "theme-picker__select settings-input", value: named, "aria-label": "Theme", onChange: (e) => setNamed(e.target.value), children: NAMED_OPTIONS.map((opt) => (_jsx("option", { value: opt, children: namedThemeLabel(opt) }, opt))) }) }), _jsx(ThemeSegmentedControl, { value: mode, onChange: setMode, className: "theme-picker__modes" })] }));
}
