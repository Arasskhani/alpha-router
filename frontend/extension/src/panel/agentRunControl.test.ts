/**
 * The agent loop under full control: screenshots as images the model reads,
 * and computer actions judged by what is under the point, then carried out
 * through the driver with the visuals in step.
 */
import { describe, expect, it, vi } from "vitest";

import type { PolicyContext } from "../lib/agentPolicy";
import type { PageResult } from "../lib/pageAgent";
import { conversation, runAgent, SCREENSHOTS_KEPT, type AgentBrowser, type AgentDeps, type ApiMessage, type ApprovalRequest, type ControlDriver, type ModelReply } from "./agentRun";
import { agentToolsFor, CONTROL_TOOLS } from "./agentTools";

const RULES: PolicyContext = { policy: { allowed_sites: [], blocked_sites: ["bank.example.com"] }, serverHost: "ai.example.com", ownHosts: ["ai.example.com"] };
const TAB = { id: 1, url: "https://shop.example.com/cart", host: "shop.example.com", title: "Cart" };
const NONCE = "0123456789ab";

function call(name: string, args: Record<string, unknown> = {}) {
  return { id: `call_${name}_${Math.random().toString(36).slice(2, 7)}`, name, arguments: JSON.stringify(args) };
}

/** What sits at each frame point (the driver maps frame → CSS as ×2). */
const AT: Record<string, Record<string, unknown>> = {
  "200,100": { element: { ref: "e1", role: "button", name: "Next", tag: "button" }, rect: { x: 190, y: 90, width: 40, height: 20 } },
  "200,300": { element: { ref: "e2", role: "button", name: "Buy now", tag: "button" }, rect: { x: 190, y: 290, width: 60, height: 20 } },
};

function fakeDriver() {
  const driver = {
    screenshot: vi.fn(async () => ({ dataUrl: "data:image/jpeg;base64,SHOT", frame: { width: 640, height: 360, scale: 0.5 }, css: { width: 1280, height: 720 } })),
    zoom: vi.fn(async () => ({ dataUrl: "data:image/jpeg;base64,ZOOM", frame: { width: 800, height: 400, scale: 4 }, css: { width: 200, height: 100 } })),
    click: vi.fn(async () => undefined),
    hover: vi.fn(async () => undefined),
    scroll: vi.fn(async () => undefined),
    drag: vi.fn(async () => ({ intercepted: true })),
    type: vi.fn(async () => undefined),
    key: vi.fn(async (spec: string) => spec !== "Frobnicate"),
    toCss: vi.fn(async (p: { x: number; y: number }) => ({ x: p.x * 2, y: p.y * 2 })),
  } satisfies ControlDriver;
  return driver;
}

function fakeBrowser(focus?: Record<string, unknown>) {
  const browser = {
    current: vi.fn(async () => TAB),
    listTabs: vi.fn(async () => [{ ...TAB, active: true }]),
    openTab: vi.fn(async (url: string) => ({ id: 3, url, host: new URL(url).hostname, title: "" })),
    switchTab: vi.fn(async () => TAB),
    navigate: vi.fn(async (url: string) => ({ ...TAB, url })),
    page: vi.fn(async (method: string, args: Record<string, unknown> = {}): Promise<PageResult> => {
      if (method === "describe_at") {
        // CSS coords arrive; the fixture is keyed by frame coords (÷2).
        const hit = AT[`${Number(args.x) / 2},${Number(args.y) / 2}`];
        return hit ? { ok: true, ...hit } : { ok: false, error: "not_found", message: "There is nothing to act on at that point." };
      }
      if (method === "describe_focus") return focus ? { ok: true, element: focus } : { ok: true };
      return { ok: true };
    }),
    hasAccess: vi.fn(async () => true),
    settle: vi.fn(async () => undefined),
  } satisfies AgentBrowser;
  return browser;
}

function harness(replies: ModelReply[], opts: { driver?: ControlDriver | null; browser?: ReturnType<typeof fakeBrowser>; approve?: boolean } = {}) {
  const sent: ApiMessage[][] = [];
  const approvals: ApprovalRequest[] = [];
  const browser = opts.browser ?? fakeBrowser();
  const driver = opts.driver === undefined ? fakeDriver() : opts.driver;
  const deps: AgentDeps = {
    model: vi.fn(async (messages: ApiMessage[]) => {
      sent.push(JSON.parse(JSON.stringify(messages)) as ApiMessage[]);
      return replies.shift() ?? { text: "Done.", toolCalls: [] };
    }),
    browser,
    driver,
    approve: vi.fn(async (request: ApprovalRequest) => {
      approvals.push(request);
      return opts.approve ?? true;
    }),
    askUser: vi.fn(async () => ""),
    review: vi.fn(async () => ({ decision: "ask" as const, reason: "Not sure." })),
    report: vi.fn(),
    onStep: vi.fn(),
    onText: vi.fn(),
  };
  const run = () => runAgent({ task: "Go to the next step.", mode: "ask", maxSteps: 10, rules: RULES, runId: "run-1", nonce: NONCE }, deps, new AbortController().signal);
  return { deps, browser, driver, sent, approvals, run };
}

