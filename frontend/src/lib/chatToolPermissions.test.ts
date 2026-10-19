import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({ api: vi.fn() }));

import {
  chatToolAllowed,
  chatToolUnavailableReason,
  loadChatToolPermissions,
  resetChatToolPermissions,
  setPermittedChatTools,
} from "./chatToolPermissions";
import { copyFreshChatTools, normalizeChatTools } from "./chatTools";

afterEach(() => resetChatToolPermissions());

describe("what the composer is allowed to offer", () => {
  it("offers everything until the server has answered", () => {
    // The menu must not flicker empty while the request is in flight, and the
    // server refuses anything that should not have been asked for anyway.
    expect(chatToolAllowed("code_interpreter")).toBe(true);
  });

  it("offers only what came back permitted", () => {
    setPermittedChatTools(["web_search"]);
    expect(chatToolAllowed("web_search")).toBe(true);
    expect(chatToolAllowed("code_interpreter")).toBe(false);
  });
});

describe("toggles saved before a tool was restricted", () => {
  it("are switched off when the state is loaded", () => {
    // A chat's toggles live on the server with the session, so this is how a
    // revoked tool comes back: not from this browser, but from the session.
    setPermittedChatTools(["web_search"]);
    const loaded = normalizeChatTools({ webSearch: true, codeInterpreter: true, webFetch: true });
    expect(loaded.webSearch).toBe(true);
    expect(loaded.codeInterpreter).toBe(false);
    expect(loaded.webFetch).toBe(false);
  });

  it("leaves settings that are not tools alone", () => {
    setPermittedChatTools([]);
    const loaded = normalizeChatTools({ webSearchDepth: "high", speechVoice: "nova" });
    expect(loaded.webSearchDepth).toBe("high");
    expect(loaded.speechVoice).toBe("nova");
  });

  it("does not resurrect anything on a fresh chat", () => {
    setPermittedChatTools(["web_search", "code_interpreter"]);
    expect(copyFreshChatTools().codeInterpreter).toBe(false);
  });

  it("keeps every toggle when the verdicts are unknown", () => {
    const loaded = normalizeChatTools({ webSearch: true, codeInterpreter: true });
    expect(loaded.webSearch).toBe(true);
    expect(loaded.codeInterpreter).toBe(true);
  });
});

describe("a tool that is permitted but cannot run now", () => {
  it("is switched off when the state is loaded", async () => {
    const { api } = await import("../api");
    vi.mocked(api).mockResolvedValueOnce([
      { key: "web_search", permitted: true, available: false, unavailable_reason: "No search service." },
      { key: "web_fetch", permitted: true, available: true },
    ]);
    await loadChatToolPermissions();
    expect(chatToolUnavailableReason("web_search")).toBe("No search service.");
    expect(chatToolUnavailableReason("web_fetch")).toBe("");
    const loaded = normalizeChatTools({ webSearch: true, webFetch: true });
    expect(loaded.webSearch).toBe(false);
    expect(loaded.webFetch).toBe(true);
  });
});
