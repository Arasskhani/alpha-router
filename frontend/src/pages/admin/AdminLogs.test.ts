import { describe, expect, it } from "vitest";

import { AUDIT_SOURCES, hasDetail, humanAction, sourceLabel } from "./AdminLogs";

/**
 * The Admin Logs page reads eight audit trails through one server-side union.
 * The picker must offer exactly the trails the server knows, under the words
 * the rest of the admin panel uses for those domains.
 */
describe("audit trail picker", () => {
  it("offers every trail the server unions, plus all of them at once", () => {
    const keys = AUDIT_SOURCES.map(([key]) => key);
    expect(keys).toEqual([
      "all",
      "security",
      "agents",
      "tools",
      "knowledge",
      "governance",
      "projects",
      "api_keys",
      "connections",
      "authentication",
      "browser_extension",
    ]);
  });

  it("labels a known trail and passes an unknown key through untouched", () => {
    expect(sourceLabel("api_keys")).toBe("API keys");
    expect(sourceLabel("governance")).toBe("Governance");
    // A trail added server-side before the picker learns it still shows *something*.
    expect(sourceLabel("billing")).toBe("billing");
    expect(sourceLabel("browser_extension")).toBe("Browser extension");
  });
});

describe("action names", () => {
  it("read as events, and a page shared from the browser says so", () => {
    expect(humanAction("tls_activate")).toBe("Tls activate");
    expect(humanAction("page_context")).toBe("Page shared with a model");
  });
});

describe("hasDetail", () => {
  it("treats an empty object, an empty array and null alike", () => {
    expect(hasDetail(null)).toBe(false);
    expect(hasDetail({})).toBe(false);
    expect(hasDetail([])).toBe(false);
  });

  it("is true for any content, whichever shape a trail stores", () => {
    // Security and knowledge store objects; the API-key and connection logs
    // store a list of field changes.
    expect(hasDetail({ https_port: 443 })).toBe(true);
    expect(hasDetail([{ field: "model" }])).toBe(true);
  });
});
