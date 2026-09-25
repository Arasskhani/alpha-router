/**
 * @vitest-environment node
 */
import { describe, expect, it, vi } from "vitest";

import { ApiError, createApi } from "./api";
import { DisconnectedError, TemporaryError, type TokenManager } from "./tokens";

const SERVER = "https://ai.example.com";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function fakeTokens(start = "at-1") {
  let current = start;
  let n = 1;
  const tokens = {
    accessToken: vi.fn(async () => current),
    replaceRejected: vi.fn(async () => {
      n += 1;
      current = `at-${n}`;
      return current;
    }),
    forget: vi.fn(async () => undefined),
  };
  return tokens;
}

function api(tokens: ReturnType<typeof fakeTokens>, fetchImpl: typeof fetch) {
  return createApi({ tokens: tokens as unknown as TokenManager, serverUrl: async () => SERVER, fetch: fetchImpl });
}

describe("calls to the server", () => {
  it("carry the bearer token and never cookies", async () => {
    const tokens = fakeTokens();
    const fetchImpl = vi.fn(async () => json(200, { ok: true }));
    const result = await api(tokens, fetchImpl as unknown as typeof fetch).json("/api/extension/me", {
      method: "POST",
      body: JSON.stringify({ a: 1 }),
    });
    expect(result).toEqual({ ok: true });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${SERVER}/api/extension/me`);
    expect(init.credentials).toBe("omit");
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer at-1");
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("retry once with a fresh token after a 401 for an expired token", async () => {
    const tokens = fakeTokens();
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(json(401, { detail: { code: "expired", message: "The access token has expired." } }))
      .mockResolvedValueOnce(json(200, { ok: true }));
    expect(await api(tokens, fetchImpl as unknown as typeof fetch).json("/api/chat/models")).toEqual({ ok: true });
    expect(tokens.replaceRejected).toHaveBeenCalledWith("at-1");
    expect(new Headers((fetchImpl.mock.calls[1][1] as RequestInit).headers).get("Authorization")).toBe("Bearer at-2");
  });

  it("mean disconnected after a second 401", async () => {
    const tokens = fakeTokens();
    const fetchImpl = vi.fn(async () => json(401, { detail: { code: "invalid_token", message: "Unknown access token." } }));
    await expect(api(tokens, fetchImpl as unknown as typeof fetch).json("/api/chat/models")).rejects.toBeInstanceOf(
      DisconnectedError,
    );
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(tokens.forget).toHaveBeenCalledOnce();
  });

  it("mean disconnected at once when the session was revoked", async () => {
    const tokens = fakeTokens();
    const fetchImpl = vi.fn(async () => json(401, { detail: { code: "revoked", message: "This browser was disconnected." } }));
    await expect(api(tokens, fetchImpl as unknown as typeof fetch).request("/api/chat/models")).rejects.toBeInstanceOf(
      DisconnectedError,
    );
    expect(tokens.replaceRejected).not.toHaveBeenCalled();
    expect(tokens.forget).toHaveBeenCalledOnce();
  });

  it("turn other refusals into ApiError with the server's code and message", async () => {
    const tokens = fakeTokens();
    const fetchImpl = vi.fn(async () =>
      json(403, { detail: { code: "extension_not_permitted", message: "The browser extension is not enabled for your account." } }),
    );
    const error = await api(tokens, fetchImpl as unknown as typeof fetch)
      .json("/api/chat/models")
      .catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(403);
    expect((error as ApiError).code).toBe("extension_not_permitted");
    expect((error as ApiError).message).toContain("not enabled");
    expect(tokens.forget).not.toHaveBeenCalled();
  });

  it("read a plain-string detail too", async () => {
    const fetchImpl = vi.fn(async () => json(429, { detail: "Rate limit exceeded. Try again shortly." }));
    const error = (await api(fakeTokens(), fetchImpl as unknown as typeof fetch)
      .json("/x")
      .catch((e: unknown) => e)) as ApiError;
    expect([error.status, error.code, error.message]).toEqual([429, null, "Rate limit exceeded. Try again shortly."]);
  });

  it("treat a network failure as temporary", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    await expect(api(fakeTokens(), fetchImpl as unknown as typeof fetch).request("/x")).rejects.toBeInstanceOf(TemporaryError);
  });

  it("let a Stop through as an abort", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new DOMException("The operation was aborted.", "AbortError");
    });
    const error = await api(fakeTokens(), fetchImpl as unknown as typeof fetch)
      .request("/x")
      .catch((e: unknown) => e);
    expect((error as DOMException).name).toBe("AbortError");
  });

  it("leave FormData's content type to the browser", async () => {
    const fetchImpl = vi.fn(async () => json(200, {}));
    const form = new FormData();
    form.append("files", new Blob(["x"]), "a.txt");
    await api(fakeTokens(), fetchImpl as unknown as typeof fetch).json("/api/chat/attachments/process", {
      method: "POST",
      body: form,
    });
    expect(new Headers((fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1].headers).has("Content-Type")).toBe(false);
  });
});
