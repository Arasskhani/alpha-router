/**
 * @vitest-environment node
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { loadConfig, parseConfig, resetConfigForTests, serverUrl } from "./config";

beforeEach(() => {
  resetConfigForTests();
  vi.stubGlobal("chrome", { runtime: { id: "abcdefghijklmnopabcdefghijklmnop", getURL: (p: string) => `chrome-extension://abcdefghijklmnopabcdefghijklmnop/${p}` } });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the server this copy belongs to", () => {
  it("is read from config.json once", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ serverUrl: "https://ai.example.com/", serverName: "Alpharouter", extensionVersion: "1.0.0.3" })));
    expect(await loadConfig(fetchImpl as unknown as typeof fetch)).toEqual({
      serverUrl: "https://ai.example.com",
      serverName: "Alpharouter",
      extensionVersion: "1.0.0.3",
    });
    await loadConfig(fetchImpl as unknown as typeof fetch);
    expect(fetchImpl).toHaveBeenCalledOnce();
    expect(fetchImpl).toHaveBeenCalledWith("chrome-extension://abcdefghijklmnopabcdefghijklmnop/config.json");
  });

  it.each([
    [{ serverUrl: "" }, ""],
    [{ serverUrl: "javascript:alert(1)" }, ""],
    [{ serverUrl: "ftp://ai.example.com" }, ""],
    [{ serverUrl: "https://ai.example.com:8443/some/path" }, "https://ai.example.com:8443"],
    [null, ""],
  ])("keeps only an http(s) origin: %o", (raw, expected) => {
    expect(parseConfig(raw).serverUrl).toBe(expected);
  });

  it("refuses to guess when this copy belongs to no server", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ serverUrl: "" }))));
    await expect(serverUrl()).rejects.toThrow("belongs to no Alpharouter server");
  });

  it("survives a missing config.json", async () => {
    const fetchImpl = vi.fn(async () => new Response("", { status: 404 }));
    expect((await loadConfig(fetchImpl as unknown as typeof fetch)).serverUrl).toBe("");
  });
});
