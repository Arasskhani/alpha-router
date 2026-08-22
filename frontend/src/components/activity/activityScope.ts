import type { ExploreGroup } from "./types";

export type ActivityScope = "service" | "user" | "mine" | "api_key" | "connection" | "group" | "agent" | "project";

export type ActivityFilterKey = "user" | "model" | "apiKey" | "app" | "status";

export type ActivityScopeConfig = {
  filterKeys: ActivityFilterKey[];
  showGroupBy: boolean;
  hideOverviewUsers: boolean;
  hideTrendsUsers: boolean;
  hideTrendsApiKeys: boolean;
  hiddenExploreGroups: ExploreGroup[];
};

const ALL_FILTERS: ActivityFilterKey[] = ["user", "model", "apiKey", "app", "status"];

export function activityScopeConfig(scope: ActivityScope): ActivityScopeConfig {
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
