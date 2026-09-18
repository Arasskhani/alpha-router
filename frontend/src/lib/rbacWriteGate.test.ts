/**
 * The admin write-lock must fail closed.
 *
 * `userCanWriteAdminPath` reads `session?.is_active === false`, which is
 * `undefined` - not `false` - when the session is null. So a null session fell
 * straight through to the cached role from localStorage, and a deactivated
 * administrator whose `/api/auth/session` request failed got a fully
 * write-enabled admin UI. AdminLayout now treats "not read yet" as read-only;
 * these cover the predicate the layout calls.
 */
import { describe, expect, it } from "vitest";
import { userCanWriteAdminPath, type SessionRbac } from "./rbac";

const SUPER: SessionRbac = {
  username: "boss",
  role: "super_admin",
  roles: ["super_admin"],
  menus: null,
  is_admin_panel: true,
  is_active: true,
  role_name: "Super Admin",
};

describe("userCanWriteAdminPath", () => {
  it("allows a live Super Admin to write", () => {
    expect(userCanWriteAdminPath("/admin/users", SUPER, "super_admin")).toBe(true);
  });

  it("refuses a deactivated account even with a privileged cached role", () => {
    const deactivated: SessionRbac = { ...SUPER, is_active: false };
    expect(userCanWriteAdminPath("/admin/users", deactivated, "super_admin")).toBe(false);
  });

  it("falls back to the cached role when the session is unknown", () => {
    // Documented, not endorsed: this is exactly why AdminLayout must not treat
    // a null session as "loaded". The predicate cannot tell the difference.
    expect(userCanWriteAdminPath("/admin/users", null, "super_admin")).toBe(true);
    expect(userCanWriteAdminPath("/admin/users", null, "user")).toBe(false);
  });

  it("refuses a path that maps to no admin menu", () => {
    expect(userCanWriteAdminPath("/admin/nonsense", SUPER, "super_admin")).toBe(false);
  });
});
