/**
 * @vitest-environment node
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { installChromeFake } from "../test/chromeFake";
import { loadTrustedSites, TRUSTED_SITES_KEY, trustSite, untrustSite } from "./trustedSites";

beforeEach(() => {
  installChromeFake();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the sites a person trusts the agent on", () => {
  it("are kept by site, once each, and can be taken back", async () => {
    expect(await loadTrustedSites()).toEqual([]);
    await trustSite("www.wikipedia.org");
    await trustSite("en.wikipedia.org");
    expect(await trustSite("shop.example.co.uk")).toEqual(["wikipedia.org", "example.co.uk"]);
    expect(await untrustSite("wikipedia.org")).toEqual(["example.co.uk"]);
    expect(await loadTrustedSites()).toEqual(["example.co.uk"]);
  });

  it("ignores what is not a site in storage", async () => {
    await chrome.storage.local.set({ [TRUSTED_SITES_KEY]: ["ok.example.com", 5, "bad site", "javascript:alert(1)"] });
    expect(await loadTrustedSites()).toEqual(["example.com"]);
  });
});
