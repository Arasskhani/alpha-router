/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setClient } from "../lib/client";
import { resetConfigForTests } from "../lib/config";
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

function toolFrame(calls: Array<{ id: string; name: string; args?: Record<string, unknown> }>): string[] {
  return calls.map((c, index) =>
    frame({ choices: [{ delta: { tool_calls: [{ index, id: c.id, type: "function", function: { name: c.name, arguments: JSON.stringify(c.args ?? {}) } }] } }] }),
  );
}

beforeEach(() => {
  chromeFake = installChromeFake({ version: "1.0.0.1" });
  resetConfigForTests();
  server = createServerFake();
  server.routes["GET /api/chat/models"] = () => json(200, MODELS);
  server.routes["POST /api/extension/events"] = () => json(200, { recorded: 1 });
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

  it("offers Auto mode only when the administrator turned it on", async () => {
    await render();
    expect(host.querySelector('[role="radiogroup"]')).toBeNull();
    act(() => root.unmount());
    root = createRoot(host);
    await render({ ...ME, features: { ...ME.features, auto_mode: true } });
    expect([...host.querySelectorAll('[role="radio"]')].map((b) => b.textContent)).toEqual(["Ask", "Auto"]);
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

  it("shows what went wrong when the server refuses the step", async () => {
    server.routes["POST /api/chat/completions"] = () =>
      json(403, { detail: { code: "model_not_allowed", message: "Your administrator does not allow the browser agent to use this model." } });
    await render();
    await start("Do something.");
    await until(() => host.textContent!.includes("Could not go on"), "the failure");
    expect(host.textContent).toContain("does not allow the browser agent to use this model");
  });
});
