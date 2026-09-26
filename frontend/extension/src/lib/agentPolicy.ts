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
 *   deletes, confirms, downloads or publishes, going to another site (which
 *   may also need the browser's permission for it), giving a program access
 *   to an account, changing what keeps an account safe, typing a person's
 *   phone number or address, uploading, and anything the rules cannot judge:
 *   a target in a frame from another site, or one drawn so as not to be seen.
 * - blocked: refused, with the reason told to the model - typing into a
 *   password, card, one-time-code or ID field, anything that buys, pays,
 *   trades or moves money, creating an account, deleting for good, an
 *   executable download, a CAPTCHA, the clipboard and the browser's own
 *   shortcuts, a special-scheme address, a site the administrator's rules
 *   keep out, acting on a read-only or protected site, and Alpharouter
 *   itself.
 *
 * The administrator can relax some of the sensitive cases (`Approvals`): the
 * words that send or delete, forms, downloads, uploads, leaving the site and
 * the page's own dialogs then count as plain actions. The rest is fixed, and
 * blocked stays blocked in every mode.
 *
 * The rules judge what the element says about itself (its role and accessible
 * name, where a link or form goes), read fresh from the page just before the
 * action - under full control, the element under the point the mouse will
 * press. The page can lie in its labels; that is why sending and paying are
 * never left to the agent alone, and the words are checked in English and in
 * Persian.
 */

import type { ElementInfo } from "../content/agent";
import { sensitiveText } from "./sensitive";
import { hostMatches, readablePage, siteRefusal, type SitePolicy } from "./sites";

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
  /** The element `args.ref` names (or the one under the point), as the page described it just now. */
  element?: ElementInfo;
  /** For a drag: what is under the point it ends at. */
  drop?: ElementInfo;
  /** For tab_switch: the tab it goes to (its host is null when it shows no web page). */
  target?: { url: string; host: string | null };
};

/**
 * The sensitive cases the administrator may relax, each true when it still
 * asks the user. What is not here is fixed.
 */
export type Approvals = {
  /** Sending a message, an email, a reply, a post; Enter in a message box. */
  send: boolean;
  /** Sending a form. */
  submit: boolean;
  /** Deleting, removing, discarding (never deleting for good, which is refused). */
  delete: boolean;
  /** Going to another site: a link, an address, a tab of another site. */
  leave_sites: boolean;
  downloads: boolean;
  uploads: boolean;
  /** The page's confirm and prompt dialogs. */
  dialogs: boolean;
};

export const DEFAULT_APPROVALS: Approvals = { send: true, submit: true, delete: true, leave_sites: true, downloads: true, uploads: true, dialogs: true };

/**
 * Where the page's content may go, for this run's model: the administrator
 * marks the organisation's internal sites, and which models may see them
 * and screenshots at all.
 */
type DataRules = {
  /** Sites internal to the organisation, as patterns (`*.example.com`). */
  internalSites: string[];
  /** This run's model may read internal sites' pages and see their screenshots. */
  modelSeesInternal: boolean;
  /** This run's model may see screenshots (of other sites) at all. */
  modelSeesScreenshots: boolean;
};

const OPEN_DATA_RULES: DataRules = { internalSites: [], modelSeesInternal: true, modelSeesScreenshots: true };

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
  /** Which sensitive cases still ask; DEFAULT_APPROVALS when not given. */
  approvals?: Approvals;
  /** Where content may go; everything allowed when not given. */
  data?: DataRules;
};

// screenshot and zoom are full control's reads: they show the page, so a page the agent may not work on is refused too.
const READ_TOOLS = new Set(["tabs_list", "read_page", "find", "get_page_text", "scroll", "wait_for", "ask_user", "done", "screenshot", "zoom"]);
const SHOWS_PAGE = new Set(["screenshot", "zoom"]);
const PAGE_TOOLS = new Set([
  "read_page",
  "find",
  "get_page_text",
  "scroll",
  "wait_for",
  "click",
  "type_text",
  "select_option",
  "press_key",
  "submit_form",
  "screenshot",
  "zoom",
  "drag",
]);

/**
 * Words on a button (or a link, in English) that buy, pay, bid or give
 * money. Order alone is checked as the whole label or with a verb, so
 * "Order history" is not one. Matched on the `labelForms` of the label.
 */
