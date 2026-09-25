/**
 * Calls to the Alpharouter server with the extension's access token.
 *
 * Never with cookies (`credentials: "omit"`): the extension is a separate
 * client with its own token, whatever the browser's Alpharouter tab is signed
 * in as. A 401 is retried once with a fresh token; a second one, or a revoked
 * session, means the browser is disconnected. Network trouble is temporary
 * and keeps the tokens.
 */

import { DisconnectedError, TemporaryError, type TokenManager } from "./tokens";

export class ApiError extends Error {
  readonly status: number;
  /** The server's machine-readable reason, when it sent one (detail.code). */
  readonly code: string | null;
  /** The rest of the server's detail object, such as the site a refusal names. */
  readonly detail: Record<string, unknown>;

  constructor(status: number, message: string, code: string | null, detail: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }

  static async from(response: Response): Promise<ApiError> {
    const { message, code, detail } = await readError(response);
    return new ApiError(response.status, message, code, detail);
  }
}

async function readError(
  response: Response,
): Promise<{ message: string; code: string | null; detail: Record<string, unknown> }> {
  let message = `Alpharouter answered ${response.status}.`;
  let code: string | null = null;
  let fields: Record<string, unknown> = {};
  try {
    const body = (await response.json()) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string") message = detail;
    else if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      fields = detail as Record<string, unknown>;
      if (typeof fields.message === "string") message = fields.message;
      if (typeof fields.code === "string") code = fields.code;
    }
  } catch {
    // Not JSON: keep the generic message.
  }
  return { message, code, detail: fields };
}

export type ApiDeps = {
  tokens: TokenManager;
  serverUrl: () => Promise<string>;
  fetch: typeof fetch;
};

export function createApi(deps: ApiDeps) {
  async function send(path: string, init: RequestInit, token: string): Promise<Response> {
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${token}`);
    if (init.body != null && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    try {
      return await deps.fetch(`${await deps.serverUrl()}${path}`, {
        ...init,
        headers,
        credentials: "omit",
        cache: "no-store",
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") throw err;
      throw new TemporaryError();
    }
  }

  /** The raw response for anything but a 401 (a stream, a status the caller reads). */
  async function request(path: string, init: RequestInit = {}): Promise<Response> {
    const token = await deps.tokens.accessToken();
    const first = await send(path, init, token);
    if (first.status !== 401) return first;
    const { code } = await readError(first.clone());
    if (code === "revoked") {
      await deps.tokens.forget();
      throw new DisconnectedError();
    }
    const second = await send(path, init, await deps.tokens.replaceRejected(token));
    if (second.status === 401) {
      await deps.tokens.forget();
      throw new DisconnectedError();
    }
    return second;
  }

  async function json<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await request(path, init);
    if (!response.ok) throw await ApiError.from(response);
    return (await response.json()) as T;
  }

  return { request, json };
}
