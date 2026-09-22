/**
 * Pure helpers behind the Storage Management "File types" card.
 *
 * The server stores extensions lowercase, without a dot, sorted. The card
 * keeps a local draft in the same shape so that what is sent on Save is
 * exactly what the operator saw, and so an entry typed as ".PDF" or "pdf,"
 * lands as "pdf" before it is compared against the list.
 */

/** A file extension the policy accepts: 1–16 lowercase letters or digits, no dot. */
export const EXTENSION_PATTERN = /^[a-z0-9]{1,16}$/;

/**
 * Turn free text ("pdf, .DOCX tar.gz\nexe") into normalised extensions.
 * Entries are split on commas, whitespace and newlines; each is trimmed,
 * lowercased and stripped of one leading dot. Both lists are deduplicated
 * and sorted; `invalid` keeps the normalised spelling so the operator can
 * see what was rejected (e.g. "tar.gz").
 */
export function normalizeExtensionInput(raw: string): { valid: string[]; invalid: string[] } {
  const valid = new Set<string>();
  const invalid = new Set<string>();
  for (const part of raw.split(/[\s,]+/)) {
    const trimmed = part.trim();
    if (!trimmed) continue;
    const ext = trimmed.toLowerCase().replace(/^\./, "");
    if (!ext) continue;
    if (EXTENSION_PATTERN.test(ext)) valid.add(ext);
    else invalid.add(ext);
  }
  return { valid: [...valid].sort(), invalid: [...invalid].sort() };
}

/** What Save would change: entries only in `after` were added, only in `before` removed. */
export function diffLists(before: string[], after: string[]): { added: string[]; removed: string[] } {
  const b = new Set(before);
  const a = new Set(after);
  return {
    added: after.filter((x) => !b.has(x)).sort(),
    removed: before.filter((x) => !a.has(x)).sort(),
  };
}

/** True when `ext` is part of the shipped default list (shown as a "default" tag on the chip). */
export function isDefaultType(ext: string, defaults: string[]): boolean {
  return defaults.includes(ext);
}
