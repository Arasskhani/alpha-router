/**
 * The browser agent's rules: before every action the model proposes, the
 * side panel decides whether it may happen, and who has to agree.
 *
 * Four classes:
 *
 * - read: looking, never asks - listing tabs, reading or searching the page,
 *   scrolling, waiting, asking the user, finishing.
 * - act: changing something on the page the user is on - a click, typing,
 *   choosing, a key, another page of the same site, another tab. Asks in Ask
 *   mode; in Auto mode the administrator's review model decides, and asks
 *   the user whenever it is not sure.
 * - sensitive: always asks the user - sending a form, a click that sends,
 *   deletes, confirms, transfers, downloads or publishes, and going to
 *   another site (which may also need the browser's permission for it).
 * - blocked: refused, with the reason told to the model - typing into a
 *   password, card, one-time-code or ID field, anything that buys or pays,
 *   a special-scheme address, a site the administrator's rules keep out, and
 *   Alpharouter itself.
 *
 * The rules judge what the element says about itself (its role and accessible
 * name, where a link or form goes), read fresh from the page just before the
 * action. The page can lie in its labels; that is why sending and paying are
 * never left to the agent alone, and the words are checked in English and in
 * Persian.
 */

import type { ElementInfo } from "../content/agent";
import { sensitiveText } from "./sensitive";
import { readablePage, siteRefusal, type SitePolicy } from "./sites";

type ActionClass = "read" | "act" | "sensitive" | "blocked";

export type Verdict = {
  class: ActionClass;
  /** Why, as a code for the step log and Admin Logs. */
  reason: string;
  /** Why, in words for the user and the model. */
  message: string;
  /** The other site an action goes to: the browser may have to allow it first. */
  site?: string;
};

/** Who has to agree before an action happens. */
export type Approval = "none" | "user" | "review" | "refuse";

export type AgentMode = "ask" | "auto";

export type ProposedAction = {
  tool: string;
  args: Record<string, unknown>;
  /** The page the action runs in or starts from; none for a tab that shows no web page. */
  page?: { url: string; host: string };
  /** The element `args.ref` names, as the page described it just now. */
  element?: ElementInfo;
  /** For tab_switch: the tab it goes to (its host is null when it shows no web page). */
  target?: { url: string; host: string | null };
};

export type PolicyContext = {
  policy: SitePolicy;
  /** This Alpharouter's host, which an allow list never shuts out. */
  serverHost: string | null;
  /**
   * The hosts this Alpharouter answers on - the server this copy of the
   * extension belongs to, and the address the server gives - as
   * `readablePage` names them. The agent works on no page of theirs, on any
   * port or scheme: a browser sends the session cookie to every port of a
   * host, so another port of it can be Alpharouter too, signed in as the user.
   */
  ownHosts: string[];
};

const READ_TOOLS = new Set(["tabs_list", "read_page", "find", "get_page_text", "scroll", "wait_for", "ask_user", "done"]);
const PAGE_TOOLS = new Set(["read_page", "find", "get_page_text", "scroll", "wait_for", "click", "type_text", "select_option", "press_key", "submit_form"]);

/**
 * Words on a button (or a link, in English) that buy, pay, bid or give
 * money. Order alone is checked as the whole label or with a verb, so
 * "Order history" is not one. Matched on `labelForm` of the label.
 */
const PURCHASE =
  /\b(buy|pay|purchase|checkout|check out|donate|pre-?order)\b|\b(place|submit|complete|confirm)( your| the| my| an)? order\b|^order( now)?$|\bplace (a )?bid\b|\bbid now\b|\b(continue|proceed|go) to (payment|checkout)\b|\b(complete|make|confirm|submit) (the |a |your )?payment\b|\badd funds\b/;
const PURCHASE_FA = /خرید|پرداخت|سفارش|تسویه|اهدا|کمک مالی/;
/** Persian words that buy even on a link; "سفارش" there is usually "my orders". */
const PURCHASE_FA_LINK = /خرید|پرداخت|اهدا/;
/** Words that send, delete, confirm, move, share, agree to or publish something. */
const SENSITIVE =
  /\b(send|submit|delete|remove|confirm|transfer|download|publish|post|reply|forward|share|approve|accept|agree|book|reserve|subscribe|unsubscribe|discard|erase|withdraw)\b|\bcancel (my |the |your )?(order|subscription|booking|reservation|account|membership|plan)\b/;
