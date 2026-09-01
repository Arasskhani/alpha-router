import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import TrendsSection from "./TrendsSection";
export default function ActivityTrendsPanel({ trends, hideUsers = false, hideApiKeys = false, onExplore }) {
    return (_jsxs("div", { className: "activity-trends", children: [_jsx(TrendsSection, { title: "Models", focus: "trends_models", dimension: trends.models, onExplore: onExplore }), hideUsers ? null : (_jsx(TrendsSection, { title: "Users", focus: "trends_users", dimension: trends.users, onExplore: onExplore })), hideApiKeys ? null : (_jsx(TrendsSection, { title: "API Keys", focus: "trends_api_keys", dimension: trends.api_keys, onExplore: onExplore })), _jsx(TrendsSection, { title: "Apps", focus: "trends_apps", dimension: trends.apps, onExplore: onExplore })] }));
}
