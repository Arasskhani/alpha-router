/**
 * Keys, one table for everyone: the agent's rules read a key through it, the
 * real keyboard (CDP `Input.*`) presses it, and the page's own events name it.
 *
 * Models write keys every which way - "Enter" and "Return", "PageDown" and
 * "Page_Down" (the xdotool names computer-use models learn), "esc", "Up",
 * "super+a" - and the rules and the keyboard once each had their own list:
 * a key the rules judged could be one the keyboard did not know, or press as
 * something else. Here every spelling resolves to one key, or to none.
 *
 * Text goes in through `Input.insertText`, which enters a whole string at once
 * and handles Persian and other non-Latin text (the Phase 0 spike confirmed it).
 * Named keys and shortcuts go through `Input.dispatchKeyEvent` with the key,
 * code and Windows virtual-key code Chromium expects.
 */

import { modifierName, modifiersMask, type Send } from "./input";

/** A key as the model names it ("ctrl+shift+a", "Return", "Space"): the key, as KeyboardEvent.key has it, and what is held. */
export type KeyCombo = { key: string; ctrl: boolean; alt: boolean; shift: boolean; meta: boolean };

export type KeyDef = { key: string; code: string; vk: number; text?: string };

/** The named keys, by KeyboardEvent.key, with their CDP fields. */
const NAMED_KEYS: Record<string, KeyDef> = {
  Enter: { key: "Enter", code: "Enter", vk: 13, text: "\r" },
  Tab: { key: "Tab", code: "Tab", vk: 9, text: "\t" },
  Escape: { key: "Escape", code: "Escape", vk: 27 },
  Backspace: { key: "Backspace", code: "Backspace", vk: 8 },
  Delete: { key: "Delete", code: "Delete", vk: 46 },
  Insert: { key: "Insert", code: "Insert", vk: 45 },
  " ": { key: " ", code: "Space", vk: 32, text: " " },
  ArrowUp: { key: "ArrowUp", code: "ArrowUp", vk: 38 },
  ArrowDown: { key: "ArrowDown", code: "ArrowDown", vk: 40 },
  ArrowLeft: { key: "ArrowLeft", code: "ArrowLeft", vk: 37 },
  ArrowRight: { key: "ArrowRight", code: "ArrowRight", vk: 39 },
  Home: { key: "Home", code: "Home", vk: 36 },
  End: { key: "End", code: "End", vk: 35 },
  PageUp: { key: "PageUp", code: "PageUp", vk: 33 },
  PageDown: { key: "PageDown", code: "PageDown", vk: 34 },
  ...Object.fromEntries(Array.from({ length: 12 }, (_, i) => [`F${i + 1}`, { key: `F${i + 1}`, code: `F${i + 1}`, vk: 112 + i }])),
};

/**
 * Every spelling of a named key, as `spelling()` reduces it (lower case, no
 * spaces, underscores or hyphens), to its KeyboardEvent.key.
 */
const ALIASES: Record<string, string> = {
  enter: "Enter",
  return: "Enter",
  kpenter: "Enter",
  numpadenter: "Enter",
  tab: "Tab",
  escape: "Escape",
  esc: "Escape",
  backspace: "Backspace",
  back: "Backspace",
  delete: "Delete",
  del: "Delete",
  kpdelete: "Delete",
  insert: "Insert",
  ins: "Insert",
  space: " ",
  spacebar: " ",
  arrowup: "ArrowUp",
  up: "ArrowUp",
  kpup: "ArrowUp",
  arrowdown: "ArrowDown",
  down: "ArrowDown",
  kpdown: "ArrowDown",
  arrowleft: "ArrowLeft",
  left: "ArrowLeft",
  kpleft: "ArrowLeft",
  arrowright: "ArrowRight",
  right: "ArrowRight",
  kpright: "ArrowRight",
  home: "Home",
  kphome: "Home",
  end: "End",
  kpend: "End",
  pageup: "PageUp",
  pgup: "PageUp",
  prior: "PageUp",
  kppageup: "PageUp",
  kpprior: "PageUp",
  pagedown: "PageDown",
  pgdn: "PageDown",
  pgdown: "PageDown",
  next: "PageDown",
  kppagedown: "PageDown",
  kpnext: "PageDown",
  ...Object.fromEntries(Array.from({ length: 12 }, (_, i) => [`f${i + 1}`, `F${i + 1}`])),
  // Punctuation by name, as in "ctrl+plus".
  plus: "+",
  minus: "-",
  equal: "=",
  equals: "=",
  comma: ",",
  period: ".",
  slash: "/",
  backslash: "\\",
  semicolon: ";",
  apostrophe: "'",
  quote: "'",
  bracketleft: "[",
  bracketright: "]",
  grave: "`",
};

