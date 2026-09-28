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
import { KEY_NAMES_SHOWN, parseKeyCombo } from "./keys";
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

export type AgentMode = "ask" | "plan" | "auto";

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
 * Buying, judged by the whole label or by the phrases that buy: "Buy",
 * "Buy now", "Pay €12", "Place order", "Proceed to checkout". Refused on
 * anything the agent would click.
 */
const PURCHASE =
  /^(buy|buy (it |this )?now|pay|pay now|purchase|purchase now|checkout|check out|order|order now|donate|donate now|pre-?order|pre-?order now)$|^pay (the |this |my |your )?(bill|invoice|balance)$|\b(buy now|buy it now|pay now|place (your |the |my |an? )?order|complete (your |the |my )?(order|purchase|payment)|(proceed|continue|go) to (checkout|payment)|confirm (and )?pay|confirm (the |your )?payment|confirm (your |the |my )?(order|purchase)|make (a )?payment|submit (your |the )?(order|payment)|add funds|bid now|place (a |an )?bid)\b|\b(buy|pay|check ?out) with (1-?click|one click|apple pay|google pay|g ?pay|paypal|shop ?pay|card|credit card|debit card)\b|\bpay (\p{Sc}|\d)|^(buy|pay|order|donate|purchase|rent|pre-?order)( it| this)?( now| today)?( for)?[\s\-\u2013\u2014\u00b7:|,]*\p{Sc}?\s?\d[\d.,]*\s?(\p{Sc}|usd|eur|gbp|chf|inr|rub|jpy|aed|irr|تومان|ریال)?$/u;
const PURCHASE_FA =
  /^(خرید|پیش ?خرید|پرداخت|سفارش|تسویه|اهدا)$|خرید (کن|کنید|نهایی|آنلاین)|(^|\s)(بخر|بخرید|بپرداز|بپردازید)(\s|$)|سفارش (دهید|بدهید|بده)|پرداخت (آنلاین|نهایی|کنید|کن|و تکمیل|قبض)|ثبت (نهایی )?(و پرداخت )?سفارش|تکمیل (سفارش|خرید|پرداخت)|نهایی کردن (سفارش|خرید)|(تایید|تأیید) (و )?(پرداخت|سفارش|خرید)|تسویه حساب|کمک مالی|پرداخت [\d۰-۹]/;
/**
 * Buying words inside a longer label ("Best laptops to buy", "Pay bills"):
 * a click there may buy - it asks, and a form it sends is refused.
 */
const PURCHASE_WORDS = /\b(buy|pay|purchase|checkout|check out|donate|pre-?order)\b/;
const PURCHASE_WORDS_FA = /(^|\s)(خرید|پرداخت|اهدا)/;
/** What starts paying later: an upgrade, a trial, a subscription - never relaxed, always asked. */
const PURCHASE_LIKE = /\b(upgrade( now| (your |the )?plan| to [\p{L}]+)?|start (your |a |the )?(free )?trial|start (your |a |the )?(membership|subscription)|become a (member|subscriber)|free trial|subscribe( now| today)?|go premium|get premium|renew( now| (your |the )?(plan|subscription))?)\b/u;
const PURCHASE_LIKE_FA = /ارتقا(ی)? (حساب|اشتراک|به)|خرید اشتراک|تمدید (اشتراک|حساب)|اشتراک (ویژه|طلایی|پریمیوم)|نسخه آزمایشی رایگان/;
/**
 * Trading and moving money, judged by the whole label or by the phrases
 * that do it: "Sell", "Swap", "Withdraw funds", "Send money". Refused.
 */
const MONEY =
  /^(sell|sell now|trade|trade now|swap|swap now|withdraw|withdraw now|withdrawal|deposit|deposit now|exchange now|convert now|top up|top up now|redeem|redeem now)$|\b(sell (all|everything|now|shares|stocks?|crypto|coins?|tokens?|bitcoin|(my |the )?positions?)|place (a |the )?trade|execute (a |the )?trade|transfer (funds|money)|send (money|funds)|send (a |the |your )?payment|wire transfer|make a deposit|deposit (funds|money)|withdraw (funds|money)|swap (tokens?|coins?|crypto)|convert (funds|currency|crypto))\b|\bsend (\p{Sc}|\d)/u;
