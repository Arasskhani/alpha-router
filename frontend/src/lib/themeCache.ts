import { STORAGE_KEYS } from "./brand";

/** Stored preference — may follow the OS when set to system. */
export type CachedTheme = "light" | "dark" | "system";

/** Effective document theme used by `[data-theme]`. */
export type ResolvedTheme = "light" | "dark";

export function loadCachedTheme(): CachedTheme {
  const raw = localStorage.getItem(STORAGE_KEYS.theme);
  if (raw === "dark" || raw === "system") return raw;
  return "light";
}

export function saveCachedTheme(theme: CachedTheme): void {
  localStorage.setItem(STORAGE_KEYS.theme, theme);
}

export function resolveTheme(theme: CachedTheme): ResolvedTheme {
  if (theme === "system") {
    if (typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches) {
      return "dark";
    }
    return "light";
  }
  return theme;
}

export function applyThemeToDocument(theme: CachedTheme = loadCachedTheme()): void {
  document.documentElement.setAttribute("data-theme", resolveTheme(theme));
}