const PURCHASE =
  /\b(buy|pay|purchase|checkout|check out|donate|pre-?order)\b|\b(place|submit|complete|confirm)( your| the| my| an)? order\b|^order( now)?$|\bplace (a )?bid\b|\bbid now\b|\b(continue|proceed|go) to (payment|checkout)\b|\b(complete|make|confirm|submit) (the |a |your )?payment\b|\badd funds\b/;
const PURCHASE_FA = /خرید|پرداخت|سفارش|تسویه|اهدا|کمک مالی/;
/** Persian words that buy even on a link; "سفارش" there is usually "my orders". */
const PURCHASE_FA_LINK = /خرید|پرداخت|اهدا/;
/** Words that trade or move money: never the agent's to press. */
const MONEY =
  /\b(sell|trade|swap|withdraw|deposit (funds|money|now)|make a deposit|transfer funds|transfer money|send money|wire transfer|place (a |the )?trade|execute (a |the )?trade|exchange now|convert funds|top up|redeem)\b|^(deposit|withdrawal)$/;
const MONEY_FA = /معامله|فروش(?!گاه|نده)|برداشت|واریز|انتقال وجه|حواله|کارت به کارت|شارژ حساب/;
/** Words that make a new account. */
const SIGN_UP = /\b(sign ?up|create (an |a |my |your |new )?account|join now|open (an |a )?account|get started free)\b|^register( now| here| for free)?$|\bregister (an |a |my |your )?account\b/;
const SIGN_UP_FA = /ثبت ?نام|ایجاد حساب|ساخت حساب|افتتاح حساب|عضویت|عضو شوید/;
/** Words that delete for good. */
const DELETE_FOREVER =
  /\b(delete (forever|permanently|for good)|permanently (delete|remove|erase)|empty (the )?(trash|bin|recycle bin)|delete (all|everything)|erase (all|everything)|purge|wipe|shred|factory reset|delete (my |the |your )?account|close (my |the |your )?account)\b/;
const DELETE_FOREVER_FA = /حذف (دائم|دائمی|همیشگی|برای همیشه|کامل)|خالی کردن سطل|پاک کردن (همه|کل)|حذف (همه|همه‌ی|کل)|حذف حساب|بستن حساب/;
/** Words that send, publish or reply (the administrator can relax these). */
const SEND = /\b(send|reply|forward|post|publish|share|subscribe|unsubscribe|tweet|comment)\b/;
const SEND_FA = /ارسال|فرستادن|بفرست|انتشار|منتشر|پست|پاسخ|بازارسال|هدایت|اشتراک|ثبت/;
/** Words that delete or discard (the administrator can relax these). */
const DELETE = /\b(delete|remove|discard|erase|trash|clear all)\b/;
const DELETE_FA = /حذف|پاک ?کردن|دور انداختن/;
/** Words that submit something other than a form (the administrator relaxes them with forms). */
const SUBMIT = /\bsubmit\b/;
/** Words that download (the administrator can relax these). */
const DOWNLOAD = /\b(download|save (as|file|to (my )?(computer|device)))\b/;
const DOWNLOAD_FA = /دانلود|بارگیری|ذخیره (فایل|در)/;
/** Words that confirm, approve, transfer or cancel something: always ask. */
const CONFIRM =
  /\b(confirm|transfer|approve|accept|agree|i agree|book|reserve|activate|deactivate|enable|disable|revoke|reset)\b|\bcancel (my |the |your )?(order|subscription|booking|reservation|account|membership|plan)\b/;
const CONFIRM_FA = /تایید|تأیید|انتقال|قبول|موافق|رزرو|لغو|فعال|غیرفعال|بازنشانی/;
/** Words that give a program access to an account, or change what keeps it safe: always ask. */
const AUTHORIZE =
  /\b(allow access|grant access|authorize|authorise|allow|continue as|connect (to|with|your)|link (account|your)|give access|api key|access token|generate (a )?(token|key)|two-?factor|2fa|change (my |your |the )?(password|email|phone)|recovery (email|phone|codes)|trusted devices?|sign out (of )?(all|everywhere)|security (settings|key))\b/;