const visualCalls = (browser: ReturnType<typeof fakeBrowser>) => browser.page.mock.calls.filter(([m]) => String(m).startsWith("visuals_")).map(([m, a]) => [m, a]);

describe("the tools a run offers", () => {
  it("adds the control tools only under full control", () => {
    const names = (tools: { function: { name: string } }[]) => tools.map((t) => t.function.name);
    expect(names(agentToolsFor({ fullControl: false }))).not.toContain("computer");
    expect(names(agentToolsFor({ fullControl: true }))).toEqual(expect.arrayContaining(["screenshot", "zoom", "computer", "read_page", "click"]));
    expect(CONTROL_TOOLS.map((t) => t.function.name)).toEqual(["screenshot", "zoom", "computer"]);
  });
});

describe("screenshots", () => {
  it("answers with the frame size and shows the image after the step, then mentions full control in the instructions", async () => {
    const h = harness([{ text: "", toolCalls: [call("screenshot")] }]);
    await h.run();
    expect(h.driver!.screenshot).toHaveBeenCalledTimes(1);
    const second = h.sent[1];
    const tool = second.find((m) => m.role === "tool")!;
    expect(tool.content).toContain("640×360");
    const image = second.find((m) => m.role === "user" && Array.isArray(m.content))!;
    expect(image.content).toEqual([{ type: "text", text: expect.stringContaining("640×360") }, { type: "image_url", image_url: { url: "data:image/jpeg;base64,SHOT" } }]);
    expect(String(second[0].content)).toContain("full control");
  });

  it("is refused without the driver", async () => {
    const h = harness([{ text: "", toolCalls: [call("screenshot")] }], { driver: null });
    await h.run();
    const tool = h.sent[1].find((m) => m.role === "tool")!;
    expect(tool.content).toContain("Full control is not on");
    expect(h.sent[1].some((m) => Array.isArray(m.content))).toBe(false);
    expect(String(h.sent[0][0].content)).not.toContain("full control");
  });

  it("keeps only the latest few in the conversation", () => {
    const shot = (n: number): ApiMessage => ({ role: "user", content: [{ type: "text", text: `shot ${n}` }, { type: "image_url", image_url: { url: `data:${n}` } }] });
    const entries = [
      { message: { role: "system", content: "sys" } as ApiMessage },
      { message: { role: "user", content: "task" } as ApiMessage },
      ...Array.from({ length: SCREENSHOTS_KEPT + 2 }, (_, i) => [
        { message: { role: "assistant", content: null, tool_calls: [{ id: `c${i}`, type: "function" as const, function: { name: "screenshot", arguments: "{}" } }] } as ApiMessage },
        { message: { role: "tool", tool_call_id: `c${i}`, content: "ok" } as ApiMessage },
        { message: shot(i) },
      ]).flat(),
    ];
    const out = conversation(entries);
    const images = out.filter((m) => Array.isArray(m.content) && m.content.some((p) => p.type === "image_url"));
    expect(images).toHaveLength(SCREENSHOTS_KEPT);
    const omitted = out.filter((m) => Array.isArray(m.content) && m.content.some((p) => p.type === "text" && p.text.includes("left out")));
    expect(omitted).toHaveLength(2);
  });

  it("zooms into a region and says its pixels are not page coordinates", async () => {
    const h = harness([{ text: "", toolCalls: [call("zoom", { region: [10, 10, 60, 40] })] }]);
    await h.run();
    expect(h.driver!.zoom).toHaveBeenCalledWith({ x: 10, y: 10, width: 50, height: 30 });
    const image = h.sent[1].find((m) => m.role === "user" && Array.isArray(m.content))!;
    expect(JSON.stringify(image.content)).toContain("not page coordinates");
  });

  it("refuses a nonsense region", async () => {
    const h = harness([{ text: "", toolCalls: [call("zoom", { region: [60, 10, 10, 40] })] }]);
    await h.run();
    expect(h.driver!.zoom).not.toHaveBeenCalled();
    expect(h.sent[1].find((m) => m.role === "tool")!.content).toContain("region");
  });
});

