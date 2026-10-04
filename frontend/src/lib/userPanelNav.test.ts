import { describe, expect, it } from "vitest";
import type { SessionRbac } from "./rbac";
import {
  isProjectWorkspacePath,
  sectionEnabled,
  topbarShortcutsForSession,
  userHomePath,
  userSidebarNavForSession,
} from "./userPanelNav";

function session(overrides: Partial<SessionRbac> = {}): SessionRbac {
  return {
    username: "user",
    role: "user",
    roles: ["user"],
    is_active: true,
    is_admin_panel: false,
    menus: [],
    categories: [],
    ...overrides,
  };
}

describe("topbar admin shortcut", () => {
  it("does not show Administration for a regular user", () => {
    const shortcuts = topbarShortcutsForSession(session());

    expect(shortcuts.map((item) => item.label)).toEqual([
      "Chat",
      "Projects",
      "Media",
      "Activity",
      "User Manual",
    ]);
  });

  it("places Administration after User Manual as the final shortcut for a full admin", () => {
    const shortcuts = topbarShortcutsForSession(
      session({
        role: "super_admin",
        roles: ["user", "super_admin"],
        is_admin_panel: true,
        menus: null,
        categories: null,
      }),
    );

    expect(shortcuts.map((item) => item.label)).toEqual([
      "Chat",
      "Projects",
      "Media",
      "Activity",
      "User Manual",
      "Administration",
    ]);
    expect(shortcuts.find((item) => item.label === "Administration")?.to).toBe("/admin");
  });

  it("links a scoped admin to the first permitted admin page", () => {
    const shortcuts = topbarShortcutsForSession(
      session({
        role: "api_keys_full_administrator",
        roles: ["user", "api_keys_full_administrator"],
        is_admin_panel: true,
        menus: ["api_keys"],
      }),
    );

    expect(shortcuts.find((item) => item.label === "Administration")?.to).toBe(
      "/admin/api-keys",
    );
  });
});

describe("isProjectWorkspacePath", () => {
  it("matches app and admin project workspaces", () => {
    expect(isProjectWorkspacePath("/app/projects/abc")).toBe(true);
    expect(isProjectWorkspacePath("/admin/projects/abc/")).toBe(true);
  });

  it("ignores the projects list and invite page", () => {
    expect(isProjectWorkspacePath("/app/projects")).toBe(false);
    expect(isProjectWorkspacePath("/app/projects/invite")).toBe(false);
    expect(isProjectWorkspacePath("/app/projects/abc/activity")).toBe(false);
    expect(isProjectWorkspacePath("/app/chat")).toBe(false);
  });
});

describe("Feature Access sections", () => {
  it("shows Chat and Projects when the server says nothing (an older server)", () => {
    const paths = userSidebarNavForSession(session()).map((item) => item.to);
    expect(paths).toContain("/app/chat");
    expect(paths).toContain("/app/projects");
    expect(userHomePath(session())).toBe("/app/chat");
  });

  it("leaves out a section the account may not open, everywhere the nav is drawn", () => {
    const noChat = session({ features: { chat: false, projects: true } });
    expect(sectionEnabled(noChat, "chat")).toBe(false);
    expect(userSidebarNavForSession(noChat).map((item) => item.to)).not.toContain("/app/chat");
    expect(topbarShortcutsForSession(noChat).map((item) => item.to)).not.toContain("/app/chat");
    expect(userHomePath(noChat)).toBe("/app/projects");
  });

  it("starts a person with neither section in Media", () => {
    const neither = session({ features: { chat: false, projects: false } });
    expect(userHomePath(neither)).toBe("/app/media");
    expect(sectionEnabled(neither, "projects")).toBe(false);
  });
});
