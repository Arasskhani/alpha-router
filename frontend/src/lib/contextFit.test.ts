import { describe, expect, it } from "vitest";

import { contextFitLabel, contextFitNote, readContextFit } from "./contextFit";

describe("what fitting left out", () => {
  it("is read only from a well-formed server value", () => {
    expect(readContextFit({ dropped: 30, summarized: 20 })).toEqual({ dropped: 30, summarized: 20 });
    expect(readContextFit({ dropped: 5 })).toEqual({ dropped: 5, summarized: 0 });
    expect(readContextFit({ dropped: 5, summarized: 9 })).toEqual({ dropped: 5, summarized: 5 });
    for (const bad of [null, "x", {}, { dropped: 0 }, { dropped: -2 }, { dropped: 1.5 }]) {
      expect(readContextFit(bad)).toBeUndefined();
    }
  });

  it("says what the model read in their place", () => {
    expect(contextFitLabel({ dropped: 12, summarized: 12 })).toBe("Older messages read as a summary, to fit the model");
    expect(contextFitLabel({ dropped: 12, summarized: 10 })).toBe(
      "Older messages read as a summary; 2 more left out, to fit the model",
    );
    expect(contextFitLabel({ dropped: 1, summarized: 0 })).toBe("1 older message left out, to fit the model");
    expect(contextFitNote({ dropped: 12, summarized: 0 })).toContain("the 12 oldest were left out");
  });
});
