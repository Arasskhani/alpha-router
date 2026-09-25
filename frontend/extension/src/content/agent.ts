/**
 * The browser agent's hands in a page: what it sees, and what it does.
 *
 * Runs inside the page (content.js), in the extension's isolated world, one
 * call at a time as the side panel asks. The panel decides whether an action
 * may happen at all (the agent's rules, the user's approval); this side only
 * does it, and checks again what it can check on the element itself - it never
 * types into a password or card field whatever it is told.
 *
 * What the agent sees is an outline of the page: its headings, and every
 * element a person could use - links, buttons, fields, menus - each with a
 * short reference ("e12") that later actions name. A reference is kept for as
 * long as its element stays in the page; once the page drops or replaces the
 * element, the reference is stale and the agent reads the page again. The
 * references live here, in the isolated world, where the page cannot reach
 * them, and hold their elements weakly.
 *
 * Only what a person could see is listed: hidden elements are where text meant
 * for a model, not for the user, is put. A field's value is shown (the agent
 * needs to know what is filled in) except for sensitive fields, whose value is
 * never read. Events are the page's own kind - a click, input and change
 * through the element's own setters - so pages built with React and the like
 * see them; sites that accept only trusted input events will not react, which
 * is a limit of acting without the debugger.
 */

import { isSensitiveField } from "../lib/sensitive";
import { extractPage, isBlockDisplayed, isTextRendered } from "./extract";
import { OVERLAY_ID } from "./overlay";

export type Visibility = (el: Element) => boolean;

/** One element the agent can act on, as the side panel's rules see it. */
export type ElementInfo = {
  ref: string;
  role: string;
  /** Its accessible name: what a screen reader would announce. Never its value. */
  name: string;
  /**
   * A control's own words, when they are not its name: a button labelled
   * "Continue" by aria-label or a <label> that says "Place order" itself.
   */
  text?: string;
  tag: string;
  /** An input's type. */
  type?: string;
  /** What is filled in (a text field, cut short) or chosen (a menu); never for a sensitive field. */
  value?: string;
  checked?: boolean;
  disabled?: boolean;
  /** A password, card or one-time-code field: the agent never types into it. */
  sensitive?: boolean;
  /** Where a link goes, in full. */
  href?: string;
  /** Activating it submits a form. */
  submits?: boolean;
  /** Where its form sends what is in it. */
  formAction?: string;
  /** A menu's choices, the first few. */
  options?: string[];
};

type AgentError =
  | "stale_ref"
  | "not_visible"
  | "disabled"
  | "covered"
  | "not_typable"
  | "sensitive_field"
  | "read_only"
  | "not_select"
  | "no_option"
  | "no_form"
  | "invalid_form"
  | "bad_key"
  | "bad_request"
  | "not_found"
  | "failed";

type Failure = { ok: false; error: AgentError; message: string };
export type Result<T extends object = object> = ({ ok: true } & T) | Failure;

const NAME_CHARS = 100;
const VALUE_CHARS = 100;
const MAX_OPTIONS = 20;
const DEFAULT_OUTLINE_CHARS = 12_000;
const MAX_OUTLINE_CHARS = 30_000;
const MAX_OUTLINE_ELEMENTS = 300;
const DEFAULT_TEXT_CHARS = 8_000;
const MAX_TEXT_CHARS = 30_000;
const MAX_FIND_RESULTS = 20;
const MAX_WAIT_SECONDS = 10;

// --- references --------------------------------------------------------------------------

type AgentState = { format: 1; next: number; byRef: Map<string, WeakRef<Element>>; byElement: WeakMap<Element, string> };

const STATE_KEY = "__alpharouterAgentState";

/**
 * The references handed out in this page. Kept on the isolated world's global
 * so a later injection of content.js finds them; data only, so a copy left by
 * another version of the extension is replaced unless it has this shape.
 */
function state(): AgentState {
  const scope = globalThis as typeof globalThis & { [STATE_KEY]?: AgentState };
  const found = scope[STATE_KEY];
  if (found && found.format === 1 && found.byRef instanceof Map) return found;
  const fresh: AgentState = { format: 1, next: 0, byRef: new Map(), byElement: new WeakMap() };
  scope[STATE_KEY] = fresh;
  return fresh;
}

function refFor(el: Element): string {
  const s = state();
  const known = s.byElement.get(el);
  if (known && s.byRef.get(known)?.deref() === el) return known;
  s.next += 1;
  const ref = `e${s.next}`;
  s.byRef.set(ref, new WeakRef(el));
  s.byElement.set(el, ref);
  return ref;
}

/** Forget references whose elements are gone, so the map does not grow with a long-lived page. */
function prune(): void {
  const s = state();
  for (const [ref, weak] of s.byRef) {
    const el = weak.deref();
    if (!el || !el.isConnected) s.byRef.delete(ref);
  }
}

function resolve(ref: unknown): Element | Failure {
  if (typeof ref !== "string" || !/^e\d{1,9}$/.test(ref)) {
    return { ok: false, error: "bad_request", message: "Name an element by its reference, such as e12." };
  }
  const el = state().byRef.get(ref)?.deref();
  if (!el || !el.isConnected) {
    return { ok: false, error: "stale_ref", message: `Element ${ref} is no longer on the page. Read the page again.` };
  }
  return el;
}

function isFailure(value: unknown): value is Failure {
  return typeof value === "object" && value !== null && (value as { ok?: unknown }).ok === false;
}

// --- what the agent sees -----------------------------------------------------------------

