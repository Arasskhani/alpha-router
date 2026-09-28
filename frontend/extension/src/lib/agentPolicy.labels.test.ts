/**
 * The rules on real labels, English and Persian, as sites write them: what
 * a click on each is. A table, so that a change to a word list shows at
 * once which real controls it moves - a block that becomes an ask, or an
 * ask that becomes a plain action.
 */
import { describe, expect, it } from "vitest";

import type { ElementInfo } from "../content/agent";
import { classifyAction, type PolicyContext } from "./agentPolicy";

const OPEN: PolicyContext = { policy: { allowed_sites: [], blocked_sites: [] }, serverHost: "ai.example.com", ownHosts: ["ai.example.com"] };
const PAGE = { url: "https://shop.example.com/", host: "shop.example.com" };

type Case = [label: string, cls: "act" | "sensitive" | "blocked", element?: Partial<ElementInfo>];

function click(name: string, element: Partial<ElementInfo> = {}) {
  return classifyAction({ tool: "click", args: {}, page: PAGE, element: { ref: "e1", role: "button", name, tag: "button", ...element } }, OPEN);
}

const LINK = { role: "link", tag: "a", href: "https://shop.example.com/somewhere" };

const CASES: Case[] = [
  // Buying: the whole label, or a phrase that buys - refused.
  ["Buy", "blocked"],
  ["Buy now", "blocked"],
  ["Buy it now", "blocked"],
  ["Pay", "blocked"],
  ["Pay now", "blocked"],
  ["Pay $12.99", "blocked"],
  ["Checkout", "blocked"],
  ["Proceed to checkout", "blocked"],
  ["Place your order", "blocked"],
  ["Complete purchase", "blocked"],
  ["Confirm payment", "blocked"],
  ["Order now", "blocked"],
  ["Donate", "blocked"],
  ["Pre-order", "blocked"],
  ["Place bid", "blocked"],
  ["Add funds", "blocked"],
  ["خرید", "blocked"],
  ["پرداخت", "blocked"],
  ["ثبت سفارش", "blocked"],
  ["تکمیل خرید", "blocked"],
  ["تایید و پرداخت", "blocked"],
  ["تسویه حساب", "blocked"],
  ["پیش‌خرید", "blocked"],
  // Buying words inside other labels: they ask, never refused on sight.
  ["Best laptops to buy", "sensitive", LINK],
  ["How to pay your bill", "sensitive", LINK],
  ["Pay with my saved card", "sensitive", { role: "checkbox", tag: "input" }],
  ["راهنمای خرید", "sensitive", LINK],
  // Nothing to do with buying at all: plain.
  ["Order history", "act"],
  ["Track my order", "act"],
  ["پیگیری سفارش", "act"],
  ["سفارش‌های من", "act", LINK],
  ["Payroll", "act"],
  ["Payment methods", "act", LINK],
  // What starts paying later: always asks.
  ["Upgrade", "sensitive"],
  ["Upgrade to Pro", "sensitive"],
  ["Start free trial", "sensitive"],
  ["Start your free trial", "sensitive"],
  ["Subscribe", "sensitive"],
  ["Subscribe now", "sensitive"],
  ["Go Premium", "sensitive"],
  ["Renew plan", "sensitive"],
  ["خرید اشتراک", "sensitive"],
  ["تمدید اشتراک", "sensitive"],
  // Trading and moving money: the whole label or its phrases - refused; the word elsewhere asks.
  ["Sell", "blocked"],
  ["Sell all", "blocked"],
  ["Sell shares", "blocked"],
  ["Swap", "blocked"],
  ["Withdraw", "blocked"],
  ["Withdraw funds", "blocked"],
  ["Send money", "blocked"],
  ["Wire transfer", "blocked"],
  ["Deposit", "blocked"],
  ["Top up", "blocked"],
  ["فروش", "blocked"],
  ["فروش سهام", "blocked"],
  ["انتقال وجه", "blocked"],
  ["کارت به کارت", "blocked"],
  ["برداشت", "blocked"],
  ["Sell on Amazon", "sensitive", LINK],
  ["Swap languages", "sensitive"],
  ["Trade-in program", "sensitive", LINK],
  ["پرفروش‌ترین", "act"],
  ["فروشگاه", "act", LINK],
  ["فروشنده شوید", "act", LINK],
  ["Deposit slip archive", "act"],
  ["Exchange rates", "act", LINK],
  // Making an account: refused - unless the label is a way in too.
  ["Sign up", "blocked"],
  ["Sign up for free", "blocked"],
  ["Register", "blocked"],
  ["Create account", "blocked"],
  ["Create your free account", "blocked"],
  ["Join now", "blocked"],
  ["ثبت نام", "blocked"],
  ["ثبت‌نام", "blocked"],
  ["عضویت", "blocked"],
  ["ایجاد حساب کاربری", "blocked"],
  ["ورود | ثبت‌نام", "act", LINK],
  ["ورود / ثبت نام", "act"],
  ["Log in or sign up", "act"],
  ["Sign in / Register", "act"],
  ["Register for the webinar", "sensitive"],
  ["Join the meeting", "sensitive"],
  ["Registration desk hours", "act"],
  // Deleting for good: refused; deleting: asks.
  ["Delete forever", "blocked"],
  ["Empty trash", "blocked"],
  ["Delete account", "blocked"],
  ["حذف دائم", "blocked"],
  ["Delete draft", "sensitive"],
  ["Remove item", "sensitive"],
  ["Discard", "sensitive"],
  ["حذف", "sensitive"],
  // Sending: asks.
  ["Send", "sensitive"],
  ["Reply all", "sensitive"],
  ["Forward", "sensitive"],
  ["Post comment", "sensitive"],
  ["ارسال", "sensitive"],
  ["پاسخ", "sensitive"],
  ["انتشار", "sensitive"],
  // Confirming and cancelling: with an object, asks; the bare OK and Cancel of a dialog act.
  ["Confirm", "sensitive"],
  ["Approve", "sensitive"],
  ["Book now", "sensitive"],
  ["Cancel my subscription", "sensitive"],
  ["تایید انتقال", "sensitive"],
  ["لغو سفارش", "sensitive"],
  ["لغو اشتراک", "sensitive"],
  ["فعال‌سازی", "sensitive"],
  ["غیرفعال کردن", "sensitive"],
  ["تایید", "act"],
  ["تأیید", "act"],
  ["لغو", "act"],
  ["Cancel", "act"],
  ["فعالیت‌ها", "act", LINK],
  ["Accept all", "act"],
  ["Accept all cookies", "act"],
  ["Accept & close", "act"],
  ["Reset filters", "act"],
  ["Reset search", "act"],
  ["Reset password", "sensitive"],
  // Access to an account, and what keeps it safe: asks.
  ["Allow access", "sensitive"],
  ["Continue as Majid", "sensitive"],
  ["Change password", "sensitive"],
  ["Two-factor authentication", "sensitive", LINK],
  ["تغییر رمز عبور", "sensitive"],
  // Downloads and uploads: ask.
  ["Download report", "sensitive"],
  ["دانلود فایل", "sensitive"],
  ["Upload photo", "sensitive"],
  ["بارگذاری تصویر", "sensitive"],
  // Ordinary controls: plain.
  ["Next", "act"],
  ["Continue", "act"],
  ["Compose", "act"],
  ["Inbox", "act", LINK],
  ["Settings", "act"],
  ["جستجو", "act"],
  ["بعدی", "act"],
  ["بازگشت", "act"],
  ["Show more", "act"],
];

