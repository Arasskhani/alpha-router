/** Alpharouter media files are served from an authenticated API route. */
import { authFetch } from "../api";
export function isAlphaRouterMediaFileUrl(url) {
    if (!url)
        return false;
    try {
        const base = typeof window !== "undefined" ? window.location.origin : "http://localhost";
        const parsed = new URL(url, base);
        return (parsed.origin === new URL(base).origin &&
            (/^\/api\/chat\/media\/\d+\/file$/.test(parsed.pathname) ||
                /^\/api\/videos\/jobs\/[0-9a-f-]{36}\/private-file$/.test(parsed.pathname) ||
                /^\/api\/projects\/[^/]+\/media\/\d+\/download$/.test(parsed.pathname)));
    }
    catch {
        return false;
    }
}
export async function fetchAuthenticatedMediaBlob(url) {
    if (!isAlphaRouterMediaFileUrl(url))
        throw new Error("Blocked unsafe authenticated media URL.");
    const res = await authFetch(url);
    if (!res.ok) {
        const text = await res.text();
        try {
            const j = JSON.parse(text);
            throw new Error(j.detail || text);
        }
        catch (e) {
            if (e instanceof Error && e.message !== text)
                throw e;
            throw new Error(text || `Failed to load media (${res.status})`);
        }
    }
    return res.blob();
}
export async function fetchAuthenticatedMediaObjectUrl(url) {
    const blob = await fetchAuthenticatedMediaBlob(url);
    return URL.createObjectURL(blob);
}