const AUTHORIZE_FA = /اجازه دسترسی|اعطای دسترسی|دسترسی بده|مجوز|تغییر رمز|رمز عبور|احراز هویت دو|تأیید دو مرحله|تایید دو مرحله|تنظیمات امنیتی|کلید api|توکن/;
/** Words that upload (the administrator can relax these). */
const UPLOAD = /\b(upload|attach(ment)?|choose file|browse files?|drop (files?|here)|add (a )?(file|photo|image|attachment))\b/;
const UPLOAD_FA = /بارگذاری|آپلود|پیوست|انتخاب فایل|افزودن فایل/;
/** Files that run when opened: never downloaded by the agent. */
const EXECUTABLE = /\.(exe|msi|msix|appx|bat|cmd|scr|ps1|psm1|vbs|vbe|jse|wsf|wsh|hta|cpl|reg|jar|sh|bash|run|bin|dmg|pkg|apk|deb|rpm|iso|img)$/i;

/** Pages where a person hands a program access to their account: every action there asks. */
const CONSENT_PAGES: Array<{ host: RegExp; path: RegExp }> = [
  { host: /^accounts\.google\.com$/, path: /^\/(o\/oauth2|signin\/oauth|v3\/signin\/consent)/ },
  { host: /^login\.microsoftonline\.com$/, path: /oauth2|\/consent/ },
  { host: /^login\.live\.com$/, path: /oauth20/ },
  { host: /^github\.com$/, path: /^\/login\/oauth/ },
  { host: /^appleid\.apple\.com$/, path: /^\/auth\/authorize/ },
  { host: /(^|\.)facebook\.com$/, path: /\/dialog\/oauth/ },
  { host: /./, path: /\/(oauth2?\/(authorize|consent)|authorize|consent)(\/|$)/ },
];

/** Where CAPTCHAs are served from: a click in one of their frames is the user's. */
const CAPTCHA_HOSTS = ["www.google.com", "google.com", "recaptcha.net", "www.recaptcha.net", "*.hcaptcha.com", "hcaptcha.com", "challenges.cloudflare.com", "*.arkoselabs.com", "*.funcaptcha.com"];

/**
 * A label as the word lists read it: compatibility forms folded, in lower
 * case, Persian written with Arabic yeh or kaf read as Persian, without the
 * tatweel and diacritics that change how a word is drawn but not what it
 * says, and without the marks around it ("Order now!", "Order now →",
 * "🛒 Buy"). Otherwise "خريد" or "خریـــد" would not be "خرید", and "Order
 * now!" would not be "Order now".
 *
 * Two forms, for the invisible format characters (zero-width joiners and
 * spaces, the word joiner, direction marks, soft hyphens): inside a word one
 * hides it (a word joiner in "Buy"), between words it parts them (one
 * between "Buy" and "now", drawn as "Buynow"). So a label is read once
 * without them and once with each as a space.
 */
function labelForms(text: string): string[] {
  const folded = text.normalize("NFKC").toLowerCase().replace(/[يى]/g, "ی").replace(/ك/g, "ک").replace(/ـ/g, "");
  return [folded.replace(/\p{Cf}/gu, ""), folded.replace(/\p{Cf}/gu, " ")].map((form) =>
    form
      .replace(/\p{M}/gu, "")
      .replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "")
      .replace(/\s+/g, " "),
  );
}
/** Fields for a person's identity documents. */
const ID_FIELD = /\b(ssn|social security|passport|national id|national identity|tax id|id number|identity number)\b/i;
const ID_FIELD_FA = /کد\s?ملی|شماره\s?ملی|شناسنامه|گذرنامه|پاسپورت/;
/** Fields for a person's contact and bank details: typing there asks (IBAN and Sheba numbers are secrets to sensitive.ts, and refused). */
const PERSONAL_FIELD = /\b(phone|mobile|telephone|address|street|date of birth|birth ?date|birthday|postal ?code|zip ?code|account number|bank account|routing number|sort code)\b/i;
const PERSONAL_FIELD_FA = /تلفن|موبایل|همراه|آدرس|نشانی|تاریخ تولد|کد ?پستی|شماره حساب/;

function matches(text: string, ...lists: RegExp[]): boolean {
  return labelForms(text).some((form) => lists.some((list) => list.test(form)));
}

function verdict(cls: ActionClass, reason: string, message: string, site?: string): Verdict {
  return site ? { class: cls, reason, message, site } : { class: cls, reason, message };
}

