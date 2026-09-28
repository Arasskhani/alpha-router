/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setClient } from "../lib/client";
import { resetConfigForTests } from "../lib/config";
import { layoutMetrics } from "../test/cdpFixtures";
import { installChromeFake, EXTENSION_ID, type ChromeFake } from "../test/chromeFake";
import { SERVER, createServerFake, frame, json, sse, type ServerFake } from "../test/serverFake";
import AgentView, { agentModels } from "./AgentView";
import type { Me } from "./types";

const ME: Me = {
  user: { username: "majid", display_name: "Majid A.", email: "m@example.com" },
  server: { name: "Alpharouter", url: SERVER },
  extension: { latest_version: "1.0.0.1", min_version: "1.0.0.0" },
  features: { chat: true, page_context: true, agent: true, auto_mode: false, private_mode: false },
  policy: { site_access: "per_site", allowed_sites: [], blocked_sites: [], page_content_models: [], agent_models: [], agent_max_steps: 25 },
};

const MODELS = [
  { id: "model::1", name: "Agent Model", kinds: ["text"], default_kinds: ["chat"] },
  { id: "model::2", name: "Other Model", kinds: ["text"] },
  { id: "model::3", name: "Image Only", kinds: ["image"] },
];

const OUTLINE = 'Page: Cart\nURL: https://shop.example.com/cart\n\n[e1] button "Next"';
const ELEMENTS = { e1: { ref: "e1", role: "button", name: "Next", tag: "button" } };

let server: ServerFake;
let chromeFake: ChromeFake;
let host: HTMLDivElement;
let root: Root;
let replies: string[][];
let tabId: number;
const pageCalls: Array<{ method: string; args: Record<string, unknown>; banner?: { run: string; label: string } | null }> = [];
const onDisconnected = vi.fn();

/** A step's answer as the server streams it: the calls, why the model finished, and [DONE]. */
function toolFrame(calls: Array<{ id: string; name: string; args?: Record<string, unknown> }>): string[] {
  return [
    ...calls.map((c, index) =>
      frame({ choices: [{ delta: { tool_calls: [{ index, id: c.id, type: "function", function: { name: c.name, arguments: JSON.stringify(c.args ?? {}) } }] } }] }),
    ),
    frame({ choices: [{ delta: {}, finish_reason: "tool_calls" }] }),
    "data: [DONE]\n\n",
  ];
}

beforeEach(() => {
  chromeFake = installChromeFake({ version: "1.0.0.1" });
  resetConfigForTests();
  server = createServerFake();
  server.routes["GET /api/chat/models"] = () => json(200, MODELS);
  server.routes["POST /api/extension/events"] = () => json(200, { recorded: 1 });
  server.routes["POST /api/extension/runs"] = () => json(200, { chat_id: "chat-run-1" });
  replies = [];
  server.routes["POST /api/chat/completions"] = (init) => sse(replies.shift() ?? toolFrame([{ id: "end", name: "done", args: { summary: "Done." } }]), { signal: init.signal }).response;
  const tab = chromeFake.tabs.add({ url: "https://shop.example.com/cart", title: "Cart", active: true });
  tabId = tab.id!;
  chromeFake.permissions.granted.add("https://shop.example.com/*");
  pageCalls.length = 0;
  chromeFake.scripting.executeScript.mockImplementation(async (injection: unknown) => {
    const { files, args } = injection as { files?: string[]; args?: [string, string, Record<string, unknown>, { run: string; label: string } | null] };
    if (files) return [];
    const [, method, input, banner] = args!;
    pageCalls.push({ method, args: input, banner });
    if (method === "read_page") return [{ result: { ok: true, outline: OUTLINE, elements: Object.values(ELEMENTS), truncated: false, url: "", title: "" } }];
    if (method === "describe") return [{ result: { ok: true, element: ELEMENTS[input.ref as "e1"] } }];
    return [{ result: { ok: true, note: "Done." } }];
  });
  onDisconnected.mockReset();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  setClient(null);
  vi.unstubAllGlobals();
});

async function render(me: Me = ME) {
  await act(async () => {
    root.render(<AgentView me={me} server={SERVER} onDisconnected={onDisconnected} />);
  });
  await act(async () => undefined);
}

