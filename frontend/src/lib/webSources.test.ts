import { describe, expect, it } from "vitest";

import { readWebSources, sourceHost, webActivityLabel } from "./webSources";

describe("the pages the web tools read for an answer", () => {
  it("are read only from a well-formed server value, as http(s) links", () => {
    expect(
      readWebSources([
        { title: "Gold price", url: "https://www.example.com/gold" },
        { url: "https://b.example/x" },
        { title: "script", url: "javascript:alert(1)" },
        { title: "file", url: "file:///etc/passwd" },
        { title: "again", url: "https://www.example.com/gold" },
        "x",
      ]),
    ).toEqual([
      { title: "Gold price", url: "https://www.example.com/gold" },
      { title: "https://b.example/x", url: "https://b.example/x" },
    ]);
    expect(readWebSources([])).toBeUndefined();
    expect(readWebSources({ url: "https://a.example" })).toBeUndefined();
    expect(readWebSources(Array.from({ length: 30 }, (_, n) => ({ url: `https://s${n}.example/` })))).toHaveLength(20);
  });

  it("name their site without www", () => {
    expect(sourceHost("https://www.example.com/a")).toBe("example.com");
    expect(sourceHost("not a url")).toBe("");
  });
});

describe("what the chat says while a web tool runs", () => {
  it("names the search or the site being read", () => {
    expect(webActivityLabel({ tool: "web_search", query: "gold price today" })).toBe("Searching the web: gold price today");
    expect(webActivityLabel({ tool: "web_search" })).toBe("Searching the web");
    expect(webActivityLabel({ tool: "web_fetch", url: "https://www.news.example/a", host: "www.news.example" })).toBe(
      "Reading news.example",
    );
    expect(webActivityLabel({ tool: "web_fetch" })).toBe("Reading a page");
    expect(webActivityLabel({ tool: "shell" })).toBeUndefined();
    expect(webActivityLabel(undefined)).toBeUndefined();
  });
});
