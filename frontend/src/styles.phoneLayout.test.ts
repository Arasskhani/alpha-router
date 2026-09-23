/**
 * The phone layout lives in a block at the end of styles.css, and it must.
 *
 * An earlier attempt put "make the chat history full width on a phone" in a
 * media query near the top of the file. The base `.alpha-router-sidebar` rule
 * came later, had the same specificity, and won on source order: on a phone
 * the history still took 260 of 390 pixels and the chat was squeezed into
 * the rest, and nothing said so. This test reads the cascade.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { PHONE_QUERY } from "./hooks/useMediaQuery";

const css = readFileSync(join(__dirname, "styles.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

/** The body of the first `@media <query> {…}` block starting at or after `from`. */
function mediaBlock(query: string, from = 0): { at: number; body: string } | null {
  const at = css.indexOf(`@media ${query}`, from);
  if (at < 0) return null;
  const open = css.indexOf("{", at);
  let depth = 0;
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === "{") depth += 1;
    else if (css[i] === "}") {
      depth -= 1;
      if (depth === 0) return { at, body: css.slice(open + 1, i) };
    }
  }
  return null;
}

/** Every `@media <query>` block in the file. */
function mediaBlocks(query: string): Array<{ at: number; body: string }> {
  const found: Array<{ at: number; body: string }> = [];
  let from = 0;
  for (;;) {
    const block = mediaBlock(query, from);
    if (!block) return found;
    found.push(block);
    from = block.at + 1;
  }
}

/** The declarations of every rule whose selector list is exactly `selector`, inside `scope`. */
function declarations(scope: string, selector: string): string | null {
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let found: string | null = null;
  let m: RegExpExecArray | null;
  while ((m = re.exec(scope))) {
    if (m[1].trim() === selector) found = (found ?? "") + m[2];
  }
  return found;
}

function lastTopLevelRule(selector: string): number {
  // Top level: not inside any @media block. Strip the blocks, remembering offsets.
  let depth = 0;
  let inMedia = false;
  let last = -1;
  for (let i = 0; i < css.length; i += 1) {
    if (css.startsWith("@media", i) && depth === 0) inMedia = true;
    if (css[i] === "{") depth += 1;
    if (css[i] === "}") {
      depth -= 1;
      if (depth === 0) inMedia = false;
    }
    if (!inMedia && depth === 0 && css.startsWith(`${selector} {`, i)) last = i;
  }
  return last;
}