describe("computer actions", () => {
  it("judges a click by the element under the point, asks, then clicks through the driver with the visuals in step", async () => {
    const h = harness([{ text: "", toolCalls: [call("computer", { action: "left_click", coordinate: [200, 100] })] }]);
    await h.run();
    // The point was looked up in CSS pixels (×2) and the click was judged on the button it found.
    expect(h.browser.page).toHaveBeenCalledWith("describe_at", { x: 400, y: 200, activates: true }, TAB, expect.anything());
    expect(h.approvals[0].summary).toContain('button "Next"');
    expect(h.driver!.click).toHaveBeenCalledWith({ x: 200, y: 100 }, { button: "left", clickCount: 1, modifiers: [] });
    const visuals = visualCalls(h.browser);
    expect(visuals).toEqual(
      expect.arrayContaining([
        ["visuals_show", {}],
        ["visuals_target", { rect: { x: 190, y: 90, width: 40, height: 20 } }],
        ["visuals_state", { state: "waiting" }],
        ["visuals_cursor", { x: 400, y: 200, click: "left" }],
        ["visuals_target", { rect: null }],
        ["visuals_hide", {}],
      ]),
    );
    const tool = h.sent[1].find((m) => m.role === "tool")!;
    expect(String(tool.content)).toContain("Clicked at (200, 100)");
  });

  it("a click on a buy button is judged like a ref click: refused outright, naming the button", async () => {
    const h = harness([{ text: "", toolCalls: [call("computer", { action: "left_click", coordinate: [200, 300] })] }]);
    await h.run();
    // Buying is never done, whatever the mode: no approval is even asked for.
    expect(h.approvals).toHaveLength(0);
    expect(h.driver!.click).not.toHaveBeenCalled();
    const tool = h.sent[1].find((m) => m.role === "tool")!;
    expect(String(tool.content)).toMatch(/Refused/);
    expect(String(tool.content)).toContain("Buy now");
  });

  it("a click where nothing is refuses before anything runs", async () => {
    const h = harness([{ text: "", toolCalls: [call("computer", { action: "left_click", coordinate: [5, 5] })] }]);
    await h.run();
    expect(h.driver!.click).not.toHaveBeenCalled();
    expect(String(h.sent[1].find((m) => m.role === "tool")!.content)).toContain("nothing to act on");
  });

  it("typing goes to the focused field and is refused in a secret one", async () => {
    const secret = { ref: "e9", role: "textbox", name: "Password", tag: "input", type: "password", sensitive: true };
    const h = harness([{ text: "", toolCalls: [call("computer", { action: "type", text: "hunter2" })] }], { browser: fakeBrowser(secret) });
    await h.run();
    expect(h.driver!.type).not.toHaveBeenCalled();
    expect(h.sent[1].find((m) => m.role === "tool")!.content).toMatch(/Refused/);
  });

  it("typing into an ordinary field asks, then types through the driver", async () => {
    const field = { ref: "e3", role: "textbox", name: "Coupon", tag: "input" };
    const h = harness([{ text: "", toolCalls: [call("computer", { action: "type", text: "SAVE10" })] }], { browser: fakeBrowser(field) });
    await h.run();
    expect(h.approvals[0].summary).toContain("Coupon");
    expect(h.driver!.type).toHaveBeenCalledWith("SAVE10");
  });

  it("a key press goes to the focused element; Enter in a message box is sensitive", async () => {
    const box = { ref: "e7", role: "textbox", name: "Message", tag: "textarea" };
    const h = harness([{ text: "", toolCalls: [call("computer", { action: "key", text: "Enter" })] }], { browser: fakeBrowser(box), approve: false });
    await h.run();
    expect(h.approvals[0].verdict.class).toBe("sensitive");
    expect(h.driver!.key).not.toHaveBeenCalled();
  });

  it("an unknown key is reported, and scroll and hover are reads that need no approval", async () => {
    const h = harness([
      {
        text: "",
        toolCalls: [
          call("computer", { action: "scroll", coordinate: [200, 100], scroll_direction: "down", scroll_amount: 2 }),
          call("computer", { action: "hover", coordinate: [200, 100] }),
          call("computer", { action: "key", text: "Frobnicate" }),
        ],
      },
    ]);
    await h.run();
    expect(h.approvals).toHaveLength(1); // only the key press asked
    expect(h.driver!.scroll).toHaveBeenCalledWith({ x: 200, y: 100 }, { y: 200 });
    expect(h.driver!.hover).toHaveBeenCalledWith({ x: 200, y: 100 }, []);
    const tools = h.sent[1].filter((m) => m.role === "tool");
    expect(String(tools[2].content)).toContain("cannot press");
  });

  it("a drag is judged on what it picks up", async () => {
    const h = harness([{ text: "", toolCalls: [call("computer", { action: "left_click_drag", start_coordinate: [200, 100], coordinate: [300, 100] })] }]);
    await h.run();
    expect(h.approvals[0].summary).toContain("Drag");
    expect(h.driver!.drag).toHaveBeenCalledWith({ x: 200, y: 100 }, { x: 300, y: 100 });
  });

  it("without the driver a computer call is refused and nothing is looked up", async () => {
    const h = harness([{ text: "", toolCalls: [call("computer", { action: "left_click", coordinate: [200, 100] })] }], { driver: null });
    await h.run();
    expect(h.browser.page).not.toHaveBeenCalledWith("describe_at", expect.anything(), expect.anything(), expect.anything());
    expect(h.sent[1].find((m) => m.role === "tool")!.content).toMatch(/Refused|not on/);
  });
});
