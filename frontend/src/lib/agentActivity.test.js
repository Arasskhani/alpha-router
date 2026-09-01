import { describe, expect, it } from "vitest";
import { activityApiPath, humanActivityEventType, nextActivitySearch, parseActivityQuery, runtimeHealthHref, } from "./agentActivity";
describe("runtimeHealthHref", () => {
    it("opens all runtime turns from the last 24 hours", () => {
        expect(runtimeHealthHref()).toBe("/admin/agent-activity?source=runtime&since_hours=24");
    });
    it("opens blocked or failed runtime turns", () => {
        expect(runtimeHealthHref("blocked")).toBe("/admin/agent-activity?source=runtime&since_hours=24&status=blocked");
        expect(runtimeHealthHref("failed")).toBe("/admin/agent-activity?source=runtime&since_hours=24&status=failed");
    });
});
describe("parseActivityQuery", () => {
    it("treats a status without source as runtime", () => {
        expect(parseActivityQuery(new URLSearchParams("status=blocked"))).toEqual({
            source: "runtime",
            status: "blocked",
            sinceHours: "",
        });
    });
});
describe("activityApiPath", () => {
    it("forwards source, status, and since_hours", () => {
        expect(activityApiPath({
            source: "runtime",
            status: "blocked",
            sinceHours: "24",
        })).toBe("/api/admin/agents/activity?limit=250&source=runtime&status=blocked&since_hours=24");
    });
});
describe("nextActivitySearch", () => {
    it("clears status when leaving runtime", () => {
        const current = new URLSearchParams("source=runtime&status=blocked&since_hours=24");
        expect(nextActivitySearch(current, { source: "agent" }).toString()).toBe("source=agent&since_hours=24");
    });
});
describe("humanActivityEventType", () => {
    it("reads runtime status as a short run label", () => {
        expect(humanActivityEventType("agent.run.blocked")).toBe("Run blocked");
    });
});
