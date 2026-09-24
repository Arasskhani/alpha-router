import { COOKIE_NAMES, STORAGE_KEYS } from "./lib/brand";
import { humanizeGatewayError } from "./lib/gatewayErrors";

export type SessionInfo = {
  username: string;
  display_name?: string | null;
  role: string;
  is_active: boolean;
  auth_provider: string;
  role_slugs?: string[];
  [key: string]: unknown;
};

let cachedSession: SessionInfo | null = null;
let bootstrapPromise: Promise<SessionInfo> | null = null;
let handlingUnauthorized = false;
const sessionListeners = new Set<(session: SessionInfo) => void>();

/**
 * Call `listener` each time the server confirms a session, and at once if it
 * already has. For start-up work that needs the session's feature switches.
 */
export function onSessionReady(listener: (session: SessionInfo) => void): () => void {
  sessionListeners.add(listener);
  if (cachedSession) listener(cachedSession);
  return () => sessionListeners.delete(listener);
}

function cookieValue(name: string): string {
  const prefix = `${encodeURIComponent(name)}=`;
  for (const part of document.cookie.split(";")) {
    const value = part.trim();
    if (value.startsWith(prefix)) return decodeURIComponent(value.slice(prefix.length));
  }
  return "";
}

function isUnsafe(method: string): boolean {
  return ["POST", "PUT", "PATCH", "DELETE"].includes(method.toUpperCase());
}

function onUnauthorized(path: string) {
  if (
    path.startsWith("/api/auth/login")
    || path.startsWith("/api/auth/login/2fa")
    || path.startsWith("/api/auth/saml/exchange")
    || path.startsWith("/api/auth/sso/exchange")
    || path.startsWith("/api/auth/logout")
  ) return;
  cachedSession = null;
  // Private Mode promises the content lives only in this browser and goes when
  // the session does. An expired or revoked session arrives here, not at the
  // Logout button, and used to leave every private message body and every
  // generated image on the disk of what may be a shared machine.
  void import("./lib/session").then((m) => m.purgePrivateModeData()).catch(() => {});
  localStorage.removeItem(STORAGE_KEYS.token);
  localStorage.removeItem(STORAGE_KEYS.role);
  if (handlingUnauthorized || window.location.pathname === "/login") return;
  handlingUnauthorized = true;
  window.location.assign("/login");
}

export function getCachedSession(): SessionInfo | null {
  return cachedSession;
}

export function clearCachedSession() {
  cachedSession = null;
  bootstrapPromise = null;
}

export async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const method = (init.method || "GET").toUpperCase();
  if (isUnsafe(method)) {
    const csrf = cookieValue(COOKIE_NAMES.csrf);
    if (csrf && !headers.has("X-CSRF-Token")) headers.set("X-CSRF-Token", csrf);
  }
  const response = await fetch(path, {
    ...init,
    credentials: "include",
    headers,
  });
  if (response.status === 401) onUnauthorized(path);
  return response;
}

export function bootstrapSession(force = false): Promise<SessionInfo> {
  if (cachedSession && !force) return Promise.resolve(cachedSession);
  if (bootstrapPromise && !force) return bootstrapPromise;
  bootstrapPromise = authFetch("/api/auth/session")
    .then(async (response) => {
      if (!response.ok) throw new Error("Not authenticated");
      const session = (await response.json()) as SessionInfo;
      cachedSession = session;
      if (session.auth_provider) {
        localStorage.setItem(STORAGE_KEYS.authProvider, session.auth_provider);
      }
      handlingUnauthorized = false;
      for (const listener of sessionListeners) {
        try {
          listener(session);
        } catch (err) {
          console.warn("Alpharouter: a session listener failed", err);
        }
      }
      return session;
    })
    .finally(() => {
      bootstrapPromise = null;
    });
  return bootstrapPromise;
}

/** Turn FastAPI / fetch errors into a user-visible string. */
export function formatApiError(err: unknown): string {
  if (err instanceof Error) {
    const msg = err.message;
    if (msg && msg !== "[object Object]") return msg;
  }
  if (err && typeof err === "object") {
    const detail = (err as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object") {
      const d = detail as { message?: string; revision?: number };
      if (d.message) {
        return d.revision != null ? `${d.message} (revision ${d.revision})` : d.message;
      }
      try {
        return JSON.stringify(detail);
      } catch {
        /* fall through */
      }
    }
  }
  if (typeof err === "string") return err;
  return "Request failed";
}

async function parseError(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const j = JSON.parse(text) as { detail?: unknown; message?: string };
    const detail = j.detail ?? j.message;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object") {
      const d = detail as { message?: string; revision?: number };
      if (d.message) {
        return d.revision != null ? `${d.message} (revision ${d.revision})` : d.message;
      }
      return JSON.stringify(detail);
    }
    return text || res.statusText;
  } catch {
    return humanizeGatewayError(text || res.statusText, res.status);
  }
}

/** True when the API rejected the request due to missing or invalid auth. */
export function isApiAuthError(err: unknown): boolean {
  if (!err || typeof err !== "object") return false;
  return (err as { status?: number }).status === 401;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (
    init?.body != null
    && !(init.body instanceof FormData)
    && !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }
  const res = await authFetch(path, { ...init, headers });
  if (!res.ok) {
    const err = new Error(await parseError(res)) as Error & { status: number };
    err.status = res.status;
    throw err;
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

/** The cap an administrative list endpoint applied, if it applied one. */
export type ListBounds = { truncated: boolean; cap: number };

export const NO_LIST_BOUNDS: ListBounds = { truncated: false, cap: 0 };

/**
 * Like `api`, but also reports whether the server left rows out.
 *
 * Several admin lists are capped rather than paged: an operator looking for
 * somebody filters rather than scrolls, but a page that silently shows 2000 of
 * 50000 rows tells them the other 48000 do not exist. The server always sets
 * `X-List-Truncated`, so a missing header means an endpoint that has no cap -
 * not a page that happens to fit.
 */
/** Paging headers a paged list endpoint sets; zeros/false when it did not page. */
export type ListPage = { total: number | null; hasMore: boolean };

export async function apiList<T>(
  path: string,
  init?: RequestInit,
): Promise<{ data: T; bounds: ListBounds; page: ListPage }> {
  const headers = new Headers(init?.headers);
  const res = await authFetch(path, { ...init, headers });
  if (!res.ok) {
    const err = new Error(await parseError(res)) as Error & { status: number };
    err.status = res.status;
    throw err;
  }
  const flag = res.headers.get("X-List-Truncated");
  const cap = Number(res.headers.get("X-List-Cap") || 0);
  const totalHeader = res.headers.get("X-List-Total");
  const total = totalHeader === null ? null : Number(totalHeader);
  return {
    data: (res.status === 204 ? undefined : await res.json()) as T,
    bounds: flag === "true" ? { truncated: true, cap: Number.isFinite(cap) ? cap : 0 } : NO_LIST_BOUNDS,
    page: { total: total !== null && Number.isFinite(total) ? total : null, hasMore: res.headers.get("X-Has-More") === "true" },
  };
}
