/**
 * The readable text of a page, as a model should see it.
 *
 * Runs inside the page (content.js), in the extension's isolated world. What
 * the user cannot see is left out - hidden elements are the usual hiding
 * place for text meant only for a model - and so is what is not content:
 * scripts, styles, form fields and their values, buttons. The main content is
 * preferred when the page marks it, and the text is capped.
 *
 * Visibility is a parameter so tests can decide it: a DOM without layout has
 * no boxes to measure.
 */

export type ExtractOptions = {
  /** Characters of page text to keep. */
  maxChars: number;
  /** Characters of the user's selection to keep. */
  maxSelectionChars: number;
  /** Is this element rendered where the user can see it? Its subtree is skipped when not. */
  isVisible: (el: Element) => boolean;
  /** Is text directly inside this element readable (a zero font size is not)? */
  isTextVisible: (el: Element) => boolean;
};

export type PageExtract = {
  url: string;
  title: string;
  text: string;
  truncated: boolean;
  selection: string;
};

/** Never content, and never worth a visibility check. */
const SKIPPED = new Set([
  "SCRIPT",
  "STYLE",
  "NOSCRIPT",
  "TEMPLATE",
  "HEAD",
  "META",
  "LINK",
  "SVG",
  "CANVAS",
  "IFRAME",
  "FRAME",
  "OBJECT",
  "EMBED",
  "AUDIO",
  "VIDEO",
  "MAP",
  // Form fields: their values are what the user typed, never page content.
  "INPUT",
  "TEXTAREA",
  "SELECT",
  "OPTION",
  "BUTTON",
  "DATALIST",
]);

const BLOCKS = new Set([
  "ADDRESS",
  "ARTICLE",
  "ASIDE",
  "BLOCKQUOTE",
  "BODY",
  "CAPTION",
  "DD",
  "DETAILS",
  "DIALOG",
  "DIV",
  "DL",
  "DT",
  "FIELDSET",
  "FIGCAPTION",
  "FIGURE",
  "FOOTER",
  "FORM",
  "H1",
  "H2",
  "H3",
  "H4",
  "H5",
  "H6",
  "HEADER",
  "HR",
  "LI",
  "MAIN",
  "NAV",
  "OL",
  "P",
  "SECTION",
  "SUMMARY",
  "TABLE",
  "TBODY",
  "TFOOT",
  "THEAD",
  "TR",
  "UL",
]);

/** Parts of a page that are about the site, not this page. */
const SITE_CHROME = "nav, footer, [role='navigation'], [role='contentinfo']";

const MIN_MAIN_CHARS = 200;
const MAX_ALT_CHARS = 200;
const MAX_TITLE_CHARS = 300;

class TextBuffer {
  private parts: string[] = [];
  private length = 0;
  /** A line break is owed before the next text. */
  private pendingBreak = false;
  private atLineStart = true;
  private endsWithSpace = false;
  full = false;

  constructor(private readonly limit: number) {}

  private push(text: string): void {
    if (this.full || !text) return;
    const room = this.limit - this.length;
    const kept = text.length > room ? text.slice(0, room) : text;
    this.parts.push(kept);
    this.length += kept.length;
    this.endsWithSpace = kept.endsWith(" ");
    if (kept !== text) this.full = true;
  }

  /** Inline text: runs of whitespace are one space, as a browser renders them, even across elements. */
  inline(raw: string): void {
    const text = raw.replace(/\s+/g, " ");
    if (!text.trim()) {
      if (!this.atLineStart && !this.pendingBreak && !this.endsWithSpace) this.push(" ");
      return;
    }
    if (this.pendingBreak) {
      this.push("\n");
      this.pendingBreak = false;
      this.atLineStart = true;
    }
    this.push(this.atLineStart || this.endsWithSpace ? text.replace(/^ /, "") : text);
    this.atLineStart = false;
  }

  /** Text shown as it is (pre, code blocks). */
  verbatim(text: string): void {
    if (!text) return;
    this.lineBreak();
    if (this.pendingBreak) {
      this.push("\n");
      this.pendingBreak = false;
    }
    this.push(text.replace(/\n+$/, ""));
    this.atLineStart = false;
    this.lineBreak();
  }

  lineBreak(): void {
    if (!this.atLineStart) this.pendingBreak = true;
  }

  /** A forced line break (<br>), even between two breaks. */
  hardBreak(): void {
    this.push("\n");
    this.pendingBreak = false;
    this.atLineStart = true;
  }

