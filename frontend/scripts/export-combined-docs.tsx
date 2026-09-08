import { createElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { docSections } from "../src/pages/admin/docs/sections.tsx";
import { userManualSections } from "../src/pages/user/docs/sections.tsx";

type Section = { id: string; title: string; group?: string; content: ReactNode };

const here = dirname(fileURLToPath(import.meta.url));
const frontendRoot = join(here, "..");
const repoRoot = join(frontendRoot, "..");
const outPath = join(repoRoot, "alpharouter-docs.html");

function extractDocsCss(css: string): string {
  const start = css.indexOf(".docs-shell {");
  const end = css.indexOf("/* Provider brand marks next to model names */");
  if (start < 0 || end < 0 || end <= start) {
    throw new Error("Could not extract docs CSS from styles.css");
  }
  return css.slice(start, end).trim();
}

function extractRootVars(css: string): string {
  const start = css.indexOf(":root {");
  const end = css.indexOf("}", start);
  if (start < 0 || end < 0) return "";
  return css.slice(start, end + 1);
}

function groupSections(sections: Section[]): Array<[string, Section[]]> {
  const map = new Map<string, Section[]>();
  for (const s of sections) {
    const g = s.group ?? "Guide";
    const list = map.get(g) ?? [];
    list.push(s);
    map.set(g, list);
  }
  return [...map.entries()];
}

function rewriteLinks(html: string, prefix: string, ids: Set<string>, other: { prefix: string; ids: Set<string> }): string {
  let out = html.replace(/href="\/admin\/docs#([^"]+)"/g, (_m, id) => `href="#ag-${id}"`);
  out = out.replace(/href="\/app\/manual#([^"]+)"/g, (_m, id) => `href="#um-${id}"`);
  out = out.replace(/href="\/admin\/manual#([^"]+)"/g, (_m, id) => `href="#um-${id}"`);
  out = out.replace(/href="\/admin\/docs"/g, 'href="#ag-introduction"');
  out = out.replace(/href="\/app\/manual"/g, 'href="#um-introduction"');
  out = out.replace(/href="\/admin\/manual"/g, 'href="#um-introduction"');
  out = out.replace(/href="#([^"]+)"/g, (m, id) => {
    if (id.startsWith("ag-") || id.startsWith("um-") || id.startsWith("book-")) return m;
    if (ids.has(id)) return `href="#${prefix}${id}"`;
    if (other.ids.has(id)) return `href="#${other.prefix}${id}"`;
    return m;
  });
  return out;
}

function renderBook(prefix: string, title: string, sections: Section[], other: { prefix: string; ids: Set<string> }): string {
  const ids = new Set(sections.map((s) => s.id));
  const groups = groupSections(sections);
  const nav = groups
    .map(
      ([group, items]) => `
        <div class="docs-nav-group">
          <div class="docs-nav-group-title">${escapeHtml(group)}</div>
          ${items
            .map(
              (item) =>
                `<a class="docs-nav-link" href="#${prefix}${escapeHtml(item.id)}">${escapeHtml(item.title)}</a>`,
            )
            .join("\n")}
        </div>`,
    )
    .join("\n");
  const body = sections
    .map((s) => {
      const inner = renderToStaticMarkup(createElement("div", null, s.content));
      const rewritten = rewriteLinks(inner, prefix, ids, other);
      return `<section class="docs-section" id="${prefix}${escapeHtml(s.id)}" data-title="${escapeHtml(s.title)}" data-group="${escapeHtml(s.group ?? "Guide")}">${rewritten}</section>`;
    })
    .join("\n");
  return `
    <section class="book" id="book-${prefix.replace(/-$/, "")}">
      <div class="docs-shell">
        <aside class="docs-sidebar">
          <div class="docs-sidebar-head">
            <span class="docs-sidebar-label">${escapeHtml(title)}</span>
          </div>
          <nav class="docs-nav">${nav}</nav>
        </aside>
        <div class="docs-main">${body}</div>
      </div>
    </section>`;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const stylesCss = readFileSync(join(frontendRoot, "src/styles.css"), "utf8");
const rootVars = extractRootVars(stylesCss);
const docsCss = extractDocsCss(stylesCss);

const adminIds = new Set(docSections.map((s) => s.id));
const userIds = new Set(userManualSections.map((s) => s.id));

const adminHtml = renderBook("ag-", "Admin Guide", docSections, { prefix: "um-", ids: userIds });
const userHtml = renderBook("um-", "User Manual", userManualSections, { prefix: "ag-", ids: adminIds });

const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Alpharouter — Admin Guide &amp; User Manual</title>
  <style>
    ${rootVars}
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; }
    body {
      font-family: Inter, Segoe UI, system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    a { color: var(--accent); }
    ${docsCss}
    .export-top {
      position: sticky;
      top: 0;
      z-index: 20;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.75rem 1rem;
      padding: 0.75rem 1rem;
      border-bottom: 1px solid var(--border);
      background: var(--surface);
    }
    .export-top h1 {
      margin: 0;
      font-size: 1.05rem;
      font-weight: 700;
    }
    .export-top nav { display: flex; gap: 0.5rem; flex-wrap: wrap; }
    .export-top a {
      text-decoration: none;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.35rem 0.65rem;
      color: var(--text);
      background: var(--bg);
      font-size: 0.85rem;
    }
    .export-top input {
      margin-left: auto;
      min-width: 16rem;
      padding: 0.45rem 0.7rem;
      border: 1px solid var(--border);
      border-radius: 8px;
      font: inherit;
      font-size: 0.875rem;
      background: var(--bg);
      color: var(--text);
    }
    .book { border-bottom: 8px solid var(--border); }
    .book .docs-shell { min-height: 70vh; }
    .docs-section[hidden] { display: none; }
    @media print {
      .export-top, .docs-sidebar { display: none !important; }
      .docs-shell { display: block; }
      .docs-main { overflow: visible; padding: 0; }
      .book { border: none; }
    }
    @media (max-width: 900px) {
      .docs-shell { flex-direction: column; }
      .docs-sidebar { width: 100%; max-height: 14rem; }
    }
  </style>
</head>
<body>
  <header class="export-top">
    <h1>Alpharouter documentation</h1>
    <nav>
      <a href="#book-ag">Admin Guide</a>
      <a href="#book-um">User Manual</a>
    </nav>
    <input id="doc-search" type="search" placeholder="Search titles…" />
  </header>
  ${adminHtml}
  ${userHtml}
  <script>
    const input = document.getElementById("doc-search");
    input.addEventListener("input", () => {
      const q = input.value.trim().toLowerCase();
      document.querySelectorAll(".docs-section").forEach((el) => {
        if (!q) { el.hidden = false; return; }
        const hay = ((el.dataset.title || "") + " " + (el.dataset.group || "") + " " + el.textContent).toLowerCase();
        el.hidden = !hay.includes(q);
      });
    });
  </script>
</body>
</html>
`;

writeFileSync(outPath, html, "utf8");
console.log(`Wrote ${outPath}`);
console.log(`Admin sections: ${docSections.length}; User sections: ${userManualSections.length}`);
