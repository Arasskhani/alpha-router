/**
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import { pageMessage, type PageContext } from "../lib/pageContext";
import { compareVersions } from "../lib/version";
import { apiMessages, completionBody, pagesIn, pickModel, textModels, type Turn } from "./chat";

const user = (content: string, id = "u1"): Turn => ({ id, role: "user", content });
const assistant = (content: string, extra: Partial<Turn> = {}): Turn => ({ id: "a1", role: "assistant", content, ...extra });

describe("models", () => {
  const models = [
    { id: "model::1", name: "A", kinds: ["text"] },
    { id: "model::2", name: "Embed", kinds: ["embeddings"] },
    { id: "model::3", name: "Old payload" },
    { id: "model::4", name: "Default", kinds: ["text"], default_kinds: ["chat"] },
    { id: "model::5", name: "System", kinds: ["text"], is_system_default: true },
  ];

  it("keeps the ones that answer text (a model without kinds counts)", () => {
    expect(textModels(models).map((m) => m.id)).toEqual(["model::1", "model::3", "model::4", "model::5"]);
  });

  it("prefers the remembered choice, then the chat default, then the system default, then the first", () => {
    expect(pickModel(models, "model::1")?.id).toBe("model::1");
    expect(pickModel(models, "model::gone")?.id).toBe("model::4");
    expect(pickModel(models.filter((m) => m.id !== "model::4"), null)?.id).toBe("model::5");
    expect(pickModel([{ id: "model::9", name: "Only" }], null)?.id).toBe("model::9");
    expect(pickModel([], null)).toBeNull();
  });
});

describe("what a turn sends", () => {
  it("leaves failed and empty answers out of the history", () => {
    expect(
      apiMessages([user("q1"), assistant("", { error: "down" }), user("q2", "u2"), assistant("half", { error: "cut" }), assistant("ok")]),
    ).toEqual([
      { role: "user", content: "q1" },
      { role: "user", content: "q2" },
      { role: "assistant", content: "ok" },
    ]);
  });

  it("asks the server to save a normal chat", () => {
    expect(completionBody({ model: "model::1", history: [], user: user("hi"), assistantId: "a9", sessionId: "s1", sentAt: 5 })).toEqual({
      model: "model::1",
      messages: [{ role: "user", content: "hi" }],
      stream: true,
      chat_session_id: "s1",
      persist_chat: true,
      user_message: { role: "user", content: "hi", clientMessageId: "u1", sentAt: 5 },
      assistant_client_message_id: "a9",
    });
  });

  it("asks for nothing to be saved in Private", () => {
    expect(completionBody({ model: "model::1", history: [], user: user("hi"), assistantId: "a9", sessionId: null, sentAt: 5 })).toEqual({
      model: "model::1",
      messages: [{ role: "user", content: "hi" }],
      stream: true,
      private_mode: true,
    });
  });
});

describe("a question about a page", () => {
  const guide: PageContext = { host: "docs.example.com", url: "https://docs.example.com/guide", title: "Guide", text: "Guide text.", truncated: false };
  const wiki: PageContext = { host: "wiki.example.com", url: "https://wiki.example.com/", title: "Wiki", text: "Wiki page.", truncated: false };
  const asked = (content: string, pages: PageContext[], id = "u1"): Turn => ({ id, role: "user", content, pages });

  it("sends the page in its own message, just before the question, which stays last", () => {
    const messages = apiMessages([asked("Summarize this", [guide])]);
    expect(messages).toEqual([
      { role: "user", content: pageMessage(guide) },
      { role: "user", content: "Summarize this" },
    ]);
  });

  it("keeps the page with its question on later turns", () => {
    const messages = apiMessages([asked("Summarize this", [guide]), assistant("A summary."), user("And the second step?", "u2")]);
    expect(messages.map((m) => m.content)).toEqual([pageMessage(guide), "Summarize this", "A summary.", "And the second step?"]);
  });

  it("declares every page the request carries, per site", () => {
    const turns = [asked("First", [guide]), assistant("One."), asked("Compare", [wiki, { ...guide, text: "More." }], "u2")];
    expect(pagesIn(turns)).toHaveLength(3);
    const body = completionBody({ model: "model::1", history: turns.slice(0, 2), user: turns[2], assistantId: "a9", sessionId: "s1", sentAt: 5 });
    expect(body.extension_page_context).toEqual({
      sites: [
        { host: "docs.example.com", chars: "Guide text.".length + "More.".length },
        { host: "wiki.example.com", chars: "Wiki page.".length },
      ],
    });
    expect((body.user_message as { content: string }).content).toBe("Compare");
  });

  it("declares pages in a private chat too", () => {
    const body = completionBody({ model: "model::1", history: [], user: asked("Q", [guide]), assistantId: "a9", sessionId: null, sentAt: 5 });
    expect(body.private_mode).toBe(true);
    expect(body.extension_page_context).toEqual({ sites: [{ host: "docs.example.com", chars: 11 }] });
  });

  it("declares nothing without a page", () => {
    const body = completionBody({ model: "model::1", history: [], user: user("hi"), assistantId: "a9", sessionId: "s1", sentAt: 5 });
    expect(body).not.toHaveProperty("extension_page_context");
  });
});

describe("extension versions", () => {
  it.each([
    ["1.0.0.1", "1.0.0.1", 0],
    ["1.0.0.2", "1.0.0.10", -1],
    ["1.0.1.0", "1.0.0.65535", 1],
    ["1.0", "1.0.0.0", 0],
  ])("%s against %s", (a, b, sign) => {
    expect(Math.sign(compareVersions(a, b))).toBe(sign);
  });
});