describe("the phone layout block", () => {
  // Older 768px blocks exist for single components; the shell's is the last one.
  const blocks = mediaBlocks(PHONE_QUERY);
  const phone = blocks[blocks.length - 1];

  it("uses the same query as usePhoneLayout and holds the drawers", () => {
    expect(PHONE_QUERY).toBe("(max-width: 768px)");
    expect(phone.body).toContain(".sidebar--drawer");
    expect(blocks.filter((b) => b.body.includes(".sidebar--drawer"))).toHaveLength(1);
  });

  it("comes after the base rules it overrides", () => {
    expect(phone.at).toBeGreaterThan(lastTopLevelRule(".alpha-router-sidebar"));
    expect(phone.at).toBeGreaterThan(lastTopLevelRule(".sidebar"));
    expect(phone.at).toBeGreaterThan(lastTopLevelRule(".layout--chat"));
    // The old, dead attempt is gone: no chat-history rule in the 640px block.
    for (const block of mediaBlocks("(max-width: 640px)")) {
      expect(block.body).not.toContain(".alpha-router-sidebar");
    }
  });

  it("turns both side panels into hidden drawers that the open state shows", () => {
    const body = phone.body;
    for (const selector of [".layout .sidebar.sidebar--drawer", ".alpha-router-sidebar.alpha-router-sidebar--drawer"]) {
      const closed = declarations(body, selector);
      expect(closed, selector).not.toBeNull();
      expect(closed).toContain("position: fixed");
      expect(closed).toContain("visibility: hidden");
      expect(closed).toContain("translateX(var(--drawer-hidden))");
      // As tall as what can be seen below the topbar: the iOS keyboard does not hide its end.
      expect(closed).toContain("height: calc(var(--app-viewport-height) - var(--app-topbar-height))");
      expect(closed).not.toMatch(/(^|[\s;])bottom: 0/);
      const open = declarations(body, `${selector}.is-open`);
      expect(open, `${selector}.is-open`).not.toBeNull();
      expect(open).toContain("visibility: visible");
      expect(open).toContain("transform: none");
    }
  });

  it("hides the desktop-only chrome and the hover rail", () => {
    const body = phone.body;
    expect(declarations(body, ".topbar-shortcuts")).toContain("display: none");
    expect(declarations(body, ".sidebar-peek-rail")).toContain("display: none");
    expect(declarations(body, ".topbar-menu-btn")).toContain("display: inline-flex");
    // The menu button exists only on a phone; the base rule keeps it out of a desktop.
    expect(declarations(css, ".topbar-menu-btn")).toContain("display: none");
  });

  it("lets tables in replies scroll rather than break numbers and words", () => {
    const table = declarations(phone.body, ".markdown-body table");
    expect(table).toContain("display: block");
    expect(table).toContain("overflow-x: auto");
    const cells = declarations(phone.body, ".markdown-body th,\n  .markdown-body td");
    expect(cells).toContain("word-break: normal");
    expect(cells).toContain("overflow-wrap: normal");
  });

  it("sizes the chat controls for a thumb and keeps iOS from zooming into fields", () => {
    expect(declarations(phone.body, ".alpha-router-msg-actions .alpha-router-msg-action-btn")).toContain(
      "min-height: 2.25rem",
    );
    expect(declarations(phone.body, ".alpha-router-composer-bar .alpha-router-composer-ctrl")).toContain(
      "min-height: 2.5rem",
    );
    expect(declarations(phone.body, ".alpha-router-composer-bar .alpha-router-send")).toContain("height: 2.5rem");
    const fields = declarations(
      phone.body,
      '.alpha-router-composer .alpha-router-composer-input,\n  .alpha-router-sidebar .alpha-router-history-search,\n  .alpha-router-model-modal input[type="search"]',
    );
    expect(fields).toContain("font-size: 16px");
  });

  it("sizes the app to the visual viewport, so the iOS keyboard cannot cover the composer", () => {
    const layout = declarations(phone.body, ".layout,\n  .layout--chat");
    expect(layout).toContain("height: var(--app-viewport-height)");
    expect(layout).toContain("max-height: var(--app-viewport-height)");
    // Without the hook (no visual viewport, or a desktop) the token is 100dvh.
    expect(declarations(css, ":root")).toContain("--app-viewport-height: 100dvh");
  });

  it("keeps the bottom tab bar in the layout's flow, so the composer ends above it", () => {
    const bar = declarations(phone.body, ".bottom-tab-bar");
    expect(bar).toContain("flex-shrink: 0");
    expect(bar).not.toContain("position: fixed");
    expect(bar).toContain("env(safe-area-inset-bottom");
    // The sheet "More" opens is modal: above the topbar, so the menu button is covered too.
    const topbar = Number(/z-index:\s*(\d+)/.exec(declarations(css, ".app-topbar") ?? "")?.[1]);
    const sheetZ = Number(/z-index:\s*(\d+)/.exec(declarations(phone.body, ".bottom-sheet-backdrop") ?? "")?.[1]);
    expect(topbar).toBeGreaterThan(0);
    expect(sheetZ).toBeGreaterThan(topbar);
  });

  it("keeps the project tabs in one strip that scrolls, not two rows", () => {
    const strip = declarations(phone.body, ".project-tabs");
    expect(strip).toContain("flex-wrap: nowrap");
    expect(strip).toContain("overflow-x: auto");
    expect(declarations(phone.body, ".project-tab")).toContain("white-space: nowrap");
    // The base rule wraps; the phone rule must come after it to win.
    expect(phone.at).toBeGreaterThan(lastTopLevelRule(".project-tabs"));
  });

  it("presents dialogs as sheets from the bottom edge, above the iOS keyboard", () => {
    const overlay = declarations(phone.body, ".modal-overlay");
    expect(overlay).toContain("align-items: flex-end");
    // As tall as what can be seen, so a sheet with a field is not behind the keyboard.
    expect(overlay).toContain("height: var(--app-viewport-height)");
    expect(overlay).toContain("padding: 0");
    const panel = declarations(phone.body, ".modal-overlay .modal-panel");
    expect(panel).toContain("width: 100%");
    expect(panel).toContain("max-height: calc(var(--app-viewport-height) - 1.5rem)");
    expect(panel).toContain("border-radius: 14px 14px 0 0");
    expect(panel).toContain("env(safe-area-inset-bottom");
    expect(declarations(phone.body, ".modal-overlay .modal-body")).toContain("overflow-y: auto");
    // Bodies that scroll an inner list keep doing it alone.
    expect(
      declarations(
        phone.body,
        ".modal-overlay .modal-body.modal-body--settings,\n  .modal-overlay .modal-body.modal-body--move-folder",
      ),
    ).toContain("overflow: hidden");
    expect(
      declarations(phone.body, ".modal-overlay .modal-actions:last-child,\n  .modal-overlay .dialog-actions:last-child"),
    ).toContain("position: sticky");
    const viewer = declarations(phone.body, ".modal-overlay .modal-panel.modal-panel--media-viewer");
    expect(viewer).toContain("height: var(--app-viewport-height)");
    expect(viewer).toContain("border-radius: 0");
    // The slide-in is skipped for people who asked for less motion.
    const reduced = mediaBlocks("(prefers-reduced-motion: reduce)");
    expect(
      reduced.some((b) =>
        (declarations(b.body, ".modal-overlay .modal-panel,\n  .action-sheet") ?? "").includes("animation: none"),
      ),
    ).toBe(true);
  });

  it("keeps tab lists and filter chips in one line that scrolls", () => {
    const strips = ".tabs,\n  .agent-filter-tabs,\n  .models-filter-bar,\n  .settings-nav";
    const rule = declarations(phone.body, strips);
    expect(rule).toContain("flex-wrap: nowrap");
    expect(rule).toContain("overflow-x: auto");
    expect(
      declarations(phone.body, ".tabs > *,\n  .agent-filter-tabs > *,\n  .models-filter-bar > *,\n  .settings-nav > *"),
    ).toContain("flex-shrink: 0");
    // The base rules wrap; the phone rules must come after them to win.
    for (const selector of [".tabs", ".agent-filter-tabs", ".models-filter-bar", ".settings-nav"]) {
      expect(phone.at, selector).toBeGreaterThan(lastTopLevelRule(selector));
    }
    // A checkbox group is not a strip: every option stays visible.
    expect(phone.body).not.toContain(".memory-admin__chips");
  });

  it("folds list filters behind a button without changing the page's layout when open", () => {
    expect(declarations(phone.body, ".filter-panel:not([hidden])")).toContain("display: contents");
    // Nothing may set `display` on the wrapper itself, or `hidden` would stop hiding it.
    expect(declarations(css, ".filter-panel")).toBeNull();
    expect(declarations(phone.body, ".filter-panel")).toBeNull();
    expect(declarations(phone.body, ".filter-panel-toggle")).toContain("min-height: 2.5rem");
  });

  it("draws the list tables as cards and keeps log tables scrolling with the first column in place", () => {
    const table = declarations(phone.body, ".data-table.data-table--cards");
    expect(table).toContain("display: block");
    // The header row is hidden from sight only; screen readers still get it.
    expect(declarations(phone.body, ".data-table.data-table--cards th")).toContain("clip-path: inset(50%)");
    // Its select-all box stays in sight, as a "Select all" bar above the cards.
    const selectAll = declarations(phone.body, '.data-table.data-table--cards th[data-card-role="select"]');
    expect(selectAll).toContain("clip-path: none");
    expect(selectAll).toContain("position: static");
    expect(declarations(phone.body, '.data-table.data-table--cards th[data-card-role="select"]::after')).toContain(
      'content: "Select all"',
    );
    expect(declarations(phone.body, ".data-table.data-table--cards tr")).toContain("border-radius: var(--radius)");
    const cell = declarations(phone.body, ".data-table.data-table--cards td");
    expect(cell).toContain("display: flex");
    // Card cells win over the column widths of fixed-layout tables (Users sets 11%, 18%…).
    expect(cell).toContain("width: auto");
    expect(declarations(phone.body, ".data-table.data-table--cards td::before")).toContain("content: attr(data-label)");
    expect(declarations(phone.body, '.data-table.data-table--cards td[data-card-role="actions"]')).toContain(
      "position: absolute",
    );
    const hidden = declarations(
      phone.body,
      ".data-table.data-table--cards td.col-lg,\n  .data-table.data-table--cards td.col-xl,\n  .users-table.data-table--cards td.users-table__department,\n  .users-table.data-table--cards td.users-table__office,\n  .users-table.data-table--cards td.users-table__job-title,\n  .users-table.data-table--cards td.users-table__auth,\n  .users-table.data-table--cards td.col-budget",
    );
    expect(hidden).toContain("display: none");
    const sticky = declarations(
      phone.body,
      ".table-wrap--api-logs .data-table--api-logs th:first-child,\n  .table-wrap--api-logs .data-table--api-logs td:first-child:not([colspan]),\n  .data-table--sticky-first th:first-child,\n  .data-table--sticky-first td:first-child:not([colspan])",
    );
    expect(sticky).toContain("position: sticky");
    expect(sticky).toContain("background: var(--surface)");
    // Project Usage and Database scroll sideways in a wrapper that only a phone
    // makes a scroll container: on a desktop their sticky header sticks to the page.
    const wrap = ".table-wrap.table-wrap--phone-scroll";
    expect(declarations(phone.body, wrap)).toContain("overflow-x: auto");
    const desktopWrap = declarations(css.slice(0, phone.at), wrap);
    expect(desktopWrap).toContain("overflow: visible");
    expect(desktopWrap).toContain("margin-bottom: 0");
    // The corner sits above the other header cells, which are sticky at z-index 1.
    expect(
      declarations(phone.body, ".table-wrap--api-logs .data-table--api-logs th:first-child,\n  .data-table--sticky-first th:first-child"),
    ).toContain("z-index: 2");
  });

  it("turns row actions into an action sheet above the drawers", () => {
    const sheet = declarations(phone.body, ".action-sheet");
    expect(sheet).toContain("position: fixed");
    expect(sheet).toContain("bottom: 0");
    expect(sheet).toContain("env(safe-area-inset-bottom");
    // Above the topbar (150) and the drawers, like the popover it replaces.
    const z = Number(/z-index:\s*(\d+)/.exec(declarations(phone.body, ".action-sheet-backdrop") ?? "")?.[1]);
    expect(z).toBeGreaterThanOrEqual(1200);
    expect(declarations(phone.body, ".action-sheet__item,\n  .action-sheet__cancel")).toContain("min-height: 3rem");
  });

  it("hides keyboard hints where there is no keyboard", () => {
    const coarse = mediaBlocks("(pointer: coarse)");
    expect(
      coarse.some((b) =>
        (declarations(b.body, ".alpha-router-kbd,\n  .alpha-router-model-modal__key-hint") ?? "").includes(
          "display: none",
        ),
      ),
    ).toBe(true);
  });

  it("flips the hidden side for right-to-left pages", () => {
    expect(declarations(css, '[dir="rtl"]')).toContain("--drawer-hidden: 100%");
    expect(declarations(css, ":root")).toContain("--drawer-hidden: -100%");
  });
});
