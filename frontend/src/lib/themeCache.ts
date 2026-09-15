import { STORAGE_KEYS } from "./brand";

/** Stored preference — may follow the OS when set to system / mint-system. */
export type CachedTheme =
  | "light"
  | "dark"
  | "system"
  | "mint"
  | "dark-mint"
  | "mint-system";

/** Effective document theme used by `[data-theme]`. */
type ResolvedTheme = "light" | "dark" | "mint" | "dark-mint";

/** Named theme shown in the Theme dropdown. */
export type NamedTheme = "default" | "mint" | "dark-mint";

/** Appearance mode controlled by Light / Dark / System buttons. */
export type ColorMode = "light" | "dark" | "system";

const THEME_VALUES = new Set<CachedTheme>([
  "light",
  "dark",
  "system",
  "mint",
  "dark-mint",
  "mint-system",
]);

export function isCachedTheme(value: string): value is CachedTheme {
  return THEME_VALUES.has(value as CachedTheme);
}

export function loadCachedTheme(): CachedTheme {
  const raw = localStorage.getItem(STORAGE_KEYS.theme);
  if (raw && isCachedTheme(raw)) return raw;
  return "light";
}

export function saveCachedTheme(theme: CachedTheme): void {
  localStorage.setItem(STORAGE_KEYS.theme, theme);
}

function prefersDarkScheme(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function resolveTheme(theme: CachedTheme): ResolvedTheme {
  if (theme === "system") {
    return prefersDarkScheme() ? "dark" : "light";
  }
  if (theme === "mint-system") {
    return prefersDarkScheme() ? "dark-mint" : "mint";
  }
  return theme;
}

function colorSchemeFor(resolved: ResolvedTheme): "light" | "dark" {
  return resolved === "dark" || resolved === "dark-mint" ? "dark" : "light";
}

export function applyThemeToDocument(theme: CachedTheme = loadCachedTheme()): void {
  const resolved = resolveTheme(theme);
  const root = document.documentElement;
  root.setAttribute("data-theme", resolved);
  root.setAttribute("data-scheme", colorSchemeFor(resolved));
}

export function namedThemeOf(theme: CachedTheme): NamedTheme {
  if (theme === "dark-mint") return "dark-mint";
  if (theme === "mint" || theme === "mint-system") return "mint";
  return "default";
}

export function colorModeOf(theme: CachedTheme): ColorMode {
  if (theme === "system" || theme === "mint-system") return "system";
  if (theme === "dark" || theme === "dark-mint") return "dark";
  return "light";
}

export function namedThemeLabel(named: NamedTheme): string {
  if (named === "mint") return "Mint";
  if (named === "dark-mint") return "Dark Mint";
  return "Default";
}

/** Combine dropdown selection + appearance buttons into a stored theme. */
export function composeTheme(named: NamedTheme, mode: ColorMode): CachedTheme {
  if (named === "dark-mint") {
    if (mode === "light") return "mint";
    if (mode === "system") return "mint-system";
    return "dark-mint";
  }
  if (named === "mint") {
    if (mode === "dark") return "dark-mint";
    if (mode === "system") return "mint-system";
    return "mint";
  }
  return mode;
}

export function followsSystemPreference(theme: CachedTheme): boolean {
  return theme === "system" || theme === "mint-system";
}
