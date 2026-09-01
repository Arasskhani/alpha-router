import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { formatTokens } from "../formatters";
import OverviewExploreLink from "./OverviewExploreLink";
export default function OverviewTopList({ title, focus, items, emptyLabel, onExplore }) {
    return (_jsxs("article", { className: "overview-top-list card", children: [_jsxs("header", { className: "overview-card-head", children: [_jsx("h3", { children: title }), _jsx(OverviewExploreLink, { focus: focus, onExplore: onExplore })] }), _jsxs("ul", { className: "overview-top-list__items", children: [items.map((item, idx) => (_jsxs("li", { children: [_jsx("span", { className: "overview-top-list__rank", children: idx + 1 }), _jsx("span", { className: "overview-top-list__avatar", "aria-hidden": true, children: item.initials }), _jsx("span", { className: "overview-top-list__meta", children: _jsx("span", { className: "overview-top-list__name", children: item.label }) }), _jsxs("span", { className: "overview-top-list__value", children: [formatTokens(item.tokens), " tok"] })] }, item.key))), items.length === 0 ? _jsx("li", { className: "overview-top-list__empty muted-text", children: emptyLabel }) : null] })] }));
}
