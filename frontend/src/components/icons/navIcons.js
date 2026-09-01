import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
const svgProps = {
    width: 16,
    height: 16,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true,
};
export function IconChat({ className = "" }) {
    return (_jsx("svg", { ...svgProps, className: className, children: _jsx("path", { d: "M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" }) }));
}
export function IconMedia({ className = "" }) {
    return (_jsxs("svg", { ...svgProps, className: className, children: [_jsx("rect", { x: "3", y: "3", width: "18", height: "18", rx: "2" }), _jsx("circle", { cx: "8.5", cy: "8.5", r: "1.5" }), _jsx("path", { d: "M21 15l-5-5L5 21" })] }));
}
export function IconActivity({ className = "" }) {
    return (_jsxs("svg", { ...svgProps, className: className, children: [_jsx("path", { d: "M6 20V10" }), _jsx("path", { d: "M12 20V4" }), _jsx("path", { d: "M18 20v-6" })] }));
}
export function IconLogs({ className = "" }) {
    return (_jsxs("svg", { ...svgProps, className: className, children: [_jsx("path", { d: "M8 6h13" }), _jsx("path", { d: "M8 12h13" }), _jsx("path", { d: "M8 18h13" }), _jsx("path", { d: "M3 6h.01" }), _jsx("path", { d: "M3 12h.01" }), _jsx("path", { d: "M3 18h.01" })] }));
}
export function IconManual({ className = "" }) {
    return (_jsxs("svg", { ...svgProps, className: className, children: [_jsx("path", { d: "M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" }), _jsx("path", { d: "M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" })] }));
}
export function IconAdmin({ className = "" }) {
    return (_jsxs("svg", { ...svgProps, className: className, children: [_jsx("path", { d: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" }), _jsx("circle", { cx: "12", cy: "12", r: "2" }), _jsx("path", { d: "M12 9.2v.4M12 14.4v.4M9.2 12h.4M14.4 12h.4M10.1 10.1l.3.3M13.6 13.6l.3.3M10.1 13.9l.3-.3M13.6 10.4l.3-.3" })] }));
}
export function IconFolder({ className = "" }) {
    return (_jsx("svg", { ...svgProps, className: className, children: _jsx("path", { d: "M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" }) }));
}
export function IconProjects({ className = "" }) {
    return (_jsxs("svg", { ...svgProps, className: className, children: [_jsx("path", { d: "M9 11H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2z" }), _jsx("path", { d: "M19 11h-4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2z" }), _jsx("path", { d: "M9 21H5a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2z" }), _jsx("path", { d: "M19 21h-4a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2z" })] }));
}
export function IconLogout({ className = "" }) {
    return (_jsxs("svg", { ...svgProps, className: className, children: [_jsx("path", { d: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" }), _jsx("polyline", { points: "16 17 21 12 16 7" }), _jsx("line", { x1: "21", y1: "12", x2: "9", y2: "12" })] }));
}
const NAV_ICONS = {
    chat: IconChat,
    media: IconMedia,
    activity: IconActivity,
    manual: IconManual,
    admin: IconAdmin,
    folder: IconFolder,
    projects: IconProjects,
};
export function NavIcon({ name, className = "nav-icon" }) {
    const Cmp = NAV_ICONS[name];
    return _jsx(Cmp, { className: className });
}
