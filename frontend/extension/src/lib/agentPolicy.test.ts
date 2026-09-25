/**
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import type { ElementInfo } from "../content/agent";
import { approvalFor, classifyAction, type PolicyContext, type ProposedAction } from "./agentPolicy";

const OPEN: PolicyContext = { policy: { allowed_sites: [], blocked_sites: [] }, serverHost: "ai.example.com", ownHosts: ["ai.example.com"] };
const RULES: PolicyContext = {
  policy: { allowed_sites: ["*.example.com", "partner.org"], blocked_sites: ["bank.example.com"] },
  serverHost: "ai.example.com",
  ownHosts: ["ai.example.com", "alpharouter.intranet"],
};
const SHOP = { url: "https://shop.example.com/cart", host: "shop.example.com" };

function el(overrides: Partial<ElementInfo>): ElementInfo {
  return { ref: "e1", role: "button", name: "Next", tag: "button", ...overrides };
}

function classify(tool: string, overrides: Partial<ProposedAction> = {}, ctx: PolicyContext = OPEN) {
  return classifyAction({ tool, args: {}, page: SHOP, ...overrides }, ctx);
}

describe("reading", () => {
  it.each(["tabs_list", "read_page", "find", "get_page_text", "scroll", "wait_for", "ask_user", "done"])("%s never asks", (tool) => {
    expect(classify(tool)).toMatchObject({ class: "read" });
  });

  it("is refused on a site the rules keep out", () => {
    const bank = { url: "https://bank.example.com/", host: "bank.example.com" };
    expect(classify("read_page", { page: bank }, RULES)).toMatchObject({ class: "blocked", reason: "site_blocked" });
    const elsewhere = { url: "https://news.other.net/", host: "news.other.net" };
    expect(classify("get_page_text", { page: elsewhere }, RULES)).toMatchObject({ class: "blocked", reason: "site_not_allowed" });
  });

  it("never happens on Alpharouter itself, on any port or scheme of its host", () => {
    const own = { url: "https://ai.example.com/chat", host: "ai.example.com" };
    expect(classify("read_page", { page: own }, RULES)).toMatchObject({ class: "blocked", reason: "own_server" });
    // The browser sends the session cookie to every port of the host: another port can be Alpharouter, signed in.
    for (const url of ["https://ai.example.com:8443/admin", "http://ai.example.com/", "http://ai.example.com:8000/docs"]) {
      expect(classify("read_page", { page: { url, host: "ai.example.com" } }, RULES)).toMatchObject({ class: "blocked", reason: "own_server" });
    }
    // The address the extension itself talks to counts as much as the one the server gives.
    const intranet = { url: "http://alpharouter.intranet/chat", host: "alpharouter.intranet" };
    expect(classify("read_page", { page: intranet }, RULES)).toMatchObject({ class: "blocked", reason: "own_server" });
    expect(classify("navigate", { args: { url: "https://AI.example.com.:8443/x" } }, RULES)).toMatchObject({ class: "blocked", reason: "own_server" });
  });

  it("needs a web page", () => {
    expect(classify("find", { page: undefined })).toMatchObject({ class: "blocked", reason: "no_page" });
  });
});

describe("clicking", () => {
  it.each([
    ["button", "Next page"],
    ["link", "Order history"],
    ["link", "سفارش‌های من"],
    ["tab", "Details"],
    ["checkbox", "Remember me"],
  ])("a %s labelled %s acts", (role, name) => {
    expect(classify("click", { element: el({ role, name }) })).toMatchObject({ class: "act" });
  });

  it.each([
    "Send",
    "Submit",
    "Delete account",
    "Remove item",
    "Confirm",
    "Transfer",
    "Download report",
    "Publish",
    "Post comment",
    "ارسال",
    "حذف",
    "تأیید و ادامه",
    "تایید",
    "انتقال وجه",
    "دانلود فایل",
    "انتشار",
  ])("a button labelled %s always asks", (name) => {
    expect(classify("click", { element: el({ name }) })).toMatchObject({ class: "sensitive", reason: "sensitive_label" });
  });

  it.each([
    "Buy now",
    "Pay",
    "Checkout",
    "Check out",
    "Purchase",
    "Place order",
    "Place your order",
    "Complete order",
    "Order",
    "Order now",
    "خرید",
    "پرداخت",
    "ثبت سفارش",
    "تسویه حساب",
  ])("a button labelled %s is refused", (name) => {
    expect(classify("click", { element: el({ name }) })).toMatchObject({ class: "blocked", reason: "purchase_label" });
  });

  it.each([
    "Continue to payment",
    "Complete payment",
    "Order now!",
    "Order now →",
    "Pre-order",
    "Place bid",
    "Donate",
    "🛒 Buy",
    "خريد",
    "تسويه حساب",
    "خریـــد",
    "پرداخـت",
    "پیش‌خرید",
  ])("a button labelled %s is refused however it is written", (name) => {
    expect(classify("click", { element: el({ name }) })).toMatchObject({ class: "blocked", reason: "purchase_label" });
  });

  it.each(["Subscribe", "Reply", "Forward", "Share", "Accept all", "I agree", "Book now", "Approve", "Cancel my subscription", "تاييد", "پاك كردن", "پاسخ", "ثبت نام"])(
    "a button labelled %s always asks",
    (name) => {
      expect(classify("click", { element: el({ name }) })).toMatchObject({ class: "sensitive", reason: "sensitive_label" });
    },
  );

  it.each(["Order history", "Booking history", "Shared files", "Accepted payments", "Cancel", "Sort order", "Payroll"])("a button labelled %s acts", (name) => {
    expect(classify("click", { element: el({ name }) })).toMatchObject({ class: "act" });
  });

  it("refuses a link that buys, in English or Persian", () => {
    expect(classify("click", { element: el({ role: "link", name: "Buy now", href: "https://shop.example.com/buy" }) })).toMatchObject({
      class: "blocked",
    });
    expect(classify("click", { element: el({ role: "link", name: "خرید", href: "https://shop.example.com/buy" }) })).toMatchObject({
      class: "blocked",
    });
  });

  it("reads the words a control shows as well as its name, which a label can hide", () => {
    expect(classify("click", { element: el({ name: "Continue", text: "Place order" }) })).toMatchObject({ class: "blocked", reason: "purchase_label" });
    expect(classify("click", { element: el({ name: "Next", text: "Delete account" }) })).toMatchObject({ class: "sensitive", reason: "sensitive_label" });
    expect(classify("submit_form", { element: el({ name: "Continue", text: "Pay now", submits: true }) })).toMatchObject({ class: "blocked" });
  });

  it("asks before clicking something nameless, which nobody can judge; a link is judged by where it goes", () => {
    expect(classify("click", { element: el({ name: "" }) })).toMatchObject({ class: "sensitive", reason: "unnamed_control" });
    expect(classify("click", { element: el({ role: "text", name: "", tag: "div" }) })).toMatchObject({ class: "sensitive", reason: "unnamed_control" });
    expect(classify("click", { element: el({ role: "link", name: "", tag: "a", href: "https://shop.example.com/cart" }) })).toMatchObject({ class: "act" });
  });

  it("does not take a longer word for a short one", () => {
    expect(classify("click", { element: el({ name: "Posts" }) })).toMatchObject({ class: "act" });
    expect(classify("click", { element: el({ name: "Payroll" }) })).toMatchObject({ class: "act" });
    expect(classify("click", { element: el({ name: "Sort order" }) })).toMatchObject({ class: "act" });
  });

  it("asks before sending a form, and refuses one going to a blocked site", () => {
    const submit = el({ name: "Continue", submits: true, formAction: "https://shop.example.com/step2" });
    expect(classify("click", { element: submit }, RULES)).toMatchObject({ class: "sensitive", reason: "submit" });
    const away = el({ name: "Continue", submits: true, formAction: "https://bank.example.com/collect" });
    expect(classify("click", { element: away }, RULES)).toMatchObject({ class: "blocked", reason: "site_blocked" });
  });

  it("treats a link to another site like going there, with its site named for the browser's permission", () => {
    const link = el({ role: "link", name: "Partner", href: "https://partner.org/deal" });
    expect(classify("click", { element: link }, RULES)).toEqual({
      class: "sensitive",
      reason: "other_site",
      message: 'Following the link "Partner" on another site: partner.org.',
      site: "partner.org",
    });
    const sameSite = el({ role: "link", name: "Cart", href: "https://shop.example.com/cart?x=1" });
    expect(classify("click", { element: sameSite }, RULES)).toMatchObject({ class: "act" });
    const blockedLink = el({ role: "link", name: "Statement", href: "https://bank.example.com/" });
    expect(classify("click", { element: blockedLink }, RULES)).toMatchObject({ class: "blocked", reason: "site_blocked" });
    const unlisted = el({ role: "link", name: "Elsewhere", href: "https://news.other.net/" });
    expect(classify("click", { element: unlisted }, RULES)).toMatchObject({ class: "blocked", reason: "site_not_allowed" });
  });

  it("judges a link by where it goes, whatever role it claims", () => {
    const menuItem = el({ role: "menuitem", name: "Statement", tag: "a", href: "https://bank.example.com/" });
    expect(classify("click", { element: menuItem }, RULES)).toMatchObject({ class: "blocked", reason: "site_blocked" });
    const buttonLink = el({ role: "button", name: "Deals", tag: "a", href: "https://partner.org/deals" });
    expect(classify("click", { element: buttonLink }, RULES)).toMatchObject({ class: "sensitive", reason: "other_site", site: "partner.org" });
    // A link's Persian "سفارش" is usually "my orders"; buying words are refused on any link.
    expect(classify("click", { element: el({ role: "tab", name: "سفارش‌های من", tag: "a", href: "https://shop.example.com/orders" }) })).toMatchObject({ class: "act" });
    expect(classify("click", { element: el({ role: "menuitem", name: "Buy now", tag: "a", href: "https://shop.example.com/buy" }) })).toMatchObject({ class: "blocked" });
  });

  it("asks before a link that opens another program, and lets script links act", () => {
    expect(classify("click", { element: el({ role: "link", name: "Email us", href: "mailto:a@b.c" }) })).toMatchObject({
      class: "sensitive",
      reason: "other_app",
    });
    expect(classify("click", { element: el({ role: "link", name: "More", href: "javascript:void(0)" }) })).toMatchObject({ class: "act" });
  });

  it("needs the element as the page describes it now", () => {
    expect(classify("click", { element: undefined })).toMatchObject({ class: "blocked", reason: "no_element" });
  });
});

describe("typing", () => {
  it("acts in an ordinary field", () => {
    expect(classify("type_text", { element: el({ role: "textbox", name: "Delivery address", tag: "input" }) })).toMatchObject({ class: "act" });
  });

  it("is refused in a password, card or one-time-code field", () => {
    expect(classify("type_text", { element: el({ role: "textbox", name: "Password", sensitive: true }) })).toMatchObject({
      class: "blocked",
      reason: "sensitive_field",
    });
  });

  it.each(["Card number", "Security code", "رمز دوم", "One-time code", "cvv2"])("is refused in a field named for a secret: %s", (name) => {
    expect(classify("type_text", { element: el({ role: "textbox", name }) })).toMatchObject({ class: "blocked", reason: "sensitive_field" });
  });

  it.each(["National ID", "Passport number", "SSN", "کد ملی", "شماره شناسنامه"])("is refused in an identity field: %s", (name) => {
    expect(classify("type_text", { element: el({ role: "textbox", name }) })).toMatchObject({ class: "blocked", reason: "id_field" });
  });
});

describe("the rest", () => {
  it("choosing an option and pressing a key act", () => {
    expect(classify("select_option", { element: el({ role: "combobox", name: "Size" }) })).toMatchObject({ class: "act" });
    expect(classify("press_key", { args: { key: "Enter" } })).toMatchObject({ class: "act" });
  });

  it("sending a form always asks, and buying through one is refused", () => {
    expect(classify("submit_form", { element: el({ role: "textbox", name: "Email" }) })).toMatchObject({ class: "sensitive", reason: "submit" });
    expect(classify("submit_form", { element: el({ name: "Pay now", submits: true }) })).toMatchObject({ class: "blocked", reason: "purchase_label" });
  });

  it("opening a page on the same site acts; another site asks; a blocked one or a special scheme is refused", () => {
    expect(classify("navigate", { args: { url: "https://shop.example.com/help" } })).toMatchObject({ class: "act", reason: "same_site" });
    expect(classify("tab_open", { args: { url: "https://partner.org/" } }, RULES)).toMatchObject({
      class: "sensitive",
      reason: "other_site",
      site: "partner.org",
    });
    expect(classify("navigate", { args: { url: "https://bank.example.com/" } }, RULES)).toMatchObject({ class: "blocked" });
    for (const url of ["javascript:alert(1)", "file:///etc/passwd", "chrome://settings", "data:text/html,hi", "about:blank", 42, "https://*/login"]) {
      expect(classify("navigate", { args: { url } })).toMatchObject({ class: "blocked", reason: "special_scheme" });
    }
    expect(classify("navigate", { args: { url: "https://ai.example.com/admin" } })).toMatchObject({ class: "blocked", reason: "own_server" });
  });

  it("opening a page from a tab that shows none is going to another site", () => {
    expect(classify("tab_open", { page: undefined, args: { url: "https://shop.example.com/" } })).toMatchObject({ class: "sensitive" });
  });

  it("switching tabs acts", () => {
    expect(classify("tab_switch", { args: { tab_id: 4 } })).toMatchObject({ class: "act" });
  });

  it("refuses a tool it does not know", () => {
    expect(classify("run_shell", {})).toMatchObject({ class: "blocked", reason: "unknown_tool" });
  });
});

describe("who agrees", () => {
  it.each([
    ["read", "ask", "none"],
    ["read", "auto", "none"],
    ["act", "ask", "user"],
    ["act", "auto", "review"],
    ["sensitive", "ask", "user"],
    ["sensitive", "auto", "user"],
    ["blocked", "ask", "refuse"],
    ["blocked", "auto", "refuse"],
  ] as const)("a %s action in %s mode: %s", (cls, mode, approval) => {
    expect(approvalFor({ class: cls, reason: "x", message: "x" }, mode)).toBe(approval);
  });
});