/** The keys the agent may name, as its tools tell the model. */
export const KEY_NAMES_SHOWN =
  "Enter, Tab, Escape, Backspace, Delete, Space, ArrowUp, ArrowDown, ArrowLeft, ArrowRight, Home, End, PageUp, PageDown, or one character; with ctrl, shift, alt or meta (cmd, win) held, joined with +, such as ctrl+a";

function spelling(token: string): string {
  return token.trim().toLowerCase().replace(/[\s_-]+/g, "");
}

/** Control characters a model may write for a key: a new line is Enter, a tab Tab; the rest are no key. */
const CONTROL_KEYS: Record<string, string> = { "\r": "Enter", "\n": "Enter", "\t": "Tab", "\b": "Backspace", "\u007f": "Delete", "\u001b": "Escape" };

/** The KeyboardEvent.key a key's name stands for, or null for no key this table knows. */
function keyOf(token: string): string | null {
  if ([...token].length === 1) {
    if (/\p{Cc}/u.test(token)) return CONTROL_KEYS[token] ?? null;
    return token;
  }
  return ALIASES[spelling(token)] ?? null;
}

/**
 * A key or shortcut as the model wrote it: the last part is the key, the
 * ones before it what is held. Null for anything that is not a key: an
 * unknown name, an unknown modifier, nothing at all.
 */
export function parseKeyCombo(raw: unknown): KeyCombo | null {
  if (typeof raw !== "string") return null;
  // One character alone is that key: a space is the space bar, "+" the plus key, a new line Enter.
  const single = [...raw].length === 1;
  const trimmed = single ? raw : raw.trim();
  if (!trimmed) return null;
  const tokens = single || trimmed === "+" ? [trimmed] : trimmed.split("+").map((t) => t.trim()).filter(Boolean);
  if (!tokens.length) return null;
  const combo: KeyCombo = { key: "", ctrl: false, alt: false, shift: false, meta: false };
  for (const token of tokens.slice(0, -1)) {
    const held = modifierName(token);
    if (!held) return null;
    combo[held] = true;
  }
  const key = keyOf(tokens[tokens.length - 1]);
  if (key === null) return null;
  combo.key = key;
  return combo;
}

/** A key's fields - key, code and virtual-key code - for a named key or one printable character, as a press of `combo` has them. */
export function keyDefFor(combo: KeyCombo): KeyDef {
  return keyDef(combo.key, combo.shift);
}

/**
 * Punctuation on a US keyboard: the key it is on (KeyboardEvent.code) and
 * that key's Windows virtual-key code. A character's own code would be
 * another key's: "." is 46, Delete's, "(" is 40, ArrowDown's.
 */
const PUNCTUATION: Record<string, { code: string; vk: number }> = {
  ";": { code: "Semicolon", vk: 186 },
  ":": { code: "Semicolon", vk: 186 },
  "=": { code: "Equal", vk: 187 },
  "+": { code: "Equal", vk: 187 },
  ",": { code: "Comma", vk: 188 },
  "<": { code: "Comma", vk: 188 },
  "-": { code: "Minus", vk: 189 },
  _: { code: "Minus", vk: 189 },
  ".": { code: "Period", vk: 190 },
  ">": { code: "Period", vk: 190 },
  "/": { code: "Slash", vk: 191 },
  "?": { code: "Slash", vk: 191 },
  "`": { code: "Backquote", vk: 192 },
  "~": { code: "Backquote", vk: 192 },
  "[": { code: "BracketLeft", vk: 219 },
  "{": { code: "BracketLeft", vk: 219 },
  "\\": { code: "Backslash", vk: 220 },
  "|": { code: "Backslash", vk: 220 },
  "]": { code: "BracketRight", vk: 221 },
  "}": { code: "BracketRight", vk: 221 },
  "'": { code: "Quote", vk: 222 },
  '"': { code: "Quote", vk: 222 },
  ...Object.fromEntries([..."!@#$%^&*()"].map((c, i) => [c, { code: `Digit${(i + 1) % 10}`, vk: 48 + ((i + 1) % 10) }])),
};

