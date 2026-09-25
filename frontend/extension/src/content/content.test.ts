/**
 * @vitest-environment happy-dom
 */
import { afterEach, describe, expect, it, vi } from "vitest";

type Scope = { __alpharouter?: { version?: number; extract: (limits: { maxChars: number; maxSelectionChars: number }) => unknown } };

afterEach(() => {
  delete (globalThis as Scope).__alpharouter;
  document.body.innerHTML = "";
});

async function inject() {
  vi.resetModules();
  await import("./content");
}

describe("content.js", () => {
  it("replaces whatever copy is already in the page, even one of the same shape", async () => {
    const stale = vi.fn(() => ({ text: "from an old copy" }));
    (globalThis as Scope).__alpharouter = { version: 2, extract: stale };
    await inject();
    const api = (globalThis as Scope).__alpharouter!;
    expect(api.extract).not.toBe(stale);
    document.body.innerHTML = "<p>Fresh text.</p>";
    expect(api.extract({ maxChars: 100, maxSelectionChars: 10 })).toMatchObject({ text: "Fresh text." });
    expect(stale).not.toHaveBeenCalled();
  });
});
