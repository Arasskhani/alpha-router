export function agentStatusTone(status) {
    const value = (status || "").toLowerCase();
    if (["active", "published", "succeeded", "approved", "ready"].includes(value)) {
        return "is-success";
    }
    if ([
        "review",
        "pending",
        "pending_kb_approval",
        "pending_domain_approval",
        "processing",
        "running",
        "leased",
        "building",
        "indexing",
        "draft",
    ].includes(value)) {
        return "is-warning";
    }
    if (["failed", "dead", "blocked", "revoked", "suspended"].includes(value)) {
        return "is-danger";
    }
    if (["archived", "paused", "deleted"].includes(value)) {
        return "is-neutral";
    }
    return "is-neutral";
}
export function humanAgentStatus(status) {
    return (status || "unknown")
        .replaceAll("_", " ")
        .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
export function safeJsonObject(text, label) {
    let parsed;
    try {
        parsed = JSON.parse(text);
    }
    catch {
        throw new Error(`${label} must be valid JSON.`);
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error(`${label} must be a JSON object.`);
    }
    return parsed;
}
export function readableDate(value) {
    if (!value)
        return "—";
    const date = new Date(value);
    return Number.isNaN(date.valueOf()) ? value : date.toLocaleString();
}
