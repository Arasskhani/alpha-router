/**
 * Keyboard input as CDP `Input.*` commands.
 *
 * Text goes in through `Input.insertText`, which enters a whole string at once
 * and handles Persian and other non-Latin text (the Phase 0 spike confirmed it).
 * Named keys and shortcuts go through `Input.dispatchKeyEvent` with the key,
 * code and Windows virtual-key code Chromium expects.
 */

import { modifiersMask, type Send } from "./input";

type KeyDef = { key: string; code: string; vk: number; text?: string };

/** The named keys the agent may press (Claude in Chrome's set), with their CDP fields. */
export const NAMED_KEYS: Record<string, KeyDef> = {
  Enter: { key: "Enter", code: "Enter", vk: 13, text: "\r" },
  Tab: { key: "Tab", code: "Tab", vk: 9, text: "\t" },
  Escape: { key: "Escape", code: "Escape", vk: 27 },
  Backspace: { key: "Backspace", code: "Backspace", vk: 8 },
  Delete: { key: "Delete", code: "Delete", vk: 46 },
  Space: { key: " ", code: "Space", vk: 32, text: " " },
  ArrowUp: { key: "ArrowUp", code: "ArrowUp", vk: 38 },
  ArrowDown: { key: "ArrowDown", code: "ArrowDown", vk: 40 },
  ArrowLeft: { key: "ArrowLeft", code: "ArrowLeft", vk: 37 },
  ArrowRight: { key: "ArrowRight", code: "ArrowRight", vk: 39 },
  Home: { key: "Home", code: "Home", vk: 36 },
  End: { key: "End", code: "End", vk: 35 },
  PageUp: { key: "PageUp", code: "PageUp", vk: 33 },
  PageDown: { key: "PageDown", code: "PageDown", vk: 34 },
};

/** Match a named key case-insensitively, so "enter" and "Enter" both work. */
export function namedKey(name: string): KeyDef | null {
  const wanted = (name || "").trim().toLowerCase();
  for (const [key, def] of Object.entries(NAMED_KEYS)) if (key.toLowerCase() === wanted) return def;
  return null;
}

/** A single printable character's key definition (letters, digits, punctuation). */
function charKey(ch: string): KeyDef {
  const upper = ch.toUpperCase();
  let code = `Key${upper}`;
  if (ch >= "0" && ch <= "9") code = `Digit${ch}`;
  else if (!(upper >= "A" && upper <= "Z")) code = "";
  return { key: ch, code, vk: upper.charCodeAt(0), text: ch };
}

export async function insertText(send: Send, text: string): Promise<void> {
  await send("Input.insertText", { text });
}

/** Press and release one key definition, holding `modifiers` for the duration. */
async function pressDef(send: Send, def: KeyDef, modifiers: readonly string[]): Promise<void> {
  const mask = modifiersMask(modifiers);
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
 * Press a named key ("Enter", "ArrowDown", …) or a shortcut ("ctrl+a", "cmd+shift+k").
 * The last token is the key; the ones before it are modifiers. Returns false when the
 * key is not one we know, so the caller can report it rather than press nothing.
 */
export async function pressKey(send: Send, spec: string, extraModifiers: readonly string[] = []): Promise<boolean> {
  const tokens = (spec || "").split("+").map((t) => t.trim()).filter(Boolean);
  if (!tokens.length) return false;
  const keyName = tokens[tokens.length - 1];
  const modifiers = [...extraModifiers, ...tokens.slice(0, -1)];
  const named = namedKey(keyName);
  if (named) {
    await pressDef(send, named, modifiers);
    return true;
  }
  if ([...keyName].length === 1) {
    await pressDef(send, charKey(keyName), modifiers);
    return true;
  }
  return false;
}
