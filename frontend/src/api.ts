export type SessionInfo = {
  username: string;
  role: string;
  is_active: boolean;
  auth_provider: string;
  role_slugs?: string[];
  [key: string]: unknown;
};

let cachedSession: SessionInfo | null = null;
let bootstrapPromise: Promise<SessionInfo> | null = null;
let handlingUnauthorized = false;

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
  localStorage.removeItem("alpha_router_token");
  localStorage.removeItem("alpha_router_role");
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
    const csrf = cookieValue("alpha_router_csrf");
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
        localStorage.setItem("alpha_router_auth_provider", session.auth_provider);
      }
      handlingUnauthorized = false;
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
    return text || res.statusText;
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