function button(label: string): HTMLButtonElement {
  const found = [...host.querySelectorAll("button")].find((b) => b.textContent === label || b.getAttribute("aria-label") === label);
  if (!found) throw new Error(`no ${label} button in: ${host.textContent}`);
  return found;
}

async function start(task: string) {
  const box = host.querySelector('textarea[aria-label="Task"]') as HTMLTextAreaElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(box, task);
    box.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => button("Start").click());
}

async function until(check: () => boolean, what: string) {
  for (let i = 0; i < 200; i += 1) {
    if (check()) return;
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
  }
  throw new Error(`timed out waiting for ${what}: ${host.textContent}`);
}

describe("the agent's models", () => {
  it("are the text models within both of the administrator's lists", () => {
    const me = { ...ME, policy: { ...ME.policy!, agent_models: ["model::1", "model::2"], page_content_models: ["model::2", "model::3"] } };
    expect(agentModels(MODELS, me).map((m) => m.id)).toEqual(["model::2"]);
    expect(agentModels(MODELS, ME).map((m) => m.id)).toEqual(["model::1", "model::2"]);
  });

  it("offers Ask and Plan always, and Auto only when the administrator turned it on", async () => {
    await render();
    expect([...host.querySelectorAll('[role="radio"]')].map((b) => b.textContent)).toEqual(["Ask", "Plan"]);
    act(() => root.unmount());
    root = createRoot(host);
    await render({ ...ME, features: { ...ME.features, auto_mode: true } });
    expect([...host.querySelectorAll('[role="radio"]')].map((b) => b.textContent)).toEqual(["Ask", "Plan", "Auto"]);
  });

  it("offers only the modes the administrator left on, and starts in the one they chose", async () => {
    await render({ ...ME, policy: { ...ME.policy!, agent_modes: ["ask"], agent_default_mode: "ask" } });
    expect([...host.querySelectorAll('[role="radio"]')].map((b) => b.textContent)).toEqual(["Ask"]);
    act(() => root.unmount());
    root = createRoot(host);
    await render({ ...ME, policy: { ...ME.policy!, agent_modes: ["ask", "plan"], agent_default_mode: "plan" } });
    const on = [...host.querySelectorAll('[role="radio"]')].find((b) => b.getAttribute("aria-checked") === "true");
    expect(on?.textContent).toBe("Plan");
  });

  it("offers the plan tool to the model when Plan mode is chosen", async () => {
    replies = [toolFrame([{ id: "c1", name: "done", args: { summary: "ok" } }])];
    await render();
    await act(async () => [...host.querySelectorAll('[role="radio"]')].find((b) => b.textContent === "Plan")!.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    await start("Do a thing.");
    await until(() => host.textContent!.includes("ok"), "the summary");
    const body = server.calls.filter((c) => c.path === "/api/chat/completions").at(-1)!.body as { browser_tools: { function: { name: string } }[] };
    expect(body.browser_tools.map((t) => t.function.name)).toContain("update_plan");
  });
});

describe("a run", () => {
  it("reads, asks before clicking, and finishes", async () => {
    replies = [toolFrame([{ id: "c1", name: "read_page" }]), toolFrame([{ id: "c2", name: "click", args: { ref: "e1" } }]), toolFrame([{ id: "c3", name: "done", args: { summary: "Moved to the next step." } }])];
    await render();
    await start("Go to the next step.");
    await until(() => Boolean(host.querySelector('[role="alertdialog"]')), "the approval card");
    expect(host.textContent).toContain('Click "Next"');
    expect(pageCalls.some((c) => c.method === "click")).toBe(false);
    await act(async () => button("Allow").click());
    await until(() => host.textContent!.includes("Moved to the next step."), "the summary");
    expect(host.textContent).toContain("Finished");
    expect(pageCalls.filter((c) => c.method === "click")).toEqual([{ method: "click", args: { ref: "e1" }, banner: expect.objectContaining({ run: expect.any(String) }) }]);
    // Each step stands alone: never saved to a chat, never tied to an assistant message.
    const bodies = server.calls.filter((c) => c.path === "/api/chat/completions").map((c) => c.body as Record<string, unknown>);
    expect(bodies).toHaveLength(3);
    for (const body of bodies) {
      expect(body).toMatchObject({ model: "model::1", stream: true, browser_tool_choice: "auto" });
      expect(Array.isArray(body.browser_tools)).toBe(true);
      expect(body).not.toHaveProperty("assistant_client_message_id");
      expect(body).not.toHaveProperty("persist_chat");
      expect(body).not.toHaveProperty("chat_session_id");
      expect(body).not.toHaveProperty("private_mode");
    }
    // The banner went up with each action on the page, and came down at the end.
    expect(pageCalls.filter((c) => c.method !== "hide_overlay").every((c) => c.banner?.run)).toBe(true);
    expect(pageCalls.at(-1)?.method).toBe("hide_overlay");
    // The trail reached the server.
    const events = server.calls.filter((c) => c.path === "/api/extension/events").flatMap((c) => (c.body as { events: unknown[] }).events);
    expect(events).toEqual(expect.arrayContaining([expect.objectContaining({ kind: "agent_step", action: "click" }), expect.objectContaining({ kind: "agent_task", outcome: "done" })]));
  });

  it("does not act when the user denies", async () => {
    replies = [toolFrame([{ id: "c1", name: "click", args: { ref: "e1" } }]), toolFrame([{ id: "c2", name: "done", args: { summary: "The user said no." } }])];
    await render();
    await start("Click next.");
    await until(() => Boolean(host.querySelector('[role="alertdialog"]')), "the approval card");
    await act(async () => button("Deny").click());
    await until(() => host.textContent!.includes("The user said no."), "the summary");
    expect(host.querySelector('[data-step-status="denied"]')).not.toBeNull();
    expect(pageCalls.some((c) => c.method === "click")).toBe(false);
  });

  it("stops with Stop, and with the Stop on the page's banner - from our script in that tab only", async () => {
    replies = [toolFrame([{ id: "c1", name: "click", args: { ref: "e1" } }])];
    await render();
    await start("Click next.");
    await until(() => Boolean(host.querySelector('[role="alertdialog"]')), "the approval card");
    // A Stop from another tab, or for another run, is not this run's.
    const run = pageCalls.find((c) => c.banner)?.banner?.run ?? "";
    await act(async () => {
      chromeFake.runtime.deliver({ type: "agent-stop", run }, { url: "https://evil.example.net/", tab: { id: 999 } as chrome.tabs.Tab });
      chromeFake.runtime.deliver({ type: "agent-stop", run: "run-other" }, { url: "https://shop.example.com/cart", tab: { id: tabId } as chrome.tabs.Tab });
    });
    expect(host.querySelector('[role="alertdialog"]')).not.toBeNull();
    await act(async () => {
      chromeFake.runtime.deliver({ type: "agent-stop", run }, { id: EXTENSION_ID, url: "https://shop.example.com/cart", tab: { id: tabId } as chrome.tabs.Tab });
    });
    await until(() => host.textContent!.includes("Stopped"), "the run to stop");
    expect(pageCalls.some((c) => c.method === "click")).toBe(false);
  });

  /**
   * A run that read the page (its banner is up there) and now waits on the
   * model for its second step; `finish` has the model answer with a second
   * read, after which the third step ends the run.
   */
  async function pageReadThenModelBusy(): Promise<{ run: string; finish: () => void }> {
    let stream: ReturnType<typeof sse> | null = null;
    let steps = 0;
    server.routes["POST /api/chat/completions"] = (init) => {
      steps += 1;
      if (steps === 1) return sse(toolFrame([{ id: "c1", name: "read_page" }]), { signal: init.signal }).response;
      if (steps > 2) return sse(toolFrame([{ id: "end", name: "done", args: { summary: "Done." } }]), { signal: init.signal }).response;
      stream = sse([], { open: true, signal: init.signal });
      return stream.response;
    };
    await render();
    await start("Wait for it.");
    await until(() => Boolean(stream), "the second step");
    const finish = () => {
      for (const frame of toolFrame([{ id: "c2", name: "read_page" }])) stream!.push(frame);
      stream!.finish();
    };
    return { run: pageCalls.find((c) => c.banner)?.banner?.run ?? "", finish };
  }

  it("pauses when the person takes over the page, and goes on from Resume in the panel", async () => {
    const { run, finish } = await pageReadThenModelBusy();
    expect(chromeFake.action.badge).toMatchObject({ text: "\u25CF", color: "#2eaadc" });
    // From another tab, or another run: not this run's.
    await act(async () => {
      chromeFake.runtime.deliver({ type: "agent-takeover", run }, { id: EXTENSION_ID, url: "https://evil.example.net/", tab: { id: 999 } as chrome.tabs.Tab });
      chromeFake.runtime.deliver({ type: "agent-takeover", run: "run-other" }, { id: EXTENSION_ID, url: "https://shop.example.com/cart", tab: { id: tabId } as chrome.tabs.Tab });
    });
    expect(host.textContent).not.toContain("You took over");
    await act(async () => {
      chromeFake.runtime.deliver({ type: "agent-takeover", run }, { id: EXTENSION_ID, url: "https://shop.example.com/cart", tab: { id: tabId } as chrome.tabs.Tab });
    });
    await until(() => host.textContent!.includes("You took over"), "the paused card");
    // The model's answer arrives while paused: the run waits before its next action, and the badge shows the pause.
    await act(async () => finish());
    await until(() => chromeFake.action.badge.color === "#969696", "the grey badge");
    expect(pageCalls.filter((c) => c.method === "read_page")).toHaveLength(1);
    await act(async () => button("Resume").click());
    await until(() => !host.textContent!.includes("You took over"), "the card to go");
    // The page was told first, then the run went on: the second read, and the end.
    expect(pageCalls.some((c) => c.method === "takeover_resume" && c.args.run === run)).toBe(true);
    await until(() => host.textContent!.includes("Done."), "the run to finish");
    expect(pageCalls.filter((c) => c.method === "read_page")).toHaveLength(2);
    expect(chromeFake.action.badge.text).toBe("");
  });

  it("goes on when the page's banner says Resume, from our script in that tab only", async () => {
    const { run, finish } = await pageReadThenModelBusy();
    const from = { id: EXTENSION_ID, url: "https://shop.example.com/cart", tab: { id: tabId } as chrome.tabs.Tab };
    await act(async () => chromeFake.runtime.deliver({ type: "agent-takeover", run }, from));
    await until(() => host.textContent!.includes("You took over"), "the paused card");
    await act(async () => chromeFake.runtime.deliver({ type: "agent-resume", run }, { url: "https://evil.example.net/", tab: { id: 999 } as chrome.tabs.Tab }));
    expect(host.textContent).toContain("You took over");
    await act(async () => chromeFake.runtime.deliver({ type: "agent-resume", run }, from));
    await until(() => !host.textContent!.includes("You took over"), "the card to go");
    // The page resumed itself: the panel does not tell it again.
    expect(pageCalls.some((c) => c.method === "takeover_resume")).toBe(false);
    await act(async () => finish());
    await until(() => host.textContent!.includes("Done"), "the run to finish");
  });

  it("stops at once from a card: the card goes, and the step it asked about says it was stopped", async () => {
    replies = [toolFrame([{ id: "c1", name: "click", args: { ref: "e1" } }])];
    await render();
    await start("Click next.");
    await until(() => Boolean(host.querySelector('[role="alertdialog"]')), "the approval card");
    await act(async () => button("Stop").click());
    await until(() => host.textContent!.includes("Stopped"), "the run to stop");
    expect(host.querySelector('[role="alertdialog"]')).toBeNull();
    expect(host.querySelector('[data-step-status="waiting"]')).toBeNull();
    expect(host.querySelector('[data-step-status="stopped"]')).not.toBeNull();
    expect(button("Start")).toBeTruthy();
  });

  it("shows the model thinking, with its words as they come, until the step's answer is in", async () => {
    let stream: ReturnType<typeof sse> | null = null;
    server.routes["POST /api/chat/completions"] = (init) => {
      if (stream) return sse(toolFrame([{ id: "end", name: "done", args: { summary: "Done." } }]), { signal: init.signal }).response;
      stream = sse([], { open: true, signal: init.signal });
      return stream.response;
    };
    await render();
    await start("Wait for it.");
    await until(() => Boolean(stream), "the first step");
    await until(() => host.textContent!.includes("Thinking… (Agent Model, "), "the thinking line");
    await act(async () => stream!.push(frame({ choices: [{ delta: { content: "Looking at the page" } }] })));
    await until(() => host.querySelector(".agent__thinking-text")?.textContent === "Looking at the page", "the model's words so far");
    await act(async () => {
      for (const f of toolFrame([{ id: "c1", name: "read_page" }])) stream!.push(f);
      stream!.finish();
    });
    await until(() => host.textContent!.includes("Finished"), "the run to end");
    expect(host.querySelector(".agent__thinking")).toBeNull();
  });

  it("stops with the panel's Stop while the model is still answering", async () => {
    let finish: (() => void) | null = null;
    server.routes["POST /api/chat/completions"] = (init) => {
      const stream = sse([], { open: true, signal: init.signal });
      finish = stream.finish;
      return stream.response;
    };
    await render();
    await start("Wait for it.");
    await until(() => Boolean(finish), "the first step");
    await act(async () => button("Stop").click());
    await until(() => host.textContent!.includes("Stopped"), "the run to stop");
    expect(button("Start")).toBeTruthy();
  });

  it("asks the browser for the site in the Start click when it is not allowed yet", async () => {
    chromeFake.permissions.granted.clear();
    chromeFake.permissions.answer = false;
    await render();
    await start("Do something.");
    expect(chromeFake.permissions.request).toHaveBeenCalledWith({ origins: ["https://shop.example.com/*"] });
    await until(() => host.textContent!.includes("needs your permission"), "the refusal");
    expect(server.calls.some((c) => c.path === "/api/chat/completions")).toBe(false);
  });

  it("starts one run however quickly Start is pressed again while Chrome asks for the site", async () => {
    chromeFake.permissions.granted.clear();
    let answer: (granted: boolean) => void = () => undefined;
    chromeFake.permissions.request.mockImplementation(
      () =>
        new Promise<boolean>((resolve) => {
          answer = (granted) => {
            chromeFake.permissions.granted.add("https://shop.example.com/*");
            resolve(granted);
          };
        }),
    );
    await render();
    await start("Do something.");
    // Start again, and Enter in the task box, while Chrome's prompt is open.
    const box = host.querySelector('textarea[aria-label="Task"]') as HTMLTextAreaElement;
    expect(box.disabled).toBe(true);
    await act(async () => {
      host.querySelector("form.chat__composer")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    expect(chromeFake.permissions.request).toHaveBeenCalledTimes(1);
    await act(async () => answer(true));
    await until(() => host.textContent!.includes("Finished"), "the run to end");
    expect(server.calls.filter((c) => c.path === "/api/chat/completions")).toHaveLength(1);
  });

  it("keeps the card waiting while Chrome asks for its site, so the two answers never cross", async () => {
    let answer: (granted: boolean) => void = () => undefined;
    chromeFake.permissions.request.mockImplementation(
      ({ origins = [] }: { origins?: string[] }) =>
        new Promise<boolean>((resolve) => {
          answer = (granted) => {
            if (granted) for (const origin of origins) chromeFake.permissions.granted.add(origin);
            resolve(granted);
          };
        }),
    );
    replies = [
      toolFrame([{ id: "c1", name: "tab_open", args: { url: "https://partner.org/deals" } }]),
      toolFrame([{ id: "c2", name: "click", args: { ref: "e1" } }]),
      toolFrame([{ id: "c3", name: "done", args: { summary: "All done." } }]),
    ];
    await render();
    await start("Look at the partner's deals.");
    await until(() => host.textContent!.includes("Chrome will ask you"), "the card for the other site");
    await act(async () => button("Allow").click());
    // Chrome's prompt is open: the card can be answered neither twice nor the other way.
    expect(button("Allow").disabled).toBe(true);
    expect(button("Deny").disabled).toBe(true);
    await act(async () => button("Deny").click());
    await act(async () => answer(true));
    await until(() => host.textContent!.includes('Click "Next"'), "the next card");
    expect(button("Allow").disabled).toBe(false);
    await act(async () => button("Allow").click());
    await until(() => host.textContent!.includes("All done."), "the summary");
  });

  it("keeps the steps the server could not take, and sends them with the next batch", async () => {
    let tries = 0;
    server.routes["POST /api/extension/events"] = () => (++tries === 1 ? json(503, { detail: "Busy." }) : json(200, { recorded: 1, refused: 0 }));
    replies = [toolFrame([{ id: "c1", name: "read_page" }]), toolFrame([{ id: "c2", name: "done", args: { summary: "Read it." } }])];
    await render();
    await start("Read the page.");
    await until(() => host.textContent!.includes("Read it."), "the first run");
    await until(() => tries === 1, "the first flush");
    replies = [toolFrame([{ id: "c3", name: "done", args: { summary: "Nothing to do." } }])];
    await start("Nothing.");
    await until(() => tries === 2, "the second flush");
    const sent = server.calls.filter((c) => c.path === "/api/extension/events").map((c) => (c.body as { events: Array<{ kind: string; detail: { task_id: string } }> }).events);
    // The second batch holds the first run's steps as well as the second's.
    expect(new Set(sent[1].map((e) => e.detail.task_id)).size).toBe(2);
    expect(sent[1].length).toBeGreaterThan(sent[0].length);
  });

  it("asks the user instead of the reviewer when an action is too long for the reviewer to see whole", async () => {
    server.routes["POST /api/extension/review-action"] = () => json(200, { decision: "allow", reason: "ok" });
    replies = [
      toolFrame([{ id: "c1", name: "click", args: { ref: "e1", note: "ی".repeat(3000) } }]),
      toolFrame([{ id: "c2", name: "done", args: { summary: "Done." } }]),
    ];
    await render({ ...ME, features: { ...ME.features, auto_mode: true } });
    await act(async () => [...host.querySelectorAll('[role="radio"]')].find((b) => b.textContent === "Auto")!.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    await start("Go on.");
    await until(() => Boolean(host.querySelector('[role="alertdialog"]')), "the approval card");
    expect(host.textContent).toContain("too long for the reviewer");
    expect(server.calls.some((c) => c.path === "/api/extension/review-action")).toBe(false);
  });

  it("puts a question from the agent to the user", async () => {
    replies = [toolFrame([{ id: "c1", name: "ask_user", args: { question: "Which size?" } }]), toolFrame([{ id: "c2", name: "done", args: { summary: "Chose M." } }])];
    await render();
    await start("Buy nothing, just pick a size.");
    await until(() => host.textContent!.includes("Which size?"), "the question");
    const box = host.querySelector('textarea[aria-label="Your answer"]') as HTMLTextAreaElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(box, "M");
      box.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => button("Answer").click());
    await until(() => host.textContent!.includes("Chose M."), "the summary");
    const second = server.calls.filter((c) => c.path === "/api/chat/completions")[1].body as { messages: Array<{ role: string; content: string }> };
    expect(second.messages.at(-1)).toMatchObject({ role: "tool", content: "The user answered: M" });
  });

  it("waits out the server's per-minute limit instead of giving up", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let calls = 0;
      server.routes["POST /api/chat/completions"] = (init) => {
        calls += 1;
        if (calls === 1) return json(429, { detail: "Too many requests." });
        return sse(toolFrame([{ id: "c1", name: "done", args: { summary: "Done after waiting." } }]), { signal: init.signal }).response;
      };
      await render();
      await start("Do something.");
      await until(() => host.textContent!.includes("Too many requests in a minute"), "the note");
      await act(async () => {
        await vi.advanceTimersByTimeAsync(16_000);
      });
      await until(() => host.textContent!.includes("Done after waiting."), "the run to go on");
      expect(calls).toBe(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps off Alpharouter's host on any port, even when the server gives no address", async () => {
    const own = chromeFake.tabs.add({ url: `${SERVER.replace("https:", "http:")}:8080/admin`, title: "Admin" });
    chromeFake.tabs.activate(own.id!);
    chromeFake.permissions.granted.add("<all_urls>");
    replies = [toolFrame([{ id: "c1", name: "read_page" }]), toolFrame([{ id: "c2", name: "done", args: { summary: "Could not read it." } }])];
    await render({ ...ME, server: { name: "Alpharouter", url: null } });
    await start("Read this page.");
    await until(() => host.textContent!.includes("Could not read it."), "the summary");
    expect(host.querySelector('[data-step-status="blocked"]')).not.toBeNull();
    expect(pageCalls.some((c) => c.method === "read_page")).toBe(false);
  });

  it("keeps the administrator's read-only sites, and what the model may see, from the policy", async () => {
    replies = [toolFrame([{ id: "c1", name: "click", args: { ref: "e1" } }]), toolFrame([{ id: "c2", name: "read_page" }]), toolFrame([{ id: "c3", name: "done", args: { summary: "Read only." } }])];
    const policy = { ...ME.policy!, read_only_sites: ["shop.example.com"], data: { internal_sites: ["shop.example.com"], internal_models: ["model::1"], screenshot_models: null } };
    await render({ ...ME, policy });
    await start("Click next.");
    await until(() => host.textContent!.includes("Read only."), "the summary");
    // The click was refused on the read-only site; the read went ahead, since this model may see the internal site.
    expect(host.querySelector('[data-step-status="blocked"]')).not.toBeNull();
    expect(pageCalls.some((c) => c.method === "click")).toBe(false);
    expect(pageCalls.some((c) => c.method === "read_page")).toBe(true);
    expect(host.textContent).toContain("read-only site");
  });

  it("keeps an internal site from a model that may not see it", async () => {
    replies = [toolFrame([{ id: "c1", name: "read_page" }]), toolFrame([{ id: "c2", name: "done", args: { summary: "Not for this model." } }])];
    const policy = { ...ME.policy!, data: { internal_sites: ["*.example.com"], internal_models: ["model::2"], screenshot_models: null } };
    await render({ ...ME, policy });
    await start("Read this page.");
    await until(() => host.textContent!.includes("Not for this model."), "the summary");
    expect(host.querySelector('[data-step-status="blocked"]')).not.toBeNull();
    expect(pageCalls.some((c) => c.method === "read_page")).toBe(false);
    expect(host.textContent).toContain("internal to your organisation");
  });

  it("shows what went wrong when the server refuses the step", async () => {
    server.routes["POST /api/chat/completions"] = () =>
      json(403, { detail: { code: "model_not_allowed", message: "Your administrator does not allow the browser agent to use this model." } });
    await render();
    await start("Do something.");
    await until(() => host.textContent!.includes("Could not go on"), "the failure");
    expect(host.textContent).toContain("does not allow the browser agent to use this model");
  });
});

describe("a finished run", () => {
  const RUN = [toolFrame([{ id: "c1", name: "read_page" }]), toolFrame([{ id: "c2", name: "click", args: { ref: "e1" } }]), toolFrame([{ id: "c3", name: "done", args: { summary: "Moved to the next step." } }])];

  it("is saved to the chat history as the task, the answer and the steps, and says so", async () => {
    replies = [...RUN];
    await render();
    await start("Go to the next step.");
    await until(() => Boolean(host.querySelector('[role="alertdialog"]')), "the approval card");
    await act(async () => button("Allow").click());
    await until(() => host.textContent!.includes("Saved to your chat history"), "the saved note");
    const saved = server.callsTo("POST", "/api/extension/runs");
    expect(saved).toHaveLength(1);
    expect(saved[0].body).toMatchObject({
      task: "Go to the next step.",
      outcome: "done",
      summary: "Moved to the next step.",
      model: "model::1",
      mode: "ask",
      steps: [
        { tool: "read_page", summary: "Read the page", status: "done" },
        { tool: "click", summary: 'Click "Next"', status: "done" },
        { tool: "done", summary: "Finish", status: "done" },
      ],
    });
    expect(JSON.stringify(saved[0].body)).not.toContain(OUTLINE.slice(0, 20));
    const link = host.querySelector("a.agent__saved, .agent__saved a") as HTMLAnchorElement;
    expect(link.href).toBe(`${SERVER}/app/chat?session=chat-run-1`);
  });

  it("is not saved when the administrator keeps no runs, nor as a private run, and the toggle shows only when allowed", async () => {
    replies = [...RUN];
    await render({ ...ME, policy: { ...ME.policy!, save_runs: false } });
    expect(host.querySelector(".agent__private")).toBeNull();
    await start("Go to the next step.");
    await until(() => Boolean(host.querySelector('[role="alertdialog"]')), "the approval card");
    await act(async () => button("Allow").click());
    await until(() => host.textContent!.includes("Finished"), "the run to end");
    expect(server.callsTo("POST", "/api/extension/runs")).toHaveLength(0);
    expect(host.textContent).not.toContain("Saved to your chat history");

    act(() => root.unmount());
    root = createRoot(host);
    replies = [...RUN];
    await render({ ...ME, features: { ...ME.features, private_mode: true } });
    const toggle = host.querySelector(".agent__private input") as HTMLInputElement;
    expect(toggle).not.toBeNull();
    await act(async () => toggle.click());
    await start("Go to the next step.");
    await until(() => Boolean(host.querySelector('[role="alertdialog"]')), "the approval card");
    await act(async () => button("Allow").click());
    await until(() => host.textContent!.includes("Finished"), "the run to end");
    expect(server.callsTo("POST", "/api/extension/runs")).toHaveLength(0);
    // Without Private Mode, or with private runs turned off, there is no toggle.
    act(() => root.unmount());
    root = createRoot(host);
    await render({ ...ME, features: { ...ME.features, private_mode: true }, policy: { ...ME.policy!, private_runs: false } });
    expect(host.querySelector(".agent__private")).toBeNull();
  });

  it("goes on quietly when the server would not save it", async () => {
    server.routes["POST /api/extension/runs"] = () => json(403, { detail: { code: "runs_not_saved", message: "No." } });
    replies = [...RUN];
    await render();
    await start("Go to the next step.");
    await until(() => Boolean(host.querySelector('[role="alertdialog"]')), "the approval card");
    await act(async () => button("Allow").click());
    await until(() => host.textContent!.includes("Finished"), "the run to end");
    await act(async () => undefined);
    expect(host.textContent).not.toContain("Saved to your chat history");
    expect(button("Start")).toBeTruthy();
  });
});

describe("full control", () => {
  const VISION = [{ id: "model::1", name: "Vision Model", kinds: ["text"], default_kinds: ["chat"], supports_vision: true }];

  it("attaches the debugger, says so, offers the control tools, and detaches after the run", async () => {
    server.routes["GET /api/chat/models"] = () => json(200, VISION);
    chromeFake.debugger.answers.set("Page.getLayoutMetrics", layoutMetrics({ width: 1280, height: 720 }));
    await render({ ...ME, features: { ...ME.features, full_control: true } });
    await start("Look at the page.");
    await until(() => host.textContent!.includes("Done."), "the run to finish");
    expect(host.textContent).toContain("Full control is on");
    const body = server.calls.filter((c) => c.path === "/api/chat/completions")[0].body as { browser_tools: Array<{ function: { name: string } }> };
    expect(body.browser_tools.map((t) => t.function.name)).toEqual(expect.arrayContaining(["computer", "screenshot", "zoom", "click"]));
    // Attached for the run, and let go afterwards.
    expect(chromeFake.debugger.attach).toHaveBeenCalled();
    expect(chromeFake.debugger.attached.has(tabId)).toBe(false);
    expect(pageCalls.some((c) => c.method === "visuals_show")).toBe(true);
  });

  it("stays standard with a model that does not read images, and says why", async () => {
    await render({ ...ME, features: { ...ME.features, full_control: true } });
    await start("Look at the page.");
    await until(() => host.textContent!.includes("Done."), "the run to finish");
    expect(host.textContent).toContain("does not read images");
    expect(chromeFake.debugger.attach).not.toHaveBeenCalled();
    const body = server.calls.filter((c) => c.path === "/api/chat/completions")[0].body as { browser_tools: Array<{ function: { name: string } }> };
    expect(body.browser_tools.map((t) => t.function.name)).not.toContain("computer");
  });

  it("falls back, and says why, when Chrome refuses the attach", async () => {
    server.routes["GET /api/chat/models"] = () => json(200, VISION);
    chromeFake.debugger.attachError = "blocked by policy";
    await render({ ...ME, features: { ...ME.features, full_control: true } });
    await start("Look at the page.");
    await until(() => host.textContent!.includes("Done."), "the run to finish");
    expect(host.textContent).toContain("Working without full control");
    expect(host.textContent).toContain("blocked by policy");
  });

  it("does nothing different when the feature is off", async () => {
    server.routes["GET /api/chat/models"] = () => json(200, VISION);
    await render();
    await start("Look at the page.");
    await until(() => host.textContent!.includes("Done."), "the run to finish");
    expect(chromeFake.debugger.attach).not.toHaveBeenCalled();
    expect(host.textContent).not.toContain("full control");
  });
});
