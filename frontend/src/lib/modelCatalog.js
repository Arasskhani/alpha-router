/** Short admin label for the measured Code Interpreter state. */
export function codeInterpreterLabel(m) {
    const info = m.code_interpreter;
    if (!info)
        return "Unknown";
    if (info.manual_override === "compatible")
        return "Allowed (pinned)";
    if (info.manual_override === "incompatible")
        return "Blocked (pinned)";
    switch (info.status) {
        case "compatible":
            return "Verified";
        case "degraded":
            return "Quarantined";
        case "incompatible":
            return "Blocked";
        case "probing":
            return "Probing";
        default:
            return "Unknown";
    }
}
export function codeInterpreterButtonClass(m) {
    const info = m.code_interpreter;
    if (!info)
        return "";
    if (info.status === "compatible")
        return " model-compat-btn--verified";
    if (info.status === "degraded" || info.status === "incompatible") {
        return " model-compat-btn--blocked";
    }
    return "";
}
export const MODEL_KIND_ORDER = [
    "text",
    "image",
    "embeddings",
    "audio",
    "video",
    "rerank",
    "speech",
    "transcription",
];
export const MODEL_KIND_LABELS = {
    text: "Text",
    image: "Image",
    embeddings: "Embeddings",
    audio: "Audio",
    video: "Video",
    rerank: "Rerank",
    speech: "Speech",
    transcription: "Transcription",
};
export const MODEL_NEW_WINDOWS = [1, 3, 7, 14, 30];
export const MODEL_NEW_WINDOW_MS = 24 * 60 * 60 * 1000;
export function isNewlyListedModel(model, days, nowMs = Date.now()) {
    if (!model.first_seen_at)
        return false;
    const seen = Date.parse(model.first_seen_at);
    if (Number.isNaN(seen))
        return false;
    return seen >= nowMs - days * MODEL_NEW_WINDOW_MS;
}
export function kindCounts(models) {
    const counts = Object.fromEntries(MODEL_KIND_ORDER.map((k) => [k, 0]));
    for (const m of models) {
        const kinds = m.kinds?.length ? m.kinds : ["text"];
        for (const k of kinds) {
            if (k in counts)
                counts[k] += 1;
        }
    }
    return counts;
}
export function enabledCounts(models) {
    let on = 0;
    let off = 0;
    for (const m of models) {
        if (m.enabled)
            on += 1;
        else
            off += 1;
    }
    return { on, off };
}
export function accessCounts(models) {
    let pub = 0;
    let priv = 0;
    for (const m of models) {
        if ((m.access_type || "public") === "private")
            priv += 1;
        else
            pub += 1;
    }
    return { public: pub, private: priv };
}
export function newWindowCounts(models, nowMs = Date.now()) {
    const counts = Object.fromEntries(MODEL_NEW_WINDOWS.map((days) => [days, 0]));
    for (const days of MODEL_NEW_WINDOWS) {
        counts[days] = models.filter((m) => isNewlyListedModel(m, days, nowMs)).length;
    }
    return counts;
}
export function accessTypeLabel(m) {
    const access = m.access_type || "public";
    if (access !== "private")
        return "Public";
    const users = m.assignment_counts?.users ?? 0;
    const groups = m.assignment_counts?.groups ?? 0;
    const n = users + groups;
    return n > 0 ? `Private (${n})` : "Private";
}
export function filterCatalogModels(models, search, activeKind, enabledFilter = null, accessFilter = null, newFilter = null, nowMs = Date.now()) {
    const q = search.trim().toLowerCase();
    return models.filter((m) => {
        if (activeKind) {
            const kinds = m.kinds?.length ? m.kinds : ["text"];
            if (!kinds.includes(activeKind))
                return false;
        }
        if (enabledFilter === "on" && !m.enabled)
            return false;
        if (enabledFilter === "off" && m.enabled)
            return false;
        const access = m.access_type || "public";
        if (accessFilter && access !== accessFilter)
            return false;
        if (newFilter && !isNewlyListedModel(m, newFilter, nowMs))
            return false;
        if (!q)
            return true;
        const name = (m.display_name || m.title || "").toLowerCase();
        const desc = (m.description || "").toLowerCase();
        return (m.external_id.toLowerCase().includes(q) ||
            name.includes(q) ||
            desc.includes(q));
    });
}
