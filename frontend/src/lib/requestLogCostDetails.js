import { api } from "../api";
export function isPersonalApiKeyLog(log) {
    if (log.api_key_kind === "personal")
        return true;
    if (typeof log.user_api_key_id === "number" && log.user_api_key_id > 0)
        return true;
    return (log.source || "").trim().toLowerCase() === "user_key";
}
export function logIdentityLabel(log) {
    if (log.identity_type === "api_key") {
        return `${log.api_key_name || log.username || "API key"} (Gateway API Key)`;
    }
    if (isPersonalApiKeyLog(log)) {
        const user = log.username || "unknown";
        const keyName = (log.api_key_name || "").trim();
        if (keyName && keyName.toLowerCase() !== user.toLowerCase()) {
            return `${user} · ${keyName} (Personal API Key)`;
        }
        return `${user} (Personal API Key)`;
    }
    if (log.identity_type === "chat") {
        return `${log.username || "unknown"} (Chat)`;
    }
    return log.username || "unknown";
}
export function confidenceLabel(key, unpriced = false) {
    if (unpriced)
        return { key: "unknown", label: "Unpriced" };
    const labels = {
        exact: "Provider",
        reconciled: "Reconciled",
        calculated: "Catalog",
        estimated: "Estimated",
        unknown: "Unknown",
    };
    return { key: key || "unknown", label: labels[key] || key || "Unknown" };
}
export function money(n) {
    return n == null || Number.isNaN(n) ? "—" : `$${n.toFixed(8)}`;
}
export function formatTokenCount(n) {
    return new Intl.NumberFormat("en-US").format(n || 0);
}
export async function fetchOwnedRequestLog(logId) {
    return api(`/api/user/request-logs/${logId}`);
}
export async function fetchOwnedRequestLogCostDetails(logId) {
    return api(`/api/user/request-logs/${logId}/cost-details`);
}
export async function fetchAdminRequestLogCostDetails(logId) {
    return api(`/api/admin/logs/${logId}/cost-details`);
}
