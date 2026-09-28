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

import { keyDefFor, KEY_NAMES_SHOWN, parseKeyCombo, type KeyCombo } from "../lib/keys";
import { looseName } from "../lib/refs";
import { isSensitiveField } from "../lib/sensitive";
import { extractPage, isBlockDisplayed, isTextRendered } from "./extract";
import { inOwnUi, isOwnHost } from "./own";

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
  /**
   * What the button that sends its form says (its name, and its own words
   * when they differ): sending the form from any of its fields presses that
   * button. Only when the panel asks about one element.
   */
  formButton?: string[];
  /** A menu's choices, the first few. */
  options?: string[];
  /** The option select_option would choose for the value asked about (describe's `choose`), as the menu shows it. */
  choice?: string;
  /**
   * A frame from another site, which this page cannot see into: the rules
   * cannot judge what a click there touches. Its site, when the frame says.
   */
  frame?: { host: string | null; path?: string };
  /**
   * The target is there but not to be seen: drawn (almost) transparent, or a
   * couple of pixels in size - the shape of a click hidden under something
   * else.
   */
  hidden?: "transparent" | "tiny";
  /** Its ARIA state, when it has one: a menu open or closed, a tab chosen, a toggle pressed, a field refused or required. */
  expanded?: boolean;
  selected?: boolean;
  pressed?: boolean;
  invalid?: boolean;
  required?: boolean;
  /** It has the keyboard (an outline's mark). */
  focused?: boolean;
  /**
   * For the rules only, never shown to the model: the words of the dialog or
   * notice it sits in ("We use cookies…", "Transfer 5,000,000 Rials?"), by
   * which a bare "Accept" or "OK" is judged.
   */
  context?: string;
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
  | "not_kept"
  | "bad_format"
  | "bad_request"
  | "not_found"
  | "stopped"
  | "paused"
  | "failed";

type Failure = { ok: false; error: AgentError; message: string };
export type Result<T extends object = object> = ({ ok: true } & T) | Failure;

const NAME_CHARS = 100;
const VALUE_CHARS = 100;
const MAX_OPTIONS = 20;
const DEFAULT_OUTLINE_CHARS = 12_000;
const MAX_OUTLINE_CHARS = 30_000;
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

/**
 * Number this document's new references from `from` on at least: the run
 * was told of references up to there on its pages before, and a new page's
 * e3 must not be taken for the e3 of the page before.
 */