function blocked(reason: string, message: string): Verdict {
  return verdict("blocked", reason, message);
}

/** Sensitive, or a plain action when the administrator relaxed this case. */
function asks(relaxed: boolean, reason: string, message: string, site?: string): Verdict {
  return verdict(relaxed ? "act" : "sensitive", reason, message, site);
}

function approvals(ctx: PolicyContext): Approvals {
  return ctx.approvals ?? DEFAULT_APPROVALS;
}

function data(ctx: PolicyContext): DataRules {
  return ctx.data ?? OPEN_DATA_RULES;
}

function inList(host: string, patterns: string[]): boolean {
  return patterns.some((pattern) => hostMatches(host, pattern));
}

/** What the agent means to do on a site: look, show it to the model as an image, or change something. */
type Intent = "read" | "screenshot" | "act";

/**
 * Why the agent may not do `intent` on the page on `host`, or null.
 * Alpharouter's own pages are told by their host, whatever the port or scheme.
 */
function siteVerdict(host: string, ctx: PolicyContext, intent: Intent): Verdict | null {
  if (ctx.ownHosts.includes(host)) {
    return blocked("own_server", "The agent does not work on Alpharouter itself, nor on any other address of its host.");
  }
  const refusal = siteRefusal(host, ctx.policy, ctx.serverHost);
  if (refusal === "site_blocked") return blocked("site_blocked", `Your administrator does not allow the agent on ${host}.`);
  if (refusal === "site_not_allowed") return blocked("site_not_allowed", `${host} is not on the list of sites your administrator allows.`);
  const rules = data(ctx);
  if (inList(host, rules.internalSites) && !rules.modelSeesInternal) {
    return blocked("internal_site", `${host} is internal to your organisation, and this model runs outside it: choose a model your administrator allows for internal sites.`);
  }
  if (intent === "screenshot" && !rules.modelSeesScreenshots) {
    return blocked("screenshot_external", "Your administrator does not let this model see screenshots: work from read_page and the reference tools.");
  }
  if (intent === "act" && inList(host, ctx.policy.protected_sites ?? [])) {
    return blocked("protected_site", `${host} is a protected site: the agent reads it and never acts there. Whatever is to be done there is for the user.`);
  }
  if (intent === "act" && inList(host, ctx.policy.read_only_sites ?? [])) {
    return blocked("read_only_site", `${host} is a read-only site for the agent: it may read the page, and changes nothing there.`);
  }
  return null;
}

/** Going to `rawUrl` from the page on `fromHost`: the same site acts, another site asks (unless relaxed). */
function goingTo(rawUrl: unknown, fromHost: string | undefined, ctx: PolicyContext, what: string): Verdict {
  const target = typeof rawUrl === "string" ? readablePage(rawUrl) : null;
  if (!target) return blocked("special_scheme", `The agent opens web pages only (http or https), never ${typeof rawUrl === "string" ? "that address" : "a missing address"}.`);
  const refused = siteVerdict(target.host, ctx, "read");
  if (refused) return refused;
  if (fromHost && target.host === fromHost) return verdict("act", "same_site", `${what} on ${target.host}.`);
  return asks(!approvals(ctx).leave_sites, "other_site", `${what} on another site: ${target.host}.`, target.host);
}

/** Whether `url` is a page where a person hands a program access to their account. */
export function consentPage(url: string | undefined): boolean {
  const page = url ? readablePage(url) : null;
  if (!page || !url) return false;
  const path = new URL(url).pathname;
  return CONSENT_PAGES.some((entry) => entry.host.test(page.host) && entry.path.test(path));
}

function purchase(name: string, role: string): boolean {
  const persian = role === "link" ? PURCHASE_FA_LINK : PURCHASE_FA;
  return labelForms(name).some((form) => PURCHASE.test(form) || persian.test(form));
}

function named(element: ElementInfo): string {
  return element.name ? `"${element.name}"` : element.text ? `"${element.text}"` : `element ${element.ref}`;
}

/** What a control says of itself: its name, and the words it shows when they differ (a label can hide them). */
function labels(element: ElementInfo): string[] {
  return [element.name, element.text ?? ""].map((label) => label.trim()).filter(Boolean);
}

