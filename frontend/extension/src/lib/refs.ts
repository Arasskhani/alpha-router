/**
 * How the agent tells whether a reference still names what it named: by
 * the element's role and name, loosely - a count in a name (an unread
 * total, a badge) may change while the element stays the same one. Any
 * other number is part of what the element is: "Delete invoice 1041" is
 * not "Delete invoice 1042", which a list that reuses its rows may put in
 * the same element after a scroll.
 */

/** Words that follow a count: "12 unread", "3 new", «۵ پیام». */
const COUNTED = "unread|new|items?|messages?|notifications?|results?|more|comments?|replies|likes?|views?|جدید|تازه|خوانده ?نشده|پیام|مورد";
const COUNT_IN_BRACKETS = /[([]\s*\d[\d,.]*\+?\s*[)\]]/g;
const COUNT_BEFORE_WORD = new RegExp(`\\d[\\d,.]*\\+?(?= (${COUNTED})(?![\\p{L}]))`, "gu");

/** A name as a reference check compares it: spaces squashed, case aside, and counts aside. */
export function looseName(name: string): string {
  const ascii = name.replace(/[۰-۹]/g, (d) => String(d.charCodeAt(0) - 0x06f0)).replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660));
  return ascii.replace(/\s+/g, " ").trim().toLowerCase().replace(COUNT_IN_BRACKETS, "#").replace(COUNT_BEFORE_WORD, "#");
}
