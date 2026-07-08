import { STORAGE_KEYS } from "./brand";

/** Device/browser theme cache — used before login when user identity is unknown. */
export type CachedTheme = "light" | "dark";

export function loadCachedTheme(): CachedTheme {
  const raw = localStorage.getItem(STORAGE_KEYS.theme);
  return raw === "dark" ? "dark" : "light";
}

export function saveCachedTheme(theme: CachedTheme): void {
  localStorage.setItem(STORAGE_KEYS.theme, theme);
}

export function applyThemeToDocument(theme: CachedTheme = loadCachedTheme()): void {
  document.documentElement.setAttribute("data-theme", theme);
}
