/** Shared chat multi-model helpers (picker / topbar / selection cap). */
export const MAX_MULTI_MODELS = 4;
export function catalogMonthLabel(now = new Date()) {
    return now.toLocaleString("en-US", { month: "long", year: "numeric" });
}
export function shortcutModKey() {
    if (typeof navigator === "undefined")
        return "Ctrl";
    const platform = navigator.platform || "";
    const ua = navigator.userAgent || "";
    if (/Mac|iPhone|iPad|iPod/i.test(platform) || /Mac OS/i.test(ua))
        return "⌘";
    return "Ctrl";
}