const MONEY_FA =
  /^(فروش|بفروش|بفروشید|معامله|برداشت|واریز|تبدیل)$|(^|\s)بفروشید(\s|$)|فروش (سهام|ارز|رمزارز|سکه|دارایی)|انتقال (وجه|پول)|ارسال (وجه|پول)|حواله|کارت به کارت|شارژ حساب|برداشت (وجه|از حساب)|واریز (وجه|به حساب)/;
/** Money words inside a longer label ("Sell on Amazon", "Swap languages"): ask, never refused on sight. */
const MONEY_WORDS = /\b(sell|trade|swap|withdraw)\b/;
const MONEY_WORDS_FA = /(^|\s)(فروش|معامله|برداشت|واریز)(\s|$)/;
/**
 * Words that make a new account, as a whole label or a phrase: "Sign up",
 * "Register", "Create your free account". "Register for the webinar" signs
 * up for something else: it asks.
 */
const SIGN_UP = /^(sign ?up|sign ?up (now|free|for free|here)|register|register (now|here|for free)|join|join (now|free|for free)|get started( free| for free)?)$|\b(create|open|register)( [\p{L}]+){0,3} account\b|\bcreate account\b/u;
const SIGN_UP_FA = /^(ثبت ?نام|ثبت ?نام کنید|عضویت|عضو شوید)$|ایجاد حساب|ساخت حساب|افتتاح حساب/;
const SIGN_UP_WORDS = /\b(sign ?up|register|join)\b/;
const SIGN_UP_WORDS_FA = /ثبت ?نام|عضویت|عضو شوید/;
/** Signing in: a label that offers it ("ورود | ثبت‌نام", "Log in or sign up") is a way in, not a new account. */
const LOGIN = /\b(log ?in|sign ?in)\b/;
const LOGIN_FA = /(^|\s)(ورود|وارد شوید)(\s|$)/;
/**
 * Words that delete for good. "delete"/"close" and "account" may have a few
 * words between them (a service name): "delete your instagram account",
 * "close my paypal account".
 */
const DELETE_FOREVER =
  /\b(delete (forever|permanently|for good)|permanently (delete|remove|erase)|empty (the )?(trash|bin|recycle bin)|delete (all|everything)|erase (all|everything)|purge|wipe|shred|factory reset)\b|\b(delete|close|deactivate|deregister)( [\p{L}]+){0,3} account\b|\b(delete|close) account\b/u;
const DELETE_FOREVER_FA = /حذف (دائم|دائمی|همیشگی|برای همیشه|کامل)|خالی کردن سطل|پاک کردن (همه|کل)|حذف (همه|همه‌ی|کل)|حذف حساب|بستن حساب|غیرفعال ?سازی حساب/;
/** Words that send, publish or reply (the administrator can relax these). Subscribing is PURCHASE_LIKE. */
const SEND = /\b(send|reply|forward|post|publish|share|unsubscribe|tweet|comment)\b/;
/** "ثبت" sends what a form holds ("ثبت", "ثبت نظر"); "ثبت‌نام" is joining, judged apart. */
const SEND_FA = /ارسال|فرستادن|بفرست|انتشار|منتشر|پست|پاسخ|بازارسال|هدایت|اشتراک|ثبت(?! ?نام)/;
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
/**
 * In Persian, the bare "OK" (تایید) and "Cancel" (لغو) of a dialog are not
 * judged by these alone: confirming or cancelling needs its object
 * ("تایید پرداخت", "لغو سفارش"); "فعال" is a switch only as a verb
 * (فعال‌سازی), never inside "فعالیت‌ها".
 */
const CONFIRM_FA = /(تایید|تأیید) [\p{L}]|انتقال|قبول|موافق|رزرو|لغو [\p{L}]|فعال ?(سازی|کردن|کنید|شود)|غیرفعال|بازنشانی/u;
/** Confirm-like words that do nothing to keep: accepting cookies by name, a reset of filters or a search. */
const HARMLESS_CONFIRM = /^(accept (all )?cookies|allow (all )?cookies|i accept( all)? cookies)$|\breset (the |all )?(filters?|search|form|zoom|view|selection|sorting)\b/;
/**
 * A cookie notice's own answers, harmless there only: a bare "Accept" in a
 * loan's terms or a trade offer accepts those.
 */
