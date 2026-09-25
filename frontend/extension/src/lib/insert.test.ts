/**
 * @vitest-environment happy-dom
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { insertIntoFocusedField, plainText } from "./insert";
import { isSensitiveField } from "./sensitive";

afterEach(() => {
  document.body.innerHTML = "";
});

function focusOn<T extends HTMLElement>(html: string): T {
  document.body.innerHTML = html;
  const el = document.body.firstElementChild as T;
  el.focus();
  return el;
}

const here = () => location.hostname;

describe("an answer put into the page", () => {
  it("goes into a text area at the caret, as typing would", () => {
    const area = focusOn<HTMLTextAreaElement>("<textarea>Dear team,\n\nBest</textarea>");
    area.setSelectionRange(12, 12);
    const events: string[] = [];
    area.addEventListener("input", (event) => events.push(`input:${(event as InputEvent).data}`));
    area.addEventListener("change", () => events.push("change"));
    expect(insertIntoFocusedField("The report is ready.\n", here())).toBe("inserted");
    expect(area.value).toBe("Dear team,\n\nThe report is ready.\nBest");
    expect(events).toEqual(["input:The report is ready.\n", "change"]);
  });

  it("goes into a one-line field on one line, within its length", () => {
    const input = focusOn<HTMLInputElement>('<input type="text" maxlength="20" value="">');
    expect(insertIntoFocusedField("First line\nsecond line and more", here())).toBe("inserted");
    expect(input.value).toBe("First line second li");
  });

  it("goes into an editor at the selection", () => {
    const editor = focusOn<HTMLDivElement>('<div contenteditable="true">Hello </div>');
    const range = document.createRange();
    range.selectNodeContents(editor);
    range.collapse(false);
    document.getSelection()?.removeAllRanges();
    document.getSelection()?.addRange(range);
    expect(insertIntoFocusedField("world", here())).toBe("inserted");
    expect(editor.textContent).toBe("Hello world");
  });

  it.each([
    ['<input type="password">', "a password field"],
    ['<input type="text" autocomplete="cc-number">', "a card number"],
    ['<input type="text" name="card_number">', "a field named for a card"],
    ['<input type="text" autocomplete="one-time-code">', "a one-time code"],
    ['<input type="text" id="cvv">', "a security code"],
    ['<input type="text" aria-label="PIN">', "a PIN"],
  ])("never goes into %s (%s)", (html) => {
    const input = focusOn<HTMLInputElement>(html);
    expect(insertIntoFocusedField("secret", here())).toBe("sensitive");
    expect(input.value).toBe("");
  });

  it("is not stopped by a word that only contains a sensitive one", () => {
    const input = focusOn<HTMLInputElement>('<input type="text" name="discard-reason">');
    expect(insertIntoFocusedField("Duplicate", here())).toBe("inserted");
    expect(input.value).toBe("Duplicate");
  });

  it.each([
    ['<input type="number">', "a number field"],
    ["<textarea readonly></textarea>", "a read-only field"],
    ["<textarea disabled></textarea>", "a disabled field"],
    ["<button>Save</button>", "a button"],
  ])("finds no field in %s (%s)", (html) => {
    focusOn(html);
    expect(insertIntoFocusedField("text", here())).toBe("no_field");
  });

  it("finds no field when nothing is focused", () => {
    document.body.innerHTML = "<textarea></textarea>";
    (document.activeElement as HTMLElement | null)?.blur();
    expect(insertIntoFocusedField("text", here())).toBe("no_field");
  });

  it("does nothing on another site than the one the panel saw", () => {
    const area = focusOn<HTMLTextAreaElement>("<textarea></textarea>");
    expect(insertIntoFocusedField("text", "elsewhere.example")).toBe("moved");
    expect(area.value).toBe("");
  });

  it("stands on its own, as Chrome serializes it into the page", () => {
    const area = focusOn<HTMLTextAreaElement>("<textarea></textarea>");
    const rebuilt = new Function(`return (${String(insertIntoFocusedField)})`)() as typeof insertIntoFocusedField;
    expect(rebuilt("Rebuilt", here())).toBe("inserted");
    expect(area.value).toBe("Rebuilt");
    vi.restoreAllMocks();
  });
});

describe("an answer as plain text", () => {
  it("drops the markdown marks and keeps the words, links with their address", () => {
    expect(
      plainText(
        [
          "# Summary",
          "",
          "The **report** is *ready*, see [the file](https://files.example/r.pdf).",
          "",
          "- `one`",
          "- two",
          "",
          "> quoted",
          "",
          "```",
          "code stays",
          "```",
        ].join("\n"),
      ),
    ).toBe("Summary\n\nThe report is ready, see the file (https://files.example/r.pdf).\n\n- one\n- two\n\nquoted\n\ncode stays");
  });

  it("leaves list stars and plain text alone", () => {
    expect(plainText("* first\n* second")).toBe("* first\n* second");
    expect(plainText("2 * 3 = 6")).toBe("2 * 3 = 6");
  });
});

describe("the rules for sensitive fields", () => {
  // insert.ts runs serialized in the page and cannot import sensitive.ts: the two copies must agree.
  it.each([
    '<input type="password">',
    '<input name="card_number">',
    '<input autocomplete="cc-exp">',
    '<input id="cvc">',
    '<input autocomplete="one-time-code">',
    '<input aria-label="Security code">',
    '<input name="iban">',
    '<input name="otp">',
    '<input name="user_pin">',
    '<input autocomplete="new-password" type="text">',
    '<input type="text" name="email">',
    '<input type="search" aria-label="Search the docs">',
    '<input type="text" name="spinach">',
    '<input type="text" name="discard-reason">',
  ])("classify %s alike", (html) => {
    const field = focusOn<HTMLInputElement>(html);
    const inserted = insertIntoFocusedField("x", here());
    expect(inserted === "sensitive").toBe(isSensitiveField(field));
  });
});
