import { describe, expect, it } from "vitest";
import type { SessionRbac } from "./rbac";
import { topbarShortcutsForSession } from "./userPanelNav";

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
      "Media",
      "Usage & Activity",
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
      "Media",
      "Usage & Activity",
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
