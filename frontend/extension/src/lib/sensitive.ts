/**
 * Fields the extension never types into and never reads a value from:
 * passwords, card numbers and codes, one-time codes, PINs, bank numbers.
 *
 * Judged from what the page says about the field - its type, name, id,
 * autocomplete and label - since a page names such fields for the browser's
 * own password manager and autofill. `insert.ts` carries the same rules in a
 * function that runs serialized in the page, where it can import nothing; a
 * test keeps the two in step.
 */

const SENSITIVE_WORDS = /\b(password|passwd|pwd|pin|cvv|cvc|csc|iban|otp)\b/;
const SENSITIVE_PARTS = /(^|[\s_-])cc-|\bcard|security.?code|one-time-code|current-password|new-password/;

/** What the page says about a field, in one lower-case string. */
function fieldDescription(el: Element): string {
  return [el.getAttribute("type"), el.getAttribute("name"), el.id, el.getAttribute("autocomplete"), el.getAttribute("aria-label")]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

export function isSensitiveField(el: Element): boolean {
  if (el.tagName === "INPUT" && (el.getAttribute("type") ?? "").toLowerCase() === "password") return true;
  const describe = fieldDescription(el);
  return SENSITIVE_WORDS.test(describe) || SENSITIVE_PARTS.test(describe);
}