function keyDef(key: string, shift: boolean): KeyDef {
  const named = NAMED_KEYS[key];
  if (named) return named;
  const upper = key.toUpperCase();
  const text = shift && upper !== key.toLowerCase() ? upper : key;
  if (key >= "0" && key <= "9") return { key: text, code: `Digit${key}`, vk: key.charCodeAt(0), text };
  if (upper >= "A" && upper <= "Z" && upper.length === 1) return { key: text, code: `Key${upper}`, vk: upper.charCodeAt(0), text };
  const mark = PUNCTUATION[key];
  if (mark) return { key: text, ...mark, text };
  // A letter of another script (Persian, Cyrillic): no key of a US keyboard, so no key code; the text is what goes in.
  return { key: text, code: "", vk: 0, text };
}

/** Whether the keyboard of the computer the browser runs on is a Mac's, where editing shortcuts are the OS's to carry out. */
function onMac(): boolean {
  const nav = globalThis.navigator as (Navigator & { userAgentData?: { platform?: string } }) | undefined;
  return /mac/i.test(nav?.userAgentData?.platform ?? nav?.platform ?? "");
}

/**
 * On a Mac, the editing commands a shortcut stands for: there the OS, not the
 * page, turns Cmd+A into "select all", and a key from CDP reaches no OS, so
 * the command goes with the key. Elsewhere the page's editing handles them.
 */
function macCommands(combo: KeyCombo): string[] | undefined {
  if (!onMac() || !(combo.ctrl || combo.meta)) return undefined;
  const letter = combo.key.toLowerCase();
  if (letter === "a") return ["selectAll"];
  if (letter === "c") return ["copy"];
  if (letter === "x") return ["cut"];
  if (letter === "z") return [combo.shift ? "redo" : "undo"];
  if (letter === "y") return ["redo"];
  return undefined;
}

export async function insertText(send: Send, text: string): Promise<void> {
  await send("Input.insertText", { text });
}

/** Press and release one key, holding what `combo` holds. */
async function pressCombo(send: Send, combo: KeyCombo): Promise<void> {
  const held = [combo.ctrl && "ctrl", combo.alt && "alt", combo.shift && "shift", combo.meta && "meta"].filter((m): m is string => Boolean(m));
  const mask = modifiersMask(held);
  const def = keyDef(combo.key, combo.shift);
  // With Ctrl/Meta held, a key is a shortcut, not text: dispatch rawKeyDown, no text.
  const isShortcut = mask & (2 | 4);
  const down: Record<string, unknown> = {
    type: isShortcut ? "rawKeyDown" : "keyDown",
    modifiers: mask,
    key: def.key,
    code: def.code,
    windowsVirtualKeyCode: def.vk,
    nativeVirtualKeyCode: def.vk,
  };
  if (def.text && !isShortcut) {
    down.text = def.text;
    down.unmodifiedText = def.text;
  }
  const commands = macCommands(combo);
  if (commands) down.commands = commands;
  await send("Input.dispatchKeyEvent", down);
  await send("Input.dispatchKeyEvent", {
    type: "keyUp",
    modifiers: mask,
    key: def.key,
    code: def.code,
    windowsVirtualKeyCode: def.vk,
    nativeVirtualKeyCode: def.vk,
  });
}

/**
 * Press a key or a shortcut ("Enter", "Page_Down", "ctrl+a", "cmd+shift+k"),
 * with `extraModifiers` held as well. Returns false when it is not a key this
 * table knows, so the caller can report it rather than press nothing.
 */
export async function pressKey(send: Send, spec: string, extraModifiers: readonly string[] = []): Promise<boolean> {
  const combo = parseKeyCombo(spec);
  if (!combo) return false;
  for (const extra of extraModifiers) {
    const held = modifierName(extra);
    if (held) combo[held] = true;
  }
  await pressCombo(send, combo);
  return true;
}
