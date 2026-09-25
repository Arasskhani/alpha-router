/**
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import { hostMatches, readablePage, siteRefusal } from "./sites";

describe("pages the extension can read at all", () => {
  it("are http and https pages, as origin and a per-site pattern", () => {
    expect(readablePage("https://Docs.Example.com:8443/guide?q=1#top")).toEqual({
      host: "docs.example.com",
      origin: "https://docs.example.com:8443",
      pattern: "https://docs.example.com:8443/*",
    });
    expect(readablePage("http://intranet/wiki")?.pattern).toBe("http://intranet/*");
  });

  it.each([
    "chrome://settings",
    "edge://extensions",
    "chrome-extension://abcdefghijklmnopabcdefghijklmnop/sidepanel.html",
    "file:///C:/report.pdf",
    "about:blank",
    "data:text/html,<p>x</p>",
    "javascript:alert(1)",
    "view-source:https://example.com",
    "https://chromewebstore.google.com/detail/x",
    "https://chrome.google.com/webstore/detail/x",
    "https://microsoftedge.microsoft.com/addons/detail/x",
    "https://user:pass@example.com/",
    "not a url",
    "",
    undefined,
  ])("never %s", (url) => {
    expect(readablePage(url)).toBeNull();
  });

  it("reads Google's other sites", () => {
    expect(readablePage("https://chrome.google.com/intl/en/chrome/")).not.toBeNull();
  });
});

describe("site patterns, as the server reads them", () => {
  it.each([
    ["example.com", "example.com", true],
    ["www.example.com", "example.com", false],
    ["example.com", "*.example.com", true],
    ["a.b.example.com", "*.example.com", true],
    ["badexample.com", "*.example.com", false],
    ["Example.COM.", "example.com", true],
  ])("%s against %s", (host, pattern, matches) => {
    expect(hostMatches(host, pattern)).toBe(matches);
  });
});

describe("the administrator's rules", () => {
  const rules = (allowed: string[], blocked: string[]) => ({ allowed_sites: allowed, blocked_sites: blocked });

  it("allow everything by default", () => {
    expect(siteRefusal("example.com", rules([], []), null)).toBeNull();
  });

  it("block wins over allow", () => {
    expect(siteRefusal("bank.example", rules(["*.example"], ["bank.example"]), null)).toBe("site_blocked");
  });

  it("shut out every unlisted site once there is an allow list", () => {
    expect(siteRefusal("mail.example.com", rules(["wiki.example.com"], []), null)).toBe("site_not_allowed");
    expect(siteRefusal("wiki.example.com", rules(["wiki.example.com"], []), null)).toBeNull();
  });

  it("never shut out Alpharouter itself, unless it is blocked", () => {
    expect(siteRefusal("ai.example.com", rules(["wiki.example.com"], []), "ai.example.com")).toBeNull();
    expect(siteRefusal("ai.example.com", rules([], ["ai.example.com"]), "ai.example.com")).toBe("site_blocked");
  });
});
