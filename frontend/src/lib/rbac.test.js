import { describe, expect, it } from "vitest";
import { adminNavSections } from "../nav/adminNav";
import { menuCategory, pathToMenu } from "./rbac";
describe("security settings nav", () => {
    it("maps the security settings route to the security category", () => {
        expect(pathToMenu("/admin/security-settings")).toBe("security_settings");
        expect(menuCategory("security_settings")).toBe("security");
    });
    it("registers Security Settings after People & access", () => {
        const titles = adminNavSections.map((section) => section.title);
        expect(titles.indexOf("People & access")).toBeGreaterThan(-1);
        expect(titles.indexOf("Security")).toBe(titles.indexOf("People & access") + 1);
        const security = adminNavSections.find((section) => section.categoryKey === "security");
        expect(security?.items.map((item) => item.to)).toEqual(["/admin/security-settings"]);
    });
});
