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
};

export type PolicyContext = {
  policy: SitePolicy;
  /** This Alpharouter's host, which an allow list never shuts out. */
  serverHost: string | null;
  /** This Alpharouter's origin ("https://ai.example.com"): the agent never works on its pages. */
  serverOrigin: string | null;
};

/**
 * An address's origin as the rules compare it: scheme, host without a
 * trailing dot, and a port only when it is not the scheme's own.
 */
export function originOf(url: string | null | undefined): string | null {
  try {
    const parsed = new URL(url ?? "");
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
    return `${parsed.protocol}//${parsed.hostname.replace(/\.$/, "").toLowerCase()}${parsed.port ? `:${parsed.port}` : ""}`;
  } catch {
    return null;
  }
}

const READ_TOOLS = new Set(["tabs_list", "read_page", "find", "get_page_text", "scroll", "wait_for", "ask_user", "done"]);
const PAGE_TOOLS = new Set(["read_page", "find", "get_page_text", "scroll", "wait_for", "click", "type_text", "select_option", "press_key", "submit_form"]);

/**
 * Words on a button (or a link, in English) that buy or pay. Order alone is
 * checked as the whole label or with a verb, so "Order history" is not one.
 */
const PURCHASE = /\b(buy|pay|purchase|checkout|check out)\b|\b(place|submit|complete|confirm)( your| the| my)? order\b|^order( now)?$/i;
const PURCHASE_FA = /خرید|پرداخت|سفارش|تسویه/;
/** Persian words that buy even on a link; "سفارش" there is usually "my orders". */
const PURCHASE_FA_LINK = /خرید|پرداخت/;
/** Words that send, delete, confirm, move or publish something. */
const SENSITIVE = /\b(send|submit|delete|remove|confirm|transfer|download|publish|post)\b/i;
const SENSITIVE_FA = /ارسال|فرستادن|بفرست|حذف|پاک\s?کردن|تایید|تأیید|انتقال|دانلود|بارگیری|انتشار|منتشر|پست/;
/** Fields for a person's identity documents. */
const ID_FIELD = /\b(ssn|social security|passport|national id|national identity|tax id|id number|identity number)\b/i;
const ID_FIELD_FA = /کد\s?ملی|شماره\s?ملی|شناسنامه|گذرنامه|پاسپورت/;

const BUTTON_ROLES = new Set(["button", "menuitem", "menuitemcheckbox", "menuitemradio", "tab", "option", "switch", "treeitem"]);

function verdict(cls: ActionClass, reason: string, message: string, site?: string): Verdict {
  return site ? { class: cls, reason, message, site } : { class: cls, reason, message };
}

function blocked(reason: string, message: string): Verdict {
  return verdict("blocked", reason, message);
}

/**
 * Why the agent may not work on the page at `url` (on `host`) at all, or null.
 * Alpharouter's own pages are told by their origin: another program on the
 * same host, on another port, is not Alpharouter.
 */
function siteVerdict(url: string, host: string, ctx: PolicyContext): Verdict | null {
  if (ctx.serverOrigin && originOf(url) === ctx.serverOrigin) {
    return blocked("own_server", "The agent does not work on Alpharouter itself.");
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
  const refused = siteVerdict(String(rawUrl), target.host, ctx);
  if (refused) return refused;
  if (fromHost && target.host === fromHost) return verdict("act", "same_site", `${what} on ${target.host}.`);
  return verdict("sensitive", "other_site", `${what} on another site: ${target.host}.`, target.host);
}

function purchase(name: string, role: string): boolean {
  if (PURCHASE.test(name)) return true;
  return role === "link" ? PURCHASE_FA_LINK.test(name) : PURCHASE_FA.test(name);
}

function sendsSomething(name: string): boolean {
  return SENSITIVE.test(name) || SENSITIVE_FA.test(name);
}

function named(element: ElementInfo): string {
  return element.name ? `"${element.name}"` : `element ${element.ref}`;
}

function clickVerdict(element: ElementInfo, page: { url: string; host: string }, ctx: PolicyContext): Verdict {
  const name = element.name.trim();
  const buttonish = BUTTON_ROLES.has(element.role) || element.submits === true;
  if ((buttonish || element.role === "link") && purchase(name, element.role)) {
    return blocked("purchase_label", `The agent never buys or pays: ${named(element)} is for the user to click.`);
  }
  if (element.role === "link" && element.href) {
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
      const refused = siteVerdict(element.formAction!, target.host, ctx);
      if (refused) return refused;
    }
    return verdict("sensitive", "submit", `Clicking ${named(element)} sends a form.`);
  }
  if (sendsSomething(name)) return verdict("sensitive", "sensitive_label", `Clicking ${named(element)} may send, delete or publish something.`);
  return verdict("act", "click", `Clicking ${named(element)}.`);
}

function typeVerdict(element: ElementInfo): Verdict {
  if (element.sensitive) {
    return blocked("sensitive_field", `The agent never types into ${named(element)}: passwords, card numbers and codes are for the user to enter.`);
  }
  const described = `${element.name} ${element.type ?? ""}`;
  if (ID_FIELD.test(described) || ID_FIELD_FA.test(described)) {
    return blocked("id_field", `The agent never types into ${named(element)}: identity numbers are for the user to enter.`);
  }
  return verdict("act", "type", `Typing into ${named(element)}.`);
}

function submitVerdict(element: ElementInfo, ctx: PolicyContext): Verdict {
  if (purchase(element.name.trim(), element.role === "link" ? "button" : element.role)) {
    return blocked("purchase_label", `The agent never buys or pays: sending ${named(element)} is for the user.`);
  }
  const target = element.formAction ? readablePage(element.formAction) : null;
  if (target) {
    const refused = siteVerdict(element.formAction!, target.host, ctx);
    if (refused) return refused;
  }
  return verdict("sensitive", "submit", `Sending the form${element.name ? ` with ${named(element)}` : ""}.`);
}

/** What kind of action this is, from the tool, the element, the addresses involved and the site rules. */
export function classifyAction(action: ProposedAction, ctx: PolicyContext): Verdict {
  const { tool, args, page, element } = action;
  if (PAGE_TOOLS.has(tool)) {
    if (!page) return blocked("no_page", "The tab does not show a web page the agent can work on.");
    const refused = siteVerdict(page.url, page.host, ctx);
    if (refused) return refused;
  }
  if (READ_TOOLS.has(tool)) return verdict("read", "read", "Looking, without changing anything.");
  switch (tool) {
    case "navigate":
      return goingTo(args.url, page?.host, ctx, "Opening a page");
    case "tab_open":
      return goingTo(args.url, page?.host, ctx, "Opening a page in a new tab");
    case "tab_switch":
      return verdict("act", "tab_switch", "Switching to another tab.");
    case "press_key":
      return verdict("act", "press_key", `Pressing ${typeof args.key === "string" ? args.key : "a key"}.`);
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
