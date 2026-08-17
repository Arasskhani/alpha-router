import { describe, expect, it } from "vitest";
import { activityScopeConfig, type ActivityScope } from "./activityScope";

describe("activityScopeConfig", () => {
  const scopes: ActivityScope[] = ["service", "user", "mine", "api_key", "connection", "group", "agent"];

  it("keeps Dashboard as the full filter set with group-by", () => {
    const cfg = activityScopeConfig("service");
    expect(cfg.showGroupBy).toBe(true);
    expect(cfg.filterKeys).toEqual(["user", "model", "apiKey", "app", "status"]);
    expect(cfg.hideOverviewUsers).toBe(false);
    expect(cfg.hiddenExploreGroups).toEqual([]);
  });

  it("hides tautological user dimensions on personal scopes", () => {
    for (const scope of ["user", "mine"] as const) {
      const cfg = activityScopeConfig(scope);
      expect(cfg.hideOverviewUsers).toBe(true);
      expect(cfg.hideTrendsUsers).toBe(true);
      expect(cfg.filterKeys).not.toContain("user");
      expect(cfg.hiddenExploreGroups).toContain("user");
    }
  });

  it("hides API key grouping on the key-scoped dashboard", () => {
    const cfg = activityScopeConfig("api_key");
    expect(cfg.hideTrendsApiKeys).toBe(true);
    expect(cfg.filterKeys).not.toContain("apiKey");
    expect(cfg.hiddenExploreGroups).toContain("api_key");
  });

  it("keeps user and model filters on Agent usage", () => {
    const cfg = activityScopeConfig("agent");
    expect(cfg.showGroupBy).toBe(false);
    expect(cfg.filterKeys).toEqual(["user", "model", "apiKey", "app", "status"]);
    expect(cfg.hideOverviewUsers).toBe(false);
    expect(cfg.hiddenExploreGroups).toEqual([]);
  });

  it("covers every activity scope", () => {
    for (const scope of scopes) {
      const cfg = activityScopeConfig(scope);
      expect(cfg.filterKeys.length).toBeGreaterThan(0);
    }
  });
});
