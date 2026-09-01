import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
function IconSun() {
    return (_jsxs("svg", { width: "16", height: "16", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": true, children: [_jsx("circle", { cx: "12", cy: "12", r: "4" }), _jsx("path", { d: "M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" })] }));
}
function IconMoon() {
    return (_jsx("svg", { width: "16", height: "16", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": true, children: _jsx("path", { d: "M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" }) }));
}
function IconSystem() {
    return (_jsxs("svg", { width: "16", height: "16", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": true, children: [_jsx("rect", { x: "2", y: "3", width: "20", height: "14", rx: "2" }), _jsx("path", { d: "M8 21h8M12 17v4" })] }));
}
const OPTIONS = [
    { value: "light", label: "Light", icon: _jsx(IconSun, {}) },
    { value: "dark", label: "Dark", icon: _jsx(IconMoon, {}) },
    { value: "system", label: "System", icon: _jsx(IconSystem, {}) },
];
/** Light / Dark / System segmented control. */
export default function ThemeSegmentedControl({ value, onChange, className = "" }) {
    return (_jsx("div", { className: `theme-segment${className ? ` ${className}` : ""}`, role: "group", "aria-label": "Color mode", children: OPTIONS.map((opt) => (_jsx("button", { type: "button", className: `theme-segment__btn${value === opt.value ? " is-active" : ""}`, "aria-label": opt.label, "aria-pressed": value === opt.value, title: opt.label, onClick: () => onChange(opt.value), children: opt.icon }, opt.value))) }));
}