const SENSITIVE_FA =
  /ارسال|فرستادن|بفرست|حذف|پاک ?کردن|تایید|تأیید|انتقال|دانلود|بارگیری|انتشار|منتشر|پست|پاسخ|بازارسال|هدایت|اشتراک|قبول|موافق|ثبت|رزرو|لغو/;

/**
 * A label as the word lists read it: compatibility forms folded, in lower
 * case, Persian written with Arabic yeh or kaf read as Persian, without the
 * zero-width joiners, tatweel and diacritics that change how a word is drawn
 * but not what it says, and without the marks around it ("Order now!",
 * "Order now →", "🛒 Buy"). Otherwise "خريد" or "خریـــد" would not be
 * "خرید", and "Order now!" would not be "Order now".
 */
function labelForm(text: string): string {
  return text
    .normalize("NFKC")
    .toLowerCase()
    .replace(/[يى]/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/[\u200b-\u200d\u00ad\u0640\ufeff]/g, "")
    .replace(/\p{M}/gu, "")
    .replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "")
    .replace(/\s+/g, " ");
}
/** Fields for a person's identity documents. */
const ID_FIELD = /\b(ssn|social security|passport|national id|national identity|tax id|id number|identity number)\b/i;
const ID_FIELD_FA = /کد\s?ملی|شماره\s?ملی|شناسنامه|گذرنامه|پاسپورت/;

function verdict(cls: ActionClass, reason: string, message: string, site?: string): Verdict {
  return site ? { class: cls, reason, message, site } : { class: cls, reason, message };
}

function blocked(reason: string, message: string): Verdict {
  return verdict("blocked", reason, message);
}

/**
 * Why the agent may not work on the page on `host` at all, or null.
 * Alpharouter's own pages are told by their host, whatever the port or scheme.
 */
function siteVerdict(host: string, ctx: PolicyContext): Verdict | null {
  if (ctx.ownHosts.includes(host)) {
    return blocked("own_server", "The agent does not work on Alpharouter itself, nor on any other address of its host.");
  }
  const refusal = siteRefusal(host, ctx.policy, ctx.serverHost);
  if (refusal === "site_blocked") return blocked("site_blocked", `Your administrator does not allow the agent on ${host}.`);
  if (refusal === "site_not_allowed") return blocked("site_not_allowed", `${host} is not on the list of sites your administrator allows.`);
  return null;
}

/** Going to `rawUrl` from the page on `fromHost`: the same site acts, another site always asks. */
function goingTo(rawUrl: unknown, fromHost: string | undefined, ctx: PolicyContext, what: string): Verdict {
  const target = typeof rawUrl === "string" ? readablePage(rawUrl) : null;
  if (!target) return blocked("special_scheme", `The agent opens web pages only (http or https), never ${typeof rawUrl === "string" ? "that address" : "a missing address"}.`);
  const refused = siteVerdict(target.host, ctx);
  if (refused) return refused;
  if (fromHost && target.host === fromHost) return verdict("act", "same_site", `${what} on ${target.host}.`);
  return verdict("sensitive", "other_site", `${what} on another site: ${target.host}.`, target.host);
}

function purchase(name: string, role: string): boolean {
  const form = labelForm(name);
  if (PURCHASE.test(form)) return true;
  return role === "link" ? PURCHASE_FA_LINK.test(form) : PURCHASE_FA.test(form);
}

function sendsSomething(name: string): boolean {
  const form = labelForm(name);
  return SENSITIVE.test(form) || SENSITIVE_FA.test(form);
}

function named(element: ElementInfo): string {
  return element.name ? `"${element.name}"` : element.text ? `"${element.text}"` : `element ${element.ref}`;
}

/** What a control says of itself: its name, and the words it shows when they differ (a label can hide them). */
function labels(element: ElementInfo): string[] {
  return [element.name, element.text ?? ""].map((label) => label.trim()).filter(Boolean);
}