const ACCEPT_ON_NOTICE = /^(accept|accept all|accept (&|and) (close|continue)|allow all|i accept( all)?|agree (&|and) (close|continue)|قبول|قبول همه|پذیرش|پذیرش همه)$/;
const COOKIE_NOTICE = /cookie|consent|gdpr|کوکی/;
/** A dialog's bare yes: judged by what the dialog asks. */
const BARE_YES = /^(ok|okay|yes|continue|done|تایید|تأیید|بله|باشه|ادامه)$/;
/** What a dialog may ask to be confirmed that is not the agent's to take lightly. */
const WEIGHTY = /\b(transfer|delete|remove|erase|send|pay|payment|purchase|order|sell|withdraw)\b/;
const WEIGHTY_FA = /انتقال|حذف|پاک|ارسال|پرداخت|خرید|سفارش|فروش|برداشت|واریز/;
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
const CAPTCHA_HOSTS = ["recaptcha.net", "www.recaptcha.net", "*.hcaptcha.com", "hcaptcha.com", "challenges.cloudflare.com", "*.arkoselabs.com", "*.funcaptcha.com"];
/** Google serves reCAPTCHA from its own host, beside Maps and the rest: there, by its path. */
const CAPTCHA_ON_GOOGLE = { hosts: ["www.google.com", "google.com"], path: /^\/recaptcha\// };

/**
 * A label as the word lists read it: compatibility forms folded, in lower
 * case, Persian written with Arabic yeh or kaf read as Persian ("تائید" as
 * "تایید", its common spelling, while "دائم" keeps its hamza), without the
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
  const folded = text.normalize("NFKC").toLowerCase().replace(/[يى]/g, "ی").replace(/ئ(?=ی)/g, "ی").replace(/ك/g, "ک").replace(/ـ/g, "");
  return [folded.replace(/\p{Cf}/gu, ""), folded.replace(/\p{Cf}/gu, " ")].map((form) =>
    form
      .replace(/\p{M}/gu, "")
      .replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "")
      .replace(/\s+/g, " "),
  );
}
/** Fields for a person's identity documents. */
const ID_FIELD = /\b(ssn|social security|national id|national identity|tax id|id number|identity number)\b|\bpassport( (number|no|id)\b| ?#|$)/i;
const ID_FIELD_FA = /کد\s?ملی|شماره\s?ملی|شناسنامه|گذرنامه|پاسپورت/;
/** Fields for a person's contact and bank details: typing there asks (IBAN and Sheba numbers are secrets to sensitive.ts, and refused). */
const PERSONAL_FIELD = /\b(phone|mobile|telephone|address|street|date of birth|birth ?date|birthday|postal ?code|zip ?code|pin ?code|account number|bank account|routing number|sort code)\b/i;
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

/** How a label reads for a word list: as a whole or by its phrases (strong), by a word inside it (weak), or not at all. */
type Reading = "strong" | "weak" | null;

function reading(label: string, strong: RegExp[], weak: RegExp[]): Reading {
  const forms = labelForms(label);
  if (forms.some((form) => strong.some((list) => list.test(form)))) return "strong";
  return forms.some((form) => weak.some((list) => list.test(form))) ? "weak" : null;
}

function purchase(label: string): Reading {
  return reading(label, [PURCHASE, PURCHASE_FA], [PURCHASE_WORDS, PURCHASE_WORDS_FA]);
}

function money(label: string): Reading {
  return reading(label, [MONEY, MONEY_FA], [MONEY_WORDS, MONEY_WORDS_FA]);
}

/** Two ways offered side by side: "ورود | ثبت‌نام", "Sign in / Register", "Log in or sign up". */
const EITHER = /\||\/|\bor\b|(^|\s)یا(\s|$)/;

/**
 * Making an account - unless the label offers signing in as the other way
 * in ("ورود | ثبت‌نام", "Log in or sign up"): that is a way to either page.
 * A control that sends a form does one thing, so "Create account and sign
 * in" or «ثبت نام و ورود» still makes the account.
 */
function signUp(label: string, submits = false): Reading {
  const found = reading(label, [SIGN_UP, SIGN_UP_FA], [SIGN_UP_WORDS, SIGN_UP_WORDS_FA]);
  if (!found || submits) return found;
  return matches(label, LOGIN, LOGIN_FA) && matches(label, EITHER) ? null : found;
}

function named(element: ElementInfo): string {
  return element.name ? `"${element.name}"` : element.text ? `"${element.text}"` : `element ${element.ref}`;
}

/** Whether a confirm-like label does nothing to keep: named cookies or a reset of filters, or a cookie notice's accept. */
function harmless(label: string, element: ElementInfo): boolean {
  if (matches(label, HARMLESS_CONFIRM)) return true;
  return matches(label, ACCEPT_ON_NOTICE) && Boolean(element.context && matches(element.context, COOKIE_NOTICE));
}

/** What a control says of itself: its name, and the words it shows when they differ (a label can hide them). */
function labels(element: ElementInfo): string[] {
  return [element.name, element.text ?? ""].map((label) => label.trim()).filter(Boolean);
}

/** A target the rules cannot judge, or one hidden from the eye: the user decides, in every mode - or a CAPTCHA, which is the user's alone. */
function unjudgeable(element: ElementInfo, what: string): Verdict | null {
  if (element.frame) {
    const host = element.frame.host;
    const onGoogle = Boolean(host && CAPTCHA_ON_GOOGLE.hosts.includes(host) && CAPTCHA_ON_GOOGLE.path.test(element.frame.path ?? ""));
    if (host && (inList(host, CAPTCHA_HOSTS) || onGoogle)) {
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
  const strongest = (read: (label: string) => Reading): Reading => (said.some((label) => read(label) === "strong") ? "strong" : said.some((label) => read(label)) ? "weak" : null);
  // A word inside a longer label may not mean it ("Best laptops to buy", "Sell on …"): on a link or a control that
  // sends no form it asks; the whole label, a buying phrase, or a form it sends is refused.
  const refuses = (found: Reading) => found === "strong" || (found === "weak" && Boolean(element.submits) && !linkish);
  // Whatever the element claims to be: a <div onclick> drawn as a button places an order as well as a <button> does.
  const buying = strongest(purchase);
  if (refuses(buying)) return blocked("purchase_label", `The agent never buys or pays: ${named(element)} is for the user to click.`);
  const trading = strongest(money);
  if (refuses(trading)) return blocked("money_label", `The agent never trades or moves money: ${named(element)} is for the user to click.`);
  if (said.some((label) => matches(label, DELETE_FOREVER, DELETE_FOREVER_FA))) {
    return blocked("permanent_deletion", `The agent never deletes for good or closes an account: ${named(element)} is for the user to click.`);
  }
  const joining = strongest((label) => signUp(label, Boolean(element.submits) && !linkish));
  if (refuses(joining)) return blocked("account_creation", `The agent never creates accounts: ${named(element)} is for the user to click.`);
  if (buying || said.some((label) => matches(label, PURCHASE_LIKE, PURCHASE_LIKE_FA))) {
    return verdict("sensitive", "purchase_like", `Clicking ${named(element)} may buy something, or start paying for one.`);
  }
  if (trading) return verdict("sensitive", "money_like", `Clicking ${named(element)} may trade or move money.`);
  if (joining) return verdict("sensitive", "registration", `Clicking ${named(element)} may sign you up for something.`);
  if (consentPage(page.url) || said.some((label) => matches(label, AUTHORIZE, AUTHORIZE_FA) && !harmless(label, element))) {
    return verdict("sensitive", "authorization", `${named(element)} may give a program access to an account, or change what keeps one safe.`);
  }
  // Before the cases the administrator can relax: "Confirm and send" confirms, whatever sending may do.
  if (said.some((label) => matches(label, CONFIRM, CONFIRM_FA) && !harmless(label, element))) {
    return verdict("sensitive", "sensitive_label", `Clicking ${named(element)} may confirm, transfer or cancel something.`);
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
  // "OK" in a dialog that asks to transfer, pay or delete does what the dialog asks.
  if (said.length && said.every((label) => matches(label, BARE_YES)) && element.context && matches(element.context, WEIGHTY, WEIGHTY_FA)) {
    return verdict("sensitive", "dialog_confirm", `Clicking ${named(element)} answers a dialog that asks to pay, move money, delete or send something.`);
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

/** Digits as a number is checked: Persian and Arabic-Indic digits read as ASCII ones. */
function asciiDigits(text: string): string {
  return text.replace(/[۰-۹]/g, (d) => String(d.charCodeAt(0) - 0x06f0)).replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660));
}

/**
 * Text as the number checks read it: compatibility forms folded (full-width
 * digits, a no-break space), the invisible format characters dropped (a
 * zero-width space between two groups hides nothing), Persian and
 * Arabic-Indic digits read as ASCII ones.
 */
function scanned(text: string): string {
  return asciiDigits(text.normalize("NFKC").replace(/\p{Cf}/gu, ""));
}

function luhn(digits: string): boolean {
  let sum = 0;
  for (let i = 0; i < digits.length; i += 1) {
    let d = Number(digits[digits.length - 1 - i]);
    if (i % 2 === 1) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    sum += d;
  }
  return sum % 10 === 0 && !/^(\d)\1+$/.test(digits);
}

/**
 * A card number in the text: 13 to 19 digits that pass the Luhn check,
 * written whole or in groups (spaces, dashes or dots between). Any run of
 * whole groups counts, so the expiry after a number ("4111 1111 1111 1111
 * 12/27") does not hide it.
 */
function cardNumberIn(text: string): boolean {
  for (const match of scanned(text).matchAll(/\d+(?:[ .-]\d+)*/g)) {
    const groups = match[0].split(/[ .-]/);
    for (let first = 0; first < groups.length; first += 1) {
      let digits = "";
      for (let last = first; last < groups.length && digits.length <= 19; last += 1) {
        digits += groups[last];
        if (digits.length >= 13 && digits.length <= 19 && luhn(digits)) return true;
      }
    }
  }
  return false;
}

function mod97(alnum: string): number {
  const moved = `${alnum.slice(4)}${alnum.slice(0, 4)}`.replace(/[A-Z]/g, (c) => String(c.charCodeAt(0) - 55));
  let rest = 0;
  for (const digit of moved) rest = (rest * 10 + Number(digit)) % 97;
  return rest;
}

/**
 * An IBAN - Sheba in Iran - in the text: two letters, two check digits and
 * the rest, 15 to 34 characters in all, whose mod 97 is 1. Written in groups,
 * any number of the groups that follow may be its end, so the words after
 * it ("… 00 is mine") do not hide it.
 */
function ibanIn(text: string): boolean {
  for (const match of scanned(text).toUpperCase().matchAll(/(?<![A-Z0-9])[A-Z]{2}\d{2}[A-Z0-9]*(?: [A-Z0-9]+)*/g)) {
    let iban = "";
    for (const group of match[0].split(" ")) {
      iban += group;
      if (iban.length > 34) break;
      if (iban.length >= 15 && /^[A-Z]{2}\d{2}[A-Z0-9]+$/.test(iban) && mod97(iban) === 1) return true;
    }
  }
  return false;
}

/** An Iranian national ID in the text: ten digits whose last is their check digit. */
function nationalIdIn(text: string): boolean {
  // Ten digits, or the three, six and one of the card ("001-234567-8").
  for (const match of scanned(text).matchAll(/(?<!\d)(?:\d{10}|\d{3}-\d{6}-\d)(?![\d-])/g)) {
    const id = match[0].replace(/-/g, "");
    if (/^(\d)\1{9}$/.test(id)) continue;
    const sum = [...id.slice(0, 9)].reduce((total, digit, i) => total + Number(digit) * (10 - i), 0) % 11;
    const check = Number(id[9]);
    if ((sum < 2 && check === sum) || (sum >= 2 && check === 11 - sum)) return true;
  }
  return false;
}

/** A field's name that asks for a code. */
const CODE_FIELD = /\bcode\b|(^|\s)کد/i;

/**
 * What is typed, read too: a field's name can say nothing while the text
 * is a card number, an IBAN or Sheba, or a national ID - never typed by the
 * agent - or a short code where a code is asked for, which the user sees first.
 */
function textVerdict(text: unknown, element: ElementInfo): Verdict | null {
  if (typeof text !== "string" || !text) return null;
  if (cardNumberIn(text)) return blocked("secret_text", "The agent never types a card number: that is for the user to enter.");
  if (ibanIn(text)) return blocked("secret_text", "The agent never types a bank account number (an IBAN or Sheba): that is for the user to enter.");
  if (nationalIdIn(text)) return blocked("secret_text", "The agent never types a national ID number: that is for the user to enter.");
  if (/^\s*\d{4,8}\s*$/.test(asciiDigits(text)) && matches(`${element.name} ${element.text ?? ""}`, CODE_FIELD)) {
    return verdict("sensitive", "code_like", `The text is a short number typed where ${named(element)} asks for a code: a one-time code is the user's to give.`);
  }
  return null;
}

function typeVerdict(element: ElementInfo, page: { url: string; host: string }, text?: unknown): Verdict {
  const cannot = unjudgeable(element, "The field");
  if (cannot) return cannot;
  const typed = textVerdict(text, element);
  if (typed?.class === "blocked") return typed;
  const secret = () =>
    blocked("sensitive_field", `The agent never types into ${named(element)}: passwords, card numbers and codes are for the user to enter. Sign in yourself, then tell the agent to go on.`);
  if (element.sensitive) return secret();
  const field = `${element.name} ${element.type ?? ""}`;
  // By its name alone: an input's type ("text") after it would hide a field called just "Passport".
  if (matches(element.name, ID_FIELD, ID_FIELD_FA)) {
    return blocked("id_field", `The agent never types into ${named(element)}: identity numbers are for the user to enter.`);
  }
  // The page judges the field by everything it says about it; its name is checked here as well.
  if (sensitiveText(element.name)) return secret();
  if (consentPage(page.url)) return verdict("sensitive", "authorization", `Typing on a page that gives a program access to an account.`);
  if (matches(field, PERSONAL_FIELD, PERSONAL_FIELD_FA) || element.type === "tel") {
    return verdict("sensitive", "personal_data", `Typing into ${named(element)} gives a page personal details.`);
  }
  if (typed) return typed;
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
  // A form is sent: a buying, trading or joining word anywhere in its button is enough.
  if (said.some((label) => purchase(label))) {
    return blocked("purchase_label", `The agent never buys or pays: sending this form (its button says "${button}") is for the user.`);
  }
  if (said.some((label) => money(label))) {
    return blocked("money_label", `The agent never trades or moves money: sending this form (its button says "${button}") is for the user.`);
  }
  if (said.some((label) => signUp(label, true))) {
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
  const dest = `${destination(element.formAction)}${element.name ? ` from ${named(element)}` : ""}`;
  // A form whose sending button confirms, sends or deletes is judged by that word, not by the softer "submit" case:
  // a "Confirm transfer" or "Send message" form must not slip past the send/delete/confirm gates.
  if (said.some((label) => matches(label, PURCHASE_LIKE, PURCHASE_LIKE_FA))) {
    return verdict("sensitive", "purchase_like", `Sending this form may start paying for something${dest}.`);
  }
  if (said.some((label) => matches(label, CONFIRM, CONFIRM_FA) && !harmless(label, element))) {
    return verdict("sensitive", "sensitive_label", `Sending this form may confirm, transfer or cancel something${dest}.`);
  }
  if (said.some((label) => matches(label, DELETE, DELETE_FA))) {
    return asks(!approvals(ctx).delete, "delete_label", `Sending this form may delete something${dest}.`);
  }
  if (said.some((label) => matches(label, SEND, SEND_FA))) {
    return asks(!approvals(ctx).send, "sensitive_label", `Sending this form may send or publish something${dest}.`);
  }
  return asks(!approvals(ctx).submit, "submit", `Sending the form${dest}.`);
}

/** A field's name that says it searches. */
const SEARCH = /\bsearch\b/;
const SEARCH_FA = /جست ?(و ?)?جو/;

/** Roles of fields that hold text a person types. */
const TEXT_ROLES = new Set(["textbox", "searchbox", "combobox", "spinbutton"]);

/** Keys that stay within the page when Ctrl or Cmd is held: editing, selecting, moving. */
const EDITING_SHORTCUTS = new Set(["a", "c", "x", "z", "y", "b", "i", "u", "Enter", "Backspace", "Delete", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"]);

/** Inputs that are buttons: Enter presses them, not their form's own sending button. */
const BUTTON_INPUTS = new Set(["submit", "button", "reset", "image"]);

function sentByEnter(element: ElementInfo, page: { url: string; host: string }, ctx: PolicyContext): Verdict {
  const sent = submitVerdict(element, page, ctx);
  return { ...sent, message: `Pressing Enter in ${named(element)} sends its form. ${sent.message}` };
}

/**
 * A key press, judged by the element it goes to (`element`: the focused
 * one, if any). Enter in a message box is how most web apps send; on a
 * control, Enter or Space works as a click in the page's own handlers; and
 * Delete outside a text field deletes whatever the page has selected. With
 * Ctrl or Cmd held, only editing keys are the agent's: the clipboard and the
 * browser's own shortcuts are not.
 */
function keyVerdict(rawKey: unknown, element: ElementInfo | undefined, page: { url: string; host: string }, ctx: PolicyContext): Verdict {
  const combo = parseKeyCombo(rawKey);
  if (!combo) return blocked("bad_key", `"${String(rawKey).slice(0, 40)}" is not a key the agent can press. It can press ${KEY_NAMES_SHOWN}.`);
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
  // Enter in a form's field - a text box, a checkbox, a date - sends the form with its sending button (the browser's
  // implicit submission): judged as sending that form, as submit_form would be. A button presses itself.
  const sendsForm = Boolean(element && element.tag === "input" && !BUTTON_INPUTS.has(element.type ?? "") && element.formAction !== undefined);
  if (element && inText && key === "Enter" && !combo.shift) {
    const search = element.role === "searchbox" || element.type === "search" || (element.role === "combobox" && matches(element.name, SEARCH, SEARCH_FA));
    if (search) return verdict("act", "press_key", `Pressing Enter in ${named(element)} to search.`);
    if (sendsForm) return sentByEnter(element, page, ctx);
    return asks(!relax.send, "enter_sends", `Pressing Enter in ${named(element)} may send what it holds.`);
  }
  if (element && sendsForm && key === "Enter" && !combo.shift) return sentByEnter(element, page, ctx);
  if (element && !inText && (key === "Enter" || key === " ")) {
    const asClick = clickVerdict(element, page, ctx);
    if (asClick.class === "act") return verdict("act", "press_key", `Pressing ${shown} on ${named(element)}.`);
    return { ...asClick, message: `Pressing ${shown} on ${named(element)} works like clicking it. ${asClick.message}` };
  }
  if (!inText && (key === "Delete" || key === "Backspace")) {
    return asks(!relax.delete, "delete_key", `Pressing ${shown} ${element ? `on ${named(element)}` : "on the page"} may delete something.`);
  }
  if (element && consentPage(page.url)) return verdict("sensitive", "authorization", `Pressing ${shown} on a page that gives a program access to an account.`);
  // A single character outside a text field is the site's own shortcut in many apps (# deletes in Gmail, e archives).
  if (!inText && !combo.ctrl && !combo.meta && !combo.alt && [...key].length === 1 && key !== " ") {
    return verdict("sensitive", "app_shortcut", `Pressing ${shown} outside a text field may be one of the site's shortcuts, which can archive, delete or send.`);
  }
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
      if (tool === "type_text") return typeVerdict(element, page!, args.text);
      if (tool === "submit_form") return submitVerdict(element, page!, ctx);
      // A menu's option can do what a button does ("Delete account", "Pay by card"): judged by the one chosen.
      if (element.choice) {
        const byOption = labelVerdict({ ...element, name: element.choice, text: undefined }, [element.choice], false, page!, ctx);
        if (byOption) return { ...byOption, message: `Choosing "${element.choice}" in ${named(element)}: ${byOption.message}` };
      }
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
      // Plan mode: once the plan is approved (the caller seeds its sites), acting on a plan site needs no more asking;
      // an off-plan site is caught by the caller and asked about. Auto mode sends acts to the reviewer.
      return mode === "auto" ? "review" : mode === "plan" ? "none" : "user";
    case "sensitive":
      return "user";
    default:
      return "refuse";
  }
}
