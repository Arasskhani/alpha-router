import { describe, expect, it, vi } from "vitest";

import type { Send } from "./input";
import { insertText, namedKey, pressKey } from "./keys";

function recorder() {
  const calls: Array<{ method: string; params: Record<string, unknown> }> = [];
  const send: Send = vi.fn(async (method, params = {}) => {
    calls.push({ method, params });
    return undefined;
  });
  return { send, calls };
}

describe("namedKey", () => {
  it("matches case-insensitively and rejects the unknown", () => {
    expect(namedKey("Enter")?.vk).toBe(13);
    expect(namedKey("arrowdown")?.code).toBe("ArrowDown");
    expect(namedKey("nope")).toBeNull();
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

  it("treats ctrl+letter as a shortcut: rawKeyDown, no text", async () => {
    const { send, calls } = recorder();
    expect(await pressKey(send, "ctrl+a")).toBe(true);
    expect(calls[0].params.type).toBe("rawKeyDown");
    expect(calls[0].params).toMatchObject({ modifiers: 2, key: "a", code: "KeyA", windowsVirtualKeyCode: 65 });
    expect(calls[0].params.text).toBeUndefined();
  });

  it("parses several modifiers before the key", async () => {
    const { send, calls } = recorder();
    await pressKey(send, "cmd+shift+k");
    expect(calls[0].params.modifiers).toBe(4 | 8);
    expect(calls[0].params).toMatchObject({ code: "KeyK", windowsVirtualKeyCode: 75 });
  });

  it("presses a single printable character", async () => {
    const { send, calls } = recorder();
    expect(await pressKey(send, "7")).toBe(true);
    expect(calls[0].params).toMatchObject({ type: "keyDown", key: "7", code: "Digit7", text: "7" });
  });

  it("refuses an unknown multi-character key", async () => {
    const { send, calls } = recorder();
    expect(await pressKey(send, "Frobnicate")).toBe(false);
    expect(calls).toHaveLength(0);
  });
});
