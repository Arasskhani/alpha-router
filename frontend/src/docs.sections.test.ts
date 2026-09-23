/**
 * A docs section's title is a plain string, shown as text in the contents
 * list, not JSX: an HTML entity typed into one is shown as typed. Ten titles
 * read "Sessions &amp; folders" and the like.
 */
import { describe, expect, it } from "vitest";

import { docSections } from "./pages/admin/docs/sections";
import { userManualSections } from "./pages/user/docs/sections";

describe("docs section titles", () => {
  it.each([
    ["Admin Guide", docSections],
    ["User Manual", userManualSections],
  ])("%s: no HTML entities in a title", (_name, sections) => {
    expect(sections.length).toBeGreaterThan(10);
    expect(
      sections
        .map((s) => s.title)
        .filter((title) => /&(?:[a-z]+|#\d+);/i.test(title)),
    ).toEqual([]);
  });
});