describe("real labels", () => {
  it.each(CASES)("%s: %s", (label, cls, element) => {
    expect(click(label, element).class).toBe(cls);
  });

  it("covers a good hundred of them, in both languages", () => {
    expect(CASES.length).toBeGreaterThanOrEqual(120);
    expect(CASES.filter(([label]) => /[؀-ۿ]/.test(label)).length).toBeGreaterThanOrEqual(35);
  });
});

describe("real fields", () => {
  function typing(name: string, element: Partial<ElementInfo> = {}, text = "hello") {
    return classifyAction({ tool: "type_text", args: { text }, page: PAGE, element: { ref: "e2", role: "textbox", name, tag: "input", ...element } }, OPEN);
  }

  it.each([
    ["Pincode", "sensitive"],
    ["Search passport and visa services", "act"],
    ["جستجوی رمزارز", "act"],
    ["Search mail", "act"],
  ] as const)("typing into %s is %s", (name, cls) => {
    expect(typing(name).class).toBe(cls);
  });

  it.each(["Password", "Card number", "Passport number", "رمز عبور", "کد ملی", "One-time code"])("never types into %s", (name) => {
    expect(typing(name).class).toBe("blocked");
  });
});

describe("Enter in a field", () => {
  function enter(element: Partial<ElementInfo>) {
    return classifyAction({ tool: "press_key", args: { key: "Enter" }, page: PAGE, element: { ref: "e3", role: "textbox", name: "Message", tag: "input", ...element } }, OPEN);
  }

  it("searches in a search box, whatever it is drawn as", () => {
    expect(enter({ role: "searchbox", name: "Search" })).toMatchObject({ class: "act" });
    expect(enter({ role: "combobox", name: "Search mail" })).toMatchObject({ class: "act" });
    expect(enter({ role: "combobox", name: "جستجو در محصولات" })).toMatchObject({ class: "act" });
  });

  it("may send from a message box or a recipient field", () => {
    expect(enter({ role: "textbox", name: "Message" })).toMatchObject({ class: "sensitive", reason: "enter_sends" });
    expect(enter({ role: "combobox", name: "To recipients" })).toMatchObject({ class: "sensitive", reason: "enter_sends" });
  });
});
