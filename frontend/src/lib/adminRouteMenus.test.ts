/**
 * Every admin route must belong to a menu in this file's own permission map.
 *
 * The bug this exists for: `/admin/code-interpreter` was added to the route
 * table, the sidebar and the *backend* permission map, but not to the copy of
 * MENU_PATH_PREFIXES in lib/rbac.ts. Nothing failed at build time, and the
 * page still rendered — for Super Admin, whose `menus` is null and so matches
 * everything. What broke was quieter and worse:
 *
 *   • `pathToMenu` returned null, so `userCanWriteAdminPath` fell through to
 *     `return false` and AdminLayout marked the page read-only for *everyone*,
 *     Super Admin included. The page showed the "read-only administrator"
 *     banner and every control was disabled.
 *   • For any role whose session carries an explicit menu list, no menu
 *     matched the path at all, so the route guard redirected them away — the
 *     page was unreachable for exactly the operators it was built for.
 *
 * An unmapped path fails closed in two different places, which is the right
 * default and the reason nothing crashed. A route that no menu claims is
 * always a mistake, so it is worth a test rather than a careful review.
 */
import { describe, expect, it } from "vitest";

import { pathToMenu } from "./rbac";

const sources = import.meta.glob("../**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** Concrete (non-parameterised) paths declared under the /admin route tree. */
function declaredAdminRoutes(): string[] {
  const routes = new Set<string>();
  for (const match of (sources["../App.tsx"] ?? "").matchAll(/<Route\s+path="([^"]+)"/g)) {
    const raw = match[1];
    if (raw.startsWith("/") || raw === "*") continue;
    routes.add(`/admin/${raw}`);
  }
  return [...routes];
}

describe("admin routes are claimed by a menu", () => {
  const routes = declaredAdminRoutes();

  it("finds the route table", () => {
    expect(routes.length).toBeGreaterThan(20);
    expect(routes).toContain("/admin/code-interpreter");
  });

  /**
   * Routes that belong to no menu today. Each one is read-only for every role
   * and unreachable for any role whose session carries an explicit menu list,
   * so this list should only ever shrink.
   *
   * `/admin/projects*` is the admin-shell mirror of the user-panel Projects
   * pages, beside `/admin/chat` and `/admin/media`. Those two are mapped to
   * their user-feature menus, which is what keeps them writable inside the
   * admin shell; Projects has no MenuKey of its own, so it was never mapped.
   * Giving it one reaches the backend MenuKey enum and the role definitions,
   * which is a larger change than this file.
   */
  const KNOWN_UNMAPPED = [
    "/admin/projects",
    "/admin/projects/:projectId",
    "/admin/projects/:projectId/activity",
    "/admin/projects/invite",
  ];

  it("maps every declared route to a menu", () => {
    const orphans = routes
      .filter((route) => pathToMenu(route.replace(/:[^/]+/g, "x")) === null)
      .filter((route) => !KNOWN_UNMAPPED.includes(route));
    expect(orphans).toEqual([]);
  });

  it("does not let the unmapped list grow unnoticed", () => {
    const stillUnmapped = KNOWN_UNMAPPED.filter(
      (route) => pathToMenu(route.replace(/:[^/]+/g, "x")) === null,
    );
    // Fails when one is fixed, so the list is pruned rather than left to rot.
    expect(stillUnmapped).toEqual(KNOWN_UNMAPPED);
  });

  it("maps every sidebar destination to the menu the sidebar claims for it", () => {
    const nav = sources["../nav/adminNav.ts"] ?? "";
    const mismatched: string[] = [];
    for (const match of nav.matchAll(/\{\s*to:\s*"(\/admin[^"]*)",[^}]*menuKey:\s*"([a-z_]+)"/g)) {
      const [, to, menuKey] = match;
      if (pathToMenu(to) !== menuKey) mismatched.push(`${to} -> ${pathToMenu(to)} (nav says ${menuKey})`);
    }
    expect(mismatched).toEqual([]);
  });

  it("puts the Code Interpreter page under operations, where its API lives", () => {
    expect(pathToMenu("/admin/code-interpreter")).toBe("operations");
  });
});
