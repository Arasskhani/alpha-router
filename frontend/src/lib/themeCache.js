import { STORAGE_KEYS } from "./brand";
const THEME_VALUES = new Set([
    "light",
    "dark",
    "system",
    "mint",
    "dark-mint",
    "mint-system",
]);
export function isCachedTheme(value) {
    return THEME_VALUES.has(value);
}
export function loadCachedTheme() {
    const raw = localStorage.getItem(STORAGE_KEYS.theme);
    if (raw && isCachedTheme(raw))
        return raw;
    return "light";
}
export function saveCachedTheme(theme) {
    localStorage.setItem(STORAGE_KEYS.theme, theme);
}
export function prefersDarkScheme() {
    return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}
export function resolveTheme(theme) {
    if (theme === "system") {
        return prefersDarkScheme() ? "dark" : "light";
    }
    if (theme === "mint-system") {
        return prefersDarkScheme() ? "dark-mint" : "mint";
    }
    return theme;
}
export function colorSchemeFor(resolved) {
    return resolved === "dark" || resolved === "dark-mint" ? "dark" : "light";
}
export function applyThemeToDocument(theme = loadCachedTheme()) {
    const resolved = resolveTheme(theme);
    const root = document.documentElement;
    root.setAttribute("data-theme", resolved);
    root.setAttribute("data-scheme", colorSchemeFor(resolved));
}
export function namedThemeOf(theme) {
    if (theme === "dark-mint")
        return "dark-mint";
    if (theme === "mint" || theme === "mint-system")
        return "mint";
    return "default";
}
export function colorModeOf(theme) {
    if (theme === "system" || theme === "mint-system")
        return "system";
    if (theme === "dark" || theme === "dark-mint")
        return "dark";
    return "light";
}
export function namedThemeLabel(named) {
    if (named === "mint")
        return "Mint";
    if (named === "dark-mint")
        return "Dark Mint";
    return "Default";
}
/** Combine dropdown selection + appearance buttons into a stored theme. */
export function composeTheme(named, mode) {
    if (named === "dark-mint") {
        if (mode === "light")
            return "mint";
        if (mode === "system")
            return "mint-system";
        return "dark-mint";
    }
    if (named === "mint") {
        if (mode === "dark")
            return "dark-mint";
        if (mode === "system")
            return "mint-system";
        return "mint";
    }
    return mode;
}
export function followsSystemPreference(theme) {
    return theme === "system" || theme === "mint-system";
}
