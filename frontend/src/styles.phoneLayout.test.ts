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

import { NAV_DRAWER_QUERY, PHONE_QUERY } from "./hooks/useMediaQuery";

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

type Specificity = [number, number, number];

/** Split a selector list at its top-level commas. */
function selectorList(list: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < list.length; i += 1) {
    if (list[i] === "(") depth += 1;
    else if (list[i] === ")") depth -= 1;
    else if (list[i] === "," && depth === 0) {
      out.push(list.slice(start, i).trim());
      start = i + 1;
    }
  }
  out.push(list.slice(start).trim());
  return out;
}

const bySpecificity = (a: Specificity, b: Specificity) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2];

/**
 * [ids, classes, types] of one selector, enough for the rules checked here:
 * :is(), :not() and :has() count as their most specific argument, :where() as
 * nothing, however deeply they nest.
 */
function specificity(selector: string): Specificity {
  const score: Specificity = [0, 0, 0];
  let rest = "";
  for (let i = 0; i < selector.length; ) {
    const fn = /^:(is|not|has|where)\(/.exec(selector.slice(i));
    if (!fn) {
      rest += selector[i];
      i += 1;
      continue;
    }
    // The argument runs to the matching parenthesis.
    const open = i + fn[0].length - 1;
    let close = open;
    for (let depth = 0; close < selector.length; close += 1) {
      if (selector[close] === "(") depth += 1;
      else if (selector[close] === ")" && --depth === 0) break;
    }
    if (fn[1] !== "where") {
      const best = selectorList(selector.slice(open + 1, close))
        .map((arg) => specificity(arg.replace(/^[>+~]\s*/, "")))
        .sort(bySpecificity)
        .pop()!;
      score[0] += best[0];
      score[1] += best[1];
      score[2] += best[2];
    }
    i = close + 1;
  }
  score[0] += (rest.match(/#[\w-]+/g) ?? []).length;
  score[1] += (rest.match(/\.[\w-]+|\[[^\]]*\]|(?<!:):(?!:)[\w-]+/g) ?? []).length;
  score[2] += (rest.match(/(^|[\s>+~])[a-zA-Z][\w-]*|::[\w-]+/g) ?? []).length;
  return score;
}

/** Whether `override` outranks `base` on specificity alone, whatever their order. */
function outranks(override: string, base: string): boolean {
  return bySpecificity(specificity(override), specificity(base)) > 0;
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

  // The navigation drawer serves phones and tablets: its own block, just before the phone block.
  const drawerBlocks = mediaBlocks(NAV_DRAWER_QUERY);
  const drawer = drawerBlocks[drawerBlocks.length - 1];

  it("uses the same queries as the hooks and holds the drawers", () => {
    expect(PHONE_QUERY).toBe("(max-width: 768px)");
    expect(NAV_DRAWER_QUERY).toBe("(max-width: 1024px)");
    // The chat history drawer is a phone's; the navigation drawer a phone's and a tablet's.
    expect(phone.body).toContain(".alpha-router-sidebar--drawer");
    expect(blocks.filter((b) => b.body.includes(".alpha-router-sidebar--drawer"))).toHaveLength(1);
    expect(drawer.body).toContain(".layout .sidebar.sidebar--drawer");
    expect(drawerBlocks.filter((b) => b.body.includes(".sidebar.sidebar--drawer"))).toHaveLength(1);
    expect(phone.body).not.toContain(".layout .sidebar.sidebar--drawer");
  });

  it("puts the drawer block after the base tablet rules and before the phone block", () => {
    // The base 1024px rules stack the navigation above the page; the drawer block must win.
    const stacked = drawerBlocks.find((b) => b.body.includes(".layout:not(.layout--chat) .sidebar {"));
    expect(stacked).toBeDefined();
    expect(drawer.at).toBeGreaterThan(stacked!.at);
    expect(drawer.at).toBeLessThan(phone.at);
    expect(declarations(drawer.body, ".layout:not(.layout--chat) .layout-body")).toContain("flex-direction: row");
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
    for (const [selector, body] of [
      [".layout .sidebar.sidebar--drawer", drawer.body],
      [".alpha-router-sidebar.alpha-router-sidebar--drawer", phone.body],
    ]) {
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
    // The menu button serves the drawer, on tablets too.
    expect(declarations(drawer.body, ".topbar-menu-btn")).toContain("display: inline-flex");
    // The menu button exists only on a phone; the base rule keeps it out of a desktop.
    expect(declarations(css, ".topbar-menu-btn")).toContain("display: none");
  });

  it("gives switches and checkboxes a finger's hit area", () => {
    // A label around a checkbox or radio is its target, and a finger tall…
    const labelled = ':where(label:has(> input:is([type="checkbox"], [type="radio"])))';
    expect(declarations(phone.body, labelled)).toContain("min-height: 2.75rem");
    // …a bare one laid out as a box for that, its text beside the box…
    const bare = ':where(label:not([class], [style]):has(> input:is([type="checkbox"], [type="radio"])))';
    const bareRule = declarations(phone.body, bare);
    expect(bareRule).toContain("display: inline-flex");
    expect(bareRule).toContain("gap: 0.4em");
    // …and at no weight, so a component's own label rules (the memory chips') still win.
    expect(specificity(labelled)).toEqual([0, 0, 0]);
    expect(specificity(bare)).toEqual([0, 0, 0]);
    expect(declarations(css.slice(0, phone.at), ".memory-admin__chips label")).toContain("gap: 0.3rem");
    // Switches and lone boxes get a 44px hit area that draws nothing, centred on a positioned box.
    const area = declarations(
      phone.body,
      ".alpha-router-toggle::before,\n  .media-page-item__check::before,\n  .models-browse-card__check::before",
    );
    expect(area).toContain('content: ""');
    expect(area).toContain("position: absolute");
    expect(area).toContain("width: max(100%, 2.75rem)");
    expect(area).toContain("height: max(100%, 2.75rem)");
    expect(area).toContain("transform: translate(-50%, -50%)");
    expect(area).not.toMatch(/background|border/);
    expect(declarations(phone.body, ".alpha-router-toggle")).toContain("position: relative");
    // A lone box's label does not grow into a 44px chip: the area is its only change.
    expect(declarations(phone.body, ".media-page-item__check,\n  .models-browse-card__check")).toContain("min-height: 0");
    // In the media list views the label is positioned for the area, not moved by the grid's offsets.
    const listViews = declarations(
      phone.body,
      ".models-browse-card__check,\n  .media-page-grid--list .media-page-item__check,\n  .media-page-grid--detail .media-page-item__check,\n  .media-page-grid--title .media-page-item__check",
    );
    expect(listViews).toContain("position: relative");
    expect(listViews).toContain("top: auto");
    expect(listViews).toContain("left: auto");
    expect(outranks(".media-page-grid--list .media-page-item__check", ".media-page-item__check")).toBe(true);
  });

  it("sizes the pickers and text actions that nothing else sizes", () => {
    const own = declarations(
      phone.body,
      ".role-multi-select__trigger,\n  .user-owner-select__item,\n  .settings-row__action,\n  .memory-admin__budget-links a",
    );
    expect(own).toContain("min-height: 2.75rem");
    // A link takes min-height only as a box.
    expect(declarations(phone.body, ".memory-admin__budget-links a")).toContain("display: inline-flex");
    // The models table's on/off button pins 26px in a rule of the same weight; the phone rule comes after it.
    expect(declarations(css.slice(0, phone.at), ".data-table .model-toggle-btn")).toContain("min-height: 26px");
    expect(declarations(phone.body, ".data-table .model-toggle-btn")).toContain("min-height: 2.75rem");
    expect(phone.at).toBeGreaterThan(lastTopLevelRule(".data-table .model-toggle-btn"));
    // "Explore ›" reaches into its card as far as it is padded, so the card's header keeps its height…
    const explore = declarations(phone.body, ".overview-explore-link") ?? "";
    const padding = /(^|[\s;])padding:\s*([\d.]+)rem ([\d.]+)rem/.exec(explore);
    const margin = /(^|[\s;])margin:\s*-([\d.]+)rem -([\d.]+)rem/.exec(explore);
    expect(padding && margin).toBeTruthy();
    expect(margin![2]).toBe(padding![2]);
    expect(margin![3]).toBe(padding![3]);
    // …44px with its 15px line…
    expect(Number(padding![2]) * 2 * 16 + 15).toBeGreaterThanOrEqual(44);
    // …and above the chart under it, which is positioned.
    expect(explore).toContain("position: relative");
    expect(explore).toContain("z-index: 1");
  });

  it("gives the topbar's logo and profile button a finger's size", () => {
    expect(declarations(phone.body, ".app-topbar .topbar-brand")).toContain("min-width: 2.75rem");
    expect(declarations(phone.body, ".app-topbar .user-profile-trigger")).toContain("min-height: 2.75rem");
    // A base rule of the same weight resets the logo's min-width; the phone rule comes after it.
    expect(declarations(css.slice(0, phone.at), ".topbar-left .topbar-brand")).toContain("min-width: auto");
    expect(outranks(".app-topbar .topbar-brand", ".topbar-left .topbar-brand")).toBe(false);
    expect(phone.at).toBeGreaterThan(lastTopLevelRule(".topbar-left .topbar-brand"));
    // The profile button fits in the phone's topbar.
    expect(declarations(phone.body, ":root")).toContain("--app-topbar-height: 48px");
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
    // Room above the toolbar for a 44px tap on the field: the tap strip was 43px.
    expect(declarations(phone.body, ".alpha-router-composer-bar")).toContain("margin-top: 0.625rem");
    // Every text field, not a chosen few: a 13px one in a dialog zoomed the page
    // and left the dialog's buttons behind the keyboard.
    const fields = declarations(
      phone.body,
      'input:not([type="checkbox"], [type="radio"], [type="range"], [type="color"], [type="file"], [type="hidden"], [type="button"], [type="submit"], [type="reset"], [type="image"]),\n  select,\n  textarea',
    );
    expect(fields).toContain("font-size: 16px !important");
    // The plan name drawn over the user plan select matches the select's text.
    expect(declarations(phone.body, ".users-table .user-plan-select-label")).toContain("font-size: 16px");
    expect(phone.at).toBeGreaterThan(lastTopLevelRule(".users-table .user-plan-select-label"));
  });

  it("gives the chat's small controls a 44px hit area, with room for it", () => {
    const rem = (decls: string | null, prop: string) => {
      const m = new RegExp(`(^|[\\s;])${prop}:\\s*(-?[\\d.]+)rem`).exec(decls ?? "");
      return m ? Number(m[2]) : NaN;
    };
    const targets = [
      ".alpha-router-msg-actions .alpha-router-msg-action-btn",
      ".alpha-router-composer-bar .alpha-router-tools-trigger--icon",
      ".alpha-router-composer-bar .alpha-router-agent-ctrl",
      ".alpha-router-composer-bar .alpha-router-attach-btn",
      ".alpha-router-composer-bar .alpha-router-voice-btn",
      ".alpha-router-composer-bar .alpha-router-send",
      ".alpha-router-composer-bar .alpha-router-stop",
      ".app-topbar .topbar-model-search__field",
      ".app-topbar .topbar-model-search__add",
      ".app-topbar .alpha-router-model-pill__remove",
    ];
    expect(declarations(phone.body, targets.join(",\n  "))).toContain("position: relative");
    const area = declarations(phone.body, targets.map((t) => `${t}::before`).join(",\n  "));
    expect(area).toContain('content: ""');
    expect(area).toContain("width: max(100%, 2.75rem)");
    expect(area).toContain("height: max(100%, 2.75rem)");
    // Composer controls clip what spills out of them; the two icon ones given an area do not.
    expect(declarations(css, ".alpha-router-composer-ctrl")).toContain("overflow: hidden");
    expect(declarations(css, ".alpha-router-agent-ctrl")).toContain("overflow: visible");
    expect(
      declarations(
        css,
        ".alpha-router-tools-trigger--icon.alpha-router-composer-ctrl,\n.alpha-router-model-trigger.alpha-router-tools-trigger--icon",
      ),
    ).toContain("overflow: visible");
    // A reply's actions share their gaps: each area reaches halfway across, not into the next button.
    const actionsGap = rem(declarations(phone.body, ".alpha-router-msg-actions"), "gap");
    expect(actionsGap).toBeGreaterThan(0);
    expect(declarations(phone.body, ".alpha-router-msg-actions .alpha-router-msg-action-btn::before")).toContain(
      `width: calc(100% + ${actionsGap}rem)`,
    );
    // The translate chip does clip, so it is 44px tall itself.
    expect(declarations(phone.body, ".alpha-router-composer-bar .alpha-router-translate-eng-btn")).toContain(
      "min-height: 2.75rem",
    );
    // 36px attach and voice buttons 0.5rem apart: their areas meet, and do not overlap.
    const attach = declarations(
      phone.body,
      ".alpha-router-composer-bar .alpha-router-attach-btn,\n  .alpha-router-composer-bar .alpha-router-voice-btn",
    );
    const gap = rem(declarations(phone.body, ".alpha-router-composer-bar .alpha-router-send-group"), "gap");
    expect(gap).toBeGreaterThanOrEqual(2.75 - rem(attach, "width"));
    // The pill row clips; it has room above and below for a remove button's area, taking no space.
    const pills = declarations(phone.body, ".app-topbar .topbar-selected-models");
    expect(rem(pills, "padding-block")).toBeGreaterThanOrEqual((2.75 - 2.25) / 2);
    expect(rem(pills, "margin-block")).toBe(-rem(pills, "padding-block"));
    // The model search's two buttons, at least 36px wide side by side: each one's area reaches away from the other…
    const searchButtons = declarations(
      phone.body,
      ".app-topbar .topbar-model-search__field,\n  .app-topbar .topbar-model-search__add",
    );
    const buttonWidth = rem(searchButtons, "min-width");
    expect(buttonWidth).toBe(2.25);
    expect(rem(declarations(phone.body, ".app-topbar .topbar-model-search__add"), "width")).toBe(buttonWidth);
    // The magnifier grows with its "Search Models" label, which only 640px and under hide.
    const field = declarations(phone.body, ".app-topbar .topbar-model-search__field");
    expect(field).toContain("flex: 0 0 auto");
    expect(field).not.toMatch(/(^|[\s;])width:/);
    expect(
      mediaBlocks("(max-width: 640px)").some((b) =>
        (declarations(b.body, ".topbar-model-search__field > span") ?? "").includes("display: none"),
      ),
    ).toBe(true);
    const fieldArea = declarations(phone.body, ".app-topbar .topbar-model-search__field::before");
    expect(fieldArea).toContain("inset-inline-end: 0");
    expect(fieldArea).toContain("transform: translateY(-50%)");
    expect(declarations(phone.body, ".app-topbar .topbar-model-search__add::before")).toContain("inset-inline-start: 0");
    // …no further than the space kept on each side: from the logo, and from the model pills.
    const pill = declarations(phone.body, ".app-topbar .topbar-model-search");
    const leftGap = rem(declarations(phone.body, ".topbar-left,\n  .topbar-left:has(.topbar-model-search)"), "gap");
    expect(rem(pill, "margin-inline") + leftGap).toBeCloseTo(2.75 - buttonWidth, 5);
    expect(outranks(".app-topbar .topbar-model-search", ".topbar-model-search")).toBe(true);
    // A model's remove area reaches back into the gap before it, not over the model's name.
    const removeArea = declarations(phone.body, ".app-topbar .alpha-router-model-pill__remove::before");
    const reachBack = -rem(removeArea, "inset-inline-start");
    expect(reachBack).toBeGreaterThan(0);
    expect(reachBack).toBeLessThan(rem(declarations(css, ".alpha-router-model-pill"), "gap"));
    // A code block's actions and the model picker's rows.
    expect(declarations(phone.body, ".alpha-router-code-block__action")).toContain("min-height: 2.75rem");
    expect(declarations(phone.body, ".alpha-router-code-block__toolbar")).toContain("padding-block: 0");
    expect(declarations(phone.body, ".alpha-router-model-modal__item")).toContain("min-height: 2.75rem");
  });

  it("keeps the topbar's model pills on one line, each over the remove area of the one before", () => {
    // The generic rule wraps; the topbar's one line must outrank it, not merely come first.
    expect(declarations(css, ".alpha-router-selected-models")).toContain("flex-wrap: wrap");
    const oneLine = ".alpha-router-selected-models.topbar-selected-models";
    expect(declarations(css, oneLine)).toContain("flex-wrap: nowrap");
    expect(outranks(oneLine, ".alpha-router-selected-models")).toBe(true);
    // Pills that do not fit scroll sideways rather than being cut off; Tab brings a half-hidden remove button wholly in.
    expect(declarations(css, oneLine)).toContain("overflow-x: auto");
    expect(declarations(css, oneLine)).toContain("overflow-y: hidden");
    expect(declarations(css, oneLine)).toContain("scroll-padding-inline: 1.5rem");
    expect(declarations(css, `${oneLine}.is-drag-scrolling`)).toContain("cursor: grabbing");
    // The last remove area stops at its pill: past it, it gave a row that fits something to scroll to.
    expect(declarations(phone.body, ".app-topbar .topbar-selected-models .alpha-router-model-pill:last-child")).toContain(
      "overflow-x: clip",
    );
    // A pill shrinks by its name only: its fixed parts (padding, border, icon, gaps, remove button) stay inside.
    expect(declarations(css, ".topbar-selected-models .alpha-router-model-pill")).toContain("min-width: 3.375rem");
    // On a narrow phone, with two or more models, a pill is its icon and its remove button.
    const crowded = ".app-topbar .topbar-selected-models:has(> .alpha-router-model-pill + .alpha-router-model-pill)";
    expect(declarations(phone.body, `${crowded} .alpha-router-model-pill__name`)).toContain("display: none");
    expect(declarations(phone.body, `${crowded} .alpha-router-model-pill`)).toContain("min-width: auto");
    expect(outranks(`${crowded} .alpha-router-model-pill`, ".topbar-selected-models .alpha-router-model-pill")).toBe(true);
    // Positioned pills paint in order: a pill takes its own taps from the remove area reaching out of the one before.
    expect(declarations(phone.body, ".app-topbar .topbar-selected-models .alpha-router-model-pill")).toContain(
      "position: relative",
    );
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
    const actions = declarations(
      phone.body,
      ".modal-overlay .modal-actions:last-child,\n  .modal-overlay .dialog-actions:last-child",
    );
    expect(actions).toContain("position: sticky");
    // The strip of body padding under the stuck buttons is filled, so the form does not show through it.
    expect(actions).toContain("box-shadow: 0 1.25rem 0 var(--surface)");
    expect(
      declarations(phone.body, ".modal-overlay .modal-body:has(.modal-actions:last-child, .dialog-actions:last-child)"),
    ).toContain("scroll-padding-bottom");
    // The close button reaches into the header's padding on its end side, whichever side that is.
    const close = declarations(phone.body, ".modal-overlay .modal-close");
    expect(close).toContain("margin-inline: 0 -0.6rem");
    expect(close).not.toMatch(/(^|[\s;])margin:/);
    const viewer = declarations(phone.body, ".modal-overlay .modal-panel.modal-panel--media-viewer");
    expect(viewer).toContain("height: var(--app-viewport-height)");
    expect(viewer).toContain("border-radius: 0");
    // The slide-in is skipped for people who asked for less motion.
    const reduced = mediaBlocks("(prefers-reduced-motion: reduce)");
    expect(
      reduced.some((b) =>
        (declarations(b.body, ".modal-overlay .modal-panel,\n  .action-sheet,\n  .role-multi-select__menu--sheet") ?? "").includes(
          "animation: none",
        ),
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

  it("makes tabs, filter chips and segments a finger tall", () => {
    const strip =
      ".tab,\n  .agent-filter-tabs > button,\n  .settings-nav-item,\n  .models-filter-chip,\n  .activity-tabs__btn,\n  .activity-segmented__btn";
    expect(declarations(phone.body, strip)).toContain("min-height: 2.75rem");
    const icons = declarations(phone.body, ".models-view-toggle__btn,\n  .theme-segment__btn");
    expect(icons).toContain("min-width: 2.75rem");
    expect(icons).toContain("min-height: 2.75rem");
    expect(declarations(phone.body, ".project-tab")).toContain("min-height: 2.75rem");
    // Base rules with the same weight set smaller sizes; the phone rules come after them.
    expect(declarations(css.slice(0, phone.at), ".agent-filter-tabs > button")).toContain("min-height: 2rem");
    expect(declarations(css.slice(0, phone.at), ".theme-segment__btn")).toContain("min-height: 30px");
    for (const selector of [".agent-filter-tabs > button", ".theme-segment__btn", ".project-tab"]) {
      expect(phone.at, selector).toBeGreaterThan(lastTopLevelRule(selector));
    }
  });

  it("folds list filters behind a button without changing the page's layout when open", () => {
    // The wrapper is there at every width (the fields must not be remounted
    // when the width crosses the breakpoint), so its rule is a base rule.
    expect(declarations(css.slice(0, phone.at), ".filter-panel:not([hidden])")).toContain("display: contents");
    // Nothing may set `display` on the wrapper itself, or `hidden` would stop hiding it.
    expect(declarations(css, ".filter-panel")).toBeNull();
    expect(declarations(phone.body, ".filter-panel")).toBeNull();
    // As tall as a button: in the Media filter row the toggle lines up with Refresh.
    expect(declarations(phone.body, ".filter-panel-toggle")).toContain("min-height: 2.75rem");
    expect(declarations(phone.body, ".media-page-filters > .filter-panel-toggle")).toContain("margin-bottom: 0");
  });

  it("makes the buttons, fields and selects the size tokens reach 44px tall", () => {
    const root = declarations(phone.body, ":root");
    expect(root).toContain("--control-height: 2.75rem");
    expect(root).toContain("--control-height-sm: 2.75rem");
    // A desktop keeps its mouse sizes.
    const desktopRoot = declarations(css.slice(0, phone.at), ":root");
    expect(desktopRoot).toContain("--control-height: 32px");
    expect(desktopRoot).toContain("--control-height-sm: 28px");
    // The controls take their height from the tokens, the small and the admin ones too.
    expect(declarations(css, ".btn")).toContain("min-height: var(--control-height)");
    expect(declarations(css, ".btn-sm")).toContain("min-height: var(--control-height-sm)");
    expect(declarations(css, ".admin-page .btn:not(.model-toggle-btn)")).toContain(
      "min-height: var(--control-height-sm)",
    );
    expect(
      declarations(
        css,
        'input:not([type="checkbox"]):not([type="radio"]):not([type="file"]):not([type="range"]):not([type="color"]):not([type="hidden"]),\nselect',
      ),
    ).toContain("min-height: var(--control-height)");
    // No phone rule pins a button smaller again.
    for (const m of phone.body.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      if (!/\.btn\b|\.btn-sm\b|row-actions-trigger/.test(m[1])) continue;
      const pinned = /(^|[\s;])(min-)?height:\s*([\d.]+)rem/.exec(m[2]);
      if (pinned) expect(Number(pinned[3]), m[1].trim()).toBeGreaterThanOrEqual(2.75);
    }
    // A short label ("All", "ON") does not leave a button narrower than it is tall.
    expect(declarations(phone.body, ".btn")).toContain("min-width: var(--control-height)");
    // The settings dialog sets 26px of its own, as specifically; the phone rule comes later.
    expect(declarations(css.slice(0, phone.at), ".modal-panel--settings .btn")).toContain("min-height: 26px");
    expect(declarations(phone.body, ".modal-panel--settings .btn")).toContain("min-height: var(--control-height-sm)");
    expect(phone.at).toBeGreaterThan(lastTopLevelRule(".modal-panel--settings .btn"));
  });

  it("gives a card's Actions button and select box 44px corners, and starts the card's lines below them", () => {
    const rem = (decls: string | null, prop: string) => {
      const m = new RegExp(`(^|[\\s;])${prop}:\\s*([\\d.]+)rem`).exec(decls ?? "");
      return m ? Number(m[2]) : NaN;
    };
    const corner = declarations(phone.body, '.data-table.data-table--cards td[data-card-role="select"]');
    expect(rem(corner, "width")).toBe(2.75);
    expect(rem(corner, "height")).toBe(2.75);
    const trigger = declarations(
      phone.body,
      '.data-table.data-table--cards td[data-card-role="actions"] .row-actions-trigger',
    );
    // Both corners at the same height; the button is 44px tall by the size tokens.
    expect(rem(trigger, "top")).toBe(rem(corner, "top"));
    expect(declarations(css, ".btn-sm")).toContain("min-height: var(--control-height-sm)");
    // The title reaches the corners' bottom: their top + 2.75rem - the card's top padding.
    const titleSelector =
      '.data-table.data-table--cards tr:has(> td[data-card-role="actions"], > td[data-card-role="select"]) > td[data-card-role="title"]';
    const title = declarations(phone.body, titleSelector);
    expect(title).toContain("box-sizing: border-box");
    const cardPadTop = rem(declarations(phone.body, ".data-table.data-table--cards tr"), "padding");
    expect(rem(title, "min-height")).toBeCloseTo(rem(corner, "top") + 2.75 - cardPadTop, 5);
    expect(outranks(titleSelector, ".data-table.data-table--cards tbody td:is(:first-child, :last-child)")).toBe(true);
    expect(outranks(titleSelector, '.data-table.data-table--cards td[data-card-role="title"]')).toBe(true);
    // The lines start after the select corner, not under its edge.
    expect(
      rem(declarations(phone.body, '.data-table.data-table--cards tr:has(> td[data-card-role="select"])'), "padding-inline-start"),
    ).toBeGreaterThanOrEqual(2.75);
  });

  it("counts specificity the way the browser does, for the selectors checked here", () => {
    expect(specificity("table.card tbody td:first-child")).toEqual([0, 2, 3]);
    expect(specificity(".data-table.data-table--cards tbody td:is(:first-child, :last-child)")).toEqual([0, 3, 2]);
    expect(specificity('.a td[data-card-role="title"]::before')).toEqual([0, 2, 2]);
    expect(specificity(".a tr:has(> td[data-x]) > td")).toEqual([0, 2, 3]);
    expect(specificity(":where(.a) b")).toEqual([0, 0, 1]);
    // Nested functions: :where() inside or around the others.
    expect(specificity(':where(label:has(> input:is([type="checkbox"], [type="radio"])))')).toEqual([0, 0, 0]);
    expect(specificity('label:has(> input:is([type="checkbox"], [type="radio"]))')).toEqual([0, 1, 2]);
    expect(specificity(".a:is(.b, :where(.c .d)) e")).toEqual([0, 2, 1]);
  });

  it("gives the card rules enough weight to beat the table rules they replace", () => {
    // Whatever the order: these base rules are more specific than a plain card rule.
    expect(outranks(".data-table.data-table--cards tbody td:is(:first-child, :last-child)", "table.card tbody td:first-child")).toBe(true);
    expect(outranks(".data-table.data-table--cards tbody td:is(:first-child, :last-child)", "table.card tbody td:last-child")).toBe(true);
    const cap = ".data-table.data-table--cards td :is(select, .role-multi-select__trigger, .user-plan-select-wrap)";
    expect(outranks(cap, ".users-table .role-multi-select__trigger")).toBe(true);
    expect(outranks(cap, ".users-table .user-plan-select-wrap")).toBe(true);
    // …and the plan select filling its wrapper outranks the cap.
    expect(outranks(".data-table.data-table--cards td .user-plan-select-wrap select", cap)).toBe(true);
    // The title keeps room for the Actions button over the padding reset.
    expect(
      outranks(
        '.data-table.data-table--cards tr:has(> td[data-card-role="actions"]) > td[data-card-role="title"]',
        ".data-table.data-table--cards tbody td:is(:first-child, :last-child)",
      ),
    ).toBe(true);
  });

  it("draws the list tables as cards and keeps log tables scrolling with the first column in place", () => {
    const table = declarations(phone.body, ".data-table.data-table--cards");
    expect(table).toContain("display: block");
    // The header row is hidden from sight only; screen readers still get it.
    const hiddenHeader = '.data-table.data-table--cards thead th:not([data-card-role="select"])';
    expect(declarations(phone.body, hiddenHeader)).toContain("clip-path: inset(50%)");
    expect(declarations(phone.body, hiddenHeader)).toContain("padding: 0");
    expect(outranks(hiddenHeader, "table.card thead th:first-child")).toBe(true);
    // Its select-all box stays in sight, as a "Select all" bar above the cards.
    const selectAll = declarations(phone.body, '.data-table.data-table--cards th[data-card-role="select"]');
    expect(selectAll).toContain("display: flex");
    expect(selectAll).toContain("position: static");
    expect(declarations(phone.body, '.data-table.data-table--cards th[data-card-role="select"]::after')).toContain(
      'content: "Select all"',
    );
    // An empty list (its message in one spanning cell) has nothing to select, and no bar.
    const emptyBar =
      '.data-table.data-table--cards:not(:has(tbody td[data-card-role="select"])) th[data-card-role="select"]';
    expect(declarations(phone.body, emptyBar)).toContain("display: none");
    expect(outranks(emptyBar, '.data-table.data-table--cards th[data-card-role="select"]')).toBe(true);
    expect(declarations(phone.body, ".data-table.data-table--cards tr")).toContain("border-radius: var(--radius)");
    const cell = declarations(phone.body, ".data-table.data-table--cards td");
    expect(cell).toContain("display: flex");
    // Card cells win over the column widths of fixed-layout tables (Users sets 11%, 18%…).
    expect(cell).toContain("width: auto");
    const label = declarations(phone.body, ".data-table.data-table--cards td::before");
    expect(label).toContain("content: attr(data-label);");
    // Read once: the header already names the cell, so the drawn label has empty alt text.
    expect(label).toContain('content: attr(data-label) / "";');
    // A cell under an empty header has no label to push it to the end of its line.
    expect(declarations(phone.body, '.data-table.data-table--cards td[data-label=""]')).toContain(
      "justify-content: flex-end",
    );
    // table.card pads its first and last cells more specifically; the card wins back.
    expect(declarations(phone.body, ".data-table.data-table--cards tbody td:is(:first-child, :last-child)")).toContain(
      "padding-inline: 0",
    );
    expect(declarations(css.slice(0, phone.at), "table.card thead th:first-child,\ntable.card tbody td:first-child")).toContain(
      "padding-left",
    );
    // The users table's role control is RoleMultiSelect's trigger button, not a select.
    expect(
      declarations(
        phone.body,
        ".data-table.data-table--cards td :is(select, .role-multi-select__trigger, .user-plan-select-wrap)",
      ),
    ).toContain("max-width: 62%");
    // The plan select fills its capped wrapper, so the name drawn over it stays inside its border.
    expect(declarations(phone.body, ".data-table.data-table--cards td .user-plan-select-wrap select")).toContain(
      "width: 100%",
    );
    // The Actions button sits in the card's corner; its cell stays in the flow,
    // so a failed action's message reads under the card instead of over it.
    expect(
      declarations(phone.body, '.data-table.data-table--cards td[data-card-role="actions"] .row-actions-trigger'),
    ).toContain("position: absolute");
    // Static, not the base .data-table .col-actions' relative: the button is placed against the card.
    expect(declarations(phone.body, '.data-table.data-table--cards td[data-card-role="actions"]')).toContain(
      "position: static",
    );
    expect(
      declarations(phone.body, '.data-table.data-table--cards td[data-card-role="actions"] .row-actions'),
    ).toContain("position: static");
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
    expect(sticky).toContain("box-shadow: 1px 0 0 var(--border)");
    // In RTL the first column is on the right, and its divider on its left.
    expect(
      declarations(
        phone.body,
        '[dir="rtl"] .table-wrap--api-logs .data-table--api-logs th:first-child,\n  [dir="rtl"] .table-wrap--api-logs .data-table--api-logs td:first-child:not([colspan]),\n  [dir="rtl"] .data-table--sticky-first th:first-child,\n  [dir="rtl"] .data-table--sticky-first td:first-child:not([colspan])',
      ),
    ).toContain("box-shadow: -1px 0 0 var(--border)");
    // The corner sits above the other header cells, which are sticky at z-index 1.
    expect(
      declarations(phone.body, ".table-wrap--api-logs .data-table--api-logs th:first-child,\n  .data-table--sticky-first th:first-child"),
    ).toContain("z-index: 2");
  });

  it("lays the docs out in one column, the contents in a side sheet above the topbar", () => {
    expect(declarations(phone.body, ".docs-shell")).toContain("flex-direction: column");
    const sheet = declarations(phone.body, ".docs-sidebar.docs-sidebar--drawer");
    expect(sheet).toContain("position: fixed");
    expect(sheet).toContain("translateX(var(--drawer-hidden))");
    expect(sheet).toContain("visibility: hidden");
    expect(sheet).toContain("height: var(--app-viewport-height)");
    // Above the topbar (150), like the More sheet: the whole page is behind it.
    expect(Number(/z-index:\s*(\d+)/.exec(sheet ?? "")?.[1])).toBeGreaterThan(150);
    expect(Number(/z-index:\s*(\d+)/.exec(declarations(phone.body, ".docs-contents-backdrop") ?? "")?.[1])).toBeGreaterThan(150);
    const open = declarations(phone.body, ".docs-sidebar.docs-sidebar--drawer.is-open");
    expect(open).toContain("visibility: visible");
    expect(open).toContain("transform: none");
    // The base rule, a 280px column beside the text, comes first.
    expect(phone.at).toBeGreaterThan(lastTopLevelRule(".docs-sidebar"));
    const reduced = mediaBlocks("(prefers-reduced-motion: reduce)");
    expect(reduced.some((b) => b.body.includes(".docs-sidebar.docs-sidebar--drawer"))).toBe(true);
  });

  it("puts the activity KPI tiles two to a row, the sparkline under the figures", () => {
    expect(declarations(phone.body, ".overview-kpi-row")).toContain("grid-template-columns: repeat(2, minmax(0, 1fr))");
    expect(declarations(phone.body, ".overview-kpi-card__body")).toContain("flex-direction: column");
    // The 900px block that makes them one column comes first.
    const oneColumn = mediaBlocks("(max-width: 900px)").find((b) => b.body.includes(".overview-kpi-row"));
    expect(oneColumn).toBeDefined();
    expect(phone.at).toBeGreaterThan(oneColumn!.at);
  });

  it("keeps the usage heatmap's cells readable, scrolling sideways with the day names in place", () => {
    const row = declarations(phone.body, ".activity-heatmap__chart-row");
    expect(row).toContain("overflow-x: auto");
    expect(declarations(phone.body, ".activity-heatmap__week")).toContain("flex: 0 0 0.75rem");
    expect(declarations(phone.body, ".activity-heatmap__grid")).toContain("flex: 0 0 auto");
    const days = declarations(phone.body, ".activity-heatmap__dow");
    expect(days).toContain("position: sticky");
    expect(days).toContain("background: var(--surface)");
    expect(phone.at).toBeGreaterThan(lastTopLevelRule(".activity-heatmap__week"));
  });

  it("lets a metric card's long headline go under its title in one piece", () => {
    expect(declarations(phone.body, ".activity-metric-card__head")).toContain("flex-wrap: wrap");
    expect(declarations(phone.body, ".activity-metric-card__total--header")).toContain("white-space: nowrap");
    expect(phone.at).toBeGreaterThan(lastTopLevelRule(".activity-metric-card__head"));
  });

  it("draws the Chat Tools cards with a plain description and an unlabelled Manage access", () => {
    expect(declarations(phone.body, '.chat-tools-table.data-table--cards td[data-card-role="title"] p')).toContain(
      "font-weight: 400",
    );
    const actionsLabel = ".chat-tools-table.data-table--cards td.chat-tools-table__actions::before";
    expect(declarations(phone.body, actionsLabel)).toContain("content: none");
    expect(outranks(actionsLabel, ".data-table.data-table--cards td::before")).toBe(true);
    // On a desktop it keeps its own word breaking, not data-table's.
    const desktopBreaking = declarations(css.slice(0, phone.at), ".chat-tools-table.data-table td,\n.chat-tools-table.data-table th");
    expect(desktopBreaking).toContain("overflow-wrap: normal");
    expect(outranks(".chat-tools-table.data-table td", ".data-table td")).toBe(true);
  });

  it("fits the media cards and list rows", () => {
    // The picture opens the file in the grid views, so Open goes there.
    expect(
      declarations(
        phone.body,
        ".media-page-grid:not(.media-page-grid--list, .media-page-grid--detail, .media-page-grid--title) .media-page-item__open",
      ),
    ).toContain("display: none");
    const lists = ".media-page-grid--list .media-page-item,\n  .media-page-grid--detail .media-page-item,\n  .media-page-grid--title .media-page-item";
    expect(declarations(phone.body, lists)).toContain("flex-wrap: wrap");
    const actions =
      ".media-page-grid--list .media-page-item__actions,\n  .media-page-grid--detail .media-page-item__actions,\n  .media-page-grid--title .media-page-item__actions";
    expect(declarations(phone.body, actions)).toContain("flex-basis: 100%");
    // The base rules for those rows come first, so the phone rules win on order.
    expect(lastTopLevelRule(".media-page-grid--title .media-page-item__actions")).toBeGreaterThan(0);
    expect(phone.at).toBeGreaterThan(lastTopLevelRule(".media-page-grid--title .media-page-item__actions"));
  });

  it("turns the role picker into a sheet from the bottom edge", () => {
    const sheet = declarations(phone.body, ".role-multi-select__menu.role-multi-select__menu--sheet");
    expect(sheet).toContain("position: fixed");
    expect(sheet).toContain("bottom: 0");
    expect(sheet).toContain("env(safe-area-inset-bottom");
    expect(Number(/z-index:\s*(\d+)/.exec(sheet ?? "")?.[1])).toBeGreaterThanOrEqual(1201);
    expect(declarations(phone.body, ".role-multi-select__menu--sheet .role-multi-select__option")).toContain(
      "min-height: 2.75rem",
    );
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

describe("the sign-in page on a phone held sideways", () => {
  const short = mediaBlocks("(max-height: 500px)");

  it("scrolls instead of cutting the card off, with the trademark line after the card", () => {
    expect(short).toHaveLength(1);
    const body = short[0].body;
    const page = declarations(body, ".login-page");
    expect(page).toContain("flex-direction: column");
    expect(page).toContain("overflow-y: auto");
    // Centred by the card's auto margins, which give way when it is taller than the screen.
    expect(page).toContain("justify-content: flex-start");
    const shell = declarations(body, ".login-page__shell");
    expect(shell).toContain("height: auto");
    expect(shell).toContain("max-height: none");
    expect(shell).toContain("margin-block: auto");
    // In the flow below the card, not laid over its Continue button.
    expect(declarations(body, ".login-page__legal")).toContain("position: static");
    // The lower glow no longer reaches past the page's edge, which would give it room to scroll for nothing.
    expect(declarations(css.slice(0, short[0].at), ".login-page__glow--b")).toContain("bottom: -8%");
    expect(declarations(body, ".login-page__glow--b")).toContain("bottom: 0");
    // Base rules pin the page and the card to the screen; the narrow layout sets the card too.
    expect(declarations(css.slice(0, short[0].at), ".login-page")).toContain("overflow: hidden");
    expect(declarations(css.slice(0, short[0].at), ".login-page__legal")).toContain("position: absolute");
    expect(short[0].at).toBeGreaterThan(lastTopLevelRule(".login-page"));
    expect(short[0].at).toBeGreaterThan(lastTopLevelRule(".login-page__shell"));
    const narrow = mediaBlocks("(max-width: 900px)").filter((b) => b.body.includes(".login-page__shell {"));
    expect(narrow.length).toBeGreaterThan(0);
    for (const block of narrow) expect(short[0].at).toBeGreaterThan(block.at);
  });
});

/** Every style rule in the file, whitespace normalised, with the @-rules it sits in, outermost first. */
function styleRules(): Array<{ at: number; selectors: string[]; body: string; atRules: string[] }> {
  const rules: Array<{ at: number; selectors: string[]; body: string; atRules: string[] }> = [];
  const atRules: string[] = [];
  let start = 0;
  for (let i = 0; i < css.length; i += 1) {
    if (css[i] === "}") {
      atRules.pop();
      start = i + 1;
    } else if (css[i] === ";" && css.slice(start, i).trim().startsWith("@")) {
      start = i + 1; // A statement like @import, with no block.
    } else if (css[i] === "{") {
      const head = css.slice(start, i).trim().replace(/\s+/g, " ");
      if (head.startsWith("@")) {
        atRules.push(head);
        start = i + 1;
        continue;
      }
      // Style rules do not nest in this file, so the declarations end at the next brace.
      const close = css.indexOf("}", i);
      rules.push({ at: start, selectors: selectorList(head), body: css.slice(i + 1, close), atRules: [...atRules] });
      i = close;
      start = close + 1;
    }
  }
  return rules;
}

/** The properties a rule sets, and whether each is !important. */
function properties(body: string): Map<string, boolean> {
  const found = new Map<string, boolean>();
  for (const declaration of body.split(";")) {
    const m = /^\s*(-?-?[a-z][\w-]*)\s*:/i.exec(declaration);
    if (m) found.set(m[1].toLowerCase(), /!\s*important\s*$/i.test(declaration));
  }
  return found;
}

// The longhands each shorthand resets. Deliberately short: enough to catch a base rule that
// sets `padding` after a query set `padding-left`, not a full table of CSS.
const shorthands = new Map<string, RegExp>([
  ["padding", /^padding-/],
  ["margin", /^margin-/],
  ["gap", /^(row|column)-gap$/],
  ["inset", /^(top|right|bottom|left)$|^inset-/],
  ["border", /^border-(?!radius)/],
  ["background", /^background-/],
  ["font", /^font-|^line-height$/],
  ["flex", /^flex-(grow|shrink|basis)$/],
  ["grid-template", /^grid-template-/],
  ["overflow", /^overflow-[xy]$/],
  ["place-items", /^(align|justify)-items$/],
  ["place-content", /^(align|justify)-content$/],
  ["place-self", /^(align|justify)-self$/],
  ["transition", /^transition-/],
  ["animation", /^animation-/],
]);

const overlaps = (a: string, b: string) =>
  a === b || Boolean(shorthands.get(a)?.test(b)) || Boolean(shorthands.get(b)?.test(a));

describe("responsive rules", () => {
  it("are not overridden by a later base rule for the same selector", () => {
    // A rule in a max-width query has no more weight than a base rule for the same selector,
    // so a base rule further down the file wins on source order and the query does nothing
    // for that property. That is how the topbar kept its desktop padding on tablets.
    const rules = styleRules();
    const base = new Map<string, Array<{ at: number; props: Map<string, boolean> }>>();
    for (const rule of rules.filter((r) => r.atRules.length === 0)) {
      for (const selector of rule.selectors) {
        base.set(selector, [...(base.get(selector) ?? []), { at: rule.at, props: properties(rule.body) }]);
      }
    }
    const dead = new Set<string>();
    for (const rule of rules) {
      const media = rule.atRules.find((a) => a.startsWith("@media"));
      if (!media?.includes("max-width")) continue;
      const props = properties(rule.body);
      for (const selector of rule.selectors) {
        for (const later of (base.get(selector) ?? []).filter((b) => b.at > rule.at)) {
          for (const [prop, important] of props) {
            for (const [laterProp, laterImportant] of later.props) {
              // An !important declaration in the query still beats a plain one after it.
              if (overlaps(prop, laterProp) && (laterImportant || !important)) {
                dead.add(`${media}: ${selector} { ${prop} } is overridden by a later base rule`);
              }
            }
          }
        }
      }
    }
    expect([...dead]).toEqual([]);
  });
});

describe("the installed app's edges", () => {
  // viewport-fit=cover lets the page reach under the notch, the iOS home
  // indicator and Android's gesture bar; without it env(safe-area-inset-*) is
  // always 0 and the home indicator sits on the tab bar. Each edge keeps its
  // content clear instead.
  const html = readFileSync(join(__dirname, "..", "index.html"), "utf8");
  const phoneBlocks = mediaBlocks(PHONE_QUERY);
  const phoneBlock = phoneBlocks[phoneBlocks.length - 1];

  it("lets the page reach the screen's edges", () => {
    expect(html).toMatch(/<meta name="viewport" content="[^"]*viewport-fit=cover[^"]*interactive-widget=resizes-content/);
  });

  it("pads the layout for the home indicator unless the tab bar or the keyboard has that edge", () => {
    expect(declarations(css, ".layout:not(.layout--has-tabbar):not([data-soft-keyboard])")).toContain(
      "padding-bottom: env(safe-area-inset-bottom, 0px)",
    );
    expect(declarations(phoneBlock.body, ".bottom-tab-bar")).toContain("padding-bottom: env(safe-area-inset-bottom, 0px)");
    expect(declarations(css, ".login-page")).toContain("padding-bottom: env(safe-area-inset-bottom, 0px)");
  });

  it("keeps the content clear of the notch in the base rules, since a landscape iPhone gets the desktop layout", () => {
    const body = declarations(css, "body");
    expect(body).toContain("padding-left: env(safe-area-inset-left, 0px)");
    expect(body).toContain("padding-right: env(safe-area-inset-right, 0px)");
  });

  // Fixed layers ignore the body's padding, so each one answers for the insets
  // itself or is listed here with the reason it does not need to.
  const NEEDS_NO_INSETS: Record<string, string> = {
    ".shell-drawer-backdrop": "a backdrop: it covers the whole screen on purpose",
    ".bottom-sheet-backdrop": "a backdrop",
    ".action-sheet-backdrop": "a backdrop",
    ".docs-contents-backdrop": "a backdrop",
    ".alpha-router-admin-drawer-overlay": "a backdrop; the drawer in it pads itself",
    ".row-actions-menu--portal": "opens beside its trigger, which is inside the safe area",
    ".alpha-router-attach-menu": "opens beside its trigger, which is inside the safe area",
    ".alpha-router-server-tools-menu": "opens beside its trigger, which is inside the safe area",
  };

  it("gives every fixed layer an answer for the insets, or a reason it needs none", () => {
    const rules = styleRules();
    const fixed = new Set(rules.filter((r) => /position:\s*fixed/.test(r.body)).flatMap((r) => r.selectors));
    const insetAware = new Set(
      rules.filter((r) => /safe-area-inset|--safe-inline/.test(r.body)).flatMap((r) => r.selectors),
    );
    const unanswered = [...fixed].filter((s) => !insetAware.has(s) && !(s in NEEDS_NO_INSETS));
    expect(unanswered).toEqual([]);
    // And the list holds no layer that is gone or no longer fixed.
    expect(Object.keys(NEEDS_NO_INSETS).filter((s) => !fixed.has(s))).toEqual([]);
  });
});

describe("the new-version notice", () => {
  it("sits in the layout's flow with a finger-sized Reload", () => {
    expect(declarations(css, ".app-notice")).toContain("flex-shrink: 0");
    expect(declarations(css, ".app-notice")).not.toContain("position: fixed");
    expect(declarations(css, ".app-notice__action")).toContain("min-height: 2.75rem");
  });
});

describe("the install suggestion bar", () => {
  it("steps aside while a dialog is open", () => {
    expect(declarations(css, 'body:has(.modal-overlay, [aria-modal="true"]) .install-banner')).toContain("display: none");
  });

  it("sits in the layout's flow with finger-sized buttons", () => {
    expect(declarations(css, ".install-banner")).toContain("flex-shrink: 0");
    expect(declarations(css, ".install-banner")).not.toContain("position: fixed");
    const buttons = declarations(css, ".install-banner__install,\n.install-banner__dismiss");
    expect(buttons).toContain("min-height: 2.75rem");
    expect(buttons).toContain("min-width: 2.75rem");
  });
});