/** A target the rules cannot judge, or one hidden from the eye: the user decides, in every mode - or a CAPTCHA, which is the user's alone. */
function unjudgeable(element: ElementInfo, what: string): Verdict | null {
  if (element.frame) {
    const host = element.frame.host;
    if (host && inList(host, CAPTCHA_HOSTS)) {
      return blocked("captcha", "That is a CAPTCHA: solve it yourself, then tell the agent to go on.");
    }
    return verdict("sensitive", "other_site_frame", `${what} is in a frame from ${host ? `another site (${host})` : "another site"}, which this page cannot see into: the rules cannot tell what it does.`);
  }
  if (element.hidden === "transparent") {
    return verdict("sensitive", "hidden_target", `${what} is drawn too faint to see (${named(element)}): a click there may not do what the page appears to offer.`);
  }
  if (element.hidden === "tiny") {
    return verdict("sensitive", "hidden_target", `${what} is only a couple of pixels in size (${named(element)}): a click there may not do what the page appears to offer.`);
  }
  return null;
}

/** The rules for a label's words: what pressing it does, from the never list down to the plain action. */
function labelVerdict(element: ElementInfo, said: string[], linkish: boolean, page: { url: string; host: string }, ctx: PolicyContext): Verdict | null {
  const relax = approvals(ctx);
  // Whatever the element claims to be: a <div onclick> drawn as a button places an order as well as a <button> does.
  if (said.some((label) => purchase(label, linkish ? "link" : element.role))) {
    return blocked("purchase_label", `The agent never buys or pays: ${named(element)} is for the user to click.`);
  }
  if (said.some((label) => matches(label, MONEY, MONEY_FA))) {
    return blocked("money_label", `The agent never trades or moves money: ${named(element)} is for the user to click.`);
  }
  if (said.some((label) => matches(label, DELETE_FOREVER, DELETE_FOREVER_FA))) {
    return blocked("permanent_deletion", `The agent never deletes for good or closes an account: ${named(element)} is for the user to click.`);
  }
  if (said.some((label) => matches(label, SIGN_UP, SIGN_UP_FA))) {
    return blocked("account_creation", `The agent never creates accounts: ${named(element)} is for the user to click.`);
  }
  if (consentPage(page.url) || said.some((label) => matches(label, AUTHORIZE, AUTHORIZE_FA))) {
    return verdict("sensitive", "authorization", `${named(element)} may give a program access to an account, or change what keeps one safe.`);
  }
  if (said.some((label) => matches(label, UPLOAD, UPLOAD_FA))) {
    return asks(!relax.uploads, "upload", `Clicking ${named(element)} may upload a file.`);
  }
  if (said.some((label) => matches(label, DOWNLOAD, DOWNLOAD_FA))) {
    return asks(!relax.downloads, "download", `Clicking ${named(element)} may download a file.`);
  }
  if (said.some((label) => matches(label, DELETE, DELETE_FA))) {
    return asks(!relax.delete, "delete_label", `Clicking ${named(element)} may delete something.`);
  }
  if (said.some((label) => matches(label, SUBMIT))) {
    return asks(!relax.submit, "submit", `Clicking ${named(element)} may send a form.`);
  }
  if (said.some((label) => matches(label, SEND, SEND_FA))) {
    return asks(!relax.send, "sensitive_label", `Clicking ${named(element)} may send or publish something.`);
  }
  if (said.some((label) => matches(label, CONFIRM, CONFIRM_FA))) {
    return verdict("sensitive", "sensitive_label", `Clicking ${named(element)} may confirm, transfer or cancel something.`);
  }
  return null;
}

