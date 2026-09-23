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
    expect(layout).toContain("height: var(--app-viewport-height, 100dvh)");
    expect(layout).toContain("max-height: var(--app-viewport-height, 100dvh)");
  });

  it("keeps the bottom tab bar in the layout's flow, so the composer ends above it", () => {
    const bar = declarations(phone.body, ".bottom-tab-bar");
    expect(bar).toContain("flex-shrink: 0");
    expect(bar).not.toContain("position: fixed");
    expect(bar).toContain("env(safe-area-inset-bottom");
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
