/**
 * @vitest-environment node
 *
 * The rules that never loosen, in one table: whatever makes the agent ask
 * less often - sites remembered for a run or across runs, search boxes and
 * harmless buttons recognised, fewer false alarms in the word lists - none of
 * these may let the agent buy, pay, move money, type a secret, send, delete,
 * make an account, solve a CAPTCHA, hand out account access or go where the
 * administrator keeps it out. Each row is the strictest answer the rules give
 * today; a change that loosens one fails here.
 */
import { describe, expect, it } from "vitest";

import type { ElementInfo } from "../content/agent";
import { approvalFor, classifyAction, type AgentMode, type PolicyContext, type ProposedAction } from "./agentPolicy";

const RULES: PolicyContext = {
  policy: { allowed_sites: [], blocked_sites: ["bank.example.com"] },
  serverHost: "ai.example.com",
  ownHosts: ["ai.example.com"],
};
const SHOP = { url: "https://shop.example.com/cart", host: "shop.example.com" };

function el(overrides: Partial<ElementInfo>): ElementInfo {
  return { ref: "e1", role: "button", name: "Next", tag: "button", ...overrides };
}

type Row = [label: string, action: Omit<ProposedAction, "page"> & { page?: ProposedAction["page"] }, expected: "blocked" | "sensitive"];

const form = { submits: true, formAction: "https://shop.example.com/checkout" };
const textbox = (name: string, extra: Partial<ElementInfo> = {}) => el({ role: "textbox", tag: "input", type: "text", name, ...extra });

