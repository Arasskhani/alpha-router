/** Client helpers for automatic user memories (`/api/user/memories`). */
import { api, authFetch } from "../api";
function trimOrNull(value) {
    return typeof value === "string" && value.trim() ? value.trim() : null;
}
export async function fetchUserMemoriesBundle(opts) {
    const params = new URLSearchParams();
    if (opts?.limit)
        params.set("limit", String(opts.limit));
    if (opts?.offset)
        params.set("offset", String(opts.offset));
    const qs = params.toString();
    const data = await api(`/api/user/memories${qs ? `?${qs}` : ""}`);
    return {
        memories: Array.isArray(data.memories) ? data.memories : [],
        total: typeof data.total === "number" ? data.total : 0,
        auto_capture: data.auto_capture !== false,
        memory_enabled: data.memory_enabled !== false,
        feature_enabled: data.feature_enabled !== false,
        extraction_configured: data.extraction_configured !== false,
        profile: {
            company: trimOrNull(data.profile?.company),
            department: trimOrNull(data.profile?.department),
            job_title: trimOrNull(data.profile?.job_title),
            reporting_to: trimOrNull(data.profile?.reporting_to),
        },
    };
}
export async function fetchUserMemoriesPage(limit, offset) {
    return fetchUserMemoriesBundle({ limit, offset });
}
export async function listUserMemories() {
    const data = await fetchUserMemoriesBundle();
    return data.memories;
}
export async function updateUserMemory(id, updates) {
    return api(`/api/user/memories/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: JSON.stringify(updates),
    });
}
export async function deleteUserMemory(id) {
    await api(`/api/user/memories/${encodeURIComponent(id)}`, { method: "DELETE" });
}
export async function deleteAllUserMemories() {
    const data = await api("/api/user/memories", { method: "DELETE" });
    return typeof data.deleted === "number" ? data.deleted : 0;
}
export async function exportUserMemories() {
    const res = await authFetch("/api/user/memories/export");
    if (!res.ok) {
        throw new Error("Failed to export memories");
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "alpharouter-memories.json";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
}
