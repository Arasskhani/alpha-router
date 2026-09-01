import { jsx as _jsx } from "react/jsx-runtime";
const TABS = [
    { id: "overview", label: "Overview" },
    { id: "trends", label: "Trends" },
    { id: "explore", label: "Explore" },
];
export default function ActivityTabs({ value, onChange }) {
    return (_jsx("nav", { className: "activity-tabs", "aria-label": "Activity views", children: TABS.map((tab) => (_jsx("button", { type: "button", className: `activity-tabs__btn${value === tab.id ? " is-active" : ""}`, "aria-current": value === tab.id ? "page" : undefined, onClick: () => onChange(tab.id), children: tab.label }, tab.id))) }));
}
