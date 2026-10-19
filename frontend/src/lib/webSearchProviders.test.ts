import { describe, expect, it } from "vitest";

import { modelKeyWarning, searchKeyWarning, WEB_SEARCH_PROVIDERS, webSearchProvider } from "./webSearchProviders";

describe("the search services", () => {
  it("are the five the server takes, with Google's apart from Gemini's id", () => {
    expect(WEB_SEARCH_PROVIDERS.map((p) => p.id)).toEqual(["brave", "tavily", "google_pse", "searxng", "duckduckgo"]);
    expect(webSearchProvider("google")).toBeUndefined();
    expect(webSearchProvider(" Tavily ")?.label).toBe("Tavily");
  });
});

describe("a key in the wrong place", () => {
  it("is said when a model provider's key is typed as a search key", () => {
    expect(searchKeyWarning("brave", "sk-proj-abc")).toMatch(/model provider's API key/);
    expect(searchKeyWarning("tavily", "sk-ant-xyz")).toMatch(/Add it under Model providers/);
  });

  it("is said when another search service's key is typed", () => {
    expect(searchKeyWarning("brave", "tvly-123")).toBe("This looks like a Tavily key, not a Brave Search one.");
    expect(searchKeyWarning("tavily", "BSAabc")).toMatch(/Brave Search key/);
  });

  it("is quiet for the right shape, an empty key, or a service with no key", () => {
    expect(searchKeyWarning("brave", "BSA-123")).toBe("");
    expect(searchKeyWarning("google_pse", "AIzaSyD")).toBe("");
    expect(searchKeyWarning("tavily", "")).toBe("");
    expect(searchKeyWarning("searxng", "sk-anything")).toBe("");
  });

  it("asks to check a key of an unusual shape", () => {
    expect(searchKeyWarning("tavily", "abc123")).toMatch(/usually start with tvly-/);
  });

  it("is said when a search key is typed as a model key", () => {
    expect(modelKeyWarning("tvly-abc")).toMatch(/Tavily key, not a model provider's/);
    expect(modelKeyWarning("BSA123")).toMatch(/Brave Search key/);
    expect(modelKeyWarning("sk-or-v1-abc")).toBe("");
  });
});