function clickVerdict(element: ElementInfo, page: { url: string; host: string }, ctx: PolicyContext): Verdict {
  const cannot = unjudgeable(element, "The target");
  if (cannot) return cannot;
  const said = labels(element);
  // A link is where it goes, whatever role it claims (a menu item, a "button").
  const linkish = element.role === "link" || Boolean(element.href);
  if (element.href && EXECUTABLE.test(new URL(element.href, page.url).pathname)) {
    return blocked("executable_download", `The agent never downloads a program: ${named(element)} points at a file that runs when opened.`);
  }
  const byLabel = labelVerdict(element, said, linkish, page, ctx);
  if (byLabel) return byLabel;
  if (element.type === "file") return asks(!approvals(ctx).uploads, "upload", `Clicking ${named(element)} opens the file picker to upload a file.`);
  if (element.href) {
    let protocol = "";
    try {
      protocol = new URL(element.href).protocol;
    } catch {
      protocol = "";
    }
    if (protocol === "http:" || protocol === "https:") {
      const going = goingTo(element.href, page.host, ctx, `Following the link ${named(element)}`);
      if (going.class !== "act" || going.reason === "other_site") return going;
    } else if (protocol !== "javascript:") {
      // mailto:, tel: and the like hand over to another program.
      return verdict("sensitive", "other_app", `The link ${named(element)} opens another program.`);
    }
  }
  if (element.submits) {
    const target = element.formAction ? readablePage(element.formAction) : null;
    if (target) {
      const refused = siteVerdict(target.host, ctx, "act");
      if (refused) return refused;
    }
    return asks(!approvals(ctx).submit, "submit", `Clicking ${named(element)} sends a form.`);
  }
  // Nothing tells what it does - an icon without a name - so neither the agent nor a reviewer can judge it.
  if (!said.length && !element.href) {
    return verdict("sensitive", "unnamed_control", `The ${element.role === "text" ? "element" : element.role} ${element.ref} has no name, so what clicking it does cannot be told.`);
  }
  return verdict("act", "click", `Clicking ${named(element)}.`);
}

