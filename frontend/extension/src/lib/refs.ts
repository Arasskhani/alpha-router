/**
 * How the agent tells whether a reference still names what it named: by
 * the element's role and name, loosely - a count in a name (an unread
 * total, a badge) may change while the element stays the same one.
 */

/** A name as a reference check compares it: spaces squashed, case and counts aside. */
export function looseName(name: string): string {
  return name.replace(/\s+/g, " ").trim().toLowerCase().replace(/\d+/g, "#");
}
