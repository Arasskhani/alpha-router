/**
 * @vitest-environment happy-dom
 */
import { afterEach, describe, expect, it, vi } from "vitest";

type Scope = {
  __alpharouter?: {
    version?: number;
    extract: (limits: { maxChars: number; maxSelectionChars: number }) => unknown;
    agent?: (method: unknown, args: unknown) => Promise<{ ok: boolean; elements?: Array<{ ref: string; name: string }> }>;
  };
  __alpharouterAgentState?: unknown;
};

afterEach(() => {
  delete (globalThis as Scope).__alpharouter;
  delete (globalThis as Scope).__alpharouterAgentState;
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

describe("content.js for the agent", () => {
  it("keeps the agent's references from one injection to the next", async () => {
    document.body.innerHTML = "<button>Continue</button>";
    await inject();
    const read = await (globalThis as Scope).__alpharouter!.agent!("read_page", {});
    const ref = read.elements![0].ref;
    await inject();
    await expect((globalThis as Scope).__alpharouter!.agent!("describe", { ref })).resolves.toMatchObject({ ok: true });
  });

  it("does not trust references left in another shape", async () => {
    (globalThis as Scope).__alpharouterAgentState = { format: 0, byRef: "junk" };
    document.body.innerHTML = "<button>Continue</button>";
    await inject();
    await expect((globalThis as Scope).__alpharouter!.agent!("read_page", {})).resolves.toMatchObject({ ok: true });
  });
});
