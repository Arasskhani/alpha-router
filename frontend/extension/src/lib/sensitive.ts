/**
 * Fields the extension never types into and never reads a value from:
 * passwords, card numbers and their codes, one-time codes, PINs, bank and
 * identity numbers.
 *
 * Judged from everything the page says about the field - its type, name, id,
 * autocomplete, placeholder, title, ARIA label and the words of its labels -
 * and from its masking (a text field drawn as dots). Pages name such fields
 * for the browser's own password manager and autofill, but as their authors
 * write them: "loginPassword", "x_card_num", "cvv2", "pin_code". So each
 * name is split into words - at changes of case, between letters and
 * digits, at anything else - before the words are matched, and Persian is
 * matched as Iranian sites write it.
 *
 * `insert.ts` runs serialized in the page, where it can import nothing: it
 * is handed `SENSITIVE_RULES` and carries its own copy of the matching, and
 * a test keeps the two in step.
 */

export type SensitiveRules = {
  /** Words that name a secret on their own. */
  words: string[];
  /** A word, and the words right after it that make it one: "card" then "number". */
  pairs: Array<[string, string[]]>;
  /** Persian, as a regular expression's source, matched on the normalized text. */
  persian: string;
};

export const SENSITIVE_RULES: SensitiveRules = {
  words: [
    "password",
    "passwd",
    "pwd",
    "passcode",
    "passphrase",
    "pin",
    "pincode",
    "cvv",
    "cvc",
    "csc",
    "ccv",
    "cvn",
    "iban",
    "sheba",
    "shaba",
    "otp",
    "totp",
    "hotp",
    "mfa",
    "pan",
    "ccnum",
    "ccnumber",
    "cardnum",
    "cardnumber",
    "cardno",
    "creditcard",
    "debitcard",
    "securitycode",
    "onetimecode",
    "secret",
    "ssn",
    "passport",
  ],
  pairs: [
    ["card", ["number", "num", "no", "nr", "code", "cvv", "cvc", "csc", "exp", "expiry", "expiration", "security", "verification"]],
    ["cc", ["number", "num", "no", "nr", "code", "exp", "expiry", "csc", "cvv", "cvc", "name"]],
    ["credit", ["card"]],
    ["debit", ["card"]],
    ["security", ["code", "number"]],
    ["verification", ["code", "number"]],
    ["one", ["time"]],
    ["auth", ["code"]],
    ["authentication", ["code"]],
    ["account", ["number", "num", "no", "nr"]],
    ["routing", ["number"]],
    ["sort", ["code"]],
    ["api", ["key"]],
    ["private", ["key"]],
    ["national", ["id", "identity", "number", "code"]],
    ["social", ["security"]],
    ["tax", ["id", "number"]],
    ["id", ["number"]],
    ["identity", ["number"]],
  ],
  persian: "رمز|کلمه ?عبور|گذرواژه|شماره ?کارت|کد ?امنیتی|تاریخ ?انقضا|شبا|کد ?تایید|کد ?تأیید|یک ?بار ?مصرف|کد ?ملی|شماره ?ملی|شناسنامه|گذرنامه|cvv2",
};

/**
 * The forms of a text the rules read: compatibility forms folded (fullwidth
 * letters, Arabic presentation forms) and tatweel dropped; then, for the
 * invisible format characters - zero-width joiners and spaces, the word
 * joiner, direction marks, soft hyphens - once without them and once with
 * each read as a space. Inside a word one hides it (a word joiner in
 * "password"), between words it parts them ("PIN" and "code").
 */
function readForms(text: string): string[] {
  const folded = text.normalize("NFKC").replace(/\u0640/g, "");
  return [folded.replace(/\p{Cf}/gu, ""), folded.replace(/\p{Cf}/gu, " ")];
}

/** Persian as the rules match it: Arabic yeh and kaf as Persian ones, and no diacritics. */
function persianForm(text: string): string {
  return text
    .replace(/[يى]/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/\p{M}/gu, "")
    .replace(/\s+/g, " ");
}

/** A name split into lower-case words: "loginPassword" → login, password; "cvv2" → cvv, 2. */
export function nameWords(text: string): string[] {
  return text
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .replace(/([A-Za-z])(\d)/g, "$1 $2")
    .replace(/(\d)([A-Za-z])/g, "$1 $2")
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

/** Whether one thing a page says about a field (a name, a label) names a secret. */
export function sensitiveText(text: string, rules: SensitiveRules = SENSITIVE_RULES): boolean {
  if (!text) return false;
  const persian = new RegExp(rules.persian, "i");
  const pairs = new Map(rules.pairs);
  return readForms(text).some((form) => {
    if (persian.test(persianForm(form)) || /(^|[\s_-])cc-/.test(form.toLowerCase())) return true;
    const words = nameWords(form);
    return words.some((word, index) => rules.words.includes(word) || Boolean(pairs.get(word)?.includes(words[index + 1] ?? "")));
  });
}

/** Everything the page says about a field, each on its own: a pair of words never spans two of them. */
function fieldDescriptions(el: Element): string[] {
  const doc = el.ownerDocument;
  const attributes = ["type", "name", "id", "autocomplete", "aria-label", "placeholder", "aria-placeholder", "title"].map((name) => el.getAttribute(name));
  const labels = Array.from((el as HTMLInputElement).labels ?? [], (label) => label.textContent);
  const labelledBy = (el.getAttribute("aria-labelledby") ?? "")
    .split(/\s+/)
    .filter(Boolean)
    .map((id) => doc.getElementById(id)?.textContent ?? "");
  return [...attributes, ...labels, ...labelledBy].filter((text): text is string => Boolean(text && text.trim())).map((text) => text.slice(0, 300));
}

/** A field drawn as dots, whatever its type says. */
function masked(el: Element): boolean {
  const view = el.ownerDocument.defaultView;
  if (!view) return false;
  const style = view.getComputedStyle(el);
  const security = style.getPropertyValue("-webkit-text-security") || style.getPropertyValue("text-security");
  return Boolean(security && security.trim() !== "none");
}

export function isSensitiveField(el: Element): boolean {
  if (el.tagName === "INPUT" && (el.getAttribute("type") ?? "").toLowerCase() === "password") return true;
  if (masked(el)) return true;
  return fieldDescriptions(el).some((text) => sensitiveText(text));
}
