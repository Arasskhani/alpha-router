import { COOKIE_NAMES, STORAGE_KEYS } from "./lib/brand";
let cachedSession = null;
let bootstrapPromise = null;
let handlingUnauthorized = false;
function cookieValue(name) {
    const prefix = `${encodeURIComponent(name)}=`;
    for (const part of document.cookie.split(";")) {
        const value = part.trim();
        if (value.startsWith(prefix))
            return decodeURIComponent(value.slice(prefix.length));
    }
    return "";
}
function isUnsafe(method) {
    return ["POST", "PUT", "PATCH", "DELETE"].includes(method.toUpperCase());
}
function onUnauthorized(path) {
    if (path.startsWith("/api/auth/login")
        || path.startsWith("/api/auth/login/2fa")
        || path.startsWith("/api/auth/saml/exchange")
        || path.startsWith("/api/auth/sso/exchange")
        || path.startsWith("/api/auth/logout"))
        return;
    cachedSession = null;
    localStorage.removeItem(STORAGE_KEYS.token);
    localStorage.removeItem(STORAGE_KEYS.role);
    if (handlingUnauthorized || window.location.pathname === "/login")
        return;
    handlingUnauthorized = true;
    window.location.assign("/login");
}
export function getCachedSession() {
    return cachedSession;
}
export function clearCachedSession() {
    cachedSession = null;
    bootstrapPromise = null;
}
export async function authFetch(path, init = {}) {
    const headers = new Headers(init.headers);
    const method = (init.method || "GET").toUpperCase();
    if (isUnsafe(method)) {
        const csrf = cookieValue(COOKIE_NAMES.csrf);
        if (csrf && !headers.has("X-CSRF-Token"))
            headers.set("X-CSRF-Token", csrf);
    }
    const response = await fetch(path, {
        ...init,
        credentials: "include",
        headers,
    });
    if (response.status === 401)
        onUnauthorized(path);
    return response;
}
export function bootstrapSession(force = false) {
    if (cachedSession && !force)
        return Promise.resolve(cachedSession);
    if (bootstrapPromise && !force)
        return bootstrapPromise;
    bootstrapPromise = authFetch("/api/auth/session")
        .then(async (response) => {
        if (!response.ok)
            throw new Error("Not authenticated");
        const session = (await response.json());
        cachedSession = session;
        if (session.auth_provider) {
            localStorage.setItem(STORAGE_KEYS.authProvider, session.auth_provider);
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
export function formatApiError(err) {
    if (err instanceof Error) {
        const msg = err.message;
        if (msg && msg !== "[object Object]")
            return msg;
    }
    if (err && typeof err === "object") {
        const detail = err.detail;
        if (typeof detail === "string")
            return detail;
        if (detail && typeof detail === "object") {
            const d = detail;
            if (d.message) {
                return d.revision != null ? `${d.message} (revision ${d.revision})` : d.message;
            }
            try {
                return JSON.stringify(detail);
            }
            catch {
                /* fall through */
            }
        }
    }
    if (typeof err === "string")
        return err;
    return "Request failed";
}
async function parseError(res) {
    const text = await res.text();
    try {
        const j = JSON.parse(text);
        const detail = j.detail ?? j.message;
        if (typeof detail === "string")
            return detail;
        if (detail && typeof detail === "object") {
            const d = detail;
            if (d.message) {
                return d.revision != null ? `${d.message} (revision ${d.revision})` : d.message;
            }
            return JSON.stringify(detail);
        }
        return text || res.statusText;
    }
    catch {
        return text || res.statusText;
    }
}
/** True when the API rejected the request due to missing or invalid auth. */
export function isApiAuthError(err) {
    if (!err || typeof err !== "object")
        return false;
    return err.status === 401;
}
export async function api(path, init) {
    const headers = new Headers(init?.headers);
    if (init?.body != null
        && !(init.body instanceof FormData)
        && !headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json");
    }
    const res = await authFetch(path, { ...init, headers });
    if (!res.ok) {
        const err = new Error(await parseError(res));
        err.status = res.status;
        throw err;
    }
    if (res.status === 204)
        return undefined;
    return res.json();
}
