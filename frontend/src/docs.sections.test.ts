/**
 * The User Manual and the Admin Guide are two large files of sections.
 *
 * A section's title is a plain string, shown as text in the contents list,
 * not JSX: an HTML entity typed into one is shown as typed ("Sessions &amp;
 * folders" was). And every table goes through DocsTable, whose wrapper
 * scrolls it sideways when it is wider than the text, as on a phone.
 *
 * A link from one section to another must find it. And what the guides say
 * about the browser extension is held to the code where a number is involved:
 * a limit changed in one place and not the other would leave the guide wrong.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { createElement, Fragment } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { docSections } from "./pages/admin/docs/sections";
import { userManualSections } from "./pages/user/docs/sections";

const css = readFileSync(join(__dirname, "styles.css"), "utf8");

type Section = { id: string; title: string; group?: string; content: unknown };

function sectionHtml(sections: Section[], id: string): string {
  const section = sections.find((s) => s.id === id);
  if (!section) throw new Error(`No section ${id}`);
  return renderToStaticMarkup(
    createElement(Fragment, null, section.content as never),
  );
}

/** The number a source file gives a constant, e.g. `const MAX_STEPS = 100;`. */
function constantIn(file: string, name: string): number {
  const text = readFileSync(join(__dirname, "..", file), "utf8");
  const match = new RegExp(`const ${name} = (\\d+);`).exec(text);
  if (!match) throw new Error(`${name} not found in ${file}`);
  return Number(match[1]);
}

const WORDS: Record<number, string> = { 3: "three", 4: "four" };

const EXTENSION_GUIDE = [
  "extension-install",
  "extension-connect",
  "extension-chat",
  "extension-agent",
];

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

  it.each([
    ["Admin Guide", docSections],
    ["User Manual", userManualSections],
  ])("%s: every link to a section finds it", (_name, sections) => {
    const ids = new Set(sections.map((s) => s.id));
    const broken = sections.flatMap((s) =>
      Array.from(
        sectionHtml(sections, s.id).matchAll(/href="#([^"]+)"/g),
        (m) => m[1],
      )
        .filter((target) => !ids.has(target))
        .map((target) => `${s.id} → #${target}`),
    );
    expect(broken).toEqual([]);
  });

  it("the User Manual explains the browser extension, and Settings points to it", () => {
    for (const id of EXTENSION_GUIDE) {
      expect(userManualSections.find((s) => s.id === id)?.group).toBe(
        "Browser extension",
      );
    }
    const settings = userManualSections.find((s) =>
      /<h3>Extension<\/h3>/.test(sectionHtml(userManualSections, s.id)),
    );
    expect(settings && sectionHtml(userManualSections, settings.id)).toContain(
      'href="#extension-install"',
    );
  });

  it("the User Manual's numbers are the extension's", () => {
    const chat = sectionHtml(userManualSections, "extension-chat");
    expect(chat).toContain(
      `Up to ${WORDS[constantIn("extension/src/panel/otherTabs.ts", "MAX_OTHER_TABS")]} other tabs`,
    );
    const agent = sectionHtml(userManualSections, "extension-agent");
    expect(agent).toContain(
      `after ${WORDS[constantIn("extension/src/panel/agentRun.ts", "MAX_ERRORS_IN_A_ROW")]} failed steps`,
    );
  });

  it("the Admin Guide says what an administrator decides about the extension", () => {
    const html = sectionHtml(docSections, "admin-browser-extension");
    for (const term of [
      "Browser Extension",
      "Browser Agent",
      "FRONTEND_URL",
      "ExtensionInstallForcelist",
      "/extension/update.xml",
      "DATA_ENCRYPTION_KEY",
      "extension_settings_updated",
      "extension_session_revoked",
      "page_context",
      "agent_step",
      "agent_task",
    ]) {
      expect(html).toContain(term);
    }
    const card = "src/components/admin/ExtensionSettingsCard.tsx";
    expect(html).toContain(
      `${constantIn(card, "MIN_STEPS")} to ${constantIn(card, "MAX_STEPS")}`,
    );
    expect(sectionHtml(docSections, "admin-chat-tools")).toContain(
      'href="#admin-browser-extension"',
    );
  });

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
