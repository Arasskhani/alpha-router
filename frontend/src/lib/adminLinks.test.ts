/**
 * Every in-app /admin link must point at a route that exists.
 *
 * The bug: a "Retention Policy -> API Logs" link was written as
 * `/admin/api-logs` while the route is `/admin/logs`. Nothing failed at build
 * time. The unmatched path fell through to the catch-all, which sent the admin
 * to the login page — from inside an authenticated session, which reads as
 * having been signed out. A typo in an href is invisible until someone clicks
 * it, so it is worth a test rather than a careful review.
 */
import { describe, expect, it } from "vitest";

// Read through Vite rather than node:fs: the frontend tsconfig has no node
// types, and this keeps the test running in the same environment as the app.
const sources = import.meta.glob("../**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const appSource = sources["../App.tsx"];

/** The literal paths declared under the `/admin` route tree in App.tsx. */
function declaredAdminRoutes(): Set<string> {
  const routes = new Set<string>();
  for (const match of appSource.matchAll(/<Route\s+path="([^"]+)"/g)) {
    const raw = match[1];
    if (raw.startsWith("/") || raw === "*") continue; // top-level or catch-all
    routes.add(`/admin/${raw}`);
  }
  return routes;
}

/** Turn `/admin/users/:userId/media` into a matcher for a concrete link. */
function matches(route: string, link: string): boolean {
  return new RegExp(`^${route.replace(/:[^/]+/g, "[^/]+")}$`).test(link);
}

describe("admin links", () => {
  const routes = declaredAdminRoutes();

  it("finds the admin route table", () => {
    // If App.tsx is restructured this test would otherwise pass vacuously.
    expect(appSource).toBeTruthy();
    expect(routes.size).toBeGreaterThan(20);
    expect(routes.has("/admin/logs")).toBe(true);
    expect(routes.has("/admin/retention-policy")).toBe(true);
  });

  it("never points at a route that does not exist", () => {
    const broken: string[] = [];
    for (const [file, text] of Object.entries(sources)) {
      if (/\.test\.tsx?$/.test(file)) continue;
      for (const match of text.matchAll(/(?:to|href)=["`](\/admin\/[^"`${?#]*)/g)) {
        const link = match[1].replace(/\/$/, "");
        if (![...routes].some((route) => matches(route, link))) {
          broken.push(`${file} -> ${link}`);
        }
      }
    }
    expect(broken).toEqual([]);
  });

  it("the Retention Policy page links to the real API Logs page", () => {
    const page = sources["../pages/admin/RetentionPolicy.tsx"];
    expect(page).toContain('to="/admin/logs"');
    expect(page).not.toContain('to="/admin/api-logs"');
  });
});
