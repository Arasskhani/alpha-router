import { afterEach, describe, expect, it, vi } from "vitest";

import type { Send } from "./input";
import { insertText, KEY_NAMES_SHOWN, parseKeyCombo, pressKey } from "./keys";

function recorder() {
  const calls: Array<{ method: string; params: Record<string, unknown> }> = [];
  const send: Send = vi.fn(async (method, params = {}) => {
    calls.push({ method, params });
    return undefined;
  });
  return { send, calls };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("parseKeyCombo", () => {
  it("reads a key and what is held", () => {
    expect(parseKeyCombo("ctrl+shift+a")).toEqual({ key: "a", ctrl: true, alt: false, shift: true, meta: false });
    expect(parseKeyCombo("cmd+Enter")).toEqual({ key: "Enter", ctrl: false, alt: false, shift: false, meta: true });
    expect(parseKeyCombo("f5")).toMatchObject({ key: "F5" });
    expect(parseKeyCombo("ctrl+plus")).toMatchObject({ key: "+", ctrl: true });
    expect(parseKeyCombo("+")).toMatchObject({ key: "+" });
    expect(parseKeyCombo(" ")).toMatchObject({ key: " " });
  });

  it("knows every spelling models use, the xdotool names included", () => {
    const same: Array<[string, string]> = [
      ["Return", "Enter"],
      ["KP_Enter", "Enter"],
      ["enter", "Enter"],
      ["Page_Down", "PageDown"],
      ["Page_Up", "PageUp"],
      ["Next", "PageDown"],
      ["pgdn", "PageDown"],
      ["Up", "ArrowUp"],
      ["Down", "ArrowDown"],
      ["Left", "ArrowLeft"],
      ["Right", "ArrowRight"],
      ["esc", "Escape"],
      ["BackSpace", "Backspace"],
      ["space", " "],
      ["Del", "Delete"],
      ["KP_Home", "Home"],
    ];
    for (const [written, key] of same) expect(parseKeyCombo(written)?.key, written).toBe(key);
  });

  it("knows every name of a held key", () => {
    for (const held of ["super", "win", "meta", "cmd", "command"]) expect(parseKeyCombo(`${held}+a`)?.meta, held).toBe(true);
    for (const held of ["alt", "option", "opt"]) expect(parseKeyCombo(`${held}+a`)?.alt, held).toBe(true);
    for (const held of ["ctrl", "control", "Ctrl"]) expect(parseKeyCombo(`${held}+a`)?.ctrl, held).toBe(true);
  });

  it("refuses what is not a key", () => {
    expect(parseKeyCombo("bogus+a")).toBeNull();
    expect(parseKeyCombo("Frobnicate")).toBeNull();
    expect(parseKeyCombo("")).toBeNull();
    expect(parseKeyCombo(7)).toBeNull();
  });

  it("names the keys it knows for the model", () => {
    for (const name of ["Enter", "PageDown", "ArrowUp", "ctrl", "meta"]) expect(KEY_NAMES_SHOWN).toContain(name);
  });
});

describe("insertText", () => {
  it("sends the whole string, Persian included", async () => {
    const { send, calls } = recorder();
    await insertText(send, "سلام دنیا");
    expect(calls).toEqual([{ method: "Input.insertText", params: { text: "سلام دنیا" } }]);
  });
});

describe("pressKey", () => {
  it("presses a named key down then up with its virtual key code and text", async () => {
    const { send, calls } = recorder();
    expect(await pressKey(send, "Enter")).toBe(true);
    expect(calls.map((c) => c.params.type)).toEqual(["keyDown", "keyUp"]);
    expect(calls[0].params).toMatchObject({ key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, text: "\r" });
  });

  it("presses the key the rules judged, however it is spelled", async () => {
    for (const [written, key, vk] of [["Return", "Enter", 13], ["Page_Down", "PageDown", 34], ["Up", "ArrowUp", 38], ["BackSpace", "Backspace", 8]] as const) {
      const { send, calls } = recorder();
      expect(await pressKey(send, written)).toBe(true);
      expect(calls[0].params, written).toMatchObject({ key, windowsVirtualKeyCode: vk });
    }
  });

  it("treats ctrl+letter as a shortcut: rawKeyDown, no text", async () => {
    const { send, calls } = recorder();
    expect(await pressKey(send, "ctrl+a")).toBe(true);
    expect(calls[0].params.type).toBe("rawKeyDown");
    expect(calls[0].params).toMatchObject({ modifiers: 2, key: "a", code: "KeyA", windowsVirtualKeyCode: 65 });
    expect(calls[0].params.text).toBeUndefined();
    expect(calls[0].params.commands).toBeUndefined();
  });

  it("holds the key the model calls super or win as meta", async () => {
    const { send, calls } = recorder();
    await pressKey(send, "super+k");
    expect(calls[0].params.modifiers).toBe(4);
  });

  it("parses several modifiers before the key, and adds the ones given apart", async () => {
    const { send, calls } = recorder();
    await pressKey(send, "cmd+shift+k");
    expect(calls[0].params.modifiers).toBe(4 | 8);
    expect(calls[0].params).toMatchObject({ code: "KeyK", windowsVirtualKeyCode: 75 });
    const second = recorder();
    await pressKey(second.send, "a", ["option"]);
    expect(second.calls[0].params.modifiers).toBe(1);
  });

  it("presses a single printable character, a capital with shift", async () => {
    const { send, calls } = recorder();
    expect(await pressKey(send, "7")).toBe(true);
    expect(calls[0].params).toMatchObject({ type: "keyDown", key: "7", code: "Digit7", text: "7" });
    const shifted = recorder();
    await pressKey(shifted.send, "shift+a");
    expect(shifted.calls[0].params).toMatchObject({ key: "A", text: "A", modifiers: 8 });
  });

  it("on a Mac, sends the editing command a shortcut stands for", async () => {
    vi.stubGlobal("navigator", { platform: "MacIntel" });
    const { send, calls } = recorder();
    await pressKey(send, "cmd+a");
    expect(calls[0].params.commands).toEqual(["selectAll"]);
    const undo = recorder();
    await pressKey(undo.send, "cmd+shift+z");
    expect(undo.calls[0].params.commands).toEqual(["redo"]);
  });

  it("refuses an unknown multi-character key", async () => {
    const { send, calls } = recorder();
    expect(await pressKey(send, "Frobnicate")).toBe(false);
    expect(calls).toHaveLength(0);
  });
});
