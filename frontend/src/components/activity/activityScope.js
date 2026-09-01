const ALL_FILTERS = ["user", "model", "apiKey", "app", "status"];
export function activityScopeConfig(scope) {
    switch (scope) {
        case "user":
        case "mine":
            return {
                filterKeys: ["model", "app", "status"],
                showGroupBy: false,
                hideOverviewUsers: true,
                hideTrendsUsers: true,
                hideTrendsApiKeys: false,
                hiddenExploreGroups: ["user"],
            };
        case "api_key":
            return {
                filterKeys: ["model", "app", "status"],
                showGroupBy: false,
                hideOverviewUsers: false,
                hideTrendsUsers: false,
                hideTrendsApiKeys: true,
                hiddenExploreGroups: ["api_key"],
            };
        case "group":
            return {
                filterKeys: ["user", "model", "app", "status"],
                showGroupBy: false,
                hideOverviewUsers: false,
                hideTrendsUsers: false,
                hideTrendsApiKeys: false,
                hiddenExploreGroups: [],
            };
        case "project":
            return {
                filterKeys: ["user", "model", "app", "status"],
                showGroupBy: false,
                hideOverviewUsers: false,
                hideTrendsUsers: false,
                hideTrendsApiKeys: true,
                hiddenExploreGroups: ["api_key"],
            };
        case "connection":
            return {
                filterKeys: ALL_FILTERS,
                showGroupBy: false,
                hideOverviewUsers: false,
                hideTrendsUsers: false,
                hideTrendsApiKeys: false,
                hiddenExploreGroups: ["provider"],
            };
        case "agent":
            return {
                filterKeys: ALL_FILTERS,
                showGroupBy: false,
                hideOverviewUsers: false,
                hideTrendsUsers: false,
                hideTrendsApiKeys: false,
                hiddenExploreGroups: [],
            };
        default:
            return {
                filterKeys: ALL_FILTERS,
                showGroupBy: true,
                hideOverviewUsers: false,
                hideTrendsUsers: false,
                hideTrendsApiKeys: false,
                hiddenExploreGroups: [],
            };
    }
}