export function raiseRefFloor(from: number): void {
  const s = state();
  if (Number.isFinite(from)) s.next = Math.max(s.next, Math.min(Math.floor(from) - 1, 900_000_000));
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

type DomApi = { dom?: { openOrClosedShadowRoot?: (el: Element) => ShadowRoot | null } };

/**
 * An element's shadow root, open or closed: a closed one the page keeps
 * from its own scripts, but an extension may read (chrome.dom), and a
 * person sees what is in it all the same.
 */
function shadowOf(el: Element): ShadowRoot | null {
  if (el.shadowRoot) return el.shadowRoot;
  try {
    return (globalThis as typeof globalThis & { chrome?: DomApi }).chrome?.dom?.openOrClosedShadowRoot?.(el) ?? null;
  } catch {
    return null;
  }
}

/** At most this many frames of the page's own site are read into, however deep. */
const MAX_FRAMES = 20;

/**
 * Every element a person could see, in page order: hidden ones and their
 * subtrees are skipped, shadow roots (open or closed) are entered through
 * their slots, frames of the page's own site are read into, and the agent's
 * own overlay is not part of the page.
 */
function* visibleElements(root: Element, isVisible: Visibility): Generator<Element> {
  const stack: Node[] = [root];
  let frames = 0;
  while (stack.length) {
    const node = stack.pop() as Node;
    if (node.nodeType === Node.DOCUMENT_FRAGMENT_NODE) {
      pushChildren(stack, Array.from(node.childNodes));
      continue;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) continue;
    const el = node as Element;
    if (SKIPPED.has(el.tagName.toUpperCase()) || isOwnHost(el) || el.hasAttribute("inert") || !isVisible(el)) continue;
    yield el;
    const tag = el.tagName.toUpperCase();
    if (tag === "SLOT") {
      const assigned = (el as HTMLSlotElement).assignedNodes?.({ flatten: true }) ?? [];
      pushChildren(stack, assigned.length ? assigned : Array.from(el.childNodes));
    } else if (tag === "IFRAME" || tag === "FRAME") {
      // A frame of this site is part of the page as a person sees it; one of another site stays closed.
      const inner = frames < MAX_FRAMES ? frameDocument(el) : null;
      if (inner?.body) {
        frames += 1;
        stack.push(inner.body);
      }
    } else {
      pushChildren(stack, Array.from((shadowOf(el) ?? el).childNodes));
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
    if (tag === "SLOT") {
      // A web component's slot shows what the page put in it ("Send" in <md-button>Send</md-button>), else its own words.
      const assigned = (child as HTMLSlotElement).assignedNodes?.({ flatten: true }) ?? [];
      pushChildren(stack, assigned.length ? assigned : Array.from(child.childNodes));
    } else pushChildren(stack, Array.from((shadowOf(child) ?? child).childNodes));
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

/** An element by its id, looked for where `el` is - its shadow root first, then its document - as aria-labelledby is resolved. */
function byId(el: Element, id: string): Element | null {
  const root = el.getRootNode() as Document | ShadowRoot;
  return (typeof root.getElementById === "function" ? root.getElementById(id) : null) ?? el.ownerDocument.getElementById(id);
}

/** The words of an element's labels; a label removed from the page (display: none) names nothing. */
function labelsOf(el: Element): string {
  const doc = el.ownerDocument;
  const found = new Set<Element>();
  const labels = (el as HTMLInputElement).labels;
  if (labels) for (const label of Array.from(labels)) found.add(label);
  if (el.id) {
    // Its labels are where it is: in its shadow root, when it is in one.
    const scope = el.getRootNode() as Document | ShadowRoot;
    for (const label of Array.from((typeof scope.querySelectorAll === "function" ? scope : doc).querySelectorAll("label"))) {
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
  const labelledBy = (el.getAttribute("aria-labelledby") ?? "").split(/\s+/).filter(Boolean);
  if (labelledBy.length) {
    const text = squash(
      labelledBy
        .map((id) => {
          const target = byId(el, id);
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
  const wrapped = wrappedControl(el);
  if (wrapped) return wrapped;
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
  // A menu drawn by the page: what it shows is what is chosen.
  if (role === "combobox" && tag !== "INPUT" && tag !== "SELECT") {
    const shown = squash(el.getAttribute("aria-valuetext") ?? (el as HTMLElement).innerText ?? el.textContent ?? "");
    if (shown) return clip(shown, VALUE_CHARS);
  }
  const aria = el.getAttribute("aria-valuetext") ?? el.getAttribute("aria-valuenow");
  return aria ? clip(aria, VALUE_CHARS) : undefined;
}

/** A field the browser says holds what it will not take, once the person has changed it (:user-invalid). */
function userInvalid(el: Element): boolean {
  try {
    return el.matches(":user-invalid");
  } catch {
    return false;
  }
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

/** The button that sends a form when it is sent from one of its fields: its first submit button. */
function defaultButton(form: HTMLFormElement): Element | null {
  return Array.from(form.elements).find((field) => submits(field)) ?? null;
}

/** What holds a control that answers something: a dialog, or a notice that says it is about cookies. */
const NOTICES = '[role="dialog"], [role="alertdialog"], dialog, [aria-modal="true"]';
const COOKIE_NOTICE = /cookie|consent|gdpr/i;
const CONTEXT_CHARS = 200;

/** The words of the dialog or cookie notice `el` sits in, for the rules; none when it sits in neither. */
function contextOf(el: Element, isVisible: Visibility): string | undefined {
  let node = parentAcrossShadow(el);
  for (let depth = 0; node && depth < 25; node = parentAcrossShadow(node), depth += 1) {
    const hint = `${node.id} ${node.getAttribute("class") ?? ""} ${node.getAttribute("aria-label") ?? ""}`;
    if (!node.matches(NOTICES) && !COOKIE_NOTICE.test(hint)) continue;
    const words = squash(`${node.getAttribute("aria-label") ?? ""} ${visibleText(node, isVisible, CONTEXT_CHARS)}`);
    return words ? clip(words, CONTEXT_CHARS) : undefined;
  }
  return undefined;
}

/**
 * Everything the panel's rules and the model need to know about one element;
 * `forRules` adds what only the rules need about a single element (its
 * form's destination and sending button).
 */
function describeElement(el: Element, role: string, isVisible: Visibility, forRules = false): ElementInfo {
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
  const aria = (name: string) => el.getAttribute(name);
  if (aria("aria-expanded") === "true") info.expanded = true;
  else if (aria("aria-expanded") === "false") info.expanded = false;
  if (aria("aria-selected") === "true") info.selected = true;
  if (aria("aria-pressed") === "true") info.pressed = true;
  if (aria("aria-invalid") === "true" || userInvalid(el)) info.invalid = true;
  if ((el as HTMLInputElement).required === true || aria("aria-required") === "true") info.required = true;
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
  if (action && (forRules || info.submits || role === "textbox" || el.tagName.toUpperCase() === "FORM")) info.formAction = action;
  const form = forRules ? formOf(el) : null;
  const button = form ? defaultButton(form) : null;
  if (button) {
    const buttonRole = roleOf(button) ?? "button";
    const said = [accessibleName(button, buttonRole), ownWords(button, buttonRole, isVisible)].filter(Boolean);
    if (said.length) info.formButton = [...new Set(said)];
  }
  if (forRules) {
    const context = contextOf(el, isVisible);
    if (context) info.context = context;
  }
  if (el.tagName.toUpperCase() === "SELECT") {
    info.options = Array.from((el as HTMLSelectElement).options)
      .slice(0, MAX_OPTIONS)
      .map((option) => clip(option.label || option.text, 60));
  }
  return info;
}

/** Controls a page often hides under a styled label: a person sees and clicks the label. */
const LABELLED_CONTROLS = new Set(["checkbox", "radio", "file"]);

/**
 * A label standing in for the control it names, when that control is not
 * drawn - an opacity-0 or screen-reader-only checkbox, switch or file input
 * under a styled label: the label is what a person sees and clicks, so it is
 * listed with the control's role, name and state, and its reference is the
 * label's (a click on it works the control).
 */
function labelProxy(el: Element, isVisible: Visibility): { control: Element; role: string } | null {
  if (el.tagName.toUpperCase() !== "LABEL") {
    // The box a styled checkbox draws around its invisible input (MUI, a data grid's row box), when no label names it.
    const wrapped = wrappedControl(el);
    const role = wrapped ? roleOf(wrapped) : null;
    return wrapped && role ? { control: wrapped, role } : null;
  }
  const control = (el as HTMLLabelElement).control;
  if (!control || control.tagName.toUpperCase() !== "INPUT" || !LABELLED_CONTROLS.has(inputType(control))) return null;
  if (isVisible(control)) return null;
  const role = roleOf(control);
  return role ? { control, role } : null;
}

/** Controls a styled box draws itself for, over an invisible native input. */
const STYLED_INPUTS = new Set(["checkbox", "radio"]);

/**
 * A checkbox or radio drawn invisible over its own styled box - MUI and Ant
 * Design put an opacity-0 input on top of what they draw - in a box that is
 * seen: a click there goes to the input, as a person's does.
 */
function styledInput(el: Element): boolean {
  if (el.tagName.toUpperCase() !== "INPUT" || !STYLED_INPUTS.has(inputType(el))) return false;
  const view = el.ownerDocument.defaultView;
  const box = parentAcrossShadow(el);
  if (!view || !box) return false;
  const opacity = Number.parseFloat(view.getComputedStyle(el).opacity);
  return Number.isFinite(opacity) && opacity < FAINT && !drawnFaint(box);
}

/** The invisible input a box without a role of its own draws, when no label names it (a label stands in for it then). */
function wrappedControl(el: Element): Element | null {
  if (el.tagName.toUpperCase() === "LABEL" || roleOf(el)) return null;
  const inputs = Array.from(el.children).filter((child) => styledInput(child) && !(child as HTMLInputElement).labels?.length);
  return inputs.length === 1 ? inputs[0] : null;
}

/** The label's entry for the hidden control it stands in for. */
function describeProxy(label: Element, proxy: { control: Element; role: string }, isVisible: Visibility): ElementInfo {
  return { ...describeElement(proxy.control, proxy.role, isVisible), ref: refFor(label) };
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
  if (info.focused) notes.push("focused");
  if (info.checked !== undefined) notes.push(info.checked ? "checked" : "not checked");
  if (info.expanded !== undefined) notes.push(info.expanded ? "expanded" : "collapsed");
  if (info.selected) notes.push("selected");
  if (info.pressed) notes.push("pressed");
  if (info.invalid) notes.push("invalid");
  if (info.required) notes.push("required");
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

/** At most this many usable elements are looked at for one outline, however long the page. */
const MAX_SCANNED_ELEMENTS = 2000;
/** find looks at no more than this many visible elements of a page. */
const MAX_FIND_SCANNED = 30_000;
/** What a page opens over the rest: while one is up, it is where the person acts. */
const DIALOGS = 'dialog[open], [role="dialog"], [role="alertdialog"], [aria-modal="true"]';
/** What the element with the keyboard is part of: the part of the page the person works in. */
const CONTAINERS = 'form, [role="dialog"], [role="alertdialog"], [role="region"], [role="search"], [role="toolbar"], [role="menu"], [role="listbox"], [role="grid"], [role="tree"], [role="tabpanel"], section, article, aside, nav, main';
/** Where a page says what just happened. */
const LIVE = '[role="alert"], [role="status"], [aria-live="assertive"], [aria-live="polite"]';
const GROUP_TITLES = ["Open dialog", "Where the keyboard is", "In the window", "Further on the page (scroll, or use find)"];

/** Whether the element can be seen in the window: its box meets the window and every area that clips it. */
function inView(el: Element): boolean {
  const view = el.ownerDocument.defaultView;
  const r = el.getBoundingClientRect();
  // No layout to go by (a document not drawn): nothing to say it is out of view.
  if (!r.width && !r.height) return true;
  const width = view?.innerWidth || el.ownerDocument.documentElement.clientWidth;
  const height = view?.innerHeight || el.ownerDocument.documentElement.clientHeight;
  if (r.bottom <= 0 || r.right <= 0 || r.top >= height || r.left >= width) return false;
  // A list that scrolls inside the page shows only part of what is in it.
  for (let node = parentAcrossShadow(el), depth = 0; node && depth < 40; node = parentAcrossShadow(node), depth += 1) {
    if (node === el.ownerDocument.body || node === el.ownerDocument.documentElement) break;
    if (!(scrollsItself(node, "y") || scrollsItself(node, "x"))) continue;
    const c = node.getBoundingClientRect();
    if (r.bottom <= c.top || r.top >= c.bottom || r.right <= c.left || r.left >= c.right) return false;
  }
  // In a frame, the frame itself has to be in view as well.
  let frame: Element | null = null;
  try {
    frame = view?.frameElement ?? null;
  } catch {
    frame = null;
  }
  return frame ? inView(frame) : true;
}

/** The dialogs open on the page now: shown, and not the agent's own. */
function openDialogs(doc: Document, isVisible: Visibility): Element[] {
  return Array.from(doc.querySelectorAll(DIALOGS)).filter((el) => {
    if (inOwnUi(el)) return false;
    for (let node: Element | null = el; node; node = parentAcrossShadow(node)) if (!isVisible(node)) return false;
    return true;
  });
}

/** A live region's words as an outline line, when it says something. */
function liveLine(el: Element, isVisible: Visibility): string | null {
  if (!el.matches(LIVE)) return null;
  const role = (el.getAttribute("role") ?? "").trim().toLowerCase();
  const words = visibleText(el, isVisible, 200);
  return words ? `(${role === "alert" || el.getAttribute("aria-live") === "assertive" ? "alert" : "status"}) ${quoted(words)}` : null;
}

/**
 * The page as the agent sees it: its headings and the elements a person
 * could use, each with a reference. What matters first comes first - an
 * open dialog, then the part of the page the keyboard is in, then what is
 * in the window, then the rest - within a budget of characters; `page`
 * gives the next parts of a long outline, and `root` (a scope) only the
 * part of the page under an element.
 */
export function snapshot(doc: Document, options: { maxChars?: number; isVisible: Visibility; root?: Element; page?: number }): Snapshot {
  prune();
  const { isVisible } = options;
  const maxChars = Math.max(1000, Math.min(MAX_OUTLINE_CHARS, options.maxChars ?? DEFAULT_OUTLINE_CHARS));
  const wanted = Math.max(1, Math.min(50, Math.floor(options.page ?? 1)));
  const pageUrl = doc.location?.href ?? "";
  const dialogs = options.root ? [] : openDialogs(doc, isVisible);
  const focused = focusedElement(doc);
  const around = focused && !options.root ? focused.closest(CONTAINERS) : null;
  const groupOf = (el: Element): number => {
    if (dialogs.some((d) => holds(d, el))) return 0;
    if (around && holds(around, el)) return 1;
    return inView(el) ? 2 : 3;
  };
  const lines: Array<{ text: string; group: number; info?: ElementInfo }> = [];
  // At most so many elements of each part are looked at: a long page's end never crowds out its open dialog.
  const scanned = [0, 0, 0, 0];
  let skipped = 0;
  const root = options.root ?? doc.body ?? doc.documentElement;
  for (const el of visibleElements(root, isVisible)) {
    const level = headingLevel(el);
    if (level !== null) {
      const text = visibleText(el, isVisible, NAME_CHARS);
      if (text) lines.push({ text: `${"#".repeat(level)} ${text}`, group: groupOf(el) });
      continue;
    }
    const live = liveLine(el, isVisible);
    if (live) lines.push({ text: live, group: groupOf(el) });
    const proxy = labelProxy(el, isVisible);
    const role = proxy ? proxy.role : roleOf(el);
    if (!role) continue;
    const group = groupOf(el);
    if (scanned[group] >= MAX_SCANNED_ELEMENTS) {
      skipped += 1;
      continue;
    }
    scanned[group] += 1;
    const info = proxy ? describeProxy(el, proxy, isVisible) : describeElement(el, role, isVisible);
    if (focused && (el === focused || (proxy && proxy.control === focused))) info.focused = true;
    lines.push({ text: outlineLine(info, pageUrl), group, info });
  }
  // What matters first, each part in the page's order.
  const ordered = [0, 1, 2, 3].flatMap((group) => lines.filter((line) => line.group === group));
  const groups = new Set(ordered.map((line) => line.group));
  const titled = groups.size > 1 || groups.has(0) || groups.has(1);
  // Pages of the outline, each within the budget; the one asked for is shown.
  const pages: Array<typeof ordered> = [[]];
  let length = 0;
  for (const line of ordered) {
    const cost = line.text.length + 1;
    if (length + cost > maxChars && pages[pages.length - 1].length) {
      pages.push([]);
      length = 0;
    }
    pages[pages.length - 1].push(line);
    length += cost;
  }
  const shown = pages[Math.min(wanted, pages.length) - 1] ?? [];
  const body: string[] = [];
  let last = -1;
  for (const line of shown) {
    if (titled && line.group !== last) {
      const dialogName = line.group === 0 && dialogs.length ? accessibleName(dialogs[dialogs.length - 1], "dialog") : "";
      body.push(`${body.length ? "\n" : ""}${GROUP_TITLES[line.group]}${dialogName ? ` ${quoted(clip(dialogName, 80))}` : ""}:`);
      last = line.group;
    }
    body.push(line.text);
  }
  const elements = shown.flatMap((line) => (line.info ? [line.info] : []));
  const title = squash(doc.title ?? "").slice(0, 300);
  const header = [`Page: ${title || "(untitled)"}`, `URL: ${modelUrl(pageUrl)}`];
  const at = Math.min(wanted, pages.length);
  const truncated = pages.length > 1 || skipped > 0;
  const footer: string[] = [];
  if (pages.length > 1) {
    footer.push(at < pages.length ? `(Part ${at} of ${pages.length} of the outline: read_page with page: ${at + 1} for the next part, or scroll, or use find, to reach the rest.)` : `(Part ${at} of ${pages.length} of the outline: the last.)`);
  }
  if (skipped) footer.push(`(${skipped} more elements are not listed: scroll, or use find, to reach the rest.)`);
  const listed = body.length ? body : ["(No headings or usable elements are visible on this page.)"];
  return { url: pageUrl, title, outline: [...header, "", ...listed, ...footer].join("\n"), elements, truncated };
}

/** read_page as the panel asks for it: the whole page or the part under `scope` (a reference), one part of it at a time. */
export function readPage(doc: Document, args: { max_chars?: unknown; scope?: unknown; page?: unknown }, isVisible: Visibility): Result<Snapshot> {
  let root: Element | undefined;
  if (args.scope !== undefined && args.scope !== null && args.scope !== "") {
    const found = usable(args.scope, isVisible);
    if (isFailure(found)) return found;
    root = found;
  }
  const count = (value: unknown) => (typeof value === "number" && Number.isFinite(value) ? value : undefined);
  return { ok: true, ...snapshot(doc, { maxChars: count(args.max_chars), isVisible, root, page: count(args.page) }) };
}

export type PageText = { url: string; title: string; text: string; truncated: boolean };

/** The page's readable text, as a question about it would send. */
export function pageText(doc: Document, options: { maxChars?: number; isVisible: Visibility }): PageText {
  const maxChars = Math.max(500, Math.min(MAX_TEXT_CHARS, options.maxChars ?? DEFAULT_TEXT_CHARS));
  const extract = extractPage(doc, {
    maxChars,
    maxSelectionChars: 0,
    isVisible: (el) => !isOwnHost(el) && options.isVisible(el),
    isTextVisible: isTextRendered,
    isBlock: isBlockDisplayed,
  });
  // An open dialog and what the page announces sit outside its main text, often at the end of the page: they come first.
  const first: string[] = [];
  const said = (words: string) => !words || extract.text.includes(words.slice(0, 120));
  for (const dialog of openDialogs(doc, options.isVisible)) {
    const name = accessibleName(dialog, "dialog");
    const words = visibleText(dialog, options.isVisible, 2000);
    if (!said(words)) first.push(`Open dialog${name ? ` ${quoted(clip(name, 80))}` : ""}: ${words}`);
  }
  for (const el of Array.from(doc.querySelectorAll(LIVE)).slice(0, 20)) {
    if (inOwnUi(el) || !shownAll(el, options.isVisible)) continue;
    const line = liveLine(el, options.isVisible);
    const words = visibleText(el, options.isVisible, 200);
    if (line && !said(words)) first.push(line);
  }
  if (!first.length) return { url: extract.url, title: extract.title, text: extract.text, truncated: extract.truncated };
  const text = [...first, extract.text].filter(Boolean).join("\n\n");
  return { url: extract.url, title: extract.title, text: text.length > maxChars ? text.slice(0, maxChars) : text, truncated: extract.truncated || text.length > maxChars };
}

/** Shown to a person: the element and everything it sits in. */
function shownAll(el: Element, isVisible: Visibility): boolean {
  for (let node: Element | null = el, depth = 0; node && depth < 60; node = parentAcrossShadow(node), depth += 1) if (!isVisible(node)) return false;
  return true;
}

export type Match = { ref: string; role: string; name: string; snippet?: string };

const TEXT_BLOCKS = new Set(["P", "LI", "TD", "TH", "DT", "DD", "BLOCKQUOTE", "FIGCAPTION", "LABEL", "SPAN", "DIV", "PRE", "CODE"]);

/** How well words match a search, as a person scanning the page would judge it: the whole of it, a word's start, anywhere in it. */
function matchScore(fields: string[], q: string): number {
  let best = 0;
  for (const raw of fields) {
    const field = squash(raw).toLowerCase();
    if (!field) continue;
    if (field === q) return 3;
    const at = field.indexOf(q);
    if (at < 0) continue;
    best = Math.max(best, at === 0 || /[\s\p{P}]/u.test(field[at - 1]) ? 2 : 1);
  }
  return best;
}

/**
 * Elements whose name, value, placeholder or text contains `query`, best
 * first: what a person could use before plain text, then the whole name
 * matched before a word's start before anywhere in it, then what is in the
 * window before the rest, then the page's order. The first twenty.
 */
export function find(doc: Document, query: unknown, isVisible: Visibility): Result<{ matches: Match[] }> {
  const q = typeof query === "string" ? squash(query).toLowerCase() : "";
  if (!q || q.length > 200) return { ok: false, error: "bad_request", message: "Say what to look for, in up to 200 characters." };
  prune();
  type Found = Match & { score: number; usable: boolean; order: number; seen: boolean };
  const found: Found[] = [];
  let order = 0;
  let looked = 0;
  const root = doc.body ?? doc.documentElement;
  for (const el of visibleElements(root, isVisible)) {
    // Bounded by what is looked at, not by what matched: a page with no match is walked no further.
    looked += 1;
    if (order >= MAX_SCANNED_ELEMENTS * 2 || looked > MAX_FIND_SCANNED) break;
    const proxy = labelProxy(el, isVisible);
    const role = proxy ? proxy.role : roleOf(el);
    if (role) {
      const info = proxy ? describeProxy(el, proxy, isVisible) : describeElement(el, role, isVisible);
      const control = proxy ? proxy.control : el;
      const score = matchScore([info.name, info.value ?? "", info.text ?? "", control.getAttribute("placeholder") ?? "", control.getAttribute("aria-label") ?? "", control.getAttribute("title") ?? ""], q);
      if (score) found.push({ ref: info.ref, role, name: info.name, score, usable: true, order: order++, seen: inView(el) });
      continue;
    }
    if (!(TEXT_BLOCKS.has(el.tagName.toUpperCase()) || headingLevel(el) !== null)) continue;
    // The innermost element holding the words: its own text nodes contain them.
    const own = squash(Array.from(el.childNodes, (child) => (child.nodeType === Node.TEXT_NODE ? child.nodeValue ?? "" : " ")).join(""));
    const at = own.toLowerCase().indexOf(q);
    if (at < 0 || !isTextRendered(el)) continue;
    const start = Math.max(0, at - 50);
    const snippet = `${start > 0 ? "…" : ""}${own.slice(start, at + q.length + 70)}${at + q.length + 70 < own.length ? "…" : ""}`;
    found.push({ ref: refFor(el), role: headingLevel(el) !== null ? "heading" : "text", name: "", snippet, score: matchScore([own], q), usable: false, order: order++, seen: inView(el) });
  }
  found.sort((a, b) => Number(b.usable) - Number(a.usable) || b.score - a.score || Number(b.seen) - Number(a.seen) || a.order - b.order);
  const matches = found.slice(0, MAX_FIND_RESULTS).map(({ ref, role, name, snippet }) => (snippet === undefined ? { ref, role, name } : { ref, role, name, snippet }));
  if (!matches.length) return { ok: false, error: "not_found", message: `Nothing visible on the page matches "${clip(q, 60)}".` };
  return { ok: true, matches };
}

/**
 * The references of the elements now on the page with this role and name
 * (loosely: counts aside) - to find again what a reference used to name,
 * when the page has put something else under it. The first three.
 */
export function findRef(doc: Document, role: unknown, name: unknown, isVisible: Visibility): Result<{ refs: string[] }> {
  if (typeof role !== "string" || typeof name !== "string" || !role || name.length > 200) {
    return { ok: false, error: "bad_request", message: "Give the role and the name to look for." };
  }
  const wanted = looseName(name);
  const refs: string[] = [];
  for (const el of visibleElements(doc.body ?? doc.documentElement, isVisible)) {
    const proxy = labelProxy(el, isVisible);
    const found = proxy ? proxy.role : roleOf(el);
    if (found !== role) continue;
    const info = proxy ? describeProxy(el, proxy, isVisible) : describeElement(el, found, isVisible);
    if (looseName(info.name) === wanted) refs.push(info.ref);
    if (refs.length >= 3) break;
  }
  return { ok: true, refs };
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
  if (inOwnUi(top)) return null;
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

/** What a click on `named` presses: its control, or - when that control is not drawn - the label that stands in for it. */
function pressedFor(named: Element, target: Element, isVisible: Visibility): Element {
  if (target === named || isVisible(target)) return target;
  const label = named.tagName.toUpperCase() === "LABEL" ? named : named.closest("label");
  return label && (label as HTMLLabelElement).control === target ? label : target;
}

export function click(ref: unknown, isVisible: Visibility): Result<{ note?: string }> {
  const named = usable(ref, isVisible);
  if (isFailure(named)) return named;
  // What the rules judged (describe with `activates`): the control the click works on.
  const target = activationTarget(named);
  if (target !== named && isDisabled(target)) return { ok: false, error: "disabled", message: `Element ${ref as string} is disabled.` };
  // A hidden checkbox under its styled label: the label is what is pressed, as a person would; it works the control.
  const el = pressedFor(named, target, isVisible);
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
/** Fields whose value is one whole thing (a date, a number, a colour): typing replaces it, as adding to it would make it invalid. */
const WHOLE_VALUE_INPUTS = new Set(["date", "time", "datetime-local", "month", "week", "number", "color"]);
/** How each of those fields takes its value: the browser drops anything else, and the field is left empty. */
const VALUE_FORMATS: Record<string, string> = {
  date: "a date written 2026-09-28 (year-month-day)",
  time: "a time written 14:30 (24-hour)",
  "datetime-local": "a date and time written 2026-09-28T14:30",
  month: "a month written 2026-09",
  week: "a week written 2026-W39",
  number: "a number in digits, with a dot for decimals and nothing between thousands (1234.5)",
  color: "a colour written #1a2b3c",
};
/** How long the page gets to put a value back before the agent reads it again. */
const READ_BACK_MS = 60;

/** A text field's caret or selection, when the field has one (an email or number field has none). */
function selectionOf(field: HTMLInputElement | HTMLTextAreaElement): { start: number; end: number } | null {
  try {
    const start = field.selectionStart;
    const end = field.selectionEnd;
    return typeof start === "number" && typeof end === "number" ? { start, end } : null;
  } catch {
    return null;
  }
}

/** Tell the page text is about to go in, as a browser does; false when the page took it over (it cancelled the event). */
function beforeInput(el: Element, inputType: string, data: string | null): boolean {
  const view = el.ownerDocument.defaultView;
  if (!view || !("InputEvent" in view)) return true;
  return el.dispatchEvent(new view.InputEvent("beforeinput", { bubbles: true, cancelable: true, composed: true, inputType, data }));
}

/**
 * Where typed text goes in an editor: at the caret when it is in the editor;
 * otherwise at the start of it - above a signature or a quoted message, where
 * a person clicking into a new message starts - or over all of it with `clear`.
 */
function placeCaret(el: Element, clear: boolean): void {
  const doc = el.ownerDocument;
  const selection = doc.getSelection();
  if (!selection) return;
  const inside = selection.rangeCount > 0 && el.contains(selection.getRangeAt(0).startContainer);
  if (inside && !clear) return;
  const range = doc.createRange();
  range.selectNodeContents(el);
  if (!clear) {
    // The first block's start: down through the first children to text, so the caret is inside the first line.
    let node: Node = el;
    while (node.firstChild && node.firstChild.nodeType === Node.ELEMENT_NODE && !["BR", "IMG"].includes((node.firstChild as Element).tagName)) node = node.firstChild;
    range.setStart(node, 0);
    range.collapse(true);
  }
  selection.removeAllRanges();
  selection.addRange(range);
}

export async function typeText(ref: unknown, text: unknown, clear: unknown, isVisible: Visibility): Promise<Result<{ note: string }>> {
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
  const view = el.ownerDocument.defaultView;
  const tick = () => new Promise((done) => (view ?? globalThis).setTimeout(done, READ_BACK_MS));
  if (tag === "INPUT" || tag === "TEXTAREA") {
    const field = el as HTMLInputElement | HTMLTextAreaElement;
    if (field.readOnly) return { ok: false, error: "read_only", message: `Element ${ref as string} cannot be changed.` };
    const insert = tag === "INPUT" ? text.replace(/\s*\n\s*/g, " ") : text;
    const whole = tag === "INPUT" && WHOLE_VALUE_INPUTS.has(inputType(el));
    const at = whole || clear === true ? null : selectionOf(field);
    const before = field.value;
    let next: string;
    let caret: number | null = null;
    if (whole || clear === true) next = insert;
    else if (at && field.ownerDocument.activeElement === field && (at.start !== before.length || at.end !== before.length)) {
      // Where the caret is: a person's typing goes there, not always at the end.
      next = `${before.slice(0, at.start)}${insert}${before.slice(at.end)}`;
      caret = at.start + insert.length;
    } else next = `${before}${insert}`;
    if (field.maxLength > 0) next = next.slice(0, field.maxLength);
    if (beforeInput(el, whole || clear === true ? "insertReplacementText" : "insertText", insert)) {
      const setter = nativeSetter(el);
      if (setter) setter(next);
      else field.value = next;
      if (caret !== null && selectionOf(field)) {
        try {
          field.setSelectionRange(Math.min(caret, field.value.length), Math.min(caret, field.value.length));
        } catch {
          // A field without a caret.
        }
      }
      fire(el, "input", insert);
      fire(el, "change");
      // A date, number or colour field drops a value not in its format: the old one goes back, and the model is told the format.
      if (whole && field.value !== next && next !== "") {
        if (setter) setter(before);
        else field.value = before;
        fire(el, "input", before);
        fire(el, "change");
        const type = inputType(el);
        return { ok: false, error: "bad_format", message: `Element ${ref as string} is a ${type} field and did not take the text: it takes ${VALUE_FORMATS[type] ?? "a value in its own format"}.` };
      }
    }
    await tick();
    // Read back: a page that keeps its own copy of the value can put the old one back.
    if (field.value === before && next !== before) {
      return { ok: false, error: "not_kept", message: `The page did not keep the text: element ${ref as string} still holds what it held before.` };
    }
    return { ok: true, note: `Typed ${insert.length} characters; the field now holds ${field.value.length}.` };
  }
  // An editor: the page's own editing command keeps its undo and its model in step.
  const doc = el.ownerDocument;
  placeCaret(el, clear === true);
  const beforeText = squash(el.textContent ?? "");
  if (beforeInput(el, clear === true ? "insertReplacementText" : "insertText", text)) {
    const typed = typeof doc.execCommand === "function" && doc.execCommand("insertText", false, text);
    if (!typed) {
      if (clear === true) el.textContent = text;
      else {
        const selection = doc.getSelection();
        const range = selection && selection.rangeCount ? selection.getRangeAt(0) : null;
        if (range && el.contains(range.startContainer)) {
          range.deleteContents();
          range.insertNode(doc.createTextNode(text));
        } else el.prepend(doc.createTextNode(text));
      }
      fire(el, "input", text);
    }
  }
  await tick();
  const nowText = squash(el.textContent ?? "");
  if (squash(text) && nowText === beforeText && (clear !== true || beforeText !== squash(text))) {
    return { ok: false, error: "not_kept", message: `The editor did not take the text: element ${ref as string} holds what it held before.` };
  }
  return { ok: true, note: `Typed ${text.length} characters.` };
}

/** The option a menu would take for `value`: by its value, then its exact label, then a label containing it. */
function matchOption(select: HTMLSelectElement, value: string): HTMLOptionElement | undefined {
  const wanted = squash(value).toLowerCase();
  const options = Array.from(select.options);
  return (
    options.find((o) => o.value === value) ??
    options.find((o) => squash(o.label || o.text).toLowerCase() === wanted) ??
    options.find((o) => squash(o.label || o.text).toLowerCase().includes(wanted))
  );
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
  const options = Array.from(select.options);
  const option = matchOption(select, value);
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
  // The way the site sends it: a click on its submit button, whose own handlers run - many pages send from
  // there, not from the form's submit event. The form alone is submitted only when it has no such button.
  const submitter = submits(el) ? el : defaultButton(form);
  if (submitter) {
    if (isDisabled(submitter)) return { ok: false, error: "disabled", message: "The form's send button is disabled: something it needs is missing." };
    const role = roleOf(submitter) ?? "button";
    const name = accessibleName(submitter, role) || ownWords(submitter, role, isVisible);
    (submitter as HTMLElement).click();
    return { ok: true, note: name ? `Pressed the form's ${quoted(clip(name, 60))} button.` : "Pressed the form's send button." };
  }
  if (typeof form.requestSubmit === "function") form.requestSubmit();
  else form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  return { ok: true, note: "The form was sent." };
}

/**
 * The element that has the keyboard: the focused element, followed into open
 * shadow roots and into same-site frames. When the focus is in a frame from
 * another site, this page cannot see into it, so the frame element itself is
 * returned - `describeFocus` marks it, and the rules treat it as unjudgeable.
 */
function focusedElement(doc: Document): Element | null {
  let el: Element | null = doc.activeElement;
  for (let depth = 0; el && depth < MAX_FRAME_DEPTH; depth += 1) {
    const shadow = shadowOf(el);
    if (shadow?.activeElement) {
      el = shadow.activeElement;
      continue;
    }
    const tag = el.tagName?.toUpperCase();
    if (tag === "IFRAME" || tag === "FRAME") {
      const inner = frameDocument(el);
      const innerFocus = inner?.activeElement ?? null;
      // A frame of this site with the keyboard inside it: follow the focus in. Otherwise
      // (another site, or nothing focused within) the frame itself is where the keyboard is.
      if (innerFocus && innerFocus !== inner?.body && innerFocus !== inner?.documentElement) {
        el = innerFocus;
        continue;
      }
      return el;
    }
    break;
  }
  return el && el !== doc.body && el !== doc.documentElement ? el : null;
}

/** The element a key press would go to, for the rules: what Enter or Delete does depends on it. */
export function describeFocus(doc: Document, isVisible: Visibility): Result<{ element?: ElementInfo }> {
  const el = focusedElement(doc);
  if (!el) return { ok: true };
  const tag = el.tagName.toUpperCase();
  // Focus inside a frame from another site: report it as a frame the rules cannot judge, with the site it names.
  if (tag === "IFRAME" || tag === "FRAME") {
    const name = clip(squash(el.getAttribute("title") ?? el.getAttribute("name") ?? ""), NAME_CHARS);
    return { ok: true, element: { ref: refFor(el), role: "frame", name, tag: tag.toLowerCase(), frame: frameSite(el) } };
  }
  const role = roleOf(el) ?? (headingLevel(el) !== null ? "heading" : "text");
  return { ok: true, element: describeElement(el, role, isVisible, true) };
}

const TABBABLE = 'a[href], area[href], button, input, select, textarea, summary, iframe, [tabindex], [contenteditable=""], [contenteditable="true"]';

/**
 * What can take the keyboard with Tab, as a browser has it (roughly): in the
 * document's order - a web component's controls where the component is,
 * open or closed - positive tabindex first.
 */
function tabOrder(doc: Document, isVisible: Visibility): HTMLElement[] {
  const found: HTMLElement[] = [];
  const walk = (root: Document | ShadowRoot, depth: number) => {
    for (const el of Array.from(root.querySelectorAll("*"))) {
      if (isOwnHost(el)) continue;
      if (el.matches(TABBABLE)) found.push(el as HTMLElement);
      const shadow = depth < MAX_FRAME_DEPTH ? shadowOf(el) : null;
      if (shadow) walk(shadow, depth + 1);
    }
  };
  walk(doc, 0);
  const candidates = found.filter((el) => {
    if (el.tabIndex < 0 || isDisabled(el) || inOwnUi(el)) return false;
    if (el.tagName.toUpperCase() === "INPUT" && inputType(el) === "hidden") return false;
    for (let node: Element | null = el; node; node = parentAcrossShadow(node)) if (!isVisible(node) || node.hasAttribute("inert")) return false;
    return true;
  });
  const positive = candidates.filter((el) => el.tabIndex > 0).sort((a, b) => a.tabIndex - b.tabIndex);
  return [...positive, ...candidates.filter((el) => el.tabIndex === 0)];
}

/** Whether the element takes typed text: a text field or an editor. */
function takesText(el: Element): boolean {
  const tag = el.tagName.toUpperCase();
  return tag === "TEXTAREA" || (tag === "INPUT" && TEXT_INPUTS.has(inputType(el))) || Boolean((el as HTMLElement).isContentEditable);
}

/** Change a text field's value as an edit would, with its input event; false when the page cancelled the edit. */
function editField(
  field: HTMLInputElement | HTMLTextAreaElement,
  inputType: string,
  edit: (value: string, at: { start: number; end: number }) => { value: string; caret: number },
  data: string | null = null,
): boolean {
  const at = selectionOf(field) ?? { start: field.value.length, end: field.value.length };
  if (!beforeInput(field, inputType, data)) return false;
  const next = edit(field.value, at);
  const setter = nativeSetter(field);
  if (setter) setter(next.value);
  else field.value = next.value;
  try {
    field.setSelectionRange(next.caret, next.caret);
  } catch {
    // A field without a caret.
  }
  const view = field.ownerDocument.defaultView;
  field.dispatchEvent(view && "InputEvent" in view ? new view.InputEvent("input", { bubbles: true, composed: true, inputType, data }) : new Event("input", { bubbles: true }));
  return true;
}

/**
 * What the browser does with a key the page left alone (its keydown was not
 * cancelled) - which an event from a script does not do by itself: Tab moves
 * the focus, Enter sends a form from its field and presses a button, Space
 * presses a control, Backspace and Delete delete, and the paging keys
 * scroll. Said in words for the result; "" when nothing happened.
 */
function keyDefault(target: Element, combo: KeyCombo, isVisible: Visibility): string {
  // The document the keyboard is in: a frame of this site's editor, not the page around it.
  const doc = target.ownerDocument;
  const key = combo.key;
  const tag = target.tagName.toUpperCase();
  const field = tag === "INPUT" || tag === "TEXTAREA" ? (target as HTMLInputElement | HTMLTextAreaElement) : null;
  const inText = takesText(target);
  if (key === "Tab" && !combo.ctrl && !combo.meta && !combo.alt) {
    const order = tabOrder(doc, isVisible);
    if (!order.length) return "";
    const here = order.indexOf(target as HTMLElement);
    const next = order[(here < 0 ? (combo.shift ? order.length : -1) : here) + (combo.shift ? -1 : 1)] ?? order[combo.shift ? order.length - 1 : 0];
    next.focus({ preventScroll: false });
    const role = roleOf(next) ?? "element";
    const name = accessibleName(next, role);
    return `The focus moved to ${role}${name ? ` ${quoted(clip(name, 60))}` : ""}.`;
  }
  // A character key in a text field types its character (a space too), where the caret is.
  if (!combo.ctrl && !combo.meta && !combo.alt && [...key].length === 1 && inText) {
    const char = keyDefFor(combo).text ?? key;
    if (field) {
      const typed = editField(field, "insertText", (value, at) => ({ value: `${value.slice(0, at.start)}${char}${value.slice(at.end)}`, caret: at.start + char.length }), char);
      return typed ? `Typed ${quoted(char)}.` : "";
    }
    if (typeof doc.execCommand === "function") doc.execCommand("insertText", false, char);
    return `Typed ${quoted(char)}.`;
  }
  if (combo.ctrl || combo.meta || combo.alt) {
    if (key.toLowerCase() === "a" && (combo.ctrl || combo.meta)) {
      if (field) field.select();
      else if (inText) doc.getSelection()?.selectAllChildren(target);
      else return "";
      return "Selected all of it.";
    }
    return "";
  }
  if (key === "Enter") {
    // A button input presses itself, as a <button> does - not its form's first sending button.
    if (tag === "INPUT" && PRESSED_INPUTS.has(inputType(target))) {
      (target as HTMLElement).click();
      return "Enter pressed it.";
    }
    if (field && tag === "INPUT") {
      const form = formOf(field);
      if (!form) return "";
      // Implicit submission: the form's default button is pressed, or - with no button - a form of one field is sent.
      const button = defaultButton(form);
      if (button) {
        if (isDisabled(button)) return "";
        (button as HTMLElement).click();
        return "The form was sent (Enter).";
      }
      const fields = Array.from(form.elements).filter((f) => f.tagName.toUpperCase() === "INPUT" && TEXT_INPUTS.has(inputType(f)));
      if (fields.length !== 1) return "";
      if (typeof form.requestSubmit === "function") form.requestSubmit();
      return "The form was sent (Enter).";
    }
    if (field) {
      editField(field, "insertLineBreak", (value, at) => ({ value: `${value.slice(0, at.start)}\n${value.slice(at.end)}`, caret: at.start + 1 }));
      return "A new line went in.";
    }
    if (inText) {
      if (typeof doc.execCommand === "function") doc.execCommand("insertParagraph");
      return "A new line went in.";
    }
    // Only the browser's own controls: a <div role="button"> answers Enter in its own handlers, which have run.
    if (tag === "BUTTON" || tag === "SUMMARY" || ((tag === "A" || tag === "AREA") && target.hasAttribute("href"))) {
      (target as HTMLElement).click();
      return "Enter pressed it.";
    }
    return "";
  }
  if (key === " " && !inText) {
    // A link scrolls the page on Space, and an ARIA control is left to its own handlers, as the browser leaves it.
    if (tag === "BUTTON" || tag === "SUMMARY" || (tag === "INPUT" && (PRESSED_INPUTS.has(inputType(target)) || inputType(target) === "checkbox" || inputType(target) === "radio"))) {
      (target as HTMLElement).click();
      return "Space pressed it.";
    }
  }
  if ((key === "Backspace" || key === "Delete") && inText) {
    const back = key === "Backspace";
    if (field) {
      const done = editField(field, back ? "deleteContentBackward" : "deleteContentForward", (value, at) => {
        if (at.start !== at.end) return { value: `${value.slice(0, at.start)}${value.slice(at.end)}`, caret: at.start };
        const from = back ? Math.max(0, at.start - 1) : at.start;
        const to = back ? at.start : Math.min(value.length, at.start + 1);
        return { value: `${value.slice(0, from)}${value.slice(to)}`, caret: from };
      });
      return done ? "Deleted." : "";
    }
    if (typeof doc.execCommand === "function") doc.execCommand(back ? "delete" : "forwardDelete");
    return "Deleted.";
  }
  if (field && (key === "Home" || key === "End" || key === "ArrowLeft" || key === "ArrowRight")) {
    const at = selectionOf(field);
    if (!at) return "";
    const caret = key === "Home" ? 0 : key === "End" ? field.value.length : key === "ArrowLeft" ? Math.max(0, at.start - 1) : Math.min(field.value.length, at.end + 1);
    field.setSelectionRange(caret, caret);
    return "";
  }
  if (!inText && ["PageDown", "PageUp", "Home", "End", " "].includes(key)) {
    // What the browser pages: the scrolling list or area the keyboard is in, or the page - never a page that does not scroll.
    const scroller = scrollerFor(doc, target, "y");
    if (!scroller) return "Nothing here scrolls.";
    const home = scroller.ownerDocument;
    const isPage = scroller === (home.scrollingElement ?? home.documentElement);
    const page = ((isPage ? home.defaultView?.innerHeight : scroller.clientHeight) || 800) * 0.9;
    const instant = "instant" as ScrollBehavior;
    if (key === "Home") scroller.scrollTo?.({ top: 0, behavior: instant });
    else if (key === "End") scroller.scrollTo?.({ top: scroller.scrollHeight, behavior: instant });
    else scroller.scrollBy?.({ top: key === "PageUp" || (key === " " && combo.shift) ? -page : page, behavior: instant });
    return `Scrolled ${scrollerName(doc, scroller)}: ${scrolledTo(doc, scroller, "y")}.`;
  }
  return "";
}

/** Inputs that are buttons: Enter and Space press them. */
const PRESSED_INPUTS = new Set(["submit", "button", "reset", "image"]);

/** Characters a key types, as keypress reports them: Enter and printable keys only. */
function typesCharacter(combo: KeyCombo): boolean {
  return !combo.ctrl && !combo.meta && !combo.alt && (combo.key === "Enter" || [...combo.key].length === 1);
}

export function pressKey(doc: Document, key: unknown, isVisible: Visibility = () => true): Result<{ note: string }> {
  // The same table the rules read the key through: what they judged is what is pressed.
  const combo = parseKeyCombo(key);
  if (!combo) {
    return { ok: false, error: "bad_key", message: `"${clip(String(key ?? ""), 40)}" is not a key the agent can press. It can press ${KEY_NAMES_SHOWN}.` };
  }
  const def = keyDefFor(combo);
  // Where describeFocus looked: the element with the keyboard, inside a web component too.
  const target = focusedElement(doc) ?? doc.body ?? doc.documentElement;
  const view = target.ownerDocument.defaultView ?? doc.defaultView;
  const Ctor = view?.KeyboardEvent ?? KeyboardEvent;
  const held = { ctrlKey: combo.ctrl, altKey: combo.alt, shiftKey: combo.shift, metaKey: combo.meta };
  // The legacy codes go in the event itself, where the page's own scripts read them (a property set here would stay in this world).
  const event = (type: "keydown" | "keypress" | "keyup") =>
    new Ctor(type, {
      key: def.key,
      code: def.code,
      keyCode: type === "keypress" ? (def.text ?? def.key).charCodeAt(0) : def.vk,
      charCode: type === "keypress" ? (def.text ?? def.key).charCodeAt(0) : 0,
      ...held,
      bubbles: true,
      cancelable: true,
      composed: true,
    });
  const shown = String(key).trim() || (def.key === " " ? "Space" : def.key);
  const down = target.dispatchEvent(event("keydown"));
  // A cancelled keypress keeps the character, the new line and the form's sending from happening, as in the browser.
  const allowed = down && (!typesCharacter(combo) || target.dispatchEvent(event("keypress")));
  // What the browser would do, unless the page took the key for itself.
  const did = allowed ? keyDefault(target, combo, isVisible) : "The page handled it itself.";
  target.dispatchEvent(event("keyup"));
  return { ok: true, note: `Pressed ${shown}.${did ? ` ${did}` : ""}` };
}

type Axis = "x" | "y";

/** The document's own scroller, when the page scrolls as a whole (a page that set overflow: hidden on it does not). */
function documentScroller(doc: Document, axis: Axis): Element | null {
  const scroller = doc.scrollingElement ?? doc.documentElement;
  const view = doc.defaultView;
  if (!scroller || !view) return null;
  for (const el of [doc.documentElement, doc.body]) {
    if (!el) continue;
    const style = view.getComputedStyle(el);
    if ((axis === "y" ? style.overflowY : style.overflowX) === "hidden") return null;
  }
  const room = axis === "y" ? scroller.scrollHeight - (view.innerHeight || scroller.clientHeight) : scroller.scrollWidth - (view.innerWidth || scroller.clientWidth);
  return room > 1 ? scroller : null;
}

/**
 * Whether an element scrolls its own content along the axis: overflow auto or
 * scroll, with more than it shows. The body does only when the root element
 * keeps its own overflow (html { overflow: hidden }); otherwise the body's
 * overflow is the page's.
 */
function scrollsItself(el: Element, axis: Axis): boolean {
  const view = el.ownerDocument.defaultView;
  if (!view || el === el.ownerDocument.documentElement) return false;
  if (el === el.ownerDocument.body) {
    const root = view.getComputedStyle(el.ownerDocument.documentElement);
    if ((axis === "y" ? root.overflowY : root.overflowX) === "visible") return false;
  }
  const style = view.getComputedStyle(el);
  const overflow = axis === "y" ? style.overflowY : style.overflowX;
  const room = axis === "y" ? el.scrollHeight - el.clientHeight : el.scrollWidth - el.clientWidth;
  return room > 1 && (overflow === "auto" || overflow === "scroll" || overflow === "overlay");
}

/**
 * What scrolls when a person turns the wheel over `start`: its nearest
 * ancestor (itself included, across shadow roots) that scrolls - a message
 * list, a side panel - or else the page itself; null when nothing does.
 */
export function scrollerFor(doc: Document, start: Element | null, axis: Axis): Element | null {
  let home = start?.ownerDocument ?? doc;
  let node: Element | null = start;
  for (let depth = 0; depth < 200; depth += 1) {
    if (node && !isOwnHost(node)) {
      if (scrollsItself(node, axis)) return node;
      node = parentAcrossShadow(node);
      continue;
    }
    const own = documentScroller(home, axis);
    if (own) return own;
    // A frame of this site that does not scroll itself: what scrolls around the frame.
    const frame = frameElementOf(home);
    if (!frame) return null;
    home = frame.ownerDocument;
    node = frame;
  }
  return null;
}

/** The frame element a document is shown in, when the page around it is this site's; null for the top document. */
function frameElementOf(doc: Document): Element | null {
  try {
    return doc.defaultView?.frameElement ?? null;
  } catch {
    return null;
  }
}

/** What a scroller is, for the result: the page, or the list or area by its role and name. */
export function scrollerName(doc: Document, scroller: Element): string {
  const home = scroller.ownerDocument ?? doc;
  if (scroller === (home.scrollingElement ?? home.documentElement)) return home === doc ? "the page" : "the frame's page";
  const role = roleOf(scroller) ?? ((scroller.getAttribute("role") ?? "").trim().split(/\s+/)[0].toLowerCase() || "area");
  const name = accessibleName(scroller, role);
  return `the ${role}${name ? ` ${quoted(clip(name, 60))}` : ""} [${refFor(scroller)}]`;
}

/** Where a scroller is now, and how much is left, in CSS pixels. */
export function scrolledTo(doc: Document, scroller: Element, axis: Axis): string {
  const home = scroller.ownerDocument ?? doc;
  const isPage = scroller === (home.scrollingElement ?? home.documentElement);
  const view = home.defaultView;
  const shown = axis === "y" ? (isPage ? view?.innerHeight : undefined) ?? scroller.clientHeight : (isPage ? view?.innerWidth : undefined) ?? scroller.clientWidth;
  const at = Math.round(axis === "y" ? scroller.scrollTop : scroller.scrollLeft);
  const size = Math.round(axis === "y" ? scroller.scrollHeight : scroller.scrollWidth);
  const left = Math.max(0, size - at - Math.round(shown));
  const edge = axis === "y" ? ["from the top", "below"] : ["from the left", "to the right"];
  return `${at} of ${size} pixels ${edge[0]}, ${left ? `${left} more ${edge[1]}` : "at the end"}`;
}

export function scroll(doc: Document, direction: unknown, ref: unknown, isVisible: Visibility): Result<{ note: string }> {
  const moves: Record<string, { axis: Axis; sign: number } | "top" | "bottom"> = {
    down: { axis: "y", sign: 1 },
    up: { axis: "y", sign: -1 },
    right: { axis: "x", sign: 1 },
    left: { axis: "x", sign: -1 },
    top: "top",
    bottom: "bottom",
  };
  const move = typeof direction === "string" ? moves[direction] : undefined;
  if (direction !== undefined && direction !== null && !move) return { ok: false, error: "bad_request", message: "Scroll up, down, left, right, top or bottom, or to an element." };
  let from: Element | null = null;
  if (ref !== undefined && ref !== null) {
    const el = usable(ref, isVisible);
    if (isFailure(el)) return el;
    if (!move) {
      el.scrollIntoView?.({ block: "center" });
      return { ok: true, note: `Element ${ref as string} is in view.` };
    }
    // With a direction: the list or area the element is in (or is) scrolls.
    from = el;
  } else {
    if (!move) return { ok: false, error: "bad_request", message: "Scroll up, down, left, right, top or bottom, or to an element." };
    // What a wheel in the middle of the window would scroll: the list under it, or the page.
    const view = doc.defaultView;
    const found = typeof doc.elementFromPoint === "function" ? doc.elementFromPoint((view?.innerWidth || 1200) / 2, (view?.innerHeight || 800) / 2) : null;
    from = found && !(inOwnUi(found)) ? found : null;
  }
  const axis: Axis = move === "top" || move === "bottom" ? "y" : move!.axis;
  const scroller = scrollerFor(doc, from, axis);
  if (!scroller) return { ok: false, error: "not_found", message: "Nothing here scrolls: all of it is in view already." };
  const home = scroller.ownerDocument;
  const isPage = scroller === (home.scrollingElement ?? home.documentElement);
  const view = home.defaultView;
  const step = Math.round((axis === "y" ? (isPage ? view?.innerHeight : scroller.clientHeight) || 800 : (isPage ? view?.innerWidth : scroller.clientWidth) || 1200) * 0.8);
  const before = axis === "y" ? scroller.scrollTop : scroller.scrollLeft;
  // Instant: a page's smooth scrolling would still be under way when the result is read.
  if (move === "top") scroller.scrollTo?.({ top: 0, behavior: "instant" as ScrollBehavior });
  else if (move === "bottom") scroller.scrollTo?.({ top: scroller.scrollHeight, behavior: "instant" as ScrollBehavior });
  else scroller.scrollBy?.({ [axis === "y" ? "top" : "left"]: move!.sign * step, behavior: "instant" as ScrollBehavior });
  const after = axis === "y" ? scroller.scrollTop : scroller.scrollLeft;
  const what = scrollerName(doc, scroller);
  const where = scrolledTo(doc, scroller, axis);
  const moved = Math.round(Math.abs(after - before));
  if (!moved) return { ok: true, note: `${what.replace(/^./, (c) => c.toUpperCase())} did not move: it is at its ${move === "top" || (move !== "bottom" && move!.sign < 0) ? "start" : "end"} (${where}).` };
  return { ok: true, note: `Scrolled ${String(direction)} ${moved} pixels in ${what}: ${where}.` };
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
export type PointRect = { x: number; y: number; width: number; height: number };

/**
 * The element at a viewport point (CSS pixels), the way a click there would
 * reach it: the document reports a web component as its host, so open shadow
 * roots are entered until the innermost element under the point is found. With
 * `activates`, the control that click would work (the button around the words).
 * Its viewport rect comes with it, for the target box. The agent's own overlay
 * is never "there": the visuals take no pointer events, and the banner is skipped.
 */
export function describeAt(doc: Document, x: unknown, y: unknown, isVisible: Visibility, activates = false): Result<{ element: ElementInfo; rect: PointRect }> {
  if (typeof x !== "number" || typeof y !== "number" || !Number.isFinite(x) || !Number.isFinite(y)) {
    return { ok: false, error: "bad_request", message: "Give the point as numbers: x and y in CSS pixels." };
  }
  return describeAtIn(doc, x, y, isVisible, activates, { x: 0, y: 0 }, 0);
}

/** Frames within frames: this deep and no further. */
const MAX_FRAME_DEPTH = 5;
/** Below this opacity a target is drawn for the eye not to see it. */
const FAINT = 0.1;
/** A target this small is not one a person would be shown to click. */
const TINY_PX = 2;

/** The document of a same-site frame, or null for one from another site (which the browser keeps closed). */
function frameDocument(frame: Element): Document | null {
  try {
    return (frame as HTMLIFrameElement).contentDocument ?? null;
  } catch {
    return null;
  }
}

/** The site a frame shows, from its address; null when it says nothing (about:blank, srcdoc). */
/** A frame's site, and the path it shows: a CAPTCHA is told by where it is served from. */
function frameSite(frame: Element): { host: string | null; path?: string } {
  const host = frameHost(frame);
  if (!host) return { host };
  try {
    return { host, path: new URL(frame.getAttribute("src") ?? "", frame.ownerDocument.baseURI).pathname.slice(0, 200) };
  } catch {
    return { host };
  }
}

function frameHost(frame: Element): string | null {
  const src = frame.getAttribute("src") ?? "";
  try {
    const url = new URL(src, frame.ownerDocument.baseURI);
    return url.protocol === "http:" || url.protocol === "https:" ? url.hostname.replace(/\.$/, "") : null;
  } catch {
    return null;
  }
}

/** Where a frame's page starts inside the frame's box: past its border and its padding. */
function contentOffset(frame: Element, box: DOMRect): { dx: number; dy: number } {
  const html = frame as HTMLElement;
  const style = frame.ownerDocument.defaultView?.getComputedStyle(frame);
  const pad = (value: string | undefined) => Number.parseFloat(value ?? "") || 0;
  return { dx: box.left + (html.clientLeft || 0) + pad(style?.paddingLeft), dy: box.top + (html.clientTop || 0) + pad(style?.paddingTop) };
}

/** Where an element's document sits in the top page's window: nothing for the top page, the frames' offsets for a frame's. */
function frameOffset(doc: Document): { x: number; y: number } {
  let x = 0;
  let y = 0;
  let view: Window | null = doc.defaultView;
  for (let depth = 0; view && depth < MAX_FRAME_DEPTH; depth += 1) {
    let frame: Element | null = null;
    try {
      frame = view.frameElement;
    } catch {
      frame = null;
    }
    if (!frame) break;
    const { dx, dy } = contentOffset(frame, frame.getBoundingClientRect());
    x += dx;
    y += dy;
    view = frame.ownerDocument.defaultView;
  }
  return { x, y };
}

/** Whether the target, or anything it sits in, is drawn too faint to see. */
function drawnFaint(el: Element): boolean {
  const view = el.ownerDocument.defaultView;
  if (!view) return false;
  for (let node: Element | null = el; node; node = parentAcrossShadow(node)) {
    const opacity = Number.parseFloat(view.getComputedStyle(node).opacity);
    if (Number.isFinite(opacity) && opacity < FAINT) return true;
  }
  return false;
}

function describeAtIn(doc: Document, x: number, y: number, isVisible: Visibility, activates: boolean, offset: { x: number; y: number }, depth: number): Result<{ element: ElementInfo; rect: PointRect }> {
  if (typeof doc.elementFromPoint !== "function") return { ok: false, error: "failed", message: "The page cannot find what is at a point." };
  let el: Element | null = doc.elementFromPoint(x, y);
  for (let shadow = el ? shadowOf(el) : null; el && shadow && typeof shadow.elementFromPoint === "function"; shadow = shadowOf(el)) {
    const inner: Element | null = shadow.elementFromPoint(x, y);
    if (!inner || inner === el) break;
    el = inner;
  }
  if (el && (inOwnUi(el))) {
    // Only the banner's own buttons take the pointer: the point is on Alpharouter's Stop or Resume.
    return { ok: false, error: "covered", message: "Alpharouter's banner is over that point (its Stop and Resume buttons). Act elsewhere, or scroll the page." };
  }
  if (!el || el === doc.documentElement) {
    return { ok: false, error: "not_found", message: "There is nothing to act on at that point." };
  }
  // An invisible input over its own styled box is the control a person sees there.
  const styled = styledInput(el);
  if (!isVisible(el) && !styled) return { ok: false, error: "not_visible", message: "What is at that point is not visible." };
  const tag = el.tagName.toUpperCase();
  if (tag === "IFRAME" || tag === "FRAME") {
    const box = el.getBoundingClientRect();
    const inner = depth < MAX_FRAME_DEPTH ? frameDocument(el) : null;
    if (inner) {
      // A frame of this site: the point, in the frame's own pixels, past its border.
      const { dx, dy } = contentOffset(el, box);
      return describeAtIn(inner, x - dx, y - dy, isVisible, activates, { x: offset.x + dx, y: offset.y + dy }, depth + 1);
    }
    // Another site's frame: what is under the point in there, this page cannot see.
    const element: ElementInfo = { ref: refFor(el), role: "frame", name: clip(squash(el.getAttribute("title") ?? el.getAttribute("name") ?? ""), NAME_CHARS), tag: tag.toLowerCase(), frame: frameSite(el) };
    return { ok: true, element, rect: { x: box.left + offset.x, y: box.top + offset.y, width: box.width, height: box.height } };
  }
  const target = activates ? activationTarget(el) : el;
  const role = roleOf(target) ?? (headingLevel(target) !== null ? "heading" : "text");
  const element = describeElement(target, role, isVisible, true);
  // A hidden control under its label: the box is the label's, where the person sees it.
  const r = pressedFor(el, target, isVisible).getBoundingClientRect();
  if (drawnFaint(el) && !styled) element.hidden = "transparent";
  else if (r.width > 0 && r.height > 0 && (r.width <= TINY_PX || r.height <= TINY_PX)) element.hidden = "tiny";
  return { ok: true, element, rect: { x: r.left + offset.x, y: r.top + offset.y, width: r.width, height: r.height } };
}

/** Whether a box is wholly inside the window. */
function inWindow(doc: Document, r: DOMRect): boolean {
  const view = doc.defaultView;
  const width = view?.innerWidth || doc.documentElement.clientWidth;
  const height = view?.innerHeight || doc.documentElement.clientHeight;
  return r.left >= 0 && r.top >= 0 && r.right <= width && r.bottom <= height;
}

/**
 * Where a real mouse should press to work the element a reference names,
 * under full control: brought into view only when it is not wholly in the
 * window already (a scroll moves what the model saw), its box in CSS
 * pixels, and the element as the rules judge it. Refused when something
 * else would take the press at its centre - a dialog, a banner.
 */
export function locate(ref: unknown, isVisible: Visibility, activates = false): Result<{ element: ElementInfo; rect: PointRect }> {
  const named = usable(ref, isVisible);
  if (isFailure(named)) return named;
  const target = activates ? activationTarget(named) : named;
  if (target !== named && isDisabled(target)) return { ok: false, error: "disabled", message: `Element ${ref as string} is disabled.` };
  const press = pressedFor(named, target, isVisible);
  const doc = press.ownerDocument;
  if (!inWindow(doc, press.getBoundingClientRect())) press.scrollIntoView?.({ block: "center", inline: "center" });
  const r = press.getBoundingClientRect();
  if (!r.width || !r.height) return { ok: false, error: "not_visible", message: `Element ${ref as string} takes no space on the page.` };
  const x = r.left + r.width / 2;
  const y = r.top + r.height / 2;
  let top: Element | null = typeof doc.elementFromPoint === "function" ? doc.elementFromPoint(x, y) : null;
  for (let shadow = top ? shadowOf(top) : null; top && shadow && typeof shadow.elementFromPoint === "function"; shadow = shadowOf(top)) {
    const inner: Element | null = shadow.elementFromPoint(x, y);
    if (!inner || inner === top) break;
    top = inner;
  }
  if (top && (inOwnUi(top))) {
    return { ok: false, error: "covered", message: "Alpharouter's banner is over that element. Scroll the page a little, then act." };
  }
  if (top && !holds(press, top) && !holds(target, top) && !holds(top, press)) {
    const role = roleOf(top);
    const name = role ? accessibleName(top, role) : visibleText(top, isVisible, 60);
    return { ok: false, error: "covered", message: `Something covers element ${ref as string}${name ? `: "${name}"` : ""}. Close it first.` };
  }
  const role = roleOf(target) ?? (headingLevel(target) !== null ? "heading" : "text");
  // In a frame of this page's site, the box is in the frame's pixels: the mouse presses in the top window's.
  const offset = frameOffset(doc);
  return { ok: true, element: describeElement(target, role, isVisible, true), rect: { x: r.left + offset.x, y: r.top + offset.y, width: r.width, height: r.height } };
}

export function describe(ref: unknown, isVisible: Visibility, activates = false, choose?: unknown): Result<{ element: ElementInfo }> {
  const named = resolve(ref);
  if (isFailure(named)) return named;
  const el = activates ? activationTarget(named) : named;
  const role = roleOf(el) ?? (headingLevel(el) !== null ? "heading" : "text");
  const element = describeElement(el, role, isVisible, true);
  // What choosing `choose` would really pick, for the card: a menu matches by value and by part of a label.
  if (typeof choose === "string" && choose.trim() && choose.length <= 500 && el.tagName.toUpperCase() === "SELECT") {
    const option = matchOption(el as HTMLSelectElement, choose);
    if (option) element.choice = clip(option.label || option.text, VALUE_CHARS);
  }
  return { ok: true, element };
}