const ROWS: Row[] = [
  // Buying and paying.
  ["Buy now", { tool: "click", args: {}, element: el({ name: "Buy now" }) }, "blocked"],
  ["Place order", { tool: "click", args: {}, element: el({ name: "Place order", ...form }) }, "blocked"],
  ["Pay $12", { tool: "click", args: {}, element: el({ name: "Pay $12" }) }, "blocked"],
  ["پرداخت", { tool: "click", args: {}, element: el({ name: "پرداخت" }) }, "blocked"],
  ["ثبت سفارش (submit)", { tool: "click", args: {}, element: el({ name: "ثبت سفارش", ...form }) }, "blocked"],
  ["form whose button buys", { tool: "submit_form", args: {}, element: textbox("Quantity", { formAction: SHOP.url, formButton: ["Buy laptop"] }) }, "blocked"],
  ["Enter sends a form that pays", { tool: "press_key", args: { key: "Enter" }, element: textbox("Amount", { formAction: SHOP.url, formButton: ["پرداخت نهایی"] }) }, "blocked"],
  ["buying word on a form's own button", { tool: "click", args: {}, element: el({ name: "Best laptops to buy", ...form }) }, "blocked"],
  ["Start free trial", { tool: "click", args: {}, element: el({ name: "Start free trial" }) }, "sensitive"],
  // Moving money.
  ["Sell all", { tool: "click", args: {}, element: el({ name: "Sell all" }) }, "blocked"],
  ["انتقال وجه", { tool: "click", args: {}, element: el({ name: "انتقال وجه" }) }, "blocked"],
  ["Send money", { tool: "click", args: {}, element: el({ name: "Send money" }) }, "blocked"],
  // Secrets.
  ["password field", { tool: "type_text", args: { text: "hunter2" }, element: textbox("Password", { type: "password", sensitive: true }) }, "blocked"],
  ["card number in a plain field", { tool: "type_text", args: { text: "4111 1111 1111 1111" }, element: textbox("Notes") }, "blocked"],
  ["IBAN in a plain field", { tool: "type_text", args: { text: "IR062960000000100324200001" }, element: textbox("Notes") }, "blocked"],
  ["national ID in a plain field", { tool: "type_text", args: { text: "0499370899" }, element: textbox("Notes") }, "blocked"],
  ["National ID field", { tool: "type_text", args: { text: "x" }, element: textbox("National ID") }, "blocked"],
  ["کد ملی field", { tool: "type_text", args: { text: "x" }, element: textbox("کد ملی") }, "blocked"],
  ["one-time code field", { tool: "type_text", args: { text: "482913" }, element: textbox("Verification code") }, "blocked"],
  ["phone field", { tool: "type_text", args: { text: "09121234567" }, element: textbox("Mobile number", { type: "tel" }) }, "sensitive"],
  ["Ctrl+V", { tool: "press_key", args: { key: "Control+v" }, element: textbox("Message") }, "blocked"],
  // Sending.
  ["Send", { tool: "click", args: {}, element: el({ name: "Send" }) }, "sensitive"],
  ["ارسال پیام", { tool: "click", args: {}, element: el({ name: "ارسال پیام" }) }, "sensitive"],
  ["Enter in a message box", { tool: "press_key", args: { key: "Enter" }, element: el({ role: "textbox", tag: "textarea", name: "Message" }) }, "sensitive"],
  ["Post a reply", { tool: "click", args: {}, element: el({ name: "Post reply" }) }, "sensitive"],
  // Deleting.
  ["Delete", { tool: "click", args: {}, element: el({ name: "Delete" }) }, "sensitive"],
  ["حذف", { tool: "click", args: {}, element: el({ name: "حذف" }) }, "sensitive"],
  ["Delete account", { tool: "click", args: {}, element: el({ name: "Delete account" }) }, "blocked"],
  ["Empty trash", { tool: "click", args: {}, element: el({ name: "Empty trash" }) }, "blocked"],
  ["Delete key outside a field", { tool: "press_key", args: { key: "Delete" } }, "sensitive"],
  // Accounts and access.
  ["Sign up", { tool: "click", args: {}, element: el({ name: "Sign up" }) }, "blocked"],
  ["ثبت نام (submit)", { tool: "click", args: {}, element: el({ name: "ثبت نام", ...form }) }, "blocked"],
  ["Authorize", { tool: "click", args: {}, element: el({ name: "Authorize app" }) }, "sensitive"],
  ["consent page", { tool: "click", args: {}, page: { url: "https://accounts.google.com/o/oauth2/auth?x=1", host: "accounts.google.com" }, element: el({ name: "Continue" }) }, "sensitive"],
  ["Confirm transfer", { tool: "click", args: {}, element: el({ name: "Confirm transfer" }) }, "sensitive"],
  // What the rules cannot see.
  ["CAPTCHA frame", { tool: "click", args: {}, element: el({ name: "I'm not a robot", frame: { host: "www.recaptcha.net" } }) }, "blocked"],
  ["frame from another site", { tool: "click", args: {}, element: el({ name: "Continue", frame: { host: "widgets.other.net" } }) }, "sensitive"],
  ["unnamed control", { tool: "click", args: {}, element: el({ name: "" }) }, "sensitive"],
  ["faint target", { tool: "click", args: {}, element: el({ name: "Next", hidden: "transparent" }) }, "sensitive"],
  // Sites.
  ["a blocked site", { tool: "navigate", args: { url: "https://bank.example.com/" } }, "blocked"],
  ["link to a blocked site", { tool: "click", args: {}, element: el({ role: "link", tag: "a", name: "My bank", href: "https://bank.example.com/" }) }, "blocked"],
  ["Alpharouter itself", { tool: "navigate", args: { url: "https://ai.example.com/admin" } }, "blocked"],
  ["javascript: address", { tool: "navigate", args: { url: "javascript:alert(1)" } }, "blocked"],
  ["another site nobody allowed", { tool: "navigate", args: { url: "https://unknown.example.net/" } }, "sensitive"],
  ["executable download", { tool: "click", args: {}, element: el({ role: "link", tag: "a", name: "Get it", href: "https://shop.example.com/setup.exe" }) }, "blocked"],
  ["Download PDF", { tool: "click", args: {}, element: el({ name: "Download PDF" }) }, "sensitive"],
  ["file input", { tool: "click", args: {}, element: el({ role: "button", tag: "input", type: "file", name: "Choose file" }) }, "sensitive"],
];

describe("the rules that never loosen", () => {
  it.each(ROWS)("%s", (_label, action, expected) => {
    const verdict = classifyAction({ page: SHOP, ...action }, RULES);
    expect(verdict.class).toBe(expected);
    // In no mode does a refused action run, nor a sensitive one go ahead without the user.
    for (const mode of ["ask", "plan", "auto"] as AgentMode[]) {
      expect(approvalFor(verdict, mode)).toBe(expected === "blocked" ? "refuse" : "user");
    }
  });
});
