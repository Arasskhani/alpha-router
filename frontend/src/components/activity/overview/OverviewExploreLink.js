import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
export default function OverviewExploreLink({ focus, onExplore }) {
    return (_jsxs("button", { type: "button", className: "overview-explore-link", onClick: () => onExplore(focus), children: ["Explore ", _jsx("span", { "aria-hidden": true, children: "\u203A" })] }));
}
