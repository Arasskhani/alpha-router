const LOCAL_DATETIME = {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
};
const LOCAL_DATE = {
    year: "numeric",
    month: "short",
    day: "numeric",
};
/** Parse API datetimes stored as naive UTC (ISO without timezone suffix). */
export function parseApiDateTime(iso) {
    if (!iso)
        return null;
    const trimmed = iso.trim();
    if (!trimmed)
        return null;
    const hasTz = /[zZ]$|[+-]\d{2}:\d{2}$/.test(trimmed);
    const normalized = hasTz ? trimmed : `${trimmed.replace(/\.\d+$/, "")}Z`;
    const d = new Date(normalized);
    return Number.isNaN(d.getTime()) ? null : d;
}
/** Format stored API datetime in the browser's local timezone. */
export function formatLocalDateTime(iso) {
    const d = parseApiDateTime(iso);
    if (!d)
        return "—";
    return d.toLocaleString(undefined, LOCAL_DATETIME);
}
export function formatLocalDate(iso) {
    const d = parseApiDateTime(iso);
    if (!d)
        return "—";
    return d.toLocaleDateString(undefined, LOCAL_DATE);
}
export function formatLocalDateTimeFromMs(ts) {
    if (ts == null || !Number.isFinite(ts))
        return null;
    return new Date(ts).toLocaleString(undefined, LOCAL_DATETIME);
}
