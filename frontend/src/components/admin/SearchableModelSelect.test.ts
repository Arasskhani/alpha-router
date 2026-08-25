import { describe, expect, it } from "vitest";
import { filterModelOptions } from "./SearchableModelSelect";

describe("filterModelOptions", () => {
  const options = [
    { value: "1", label: "OpenAI: GPT-4o · openai" },
    { value: "2", label: "google/gemini-embedding-001 · openrouter · 3072d" },
    { value: "3", label: "text-embedding-3-small · openai · 1536d" },
  ];

  it("returns all options when the query is empty", () => {
    expect(filterModelOptions(options, "")).toHaveLength(3);
  });

  it("matches provider, id, or dimensions", () => {
    expect(filterModelOptions(options, "3072").map((o) => o.value)).toEqual(["2"]);
    expect(filterModelOptions(options, "embedding-3").map((o) => o.value)).toEqual(["3"]);
    expect(filterModelOptions(options, "gpt-4o").map((o) => o.value)).toEqual(["1"]);
  });
});
