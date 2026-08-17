/** Detect RTL (Persian/Arabic) vs LTR (Latin) for chat inputs and messages. */

export type TextDirection = "rtl" | "ltr";

const RTL_CHAR = /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]/;
const LTR_CHAR = /[A-Za-z0-9]/;

function charDirection(ch: string): TextDirection | null {
  if (!ch || /\s/.test(ch)) return null;
  if (RTL_CHAR.test(ch)) return "rtl";
  if (LTR_CHAR.test(ch)) return "ltr";
  return null;
}

/** Strip markdown syntax so direction follows the readable text, not `#` or `-` bullets. */
function stripMarkdownForDirection(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`[^`]+`/g, " ")
    // Long agent citation markers are LTR noise and must not flip RTL majority.
    .replace(/\[\[cite:[A-Za-z0-9._:-]{1,128}\]\]/g, " ")
    .replace(/!\[[^\]]*\]\([^)]+\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+\.\s+/gm, "")
    .replace(/[*_~]/g, "");
}

/** Direction from the character nearest the caret (keyboard context). */
export function inputDirectionForText(text: string, caretIndex?: number): TextDirection {
  const pos = Math.max(0, Math.min(caretIndex ?? text.length, text.length));
  if (pos > 0) {
    const atCaret = charDirection(text[pos - 1] ?? "");
    if (atCaret) return atCaret;
  }
  for (let i = pos - 2; i >= 0; i -= 1) {
    const dir = charDirection(text[i] ?? "");
    if (dir) return dir;
  }
  for (let i = pos; i < text.length; i += 1) {
    const dir = charDirection(text[i] ?? "");
    if (dir) return dir;
  }
  return "ltr";
}

/** Direction for displaying a whole message bubble (majority script wins). */
export function messageDirectionForText(text: string): TextDirection {
  const sample = stripMarkdownForDirection(text.trim());
  if (!sample) return "ltr";
  let rtl = 0;
  let ltr = 0;
  for (const ch of sample) {
    const dir = charDirection(ch);
    if (dir === "rtl") rtl += 1;
    else if (dir === "ltr") ltr += 1;
  }
  if (rtl === 0 && ltr === 0) return "ltr";
  return rtl >= ltr ? "rtl" : "ltr";
}

/** True when the draft likely needs translation to English (non-Latin or RTL script). */
export function textNeedsEnglishTranslation(text: string): boolean {
  const sample = stripMarkdownForDirection(text.trim());
  if (!sample) return false;
  if (RTL_CHAR.test(sample)) return true;
  let latin = 0;
  let otherLetters = 0;
  for (const ch of sample) {
    if (!/\p{L}/u.test(ch)) continue;
    if (/[A-Za-z]/.test(ch)) latin += 1;
    else otherLetters += 1;
  }
  if (latin === 0 && otherLetters === 0) return false;
  return otherLetters > 0 && latin / (latin + otherLetters) < 0.85;
}
