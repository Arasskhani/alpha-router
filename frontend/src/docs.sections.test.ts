/**
 * The User Manual and the Admin Guide are two large files of sections.
 *
 * A section's title is a plain string, shown as text in the contents list,
 * not JSX: an HTML entity typed into one is shown as typed ("Sessions &amp;
 * folders" was). And every table goes through DocsTable, whose wrapper
 * scrolls it sideways when it is wider than the text, as on a phone.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { docSections } from "./pages/admin/docs/sections";
import { userManualSections } from "./pages/user/docs/sections";

const css = readFileSync(join(__dirname, "styles.css"), "utf8");

describe("the docs", () => {
  it.each([
    ["Admin Guide", docSections],
    ["User Manual", userManualSections],
  ])("%s: no HTML entities in a title", (_name, sections) => {
    expect(sections.length).toBeGreaterThan(10);
    expect(
      sections
        .map((s) => s.title)
        .filter((title) => /&(?:[a-z]+|#\d+|#x[0-9a-f]+);/i.test(title)),
    ).toEqual([]);
  });

  it.each(["pages/admin/docs/sections.tsx", "pages/user/docs/sections.tsx"])(
    "%s: every table is a DocsTable",
    (file) => {
      const text = readFileSync(join(__dirname, file), "utf8");
      expect(text).not.toMatch(/<table\b/);
      expect(text).toMatch(/<DocsTable>/);
    },
  );

  it("scroll a table sideways in its wrapper on a phone, the wrapper carrying the table's margin", () => {
    const wrap = /\n\.docs-table-wrap \{([^}]*)\}/.exec(css)?.[1] ?? "";
    expect(wrap).toContain("margin: 1rem 0");
    // On a desktop the wrapper must not scroll: the header sticks to the scrolling text.
    expect(wrap).not.toContain("overflow");
    expect(
      /\n {2}\.docs-table-wrap \{([^}]*)\}/.exec(
        css.slice(css.lastIndexOf("@media (max-width: 768px)")),
      )?.[1],
    ).toContain("overflow-x: auto");
    expect(
      /\n\.docs-table-wrap > \.docs-table \{([^}]*)\}/.exec(css)?.[1],
    ).toContain("margin: 0");
  });
});