function clickVerdict(element: ElementInfo, page: { url: string; host: string }, ctx: PolicyContext): Verdict {
  const said = labels(element);
  // A link is where it goes, whatever role it claims (a menu item, a "button").
  const linkish = element.role === "link" || Boolean(element.href);
  // Whatever the element claims to be: a <div onclick> drawn as a button places an order as well as a <button> does.
  if (said.some((label) => purchase(label, linkish ? "link" : element.role))) {
    return blocked("purchase_label", `The agent never buys or pays: ${named(element)} is for the user to click.`);
  }
  if (element.href) {
    let protocol = "";
    try {
      protocol = new URL(element.href).protocol;
    } catch {
      protocol = "";
    }
    if (protocol === "http:" || protocol === "https:") {
      const going = goingTo(element.href, page.host, ctx, `Following the link ${named(element)}`);
      if (going.class !== "act") return going;
    } else if (protocol !== "javascript:") {
      // mailto:, tel: and the like hand over to another program.
      return verdict("sensitive", "other_app", `The link ${named(element)} opens another program.`);
    }
  }
  if (element.submits) {
    const target = element.formAction ? readablePage(element.formAction) : null;
    if (target) {
      const refused = siteVerdict(target.host, ctx);
      if (refused) return refused;
    }
    return verdict("sensitive", "submit", `Clicking ${named(element)} sends a form.`);
  }
  if (said.some(sendsSomething)) return verdict("sensitive", "sensitive_label", `Clicking ${named(element)} may send, delete or publish something.`);
  // Nothing tells what it does - an icon without a name - so neither the agent nor a reviewer can judge it.
  if (!said.length && !element.href) {
    return verdict("sensitive", "unnamed_control", `The ${element.role === "text" ? "element" : element.role} ${element.ref} has no name, so what clicking it does cannot be told.`);
  }
  return verdict("act", "click", `Clicking ${named(element)}.`);
}

function typeVerdict(element: ElementInfo): Verdict {
  const secret = () => blocked("sensitive_field", `The agent never types into ${named(element)}: passwords, card numbers and codes are for the user to enter.`);
  if (element.sensitive) return secret();
  const described = labelForm(`${element.name} ${element.type ?? ""}`);
  if (ID_FIELD.test(described) || ID_FIELD_FA.test(described)) {
    return blocked("id_field", `The agent never types into ${named(element)}: identity numbers are for the user to enter.`);
  }
  // The page judges the field by everything it says about it; its name is checked here as well.
  if (sensitiveText(element.name)) return secret();
  return verdict("act", "type", `Typing into ${named(element)}.`);
}

/** A form's destination for a message: its site and path, never its query. */
function destination(url: string | undefined): string {
  const target = url ? readablePage(url) : null;
  if (!target || !url) return "";
  const path = new URL(url).pathname;
  return ` to ${target.host}${path === "/" ? "" : path}`;
}

/**
 * Sending a form is judged by the form: sent from any of its fields, it
 * presses the form's own sending button, and goes where the form sends.
 */
function submitVerdict(element: ElementInfo, ctx: PolicyContext): Verdict {
  const said = [...labels(element), ...(element.formButton ?? [])];
  if (said.some((label) => purchase(label, "button"))) {
    return blocked("purchase_label", `The agent never buys or pays: sending this form (its button says "${element.formButton?.[0] ?? element.name}") is for the user.`);
  }
  const target = element.formAction ? readablePage(element.formAction) : null;
  if (target) {
    const refused = siteVerdict(target.host, ctx);
    if (refused) return refused;
  }
  return verdict("sensitive", "submit", `Sending the form${destination(element.formAction)}${element.name ? ` from ${named(element)}` : ""}.`);
}

/** Roles of fields that hold text a person types. */
const TEXT_ROLES = new Set(["textbox", "searchbox", "combobox", "spinbutton"]);

/**
 * A key press, judged by the element it goes to (`element`: the focused
 * one, if any). Enter in a message box is how most web apps send; on a
 * control, Enter or Space works as a click in the page's own handlers; and
 * Delete outside a text field deletes whatever the page has selected.
 */
