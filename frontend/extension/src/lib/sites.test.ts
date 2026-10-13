/**
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import { hostMatches, readablePage, sameSite, siteOf, siteRefusal } from "./sites";

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
    // Hosts only a URL parser accepts: as a permission pattern, "*" is every site.
    "https://*/login",
    "https://*.bank.example/",
    "https://exa$mple.com/",
    "not a url",
    "",
    undefined,
  ])("never %s", (url) => {
    expect(readablePage(url)).toBeNull();
  });

  it("names a host written with its final dot without it, for the rules and the server", () => {
    expect(readablePage("https://docs.example.com./guide")).toEqual({
      host: "docs.example.com",
      origin: "https://docs.example.com.",
      pattern: "https://docs.example.com./*",
    });
    expect(siteRefusal(readablePage("https://ai.example.com./")!.host, { allowed_sites: ["wiki.example.com"], blocked_sites: [] }, "ai.example.com")).toBeNull();
  });

  it("reads hosts with underscores, IPv6 addresses and internationalized names", () => {
    expect(readablePage("https://my_server.local/")?.host).toBe("my_server.local");
    expect(readablePage("http://[::1]:8080/")?.pattern).toBe("http://[::1]:8080/*");
    expect(readablePage("https://مثال.example/")?.host).toBe("xn--mgbh0fb.example");
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

describe("the site a host belongs to", () => {
  it.each([
    ["www.google.com", "google.com"],
    ["google.com", "google.com"],
    ["mail.google.com", "google.com"],
    ["en.wikipedia.org", "wikipedia.org"],
    ["en.m.wikipedia.org", "wikipedia.org"],
    ["shop.example.co.uk", "example.co.uk"],
    ["example.co.uk", "example.co.uk"],
    ["www.digikala.com", "digikala.com"],
    ["portal.tehran.ac.ir", "tehran.ac.ir"],
    ["alice.github.io", "alice.github.io"],
    ["docs.alice.github.io", "alice.github.io"],
    ["github.io", "github.io"],
    // Tenants of one service are each their own site.
    ["corp.sharepoint.com", "corp.sharepoint.com"],
    ["evil-my.sharepoint.com", "evil-my.sharepoint.com"],
    ["acme.atlassian.net", "acme.atlassian.net"],
    ["shop.myshopify.com", "shop.myshopify.com"],
    ["files.acct.web.core.windows.net", "acct.web.core.windows.net"],
    ["acme.my.salesforce.com", "acme.my.salesforce.com"],
    ["localhost", "localhost"],
    ["intranet", "intranet"],
    ["10.0.0.5", "10.0.0.5"],
    ["[::1]", "[::1]"],
    ["WWW.Example.COM.", "example.com"],
  ])("%s is %s", (host, site) => {
    expect(siteOf(host)).toBe(site);
  });

  it("tells two people's hosted sites apart, and one company's subdomains as one", () => {
    expect(sameSite("alice.github.io", "bob.github.io")).toBe(false);
    expect(sameSite("www.example.com", "shop.example.com")).toBe(true);
    expect(sameSite("example.com", "example.org")).toBe(false);
  });
});
