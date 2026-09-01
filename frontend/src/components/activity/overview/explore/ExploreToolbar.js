import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import ExploreMenu from "./ExploreMenu";
import { EXPLORE_GROUP_OPTIONS, EXPLORE_METRIC_OPTIONS, EXPLORE_ROLLUP_OPTIONS, EXPLORE_TOP_N_OPTIONS, groupLabel, } from "./explorePresets";
export default function ExploreToolbar({ controls, hiddenGroups = [], onChange }) {
    const groupOptions = EXPLORE_GROUP_OPTIONS.filter((o) => o.value === controls.group || !hiddenGroups.includes(o.value));
    const subgroupOptions = groupOptions.filter((o) => o.value !== "none" && o.value !== controls.group);
    return (_jsx("div", { className: "explore-toolbar", children: _jsxs("div", { className: "explore-toolbar__left", children: [_jsx(ExploreMenu, { value: controls.metric, options: EXPLORE_METRIC_OPTIONS, onChange: (v) => onChange({ metric: v }, true), searchable: true, searchPlaceholder: "Metric", ariaLabel: "Explore metric" }), _jsx("span", { className: "explore-toolbar__by", children: "by" }), _jsx(ExploreMenu, { value: controls.group, options: groupOptions, onChange: (v) => {
                        const group = v;
                        const patch = { group };
                        if (controls.subgroup === group)
                            patch.subgroup = "";
                        onChange(patch, true);
                    }, searchable: true, searchPlaceholder: "Group", ariaLabel: "Group by" }), _jsx(ExploreMenu, { value: controls.subgroup || "", options: [{ value: "", label: "None" }, ...subgroupOptions], onChange: (v) => onChange({ subgroup: (v || "") }, true), triggerLabel: controls.subgroup ? groupLabel(controls.subgroup) : "+ Subgroup", searchable: true, searchPlaceholder: "Search", ariaLabel: "Subgroup", className: !controls.subgroup ? "explore-menu--subgroup" : "" }), _jsx(ExploreMenu, { value: controls.rollup, options: EXPLORE_ROLLUP_OPTIONS, onChange: (v) => onChange({ rollup: v }, true), triggerPrefix: "Rollup: ", ariaLabel: "Rollup" }), _jsxs("div", { className: "explore-toolbar__segmented", children: [_jsx(ExploreMenu, { value: controls.topMode, options: [
                                { value: "top", label: "Top" },
                                { value: "bottom", label: "Bottom" },
                            ], onChange: (v) => onChange({ topMode: v }, true), ariaLabel: "Top or bottom", className: "explore-menu--segment" }), _jsx(ExploreMenu, { value: String(controls.topN), options: EXPLORE_TOP_N_OPTIONS.map((n) => ({ value: String(n), label: String(n) })), onChange: (v) => onChange({ topN: Number(v) }, true), ariaLabel: "Top N", className: "explore-menu--segment" })] }), _jsx(ExploreMenu, { value: controls.rankBy, options: [
                        { value: "metric", label: "Current metric" },
                        { value: "requests", label: "Requests" },
                    ], onChange: (v) => onChange({ rankBy: v }, true), triggerPrefix: "Rank by: ", ariaLabel: "Rank by" })] }) }));
}