function keyVerdict(rawKey: unknown, element: ElementInfo | undefined, page: { url: string; host: string }, ctx: PolicyContext): Verdict {
  const key = rawKey === "Space" ? " " : typeof rawKey === "string" ? rawKey : "";
  const shown = key === " " ? "Space" : key || "a key";
  const inText = Boolean(element && (TEXT_ROLES.has(element.role) || element.tag === "textarea"));
  if (element && inText && key === "Enter") {
    if (element.role === "searchbox" || element.type === "search") return verdict("act", "press_key", `Pressing Enter in ${named(element)} to search.`);
    return verdict("sensitive", "enter_sends", `Pressing Enter in ${named(element)} may send what it holds.`);
  }
  if (element && !inText && (key === "Enter" || key === " ")) {
    const asClick = clickVerdict(element, page, ctx);
    if (asClick.class === "act") return verdict("act", "press_key", `Pressing ${shown} on ${named(element)}.`);
    return { ...asClick, message: `Pressing ${shown} on ${named(element)} works like clicking it. ${asClick.message}` };
  }
  if (!inText && (key === "Delete" || key === "Backspace")) {
    return verdict("sensitive", "delete_key", `Pressing ${shown} ${element ? `on ${named(element)}` : "on the page"} may delete something.`);
  }
  return verdict("act", "press_key", `Pressing ${shown}${element ? ` in ${named(element)}` : ""}.`);
}

/** What kind of action this is, from the tool, the element, the addresses involved and the site rules. */
export function classifyAction(action: ProposedAction, ctx: PolicyContext): Verdict {
  const { tool, args, page, element, target } = action;
  if (PAGE_TOOLS.has(tool)) {
    if (!page) return blocked("no_page", "The tab does not show a web page the agent can work on.");
    const refused = siteVerdict(page.host, ctx);
    if (refused) return refused;
  }
  if (READ_TOOLS.has(tool)) return verdict("read", "read", "Looking, without changing anything.");
  switch (tool) {
    case "navigate": {
      // A tab the agent may not work on is the user's: it is not sent elsewhere either.
      const away = page ? siteVerdict(page.host, ctx) : null;
      if (away) return blocked("tab_refused", `The agent does not send away a tab it may not work on (${page!.host}). Open the page in a new tab instead.`);
      return goingTo(args.url, page?.host, ctx, "Opening a page");
    }
    case "tab_open":
      return goingTo(args.url, page?.host, ctx, "Opening a page in a new tab");
    case "tab_switch": {
      // Working in another tab is working on its site: the same rules as going there.
      if (!target) return blocked("no_tab", "There is no such tab in this window.");
      if (!target.host) return verdict("act", "tab_switch", "Switching to a tab that shows no web page.");
      const refused = siteVerdict(target.host, ctx);
      if (refused) return refused;
      if (page && target.host === page.host) return verdict("act", "tab_switch", `Switching to another tab of ${target.host}.`);
      return verdict("sensitive", "other_site", `Switching to a tab on another site: ${target.host}.`, target.host);
    }
    case "press_key":
      return keyVerdict(args.key, element, page!, ctx);
    case "click":
    case "type_text":
    case "select_option":
    case "submit_form": {
      if (!element) return blocked("no_element", "The element is not on the page any more. Read the page again.");
      if (tool === "click") return clickVerdict(element, page!, ctx);
      if (tool === "type_text") return typeVerdict(element);
      if (tool === "submit_form") return submitVerdict(element, ctx);
      return verdict("act", "select", `Choosing an option in ${named(element)}.`);
    }
    default:
      return blocked("unknown_tool", `The agent has no tool called ${tool}.`);
  }
}

/** Who has to agree: reads go ahead, sensitive actions always ask, and Auto mode lets the review model decide the rest. */
export function approvalFor(result: Verdict, mode: AgentMode): Approval {
  switch (result.class) {
    case "read":
      return "none";
    case "act":
      return mode === "auto" ? "review" : "user";
    case "sensitive":
      return "user";
    default:
      return "refuse";
  }
}