function typeVerdict(element: ElementInfo, page: { url: string; host: string }): Verdict {
  const cannot = unjudgeable(element, "The field");
  if (cannot) return cannot;
  const secret = () =>
    blocked("sensitive_field", `The agent never types into ${named(element)}: passwords, card numbers and codes are for the user to enter. Sign in yourself, then tell the agent to go on.`);
  if (element.sensitive) return secret();
  const field = `${element.name} ${element.type ?? ""}`;
  if (matches(field, ID_FIELD, ID_FIELD_FA)) {
    return blocked("id_field", `The agent never types into ${named(element)}: identity numbers are for the user to enter.`);
  }
  // The page judges the field by everything it says about it; its name is checked here as well.
  if (sensitiveText(element.name)) return secret();
  if (consentPage(page.url)) return verdict("sensitive", "authorization", `Typing on a page that gives a program access to an account.`);
  if (matches(field, PERSONAL_FIELD, PERSONAL_FIELD_FA) || element.type === "tel") {
    return verdict("sensitive", "personal_data", `Typing into ${named(element)} gives a page personal details.`);
  }
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
function submitVerdict(element: ElementInfo, page: { url: string; host: string }, ctx: PolicyContext): Verdict {
  const cannot = unjudgeable(element, "The form");
  if (cannot) return cannot;
  const said = [...labels(element), ...(element.formButton ?? [])];
  const button = element.formButton?.[0] ?? element.name;
  if (said.some((label) => purchase(label, "button"))) {
    return blocked("purchase_label", `The agent never buys or pays: sending this form (its button says "${button}") is for the user.`);
  }
  if (said.some((label) => matches(label, MONEY, MONEY_FA))) {
    return blocked("money_label", `The agent never trades or moves money: sending this form (its button says "${button}") is for the user.`);
  }
  if (said.some((label) => matches(label, SIGN_UP, SIGN_UP_FA))) {
    return blocked("account_creation", `The agent never creates accounts: sending this form (its button says "${button}") is for the user.`);
  }
  if (said.some((label) => matches(label, DELETE_FOREVER, DELETE_FOREVER_FA))) {
    return blocked("permanent_deletion", `The agent never deletes for good or closes an account: sending this form (its button says "${button}") is for the user.`);
  }
  const target = element.formAction ? readablePage(element.formAction) : null;
  if (target) {
    const refused = siteVerdict(target.host, ctx, "act");
    if (refused) return refused;
  }
  if (consentPage(page.url) || said.some((label) => matches(label, AUTHORIZE, AUTHORIZE_FA))) {
    return verdict("sensitive", "authorization", `Sending this form may give a program access to an account, or change what keeps one safe.`);
  }
  return asks(!approvals(ctx).submit, "submit", `Sending the form${destination(element.formAction)}${element.name ? ` from ${named(element)}` : ""}.`);
}

/** Roles of fields that hold text a person types. */
const TEXT_ROLES = new Set(["textbox", "searchbox", "combobox", "spinbutton"]);

/** A key as the model names it ("ctrl+shift+a", "Enter", "Space"): the key, and what is held. */
export type KeyCombo = { key: string; ctrl: boolean; alt: boolean; shift: boolean; meta: boolean };

/** Key names as the model may write them, lower-cased, to the key as the rules read it. */
const KEY_NAMES: Record<string, string> = {
  enter: "Enter",
  return: "Enter",
  tab: "Tab",
  escape: "Escape",
  esc: "Escape",
  backspace: "Backspace",
  delete: "Delete",
  del: "Delete",
  space: " ",
  spacebar: " ",
  " ": " ",
  arrowup: "ArrowUp",
  up: "ArrowUp",
  arrowdown: "ArrowDown",
  down: "ArrowDown",
  arrowleft: "ArrowLeft",
  left: "ArrowLeft",
  arrowright: "ArrowRight",
  right: "ArrowRight",
  home: "Home",
  end: "End",
  pageup: "PageUp",
  pagedown: "PageDown",
  insert: "Insert",
};

export function parseKeyCombo(raw: unknown): KeyCombo | null {
  if (typeof raw !== "string" || !raw.trim()) return null;
  const tokens = raw.split("+").map((t) => t.trim()).filter(Boolean);
  if (!tokens.length) return null;
  const combo: KeyCombo = { key: "", ctrl: false, alt: false, shift: false, meta: false };
  for (const token of tokens.slice(0, -1)) {
    const mod = token.toLowerCase();
    if (mod === "ctrl" || mod === "control") combo.ctrl = true;
    else if (mod === "alt" || mod === "option") combo.alt = true;
    else if (mod === "shift") combo.shift = true;
    else if (mod === "meta" || mod === "cmd" || mod === "command" || mod === "win" || mod === "super") combo.meta = true;
    else return null;
  }
  const last = tokens[tokens.length - 1];
  const lower = last.toLowerCase();
  combo.key = KEY_NAMES[lower] ?? ([...last].length === 1 ? last : lower.replace(/^./, (c) => c.toUpperCase()));
  return combo;
}

/** Keys that stay within the page when Ctrl or Cmd is held: editing, selecting, moving. */
const EDITING_SHORTCUTS = new Set(["a", "c", "x", "z", "y", "b", "i", "u", "Enter", "Backspace", "Delete", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"]);

/**
 * A key press, judged by the element it goes to (`element`: the focused
 * one, if any). Enter in a message box is how most web apps send; on a
 * control, Enter or Space works as a click in the page's own handlers; and
 * Delete outside a text field deletes whatever the page has selected. With
 * Ctrl or Cmd held, only editing keys are the agent's: the clipboard and the
 * browser's own shortcuts are not.
 */
function keyVerdict(rawKey: unknown, element: ElementInfo | undefined, page: { url: string; host: string }, ctx: PolicyContext): Verdict {
  const combo = parseKeyCombo(rawKey) ?? { key: "", ctrl: false, alt: false, shift: false, meta: false };
  const key = combo.key;
  const shown = key === " " ? "Space" : key || "a key";
  if (element) {
    const cannot = unjudgeable(element, "The focused element");
    if (cannot) return cannot;
  }
  if ((combo.ctrl || combo.meta) && key.toLowerCase() === "v") {
    return blocked("clipboard", "The agent never pastes what is on your clipboard: it types the text itself.");
  }
  if (combo.alt || ((combo.ctrl || combo.meta) && !EDITING_SHORTCUTS.has(key.length === 1 ? key.toLowerCase() : key))) {
    return blocked("browser_shortcut", `The agent does not press ${String(rawKey)}: keys that reach the browser itself (tabs, zoom, printing, the address bar, history) are not its to press.`);
  }
  if (/^F\d{1,2}$/.test(key)) return blocked("browser_shortcut", `The agent does not press ${key}: function keys reach the browser itself.`);
  const relax = approvals(ctx);
  const inText = Boolean(element && (TEXT_ROLES.has(element.role) || element.tag === "textarea"));
  if (element && inText && key === "Enter" && !combo.shift) {
    if (element.role === "searchbox" || element.type === "search") return verdict("act", "press_key", `Pressing Enter in ${named(element)} to search.`);
    return asks(!relax.send, "enter_sends", `Pressing Enter in ${named(element)} may send what it holds.`);
  }
  if (element && !inText && (key === "Enter" || key === " ")) {
    const asClick = clickVerdict(element, page, ctx);
    if (asClick.class === "act") return verdict("act", "press_key", `Pressing ${shown} on ${named(element)}.`);
    return { ...asClick, message: `Pressing ${shown} on ${named(element)} works like clicking it. ${asClick.message}` };
  }
  if (!inText && (key === "Delete" || key === "Backspace")) {
    return asks(!relax.delete, "delete_key", `Pressing ${shown} ${element ? `on ${named(element)}` : "on the page"} may delete something.`);
  }
  if (element && consentPage(page.url)) return verdict("sensitive", "authorization", `Pressing ${shown} on a page that gives a program access to an account.`);
  return verdict("act", "press_key", `Pressing ${shown}${element ? ` in ${named(element)}` : ""}.`);
}

/** A drag: judged by what it takes and where it drops - a drop on a file input or an upload zone uploads. */
function dragVerdict(source: ElementInfo, drop: ElementInfo | undefined, page: { url: string; host: string }, ctx: PolicyContext): Verdict {
  const cannot = unjudgeable(source, "The dragged element") ?? (drop ? unjudgeable(drop, "The drop target") : null);
  if (cannot) return cannot;
  if (drop) {
    const said = labels(drop);
    if (drop.type === "file" || said.some((label) => matches(label, UPLOAD, UPLOAD_FA))) {
      return asks(!approvals(ctx).uploads, "upload", `Dropping onto ${named(drop)} may upload a file.`);
    }
    const byLabel = labelVerdict(drop, said, Boolean(drop.href), page, ctx);
    if (byLabel && byLabel.class === "blocked") return byLabel;
  }
  return verdict("act", "drag", `Dragging ${named(source)}${drop ? ` to ${named(drop)}` : ""}.`);
}

/** What kind of action this is, from the tool, the element, the addresses involved and the site rules. */
export function classifyAction(action: ProposedAction, ctx: PolicyContext): Verdict {
  const { tool, args, page, element, drop, target } = action;
  if (PAGE_TOOLS.has(tool)) {
    if (!page) return blocked("no_page", "The tab does not show a web page the agent can work on.");
    const refused = siteVerdict(page.host, ctx, SHOWS_PAGE.has(tool) ? "screenshot" : READ_TOOLS.has(tool) ? "read" : "act");
    if (refused) return refused;
  }
  if (READ_TOOLS.has(tool)) return verdict("read", "read", "Looking, without changing anything.");
  switch (tool) {
    case "navigate": {
      // A tab the agent may not work on is the user's: it is not sent elsewhere either.
      const away = page ? siteVerdict(page.host, ctx, "read") : null;
      if (away) return blocked("tab_refused", `The agent does not send away a tab it may not work on (${page!.host}). Open the page in a new tab instead.`);
      return goingTo(args.url, page?.host, ctx, "Opening a page");
    }
    case "tab_open":
      return goingTo(args.url, page?.host, ctx, "Opening a page in a new tab");
    case "tab_switch": {
      // Working in another tab is working on its site: the same rules as going there.
      if (!target) return blocked("no_tab", "There is no such tab in this window.");
      if (!target.host) return verdict("act", "tab_switch", "Switching to a tab that shows no web page.");
      const refused = siteVerdict(target.host, ctx, "read");
      if (refused) return refused;
      if (page && target.host === page.host) return verdict("act", "tab_switch", `Switching to another tab of ${target.host}.`);
      return asks(!approvals(ctx).leave_sites, "other_site", `Switching to a tab on another site: ${target.host}.`, target.host);
    }
    case "press_key":
      return keyVerdict(args.key, element, page!, ctx);
    case "drag":
      if (!element) return blocked("no_element", "There is nothing to drag at that point. Take a new screenshot.");
      return dragVerdict(element, drop, page!, ctx);
    case "click":
    case "type_text":
    case "select_option":
    case "submit_form": {
      if (!element) return blocked("no_element", "The element is not on the page any more. Read the page again.");
      if (tool === "click") return clickVerdict(element, page!, ctx);
      if (tool === "type_text") return typeVerdict(element, page!);
      if (tool === "submit_form") return submitVerdict(element, page!, ctx);
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