/** Never content, and never worth a visibility check. */
const SKIPPED = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "HEAD", "META", "LINK", "TITLE"]);

/**
 * Every element a person could see, in page order: hidden ones and their
 * subtrees are skipped, open shadow roots are entered through their slots,
 * and the agent's own overlay is not part of the page.
 */
function* visibleElements(root: Element, isVisible: Visibility): Generator<Element> {
  const stack: Node[] = [root];
  while (stack.length) {
    const node = stack.pop() as Node;
    if (node.nodeType === Node.DOCUMENT_FRAGMENT_NODE) {
      pushChildren(stack, Array.from(node.childNodes));
      continue;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) continue;
    const el = node as Element;
    if (SKIPPED.has(el.tagName.toUpperCase()) || el.id === OVERLAY_ID || el.hasAttribute("inert") || !isVisible(el)) continue;
    yield el;
    if (el.tagName.toUpperCase() === "SLOT") {
      const assigned = (el as HTMLSlotElement).assignedNodes?.({ flatten: true }) ?? [];
      pushChildren(stack, assigned.length ? assigned : Array.from(el.childNodes));
    } else {
      pushChildren(stack, Array.from((el.shadowRoot ?? el).childNodes));
    }
  }
}

function pushChildren(stack: Node[], children: Node[]): void {
  for (let i = children.length - 1; i >= 0; i -= 1) stack.push(children[i]);
}