  toString(): string {
    return this.parts
      .join("")
      .replace(/[ \t]+\n/g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }
}

/**
 * Preformatted text as it is shown, whitespace and all, from the parts the
 * user can see: a <pre> hides text as well as any other element.
 */
function preformatted(node: Node, options: ExtractOptions): string {
  if (node.nodeType === Node.TEXT_NODE) {
    const parent = node.parentElement;
    return !parent || options.isTextVisible(parent) ? (node.nodeValue ?? "") : "";
  }
  const children = (el: ParentNode) => Array.from(el.childNodes, (child) => preformatted(child, options)).join("");
  if (node.nodeType === Node.DOCUMENT_FRAGMENT_NODE) return children(node as DocumentFragment);
  if (node.nodeType !== Node.ELEMENT_NODE) return "";
  const el = node as Element;
  const tag = el.tagName.toUpperCase();
  if (SKIPPED.has(tag) || !options.isVisible(el)) return "";
  if (tag === "BR") return "\n";
  return children(el.shadowRoot ?? el);
}

function walk(node: Node, out: TextBuffer, options: ExtractOptions, skip: Set<Element>): void {
  if (out.full) return;
  if (node.nodeType === Node.TEXT_NODE) {
    const parent = node.parentElement;
    if (!parent || options.isTextVisible(parent)) out.inline(node.nodeValue ?? "");
    return;
  }
  if (node.nodeType === Node.DOCUMENT_FRAGMENT_NODE) {
    for (const child of Array.from(node.childNodes)) walk(child, out, options, skip);
    return;
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return;
  const el = node as Element;
  const tag = el.tagName.toUpperCase();
  if (SKIPPED.has(tag) || skip.has(el) || !options.isVisible(el)) return;
  if (tag === "BR") {
    out.hardBreak();
    return;
  }
  if (tag === "IMG") {
    const alt = (el.getAttribute("alt") ?? "").replace(/\s+/g, " ").trim().slice(0, MAX_ALT_CHARS);
    if (alt) out.inline(` [Image: ${alt}] `);
    return;
  }
  if (tag === "PRE") {
    out.verbatim(Array.from((el.shadowRoot ?? el).childNodes, (child) => preformatted(child, options)).join(""));
    return;
  }
  const block = BLOCKS.has(tag);
  if (block) out.lineBreak();
  const heading = /^H([1-6])$/.exec(tag);
  if (heading) out.inline(`${"#".repeat(Number(heading[1]))} `);
  else if (tag === "LI") out.inline("- ");
  // Open shadow roots hold the content of web components; a closed one is out of reach.
  const children = el.shadowRoot ? [el.shadowRoot] : Array.from(el.childNodes);
  if (tag === "SLOT") {
    const assigned = (el as HTMLSlotElement).assignedNodes?.({ flatten: true }) ?? [];
    for (const child of assigned.length ? assigned : children) walk(child, out, options, skip);
  } else {
    for (const child of children) walk(child, out, options, skip);
  }
  if (tag === "TD" || tag === "TH") out.inline(" | ");
  if (block) out.lineBreak();
}

function visibleWithAncestors(el: Element, options: ExtractOptions): boolean {
  for (let node: Element | null = el; node; node = node.parentElement) {
    if (!options.isVisible(node)) return false;
  }
  return true;
}

/** The page's main content when it marks exactly one, else the whole body. */
function contentRoots(doc: Document, options: ExtractOptions): Element[] {
  const body = doc.body ?? doc.documentElement;
  const roots: Element[] = [];
  for (const selector of ["main, [role='main']", "article"]) {
    const found = Array.from(doc.querySelectorAll(selector)).filter((el) => visibleWithAncestors(el, options));
    if (found.length === 1) {
      roots.push(found[0]);
      break;
    }
  }
  roots.push(body);
  return roots;
}

function extractFrom(root: Element, options: ExtractOptions): { text: string; truncated: boolean } {
  const out = new TextBuffer(options.maxChars);
  // Site navigation and footers are left out when reading the whole body.
  const skip = new Set(root.tagName.toUpperCase() === "BODY" ? Array.from(root.querySelectorAll(SITE_CHROME)) : []);
  walk(root, out, options, skip);
  return { text: out.toString(), truncated: out.full };
}

function selectionText(doc: Document, limit: number): string {
  const selected = doc.getSelection?.()?.toString() ?? "";
  return selected.replace(/[ \t]+/g, " ").trim().slice(0, limit);
}

export function extractPage(doc: Document, options: ExtractOptions): PageExtract {
  const roots = contentRoots(doc, options);
  let result = extractFrom(roots[0], options);
  // A main element that holds almost nothing (an app shell) is not the content.
  if (roots.length > 1 && result.text.length < MIN_MAIN_CHARS) result = extractFrom(roots[1], options);
  return {
    url: doc.location?.href ?? "",
    title: (doc.title ?? "").replace(/\s+/g, " ").trim().slice(0, MAX_TITLE_CHARS),
    text: result.text,
    truncated: result.truncated,
    selection: selectionText(doc, options.maxSelectionChars),
  };
}

function clips(style: CSSStyleDeclaration): boolean {
  return [style.overflow, style.overflowX, style.overflowY].some((value) => value === "hidden" || value === "clip");
}

/**
 * The browser's own answer: not display:none, visibility:hidden, opacity 0,
 * `hidden` or `aria-hidden`; has a box; is not a clipped zero-size box (the
 * screen-reader-only pattern); is not pushed off the page to the left or top.
 */
export function isRendered(el: Element): boolean {
  if (el.hasAttribute("hidden") || el.getAttribute("aria-hidden") === "true") return false;
  const view = el.ownerDocument.defaultView;
  if (!view) return true;
  const style = view.getComputedStyle(el);
  if (style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse") return false;
  if (Number.parseFloat(style.opacity) === 0) return false;
  if (style.display === "contents") return true;
  if (el.getClientRects().length === 0) return false;
  const rect = el.getBoundingClientRect();
  if ((rect.width <= 1 || rect.height <= 1) && clips(style)) return false;
  if (/inset\((50|100)%/.test(style.clipPath)) return false;
  if (rect.right + view.scrollX < 0 || rect.bottom + view.scrollY < 0) return false;
  return true;
}

/** Text in a zero font size is there for machines only. */
export function isTextRendered(el: Element): boolean {
  const view = el.ownerDocument.defaultView;
  if (!view) return true;
  return Number.parseFloat(view.getComputedStyle(el).fontSize) !== 0;
}
