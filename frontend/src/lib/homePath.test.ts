import { describe, expect, it } from "vitest";
import { adminNavSections } from "../nav/adminNav";
import { homePathFor } from "./homePath";
import { filterAdminNav, firstAllowedAdminPath } from "./rbac";

describe("homePathFor", () => {
  it("starts a user in chat", () => {
    expect(homePathFor({ role: "user" })).toBe("/app/chat");
  });

  it("starts a user whose Chat is closed in the first section that is open", () => {
    expect(homePathFor({ role: "user", features: { chat: false } })).toBe("/app/projects");
    expect(homePathFor({ role: "user", features: { chat: false, projects: false } })).toBe("/app/media");
  });

  it("starts an admin-panel role on the first admin page its menus allow", () => {
    expect(homePathFor({ role: "super_admin" })).toBe(firstAllowedAdminPath(adminNavSections));
    const limited = homePathFor({ role: "agents_administrator" });
    expect(limited).toBe(firstAllowedAdminPath(filterAdminNav(adminNavSections, "agents_administrator")));
    expect(limited.startsWith("/admin")).toBe(true);
  });
});