function squash(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

function clip(text: string, limit: number): string {
  const flat = squash(text);
  return flat.length <= limit ? flat : `${flat.slice(0, limit - 1)}…`;
}

const FIELDS = new Set(["INPUT", "TEXTAREA", "SELECT", "OPTION", "DATALIST"]);

/**
 * Whether an element's words count for its name, as a screen reader reads
 * them: all but what is removed from the page (display: none, visibility:
 * hidden, `hidden`, aria-hidden). Screen-reader-only text - a one-pixel,
 * clipped box, the usual name of an icon button - counts, though it is not
 * drawn: without it a "Delete account" button with only an icon is nameless.
 */
function isExposed(el: Element): boolean {
  if (el.hasAttribute("hidden") || el.getAttribute("aria-hidden") === "true") return false;
  const view = el.ownerDocument.defaultView;
  if (!view) return true;
  const style = view.getComputedStyle(el);
  return style.display !== "none" && style.visibility !== "hidden" && style.visibility !== "collapse";
}

/** The text a person sees in an element, images by their alt text, without any field's value. */
function visibleText(el: Element, isVisible: Visibility, limit = 200): string {
  const parts: string[] = [];
  let length = 0;
  const stack: Node[] = [el];
  while (stack.length && length < limit) {
    const node = stack.pop() as Node;
    if (node.nodeType === Node.TEXT_NODE) {
      const parent = node.parentElement;
      if (!parent || isTextRendered(parent)) {
        const value = node.nodeValue ?? "";
        parts.push(value);
        length += value.length;
      }
      continue;
    }
    if (node.nodeType === Node.DOCUMENT_FRAGMENT_NODE) {
      pushChildren(stack, Array.from(node.childNodes));
      continue;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) continue;
    const child = node as Element;
    const tag = child.tagName.toUpperCase();
    if (SKIPPED.has(tag) || FIELDS.has(tag) || (child !== el && !isVisible(child))) continue;
    if (tag === "IMG") {
      const alt = child.getAttribute("alt");
      if (alt) parts.push(` ${alt} `);
      continue;
    }
    if (isBlockDisplayed(child)) parts.push(" ");
    pushChildren(stack, Array.from((child.shadowRoot ?? child).childNodes));
    if (isBlockDisplayed(child)) parts.push(" ");
  }
  return clip(parts.join(""), limit);
}

const INTERACTIVE_ROLES = new Set([
  "button",
  "link",
  "checkbox",
  "radio",
  "switch",
  "tab",
  "menuitem",
  "menuitemcheckbox",
  "menuitemradio",
  "option",
  "textbox",
  "searchbox",
  "combobox",
  "listbox",
  "slider",
  "spinbutton",
  "treeitem",
]);

const BUTTON_INPUTS = new Set(["button", "submit", "reset", "image"]);
const TEXT_INPUTS = new Set(["", "text", "search", "email", "url", "tel", "password", "number"]);
/** The input types a browser knows; any other value makes a text field. */
const INPUT_TYPES = new Set([
  "hidden",
  "text",
  "search",
  "tel",
  "url",
  "email",
  "password",
  "date",
  "month",
  "week",
  "time",
  "datetime-local",
  "number",
  "range",
  "color",
  "checkbox",
  "radio",
  "file",
  "submit",
  "image",
  "reset",
  "button",
]);

/**
 * An input's type as the browser reads it: the attribute in any case, but
 * never trimmed - `type="submit "` is no type the browser knows, so the
 * field is a text field.
 */
function inputType(el: Element): string {
  const raw = (el.getAttribute("type") ?? "").toLowerCase();
  return INPUT_TYPES.has(raw) ? raw : "text";
}

/** The element's role when a person could use it; null for everything else. */
function roleOf(el: Element): string | null {
  const explicit = (el.getAttribute("role") ?? "").trim().split(/\s+/)[0].toLowerCase();
  if (explicit && INTERACTIVE_ROLES.has(explicit)) return explicit;
  switch (el.tagName.toUpperCase()) {
    case "A":
    case "AREA":
      return el.hasAttribute("href") ? "link" : null;
    case "BUTTON":
    case "SUMMARY":
      return "button";
    case "TEXTAREA":
      return "textbox";
    case "SELECT": {
      const select = el as HTMLSelectElement;
      return select.multiple || select.size > 1 ? "listbox" : "combobox";
    }
    case "INPUT": {
      const type = inputType(el);
      if (type === "hidden") return null;
      if (BUTTON_INPUTS.has(type)) return "button";
      if (type === "checkbox") return "checkbox";
      if (type === "radio") return "radio";
      if (type === "range") return "slider";
      if (type === "number") return "spinbutton";
      if (type === "search") return "searchbox";
      if (type === "file") return "file";
      return "textbox";
    }
    default:
      break;
  }
  const editable = el as HTMLElement;
  if (editable.isContentEditable && !editable.parentElement?.isContentEditable) return "textbox";
  return null;
}

function headingLevel(el: Element): number | null {
  const match = /^H([1-6])$/.exec(el.tagName.toUpperCase());
  if (match) return Number(match[1]);
  if ((el.getAttribute("role") ?? "").trim().toLowerCase() === "heading") {
    const level = Number(el.getAttribute("aria-level"));
    return level >= 1 && level <= 6 ? level : 2;
  }
  return null;
}

/** A label's words, without the text of the fields inside it (a menu's options, a box's value). */
function labelText(label: Element): string {
  return visibleText(label, isExposed, NAME_CHARS);
}

/** The words of an element's labels; a label removed from the page (display: none) names nothing. */
function labelsOf(el: Element): string {
  const doc = el.ownerDocument;
  const found = new Set<Element>();
  const labels = (el as HTMLInputElement).labels;
  if (labels) for (const label of Array.from(labels)) found.add(label);
  if (el.id) {
    for (const label of Array.from(doc.querySelectorAll("label"))) {
      if (label.getAttribute("for") === el.id) found.add(label);
    }
  }
  const wrapping = el.closest("label");
  if (wrapping) found.add(wrapping);
  return squash(
    Array.from(found)
      .filter(isExposed)
      .map(labelText)
      .join(" "),
  );
}

/**
 * What a screen reader would announce - aria-labelledby, aria-label, the
 * field's labels, alt and title, then the words inside - cut short. A text
 * field's own text is its value, never its name.
 */
function accessibleName(el: Element, role: string): string {
  const doc = el.ownerDocument;
  const labelledBy = (el.getAttribute("aria-labelledby") ?? "").split(/\s+/).filter(Boolean);
  if (labelledBy.length) {
    const text = squash(
      labelledBy
        .map((id) => {
          const target = doc.getElementById(id);
          // Named on purpose, a hidden element still names: then all of it does, as a screen reader has it.
          if (!target) return "";
          return visibleText(target, isExposed(target) ? isExposed : () => true, NAME_CHARS);
        })
        .join(" "),
    );
    if (text) return clip(text, NAME_CHARS);
  }
  const aria = squash(el.getAttribute("aria-label") ?? "");
  if (aria) return clip(aria, NAME_CHARS);
  const tag = el.tagName.toUpperCase();
  if (FIELDS.has(tag) || tag === "BUTTON" || tag === "METER" || tag === "PROGRESS") {
    const labels = labelsOf(el);
    if (labels) return clip(labels, NAME_CHARS);
  }
  if (tag === "INPUT") {
    const type = inputType(el);
    if (type === "image") return clip(el.getAttribute("alt") || el.getAttribute("value") || "Submit", NAME_CHARS);
    if (BUTTON_INPUTS.has(type)) {
      return clip(el.getAttribute("value") || (type === "reset" ? "Reset" : type === "submit" ? "Submit" : ""), NAME_CHARS);
    }
  }
  const textual = role === "textbox" || role === "searchbox" || role === "combobox" || role === "spinbutton";
  if (!textual) {
    const inside = visibleText(el, isExposed, NAME_CHARS);
    if (inside) return inside;
  }
  const title = squash(el.getAttribute("title") ?? "");
  if (title) return clip(title, NAME_CHARS);
  const placeholder = squash(el.getAttribute("placeholder") ?? el.getAttribute("aria-placeholder") ?? "");
  if (placeholder) return clip(placeholder, NAME_CHARS);
  return "";
}

function absoluteUrl(el: Element, attribute: string, fallback?: string): string | undefined {
  const raw = el.getAttribute(attribute) ?? fallback;
  if (raw === undefined || raw === null) return undefined;
  try {
    return new URL(raw, el.ownerDocument.baseURI).href;
  } catch {
    return undefined;
  }
}

function isDisabled(el: Element): boolean {
  if (el.getAttribute("aria-disabled") === "true") return true;
  try {
    return el.matches(":disabled");
  } catch {
    return Boolean((el as HTMLButtonElement).disabled);
  }
}

function formOf(el: Element): HTMLFormElement | null {
  if (el.tagName.toUpperCase() === "FORM") return el as HTMLFormElement;
  const owner = (el as HTMLInputElement).form;
  return owner ?? (el.closest("form") as HTMLFormElement | null);
}

/**
 * Whether activating it sends its form. A button is a submit button unless
 * its type is exactly "button" or "reset" in some case: a missing, empty or
 * unknown type ("", "bogus", "button ") submits, as the browser has it.
 */
function submits(el: Element): boolean {
  const tag = el.tagName.toUpperCase();
  if (tag === "BUTTON") {
    const type = (el.getAttribute("type") ?? "").toLowerCase();
    return type !== "button" && type !== "reset" && formOf(el) !== null;
  }
  return tag === "INPUT" && (inputType(el) === "submit" || inputType(el) === "image") && formOf(el) !== null;
}

function parentAcrossShadow(el: Element): Element | null {
  if (el.parentElement) return el.parentElement;
  const root = el.getRootNode();
  return root instanceof ShadowRoot ? root.host : null;
}

/**
 * The element a click on `el` works on: `el` itself, or its nearest
 * ancestor across shadow roots that acts on a click - a link, a button, a
 * form field, a summary, an element that says it is a control - and for a
 * label, the field it labels. A click on the words inside a button is the
 * button's click, and on a label for a submit button it sends the form, so
 * that is the element the rules judge and the one clicked.
 */
function activationTarget(el: Element): Element {
  for (let node: Element | null = el; node; node = parentAcrossShadow(node)) {
    const tag = node.tagName.toUpperCase();
    if ((tag === "A" || tag === "AREA") && node.hasAttribute("href")) return node;
    if (tag === "BUTTON" || tag === "SUMMARY" || tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return node;
    if (tag === "LABEL") return (node as HTMLLabelElement).control ?? node;
    const role = (node.getAttribute("role") ?? "").trim().split(/\s+/)[0].toLowerCase();
    if (role && INTERACTIVE_ROLES.has(role)) return node;
  }
  return el;
}

function formAction(el: Element): string | undefined {
  const form = formOf(el);
  if (!form) return undefined;
  if (el !== form && el.hasAttribute("formaction")) return absoluteUrl(el, "formaction");
  return absoluteUrl(form, "action", el.ownerDocument.location?.href ?? "");
}

function currentValue(el: Element, role: string): string | undefined {
  const tag = el.tagName.toUpperCase();
  if (tag === "SELECT") {
    const select = el as HTMLSelectElement;
    const chosen = Array.from(select.selectedOptions ?? []).map((option) => squash(option.label || option.text));
    return chosen.length ? clip(chosen.join(", "), VALUE_CHARS) : undefined;
  }
  if (tag === "INPUT" || tag === "TEXTAREA") {
    if (role === "button" || role === "checkbox" || role === "radio" || role === "file") return undefined;
    const value = (el as HTMLInputElement).value ?? "";
    return value ? clip(value, VALUE_CHARS) : undefined;
  }
  if (role === "textbox" && (el as HTMLElement).isContentEditable) {
    const text = squash(el.textContent ?? "");
    return text ? clip(text, VALUE_CHARS) : undefined;
  }
  const aria = el.getAttribute("aria-valuetext") ?? el.getAttribute("aria-valuenow");
  return aria ? clip(aria, VALUE_CHARS) : undefined;
}

function checkedState(el: Element, role: string): boolean | undefined {
  if (!["checkbox", "radio", "switch", "menuitemcheckbox", "menuitemradio"].includes(role)) return undefined;
  if (el.tagName.toUpperCase() === "INPUT") return Boolean((el as HTMLInputElement).checked);
  const aria = el.getAttribute("aria-checked");
  return aria === "true" ? true : aria === "false" ? false : undefined;
}

/** Roles of controls a person clicks, whose own words say what the click does. */
const CLICKED_ROLES = new Set(["button", "link", "menuitem", "menuitemcheckbox", "menuitemradio", "tab", "option", "switch", "treeitem"]);

/** The words a clicked control shows itself - a button's text, a submit input's value - which its name can hide. */
function ownWords(el: Element, role: string, isVisible: Visibility): string {
  if (!CLICKED_ROLES.has(role)) return "";
  if (el.tagName.toUpperCase() === "INPUT") return clip(el.getAttribute("value") ?? "", NAME_CHARS);
  return visibleText(el, isVisible, NAME_CHARS);
}

/** Input types whose value is never text a person typed. */
const NOT_TEXT_INPUTS = new Set(["hidden", "checkbox", "radio", "file", "submit", "image", "reset", "button", "range", "color"]);

/** Whether the element holds text someone typed - a text-like input, a text area, an editor - whatever role it claims. */
function holdsText(el: Element): boolean {
  const tag = el.tagName.toUpperCase();
  if (tag === "TEXTAREA") return true;
  if (tag === "INPUT") return !NOT_TEXT_INPUTS.has(inputType(el));
  return Boolean((el as HTMLElement).isContentEditable);
}

/** Everything the panel's rules and the model need to know about one element. */
function describeElement(el: Element, role: string, isVisible: Visibility): ElementInfo {
  const info: ElementInfo = { ref: refFor(el), role, name: accessibleName(el, role), tag: el.tagName.toLowerCase() };
  if (el.tagName.toUpperCase() === "INPUT") info.type = inputType(el);
  // By the field, not its role: <input type="password" role="combobox"> still holds a password.
  const sensitive = holdsText(el) && isSensitiveField(el);
  if (sensitive) info.sensitive = true;
  else {
    const value = currentValue(el, role);
    if (value !== undefined) info.value = value;
  }
  const checked = checkedState(el, role);
  if (checked !== undefined) info.checked = checked;
  if (isDisabled(el)) info.disabled = true;
  const own = ownWords(el, role, isVisible);
  if (own && own !== info.name) info.text = own;
  // Every link's address, whatever role it claims: a menu item or a "button" that is a link still goes there.
  const tag = el.tagName.toUpperCase();
  if ((tag === "A" || tag === "AREA") && el.hasAttribute("href")) {
    const href = absoluteUrl(el, "href");
    if (href) info.href = href;
  }
  if (submits(el)) info.submits = true;
  const action = formAction(el);
  if (action && (info.submits || role === "textbox" || el.tagName.toUpperCase() === "FORM")) info.formAction = action;
  if (el.tagName.toUpperCase() === "SELECT") {
    info.options = Array.from((el as HTMLSelectElement).options)
      .slice(0, MAX_OPTIONS)
      .map((option) => clip(option.label || option.text, 60));
  }
  return info;
}

/** A link's address as the model reads it: the path on this site, or the other site and path; never a query. */
function shownHref(href: string, pageUrl: string): string {
  try {
    const url = new URL(href);
    if (!/^https?:$/.test(url.protocol)) return url.protocol;
    const page = new URL(pageUrl);
    return url.origin === page.origin ? url.pathname : `${url.origin}${url.pathname}`;
  } catch {
    return "";
  }
}

function quoted(text: string): string {
  return `"${text.replace(/"/g, "'")}"`;
}

function outlineLine(info: ElementInfo, pageUrl: string): string {
  const parts = [`[${info.ref}]`, info.role, quoted(info.name)];
  if (info.value !== undefined) parts.push(`= ${quoted(info.value)}`);
  if (info.href) {
    const where = shownHref(info.href, pageUrl);
    if (where) parts.push(`→ ${where}`);
  }
  const notes: string[] = [];
  if (info.checked !== undefined) notes.push(info.checked ? "checked" : "not checked");
  if (info.disabled) notes.push("disabled");
  if (info.sensitive) notes.push("sensitive: the agent cannot type here");
  if (info.submits) notes.push("submits a form");
  if (info.options?.length) notes.push(`options: ${info.options.slice(0, 10).join(" | ")}${info.options.length > 10 ? " | …" : ""}`);
  if (notes.length) parts.push(`(${notes.join("; ")})`);
  return parts.join(" ");
}

/** The part of a URL worth telling the model: never the query or the fragment. */
function modelUrl(raw: string): string {
  try {
    const url = new URL(raw);
    return /^https?:$/.test(url.protocol) ? `${url.origin}${url.pathname}` : url.protocol;
  } catch {
    return "";
  }
}

export type Snapshot = { url: string; title: string; outline: string; elements: ElementInfo[]; truncated: boolean };

/** The page as the agent sees it: its headings and the elements a person could use, each with a reference. */
export function snapshot(doc: Document, options: { maxChars?: number; isVisible: Visibility }): Snapshot {
  prune();
  const maxChars = Math.max(1000, Math.min(MAX_OUTLINE_CHARS, options.maxChars ?? DEFAULT_OUTLINE_CHARS));
  const pageUrl = doc.location?.href ?? "";
  const lines: string[] = [];
  const elements: ElementInfo[] = [];
  let count = 0;
  let length = 0;
  let truncated = false;
  const root = doc.body ?? doc.documentElement;
  for (const el of visibleElements(root, options.isVisible)) {
    const level = headingLevel(el);
    let line: string | null = null;
    if (level !== null) {
      const text = visibleText(el, options.isVisible, NAME_CHARS);
      if (text) line = `${"#".repeat(level)} ${text}`;
    } else {
      const role = roleOf(el);
      if (!role) continue;
      count += 1;
      if (elements.length >= MAX_OUTLINE_ELEMENTS) {
        truncated = true;
        continue;
      }
      const info = describeElement(el, role, options.isVisible);
      elements.push(info);
      line = outlineLine(info, pageUrl);
    }
    if (!line) continue;
    if (length + line.length + 1 > maxChars) {
      truncated = true;
      break;
    }
    lines.push(line);
    length += line.length + 1;
  }
  const title = squash(doc.title ?? "").slice(0, 300);
  const header = [`Page: ${title || "(untitled)"}`, `URL: ${modelUrl(pageUrl)}`];
  const footer = truncated
    ? [`(The outline stops here${count > elements.length ? `: ${elements.length} of ${count} elements are listed` : ""}. Scroll, or use find, to reach the rest.)`]
    : [];
  const body = lines.length ? lines : ["(No headings or usable elements are visible on this page.)"];
  return { url: pageUrl, title, outline: [...header, "", ...body, ...footer].join("\n"), elements, truncated };
}

export type PageText = { url: string; title: string; text: string; truncated: boolean };

/** The page's readable text, as a question about it would send. */
export function pageText(doc: Document, options: { maxChars?: number; isVisible: Visibility }): PageText {
  const maxChars = Math.max(500, Math.min(MAX_TEXT_CHARS, options.maxChars ?? DEFAULT_TEXT_CHARS));
  const extract = extractPage(doc, {
    maxChars,
    maxSelectionChars: 0,
    isVisible: (el) => el.id !== OVERLAY_ID && options.isVisible(el),
    isTextVisible: isTextRendered,
    isBlock: isBlockDisplayed,
  });
  return { url: extract.url, title: extract.title, text: extract.text, truncated: extract.truncated };
}

export type Match = { ref: string; role: string; name: string; snippet?: string };

const TEXT_BLOCKS = new Set(["P", "LI", "TD", "TH", "DT", "DD", "BLOCKQUOTE", "FIGCAPTION", "LABEL", "SPAN", "DIV", "PRE", "CODE"]);

/** Elements whose name, value or text contains `query`: the ones a person could use first, then text. */
export function find(doc: Document, query: unknown, isVisible: Visibility): Result<{ matches: Match[] }> {
  const q = typeof query === "string" ? squash(query).toLowerCase() : "";
  if (!q || q.length > 200) return { ok: false, error: "bad_request", message: "Say what to look for, in up to 200 characters." };
  prune();
  const usable: Match[] = [];
  const text: Match[] = [];
  const root = doc.body ?? doc.documentElement;
  for (const el of visibleElements(root, isVisible)) {
    if (usable.length >= MAX_FIND_RESULTS) break;
    const role = roleOf(el);
    if (role) {
      const info = describeElement(el, role, isVisible);
      if (`${info.name} ${info.value ?? ""}`.toLowerCase().includes(q)) usable.push({ ref: info.ref, role, name: info.name });
      continue;
    }
    if (text.length >= MAX_FIND_RESULTS || !(TEXT_BLOCKS.has(el.tagName.toUpperCase()) || headingLevel(el) !== null)) continue;
    // The innermost element holding the words: its own text nodes contain them.
    const own = squash(Array.from(el.childNodes, (child) => (child.nodeType === Node.TEXT_NODE ? child.nodeValue ?? "" : " ")).join(""));
    const at = own.toLowerCase().indexOf(q);
    if (at < 0 || !isTextRendered(el)) continue;
    const start = Math.max(0, at - 50);
    const snippet = `${start > 0 ? "…" : ""}${own.slice(start, at + q.length + 70)}${at + q.length + 70 < own.length ? "…" : ""}`;
    text.push({ ref: refFor(el), role: headingLevel(el) !== null ? "heading" : "text", name: "", snippet });
  }
  const matches = [...usable, ...text].slice(0, MAX_FIND_RESULTS);
  if (!matches.length) return { ok: false, error: "not_found", message: `Nothing visible on the page matches "${clip(q, 60)}".` };
  return { ok: true, matches };
}

// --- what the agent does -------------------------------------------------------------------

function usable(ref: unknown, isVisible: Visibility): Element | Failure {
  const el = resolve(ref);
  if (isFailure(el)) return el;
  for (let node: Element | null = el; node; node = node.parentElement) {
    if (!isVisible(node)) return { ok: false, error: "not_visible", message: `Element ${ref as string} is not visible.` };
  }
  if (isDisabled(el)) return { ok: false, error: "disabled", message: `Element ${ref as string} is disabled.` };
  return el;
}

function pointer(el: Element, type: string, x: number, y: number): void {
  const init = { bubbles: true, cancelable: true, composed: true, clientX: x, clientY: y, button: 0 };
  const view = el.ownerDocument.defaultView;
  const Ctor = type.startsWith("pointer") && view && "PointerEvent" in view ? view.PointerEvent : view?.MouseEvent ?? MouseEvent;
  el.dispatchEvent(new Ctor(type, { ...init, ...(type.startsWith("pointer") ? { pointerId: 1, isPrimary: true, pointerType: "mouse" } : {}) }));
}

/** Whether something else - a dialog, a cookie banner - sits on top of the element's middle. */
function coveredBy(el: Element): Element | null {
  const doc = el.ownerDocument;
  if (typeof doc.elementFromPoint !== "function") return null;
  const rect = el.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const top = doc.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
  if (!top || el.contains(top) || holds(top, el)) return null;
  // Our own overlay is never in the way.
  if (top.id === OVERLAY_ID || top.closest(`#${OVERLAY_ID}`)) return null;
  return top;
}

/**
 * Whether `outer` is `el` or holds it, across shadow roots: the document
 * reports a point inside a web component as the component itself.
 */
function holds(outer: Element, el: Element): boolean {
  let node: Element | null = el;
  while (node) {
    if (node === outer) return true;
    const parent: Element | null = node.parentElement;
    if (parent) {
      node = parent;
      continue;
    }
    const root = node.getRootNode();
    node = root instanceof ShadowRoot ? root.host : null;
  }
  return false;
}

export function click(ref: unknown, isVisible: Visibility): Result<{ note?: string }> {
  const named = usable(ref, isVisible);
  if (isFailure(named)) return named;
  // What the rules judged (describe with `activates`): the control the click works on.
  const el = activationTarget(named);
  if (el !== named && isDisabled(el)) return { ok: false, error: "disabled", message: `Element ${ref as string} is disabled.` };
  const html = el as HTMLElement;
  el.scrollIntoView?.({ block: "center", inline: "center" });
  const cover = coveredBy(el);
  if (cover) {
    const role = roleOf(cover);
    const name = role ? accessibleName(cover, role) : visibleText(cover, isVisible, 60);
    return { ok: false, error: "covered", message: `Something covers element ${ref as string}${name ? `: "${name}"` : ""}. Close it first.` };
  }
  const rect = el.getBoundingClientRect();
  const x = rect.left + rect.width / 2;
  const y = rect.top + rect.height / 2;
  pointer(el, "pointerdown", x, y);
  pointer(el, "mousedown", x, y);
  html.focus?.({ preventScroll: true });
  pointer(el, "pointerup", x, y);
  pointer(el, "mouseup", x, y);
  if (typeof html.click === "function") html.click();
  else pointer(el, "click", x, y);
  if (el.tagName.toUpperCase() === "SELECT") return { ok: true, note: "A menu does not open for the agent: use select_option." };
  return { ok: true };
}

function nativeSetter(el: Element): ((value: string) => void) | null {
  const view = el.ownerDocument.defaultView;
  const tag = el.tagName.toUpperCase();
  const proto =
    tag === "TEXTAREA" ? view?.HTMLTextAreaElement.prototype : tag === "SELECT" ? view?.HTMLSelectElement.prototype : view?.HTMLInputElement.prototype;
  const setter = proto ? Object.getOwnPropertyDescriptor(proto, "value")?.set : undefined;
  return setter ? (value: string) => setter.call(el, value) : null;
}

function fire(el: Element, type: "input" | "change", data?: string): void {
  const view = el.ownerDocument.defaultView;
  const event =
    type === "input" && view && "InputEvent" in view
      ? new view.InputEvent("input", { bubbles: true, composed: true, inputType: "insertText", data: data ?? null })
      : new (view?.Event ?? Event)(type, { bubbles: true });
  el.dispatchEvent(event);
}

const TYPABLE_INPUTS = new Set([...TEXT_INPUTS, "date", "time", "datetime-local", "month", "week", "color"]);

export function typeText(ref: unknown, text: unknown, clear: unknown, isVisible: Visibility): Result<{ note: string }> {
  if (typeof text !== "string" || text.length > 10_000) {
    return { ok: false, error: "bad_request", message: "Give the text to type, up to 10,000 characters." };
  }
  const el = usable(ref, isVisible);
  if (isFailure(el)) return el;
  const tag = el.tagName.toUpperCase();
  const editable = (el as HTMLElement).isContentEditable;
  const typable = tag === "TEXTAREA" || (tag === "INPUT" && TYPABLE_INPUTS.has(inputType(el))) || editable;
  if (!typable) return { ok: false, error: "not_typable", message: `Element ${ref as string} is not a text field.` };
  if (isSensitiveField(el)) {
    return { ok: false, error: "sensitive_field", message: "The agent never types into password, card or one-time-code fields. Ask the user to fill it in." };
  }
  const html = el as HTMLElement;
  el.scrollIntoView?.({ block: "center" });
  html.focus?.({ preventScroll: true });
  if (tag === "INPUT" || tag === "TEXTAREA") {
    const field = el as HTMLInputElement | HTMLTextAreaElement;
    if (field.readOnly) return { ok: false, error: "read_only", message: `Element ${ref as string} cannot be changed.` };
    const insert = tag === "INPUT" ? text.replace(/\s*\n\s*/g, " ") : text;
    let next = clear === true ? insert : `${field.value}${insert}`;
    if (field.maxLength > 0) next = next.slice(0, field.maxLength);
    const setter = nativeSetter(el);
    if (setter) setter(next);
    else field.value = next;
    fire(el, "input", insert);
    fire(el, "change");
    return { ok: true, note: `Typed ${insert.length} characters; the field now holds ${field.value.length}.` };
  }
  // An editor: the page's own editing command keeps its undo and its model in step.
  const doc = el.ownerDocument;
  const selection = doc.getSelection();
  if (selection) {
    const range = doc.createRange();
    range.selectNodeContents(el);
    if (clear !== true) range.collapse(false);
    selection.removeAllRanges();
    selection.addRange(range);
  }
  const typed = typeof doc.execCommand === "function" && doc.execCommand("insertText", false, text);
  if (!typed) {
    if (clear === true) el.textContent = text;
    else el.append(doc.createTextNode(text));
    fire(el, "input", text);
  }
  return { ok: true, note: `Typed ${text.length} characters.` };
}

export function selectOption(ref: unknown, value: unknown, isVisible: Visibility): Result<{ note: string }> {
  if (typeof value !== "string" || !value.trim() || value.length > 500) {
    return { ok: false, error: "bad_request", message: "Say which option to choose." };
  }
  const el = usable(ref, isVisible);
  if (isFailure(el)) return el;
  if (el.tagName.toUpperCase() !== "SELECT") {
    return { ok: false, error: "not_select", message: `Element ${ref as string} is not a menu: click it, then click the option.` };
  }
  const select = el as HTMLSelectElement;
  const wanted = squash(value).toLowerCase();
  const options = Array.from(select.options);
  const option =
    options.find((o) => o.value === value) ??
    options.find((o) => squash(o.label || o.text).toLowerCase() === wanted) ??
    options.find((o) => squash(o.label || o.text).toLowerCase().includes(wanted));
  if (!option) {
    const names = options.slice(0, MAX_OPTIONS).map((o) => squash(o.label || o.text)).join(" | ");
    return { ok: false, error: "no_option", message: `No option matches "${clip(value, 60)}". The options are: ${names}` };
  }
  if (option.disabled) return { ok: false, error: "disabled", message: `The option "${squash(option.label || option.text)}" cannot be chosen.` };
  select.focus?.({ preventScroll: true });
  const setter = nativeSetter(el);
  if (setter) setter(option.value);
  else select.value = option.value;
  fire(el, "input");
  fire(el, "change");
  return { ok: true, note: `Chose "${squash(option.label || option.text)}".` };
}

export function submitForm(ref: unknown, isVisible: Visibility): Result<{ note: string }> {
  const el = usable(ref, isVisible);
  if (isFailure(el)) return el;
  const form = formOf(el);
  if (!form) return { ok: false, error: "no_form", message: `Element ${ref as string} is not in a form.` };
  const invalid = Array.from(form.elements).filter(
    (field) => typeof (field as HTMLInputElement).checkValidity === "function" && !(field as HTMLInputElement).checkValidity(),
  );
  if (invalid.length) {
    const names = invalid.slice(0, 5).map((field) => {
      const role = roleOf(field) ?? "field";
      return accessibleName(field, role) || field.getAttribute("name") || role;
    });
    return { ok: false, error: "invalid_form", message: `The form is not complete: ${names.map(quoted).join(", ")}.` };
  }
  const submitter = submits(el) ? (el as HTMLButtonElement | HTMLInputElement) : undefined;
  if (typeof form.requestSubmit === "function") form.requestSubmit(submitter);
  else form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  return { ok: true, note: "The form was sent." };
}

/** Keys the agent may press, with the legacy codes some pages still read. */
const KEYS: Record<string, { code: string; keyCode: number }> = {
  Enter: { code: "Enter", keyCode: 13 },
  Tab: { code: "Tab", keyCode: 9 },
  Escape: { code: "Escape", keyCode: 27 },
  Backspace: { code: "Backspace", keyCode: 8 },
  Delete: { code: "Delete", keyCode: 46 },
  ArrowUp: { code: "ArrowUp", keyCode: 38 },
  ArrowDown: { code: "ArrowDown", keyCode: 40 },
  ArrowLeft: { code: "ArrowLeft", keyCode: 37 },
  ArrowRight: { code: "ArrowRight", keyCode: 39 },
  Home: { code: "Home", keyCode: 36 },
  End: { code: "End", keyCode: 35 },
  PageUp: { code: "PageUp", keyCode: 33 },
  PageDown: { code: "PageDown", keyCode: 34 },
  " ": { code: "Space", keyCode: 32 },
};

export function pressKey(doc: Document, key: unknown): Result<{ note: string }> {
  const name = key === "Space" ? " " : key;
  const known = typeof name === "string" ? KEYS[name] : undefined;
  if (typeof name !== "string" || !known) {
    return { ok: false, error: "bad_key", message: `The agent can press: ${Object.keys(KEYS).map((k) => (k === " " ? "Space" : k)).join(", ")}.` };
  }
  const target = (doc.activeElement && doc.activeElement !== doc.documentElement ? doc.activeElement : doc.body) ?? doc.documentElement;
  const view = doc.defaultView;
  for (const type of ["keydown", "keyup"] as const) {
    const event = new (view?.KeyboardEvent ?? KeyboardEvent)(type, { key: name, code: known.code, bubbles: true, cancelable: true, composed: true });
    Object.defineProperty(event, "keyCode", { get: () => known.keyCode });
    Object.defineProperty(event, "which", { get: () => known.keyCode });
    target.dispatchEvent(event);
  }
  return { ok: true, note: `Pressed ${name === " " ? "Space" : name}. A key from the agent reaches the page's own handlers only; it does not submit forms or move the focus by itself.` };
}

export function scroll(doc: Document, direction: unknown, ref: unknown, isVisible: Visibility): Result<{ note: string }> {
  if (ref !== undefined && ref !== null) {
    const el = usable(ref, isVisible);
    if (isFailure(el)) return el;
    el.scrollIntoView?.({ block: "center" });
    return { ok: true, note: `Element ${ref as string} is in view.` };
  }
  const view = doc.defaultView;
  const scroller = doc.scrollingElement ?? doc.documentElement;
  const page = view?.innerHeight || 800;
  const wide = view?.innerWidth || 1200;
  const moves: Record<string, [number, number] | "top" | "bottom"> = {
    down: [0, page * 0.8],
    up: [0, -page * 0.8],
    right: [wide * 0.8, 0],
    left: [-wide * 0.8, 0],
    top: "top",
    bottom: "bottom",
  };
  const move = typeof direction === "string" ? moves[direction] : undefined;
  if (!move) return { ok: false, error: "bad_request", message: "Scroll up, down, left, right, top or bottom, or to an element." };
  if (move === "top") scroller.scrollTo?.({ top: 0 });
  else if (move === "bottom") scroller.scrollTo?.({ top: scroller.scrollHeight });
  else scroller.scrollBy?.({ left: move[0], top: move[1] });
  return { ok: true, note: `Scrolled ${direction as string}: ${Math.round(scroller.scrollTop)} of ${Math.round(scroller.scrollHeight)} pixels from the top.` };
}

export async function waitFor(doc: Document, text: unknown, seconds: unknown): Promise<Result<{ note: string }>> {
  const limit = Math.max(0.1, Math.min(MAX_WAIT_SECONDS, typeof seconds === "number" && Number.isFinite(seconds) ? seconds : 2));
  const said = typeof text === "string" ? squash(text) : "";
  if (said.length > 200) return { ok: false, error: "bad_request", message: "Wait for at most 200 characters of text." };
  const wanted = said.toLowerCase();
  const present = () => squash((doc.body as HTMLElement | null)?.innerText ?? doc.body?.textContent ?? "").toLowerCase().includes(wanted);
  const deadline = Date.now() + limit * 1000;
  if (!wanted) {
    await new Promise((done) => setTimeout(done, limit * 1000));
    return { ok: true, note: `Waited ${limit} seconds.` };
  }
  const found = { ok: true as const, note: `"${clip(said, 60)}" is on the page.` };
  while (Date.now() < deadline) {
    if (present()) return found;
    await new Promise((done) => setTimeout(done, 200));
  }
  return present() ? found : { ok: false, error: "not_found", message: `"${clip(said, 60)}" did not appear within ${limit} seconds.` };
}

/**
 * One element as the rules judge it. With `activates` (for a click), the
 * control the click works on: the button around the words named, the field
 * of a label.
 */
export function describe(ref: unknown, isVisible: Visibility, activates = false): Result<{ element: ElementInfo }> {
  const named = resolve(ref);
  if (isFailure(named)) return named;
  const el = activates ? activationTarget(named) : named;
  const role = roleOf(el) ?? (headingLevel(el) !== null ? "heading" : "text");
  return { ok: true, element: describeElement(el, role, isVisible) };
}
