/**
 * The agent loop while the person has taken over: it waits at its safe
 * points, tells the page and the badge, sends nothing to a page that is
 * paused, and goes on - or stops - as the person decides.
 */
import { describe, expect, it, vi } from "vitest";

import type { PolicyContext } from "../lib/agentPolicy";
import type { PageResult } from "../lib/pageAgent";
import { runAgent, type AgentBrowser, type AgentDeps, type ControlDriver, type ModelReply, type RunState, type StepView } from "./agentRun";
import { createPauseGate } from "./pauseGate";

const RULES: PolicyContext = { policy: { allowed_sites: [], blocked_sites: [] }, serverHost: "ai.example.com", ownHosts: ["ai.example.com"] };
const TAB = { id: 1, url: "https://shop.example.com/cart", host: "shop.example.com", title: "Cart" };
const NEXT = { element: { ref: "e1", role: "button", name: "Next", tag: "button" }, rect: { x: 190, y: 90, width: 40, height: 20 } };

function call(name: string, args: Record<string, unknown> = {}) {
  return { id: `call_${name}_${Math.random().toString(36).slice(2, 7)}`, name, arguments: JSON.stringify(args) };
}

const click = () => ({ text: "", toolCalls: [call("computer", { action: "left_click", coordinate: [200, 100] })] });
const done = () => ({ text: "", toolCalls: [call("done", { summary: "ok" })] });

function fakeDriver(): ControlDriver {
  return {
    screenshot: vi.fn(async () => ({ dataUrl: "data:image/jpeg;base64,SHOT", frame: { width: 640, height: 360, scale: 0.5 }, css: { width: 1280, height: 720 } })),
    zoom: vi.fn(async () => ({ dataUrl: "data:image/jpeg;base64,ZOOM", frame: { width: 800, height: 400, scale: 4 }, css: { width: 200, height: 100 } })),
    crop: vi.fn(async () => ({ dataUrl: "data:image/jpeg;base64,CROP", frame: { width: 176, height: 136, scale: 2 }, css: { width: 88, height: 68 } })),
    click: vi.fn(async () => undefined),
    clickAt: vi.fn(async () => undefined),
    hover: vi.fn(async () => undefined),
    scroll: vi.fn(async () => undefined),
    drag: vi.fn(async () => ({ intercepted: true })),
    type: vi.fn(async () => undefined),
    key: vi.fn(async () => true),
    toCss: vi.fn(async (p: { x: number; y: number }) => ({ x: p.x * 2, y: p.y * 2 })),
    onDialog: vi.fn(),
    handleDialog: vi.fn(async () => undefined),
  };
}

/** The page: paused or not when the panel asks to send input; everything else just works. */
function fakeBrowser(pausedOnDispatch: () => boolean = () => false, dom: Partial<Record<string, PageResult>> = {}) {
  const browser = {
    current: vi.fn(async () => TAB),
    listTabs: vi.fn(async () => [{ ...TAB, active: true }]),
    openTab: vi.fn(async (url: string) => ({ id: 3, url, host: new URL(url).hostname, title: "" })),
    switchTab: vi.fn(async () => TAB),
    navigate: vi.fn(async (url: string) => ({ ...TAB, url })),
    page: vi.fn(async (method: string, args: Record<string, unknown> = {}): Promise<PageResult> => {
      if (method === "describe_at") return { ok: true, ...NEXT };
      if (method === "describe_focus") return { ok: true, element: { ref: "e3", role: "textbox", name: "Coupon", tag: "input" } };
      if (method === "takeover_dispatch") return { ok: true, paused: args.on === true && pausedOnDispatch() };
      if (method in dom) return dom[method]!;
      if (method === "describe") return { ok: true, element: NEXT.element };
      return { ok: true, note: "Done." };
    }),
    hasAccess: vi.fn(async () => true),
    settle: vi.fn(async () => undefined),
  } satisfies AgentBrowser;
  return browser;
}

