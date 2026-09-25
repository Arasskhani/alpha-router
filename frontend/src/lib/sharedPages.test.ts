import { describe, expect, it } from "vitest";

import { answerImages, readSharedPages, sharedPagesLabel } from "./sharedPages";

describe("the server's mark on an answer built from shared pages", () => {
  it("is read with its sites", () => {
    expect(readSharedPages({ sites: ["docs.example.com", "intranet"] })).toEqual({ sites: ["docs.example.com", "intranet"] });
  });

  it("still counts when its sites are missing or unusable: the protection never hinges on them", () => {
    expect(readSharedPages({})).toEqual({ sites: [] });
    expect(readSharedPages({ sites: [42, "", "x".repeat(300), "ok.example"] })).toEqual({ sites: ["ok.example"] });
  });

  it("keeps at most twenty sites", () => {
    const sites = Array.from({ length: 25 }, (_, i) => `s${i}.example`);
    expect(readSharedPages({ sites })?.sites).toHaveLength(20);
  });

  it.each([undefined, null, "docs.example.com", 1, ["docs.example.com"]])("is absent for %j", (value) => {
    expect(readSharedPages(value)).toBeUndefined();
  });
});

describe("how the chat shows such an answer", () => {
  it("never loads its images", () => {
    expect(answerImages({ pageContext: { sites: ["docs.example.com"] } })).toBe("link");
    expect(answerImages({ pageContext: { sites: [] } })).toBe("link");
    expect(answerImages({})).toBe("load");
  });

  it.each([
    [[], "From a shared page"],
    [["docs.example.com"], "From a page on docs.example.com"],
    [["a.example", "b.example"], "From pages on a.example and b.example"],
    [["a.example", "b.example", "c.example"], "From pages on a.example and 2 other sites"],
  ])("labels %j as %s", (sites, label) => {
    expect(sharedPagesLabel({ sites })).toBe(label);
  });
});
