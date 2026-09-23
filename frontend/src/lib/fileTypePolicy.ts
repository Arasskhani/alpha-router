/**
 * Pure helpers behind the Storage Management "File types" card and its two
 * list popups.
 *
 * The server stores extensions lowercase, without a dot, sorted. The popup
 * keeps a local draft in the same shape so that what is sent on Save is
 * exactly what the operator saw, and so an entry typed as ".PDF" or "pdf,"
 * lands as "pdf" before it is compared against the list.
 */

export type FileTypeMode = "blocklist" | "allowlist";

/** Which of the two lists: the one that refuses, or the one that admits. */
export type FileTypeListKey = "blocked" | "allowed";

/** The policy as `GET /api/admin/storage` and the file-type endpoints return it. */
export type FileTypePolicy = {
  mode: FileTypeMode;
  blocked: string[];
  allowed: string[];
  default_blocked: string[];
  default_allowed: string[];
};

/** The server refuses a list longer than this (`upload_file_policy.MAX_LIST_ENTRIES`). */
export const MAX_LIST_ENTRIES = 500;

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

/** A search box entry as the lists spell things: trimmed, lowercase, no leading dot. */
export function normalizeSearchQuery(query: string): string {
  return query.trim().toLowerCase().replace(/^\./, "");
}

/**
 * The entries a search matches: every one that contains the query, ignoring
 * case and a leading dot, so ".PD" finds "pdf". An empty query matches all.
 */
export function filterExtensions(list: string[], query: string): string[] {
  const q = normalizeSearchQuery(query);
  if (!q) return list;
  return list.filter((ext) => ext.includes(q));
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

/** True when `ext` is part of the shipped default list; the entries that are not get a "custom" tag. */
export function isDefaultType(ext: string, defaults: string[]): boolean {
  return defaults.includes(ext);
}
