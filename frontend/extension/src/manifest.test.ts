/**
 * The extension's manifest template: what the extension may do before any
 * server has touched it. The server adds only its own key, origin, version,
 * update URL and the admin's site-access mode (extension_package.py); every
 * permission beyond those is decided here, so it is pinned here.
 */
import { describe, expect, it } from "vitest";

import manifest from "../manifest.template.json";

const template = manifest as Record<string, unknown> & typeof manifest;

describe("the extension manifest template", () => {
  it("is Manifest V3 for Chrome and Edge 116 and later", () => {
    expect(template.manifest_version).toBe(3);
    // chrome.sidePanel.open() needs 116.
    expect(template.minimum_chrome_version).toBe("116");
    expect(template.name).toBe("Alpharouter");
    expect(template.description.length).toBeLessThanOrEqual(132);
  });

  it("asks for exactly these permissions", () => {
    expect(template.permissions).toEqual([
      "activeTab",
      "contextMenus",
      "scripting",
      "sidePanel",
      "storage",
      "tabGroups",
      "tabs",
    ]);
  });

  it("holds no permission that would read cookies, history, downloads or drive the debugger", () => {
    for (const risky of ["cookies", "history", "downloads", "debugger", "identity", "webRequest", "management"]) {
      expect(template.permissions).not.toContain(risky);
    }
  });

  it("has no site access of its own: sites are asked for one by one", () => {
    expect(template.host_permissions).toEqual([]);
    expect(template.optional_host_permissions).toEqual(["<all_urls>"]);
  });

  it("cannot be messaged by web pages or other extensions", () => {
    expect("externally_connectable" in template).toBe(false);
  });

  it("runs only its own scripts, and lets the server's origin be reached", () => {
    expect(template.content_security_policy).toEqual({
      extension_pages: "script-src 'self'; object-src 'self'",
    });
    // A connect-src here would have to name the server, which differs per install.
    expect(template.content_security_policy.extension_pages).not.toContain("connect-src");
  });

  it("opens its side panel from the toolbar and from a shortcut", () => {
    expect(template.side_panel).toEqual({ default_path: "sidepanel.html" });
    expect(template.commands._execute_action.suggested_key.default).toBe("Alt+Shift+A");
  });

  it("runs its background code as a module service worker", () => {
    expect(template.background).toEqual({ service_worker: "background.js", type: "module" });
  });

  it("leaves what belongs to a server for the server to fill in", () => {
    for (const key of ["key", "update_url", "web_accessible_resources", "version_name"]) {
      expect(key in template).toBe(false);
    }
  });
});