function harness(replies: ModelReply[], opts: { browser?: ReturnType<typeof fakeBrowser>; driver?: ControlDriver | null; mode?: "ask" | "auto" } = {}) {
  const abort = new AbortController();
  const gate = createPauseGate(abort.signal);
  const browser = opts.browser ?? fakeBrowser();
  const driver = opts.driver === undefined ? fakeDriver() : opts.driver;
  const states: RunState[] = [];
  const steps: StepView[] = [];
  let modelCalls = 0;
  const deps: AgentDeps = {
    model: vi.fn(async () => {
      modelCalls += 1;
      return replies.shift() ?? { text: "Done.", toolCalls: [] };
    }),
    browser,
    driver,
    pause: gate,
    onState: (state) => states.push(state),
    approve: vi.fn(async () => true),
    askUser: vi.fn(async () => ""),
    review: vi.fn(async () => ({ decision: "allow" as const, reason: "" })),
    report: vi.fn(),
    onStep: (step) => steps.push(step),
    onText: vi.fn(),
  };
  const run = () => runAgent({ task: "Go on.", mode: opts.mode ?? "auto", maxSteps: 20, rules: RULES, runId: "run-1", nonce: "0123456789ab" }, deps, abort.signal);
  return { deps, browser, driver, gate, abort, states, steps, run, modelCalls: () => modelCalls };
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const stateCalls = (browser: ReturnType<typeof fakeBrowser>) => browser.page.mock.calls.filter(([m]) => m === "visuals_state").map(([, a]) => (a as { state: string }).state);
const dispatchCalls = (browser: ReturnType<typeof fakeBrowser>) => browser.page.mock.calls.filter(([m]) => m === "takeover_dispatch").map(([, a]) => (a as { on: boolean }).on);

describe("a paused run", () => {
  it("waits before asking the model again, shows paused on the page and the badge, and goes on when resumed", async () => {
    const h = harness([click(), done()]);
    // Paused before the run starts: it waits at its first safe point.
    h.gate.pause();
    const finished = h.run();
    await tick();
    await tick();
    expect(h.modelCalls()).toBe(0);
    expect(h.states).toEqual(["working", "paused"]);
    expect(stateCalls(h.browser)).toEqual(["working", "paused"]);
    h.gate.resume();
    const result = await finished;
    expect(result.outcome).toBe("done");
    expect(h.states.slice(0, 3)).toEqual(["working", "paused", "working"]);
    expect((h.driver as ReturnType<typeof fakeDriver>).click).toHaveBeenCalledTimes(1);
  });

  it("waits again right before the press, once the action was allowed, and judges the point again after", async () => {
    let looks = 0;
    const browser = fakeBrowser();
    const h = harness([click(), done()], { browser });
    // Take over while the action is being judged: the first describe_at is the judgment, and it pauses then.
    browser.page.mockImplementation(async (method: string) => {
      if (method === "describe_at") {
        looks += 1;
        if (looks === 1) h.gate.pause();
        return { ok: true, ...NEXT };
      }
      if (method === "takeover_dispatch") return { ok: true, paused: false };
      return { ok: true, note: "Done." };
    });
    const finished = h.run();
    await tick();
    await tick();
    await tick();
    expect((h.driver as ReturnType<typeof fakeDriver>).click).not.toHaveBeenCalled();
    expect(looks).toBe(1);
    h.gate.resume();
    await finished;
    // Judged a second time only after the resume: the page may have changed under the person.
    expect(looks).toBe(2);
    expect((h.driver as ReturnType<typeof fakeDriver>).click).toHaveBeenCalledTimes(1);
  });

  it("ends as stopped when the person stops it instead of resuming", async () => {
    const h = harness([click(), done()]);
    h.gate.pause();
    const finished = h.run();
    await tick();
    h.abort.abort();
    const result = await finished;
    expect(result.outcome).toBe("stopped");
    expect((h.driver as ReturnType<typeof fakeDriver>).click).not.toHaveBeenCalled();
  });
});

describe("the administrator's limits on a run", () => {
  it("ends the run at its time limit, before the next model call", async () => {
    const h = harness([click(), click(), done()]);
    vi.useFakeTimers({ now: 1_000_000 });
    try {
      // Time passes while the model answers the second step.
      (h.deps.model as ReturnType<typeof vi.fn>).mockImplementation(async () => {
        vi.setSystemTime(Date.now() + 4 * 60_000);
        return [click(), click(), done()][h.modelCalls()] ?? { text: "Done.", toolCalls: [] };
      });
      const result = await runAgent(
        { task: "Go on.", mode: "auto", maxSteps: 20, maxMinutes: 5, rules: RULES, runId: "run-1", nonce: "0123456789ab" },
        h.deps,
        h.abort.signal,
      );
      expect(result.outcome).toBe("max_minutes");
      expect(result.summary).toContain("5 minutes");
      expect(result.steps).toBe(2);
      expect((h.deps.report as ReturnType<typeof vi.fn>).mock.calls.at(-1)?.[0]).toMatchObject({ kind: "agent_task", outcome: "max_minutes" });
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps only as many screenshots as the administrator allows", async () => {
    const shot = () => ({ text: "", toolCalls: [call("screenshot")] });
    const h = harness([shot(), shot(), shot(), done()]);
    const sent: number[] = [];
    (h.deps.model as ReturnType<typeof vi.fn>).mockImplementation(async (messages: Array<{ content: unknown }>) => {
      sent.push(messages.filter((m) => Array.isArray(m.content) && m.content.some((p: { type: string }) => p.type === "image_url")).length);
      return [shot(), shot(), shot(), done()][sent.length - 1] ?? { text: "Done.", toolCalls: [] };
    });
    await runAgent(
      { task: "Look.", mode: "auto", maxSteps: 20, screenshotsKept: 1, rules: RULES, runId: "run-1", nonce: "0123456789ab" },
      h.deps,
      h.abort.signal,
    );
    // Three screenshots were taken; the model only ever sees the latest one.
    expect(sent).toEqual([0, 1, 1, 1]);
  });

  it("tells the model when the browser would not open a tab, and goes on", async () => {
    const browser = fakeBrowser();
    browser.openTab.mockRejectedValue(new Error("This run may open at most 2 tabs. Work in the tabs you have, or switch to one."));
    const h = harness([{ text: "", toolCalls: [call("tab_open", { url: "https://partner.org/" })] }, done()], { browser, mode: "ask" });
    const result = await h.run();
    expect(result.outcome).toBe("done");
    // The step goes waiting (the site asks), running, then error: the last word is what the model was told.
    const last = h.steps.filter((step) => step.tool === "tab_open").at(-1);
    expect(last?.status).toBe("error");
    expect(last?.detail).toContain("at most 2 tabs");
  });
});

describe("the agent's own input", () => {
  it("goes out inside a window the page knows about, opened before and closed after", async () => {
    const h = harness([click(), { text: "", toolCalls: [call("computer", { action: "type", text: "hi" })] }, done()]);
    await h.run();
    expect(dispatchCalls(h.browser)).toEqual([true, false, true, false]);
  });

  it("closes the window even when the input fails", async () => {
    const h = harness([{ text: "", toolCalls: [call("computer", { action: "type", text: "hi" })] }, done()]);
    (h.driver as ReturnType<typeof fakeDriver>).type = vi.fn(async () => {
      throw new Error("the page went away");
    });
    const result = await h.run();
    // The model is told the input failed, and the run goes on to its end.
    expect(result.outcome).toBe("done");
    expect(dispatchCalls(h.browser)).toEqual([true, false]);
  });

  it("is not sent to a page the person has just taken over, and that is not a failure of the agent's", async () => {
    // The take-over reached the page before the panel heard of it: the first time the panel asks to send, the page says paused.
    let asked = 0;
    const h = harness([click(), click(), done()], { browser: fakeBrowser(() => (asked += 1) === 1) });
    const result = await h.run();
    expect(result.outcome).toBe("done");
    const driver = h.driver as ReturnType<typeof fakeDriver>;
    expect(driver.click).toHaveBeenCalledTimes(1);
    const skipped = h.steps.find((step) => step.status === "skipped");
    expect(skipped?.detail).toBe("The user took over");
    expect(h.steps.some((step) => step.status === "error")).toBe(false);
    // The window that was refused is not closed (it never opened); the next one opens and closes.
    expect(dispatchCalls(h.browser)).toEqual([true, true, false]);
  });

  it("without full control, a page that answers paused is not a failure either", async () => {
    const browser = fakeBrowser(() => false, { click: { ok: false, error: "paused", message: "The user took over this page." } });
    const h = harness([{ text: "", toolCalls: [call("click", { ref: "e1" })] }, done()], { browser, driver: null, mode: "ask" });
    const result = await h.run();
    expect(result.outcome).toBe("done");
    expect(h.steps.find((step) => step.status === "skipped")?.detail).toBe("The user took over");
    expect(h.steps.some((step) => step.status === "error")).toBe(false);
  });
});

describe("what a step keeps for the saved run", () => {
  it("has the length of what was typed, never the text", async () => {
    const { keptSummary } = await import("./agentRun");
    expect(keptSummary("type_text", { ref: "e3", text: "SAVE10" }, 'Type "SAVE10" into "Coupon"')).toBe('Type 6 characters into "Coupon"');
    expect(keptSummary("computer", { action: "type", text: "hello" }, 'Type "hello" into "Name"')).toBe('Type 5 characters into "Name"');
    // A summary that does not carry the text as shown still says only how much was typed.
    expect(keptSummary("type_text", { text: "secret" }, "Typed something")).toBe("Type 6 characters");
    expect(keptSummary("click", { ref: "e1" }, 'Click "Next"')).toBeUndefined();
    expect(keptSummary("computer", { action: "left_click" }, "Click at (1, 2)")).toBeUndefined();
  });

  it("reaches the panel with the step", async () => {
    const h = harness([{ text: "", toolCalls: [call("computer", { action: "type", text: "hi there" })] }, done()]);
    await h.run();
    const typed = h.steps.filter((step) => step.tool === "computer").at(-1);
    expect(typed?.summary).toContain('"hi there"');
    expect(typed?.kept).toBe('Type 8 characters into textbox "Coupon"');
    expect(typed?.kept).not.toContain("hi there");
  });
});
