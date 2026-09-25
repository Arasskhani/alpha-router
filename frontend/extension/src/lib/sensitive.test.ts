/**
 * @vitest-environment happy-dom
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { isSensitiveField, nameWords, sensitiveText } from "./sensitive";

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

function field(html: string): Element {
  document.body.innerHTML = html;
  return document.querySelector("input, textarea, [contenteditable]")!;
}

describe("names as page authors write them", () => {
  it("are split into words at case changes, digits and punctuation", () => {
    expect(nameWords("loginPassword")).toEqual(["login", "password"]);
    expect(nameWords("CCNumber")).toEqual(["cc", "number"]);
    expect(nameWords("cvv2")).toEqual(["cvv", "2"]);
    expect(nameWords("x_card_num")).toEqual(["x", "card", "num"]);
    expect(nameWords("billing-card.number")).toEqual(["billing", "card", "number"]);
  });

  it.each([
    "user_password",
    "loginPassword",
    "newPassword",
    "password1",
    "x_card_num",
    "x_card_code",
    "billing_card_number",
    "creditCardNumber",
    "ccNumber",
    "cc_number",
    "ccnum",
    "cvv2",
    "cc_cvv",
    "pinCode",
    "pin_code",
    "pin2",
    "otp_code",
    "otp1",
    "verificationCode",
    "accountNumber",
    "pan",
    "Security code",
    "One-time code",
    "API key",
    "National ID",
    "cc-exp",
    "رمز دوم",
    "رمز عبور",
    "کلمه‌عبور",
    "شماره كارت",
    "كد تاييد",
    "کد امنیتی cvv2",
    "تاریخ انقضا",
    "شماره شبا",
    "کد ملی",
  ])("%s names a secret", (text) => {
    expect(sensitiveText(text)).toBe(true);
  });

  it.each([
    "email",
    "Search the docs",
    "spinach",
    "discard-reason",
    "company",
    "Japan",
    "shipping",
    "postal_code",
    "Promo code",
    "Name on card",
    "Phone number",
    "Your city",
    "کد پستی",
    "شماره موبایل",
    "",
  ])("%s does not", (text) => {
    expect(sensitiveText(text)).toBe(false);
  });
});

describe("a field", () => {
  it.each([
    ['<input type="password">', "its type"],
    ['<input type="PASSWORD">', "its type in capitals"],
    ['<input name="x_card_num" value="4111 1111 1111 1111">', "its name"],
    ['<input placeholder="Card number">', "its placeholder"],
    ['<label for="f">Card number</label><input id="f">', "its label"],
    ['<label>Your PIN <input></label>', "the label around it"],
    ['<span id="l">Verification code</span><input aria-labelledby="l">', "the element that names it"],
    ['<input type="password" role="combobox" aria-label="PIN">', "its type, whatever role it claims"],
    ['<textarea name="private_key"></textarea>', "a text area's name"],
    ['<div contenteditable="true" aria-label="Recovery passphrase"></div>', "an editor's label"],
  ])("%s is sensitive by %s", (html) => {
    expect(isSensitiveField(field(html))).toBe(true);
  });

  it("is sensitive when it is drawn as dots, whatever its type", () => {
    const input = field('<input name="code">');
    // A DOM without a style engine: the browser's computed style, as Chrome gives it for such a field.
    vi.spyOn(window, "getComputedStyle").mockImplementation(
      () => ({ getPropertyValue: (name: string) => (name === "-webkit-text-security" ? "disc" : "") }) as unknown as CSSStyleDeclaration,
    );
    expect(isSensitiveField(input)).toBe(true);
  });

  it.each([
    ['<input name="card" placeholder="Number of guests">', "words from two attributes never make a pair"],
    ['<label for="f">Nickname</label><input id="f" name="nick">', "an ordinary label"],
    ['<input type="search" aria-label="Search the docs">', "a search box"],
  ])("%s is not: %s", (html) => {
    expect(isSensitiveField(field(html))).toBe(false);
  });
});
