import { describe, expect, it } from "vitest";
import { adminNavSections } from "../nav/adminNav";
import {
  canAccessMenu,
  isAdminPanelRole,
  menuCategory,
  pathToMenu,
  userCanWriteAdminPath,
  userHasSuperAdminAccess,
} from "./rbac";

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

describe("Read Only Super Admin", () => {
  const role = "read_only_super_admin";
  const session = { username: "auditor", role, roles: [role], is_active: true, menus: null, categories: null };
  const adminPaths = [
    "/admin",
    "/admin/users",
    "/admin/roles",
    "/admin/api-keys",
    "/admin/models",
    "/admin/connections",
    "/admin/security-settings",
    "/admin/logs",
    "/admin/admin-logs",
    "/admin/retention-policy",
    "/admin/smtp",
    "/admin/plans",
    "/admin/groups",
    "/admin/authentication",
    "/admin/operations",
    "/admin/database",
    "/admin/reports",
    "/admin/agents",
  ];

  it("reaches every admin menu, like Super Admin", () => {
    for (const path of adminPaths) {
      const menu = pathToMenu(path);
      expect(menu, path).not.toBeNull();
      expect(canAccessMenu(role, menu!), path).toBe(true);
    }
  });

  it("cannot write on any of them", () => {
    for (const path of adminPaths) {
      expect(userCanWriteAdminPath(path, session), path).toBe(false);
    }
  });

  it("is an admin-panel role but not a Super Admin", () => {
    expect(isAdminPanelRole(role)).toBe(true);
    expect(userHasSuperAdminAccess([role])).toBe(false);
  });

  it("vetoes writes even when the user is also Super Admin", () => {
    const both = { ...session, role: "super_admin", roles: ["super_admin", role] };
    expect(userCanWriteAdminPath("/admin/users", both)).toBe(false);
  });

  it("keeps chat and media usable", () => {
    expect(userCanWriteAdminPath("/admin/chat", session)).toBe(true);
    expect(userCanWriteAdminPath("/admin/media", session)).toBe(true);
  });

  it("is write-locked the same way the retired global read-only slugs are", () => {
    for (const legacy of ["read_only_full_administrator", "read_only_administrator"]) {
      const s = { ...session, role: legacy, roles: [legacy] };
      expect(canAccessMenu(legacy, "users"), legacy).toBe(true);
      expect(userCanWriteAdminPath("/admin/users", s), legacy).toBe(false);
    }
  });
});
