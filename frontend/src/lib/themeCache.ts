import { STORAGE_KEYS } from "./brand";

/** Stored preference — may follow the OS when set to system / mint-system. */
export type CachedTheme =
  | "light"
  | "dark"
  | "system"
  | "mint"
  | "dark-mint"
  | "mint-system"
  | "alpha-black";

/** Effective document theme used by `[data-theme]`. */
type ResolvedTheme = "light" | "dark" | "mint" | "dark-mint" | "alpha-black";

/** Named theme shown in the Theme dropdown. */
export type NamedTheme = "default" | "mint" | "dark-mint" | "alpha-black";

/** The Theme dropdown's choices, in order. */
export const NAMED_THEMES: NamedTheme[] = ["default", "mint", "dark-mint", "alpha-black"];

/** Appearance mode controlled by Light / Dark / System buttons. */
export type ColorMode = "light" | "dark" | "system";

const THEME_VALUES = new Set<CachedTheme>([
  "light",
  "dark",
  "system",
  "mint",
  "dark-mint",
  "mint-system",
  "alpha-black",
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
  return resolved === "dark" || resolved === "dark-mint" || resolved === "alpha-black" ? "dark" : "light";
}

/** Each theme's --surface (styles.css): the topbar's colour, which the browser and status bar take. */
export const THEME_SURFACE: Record<ResolvedTheme, string> = {
  light: "#ffffff",
  dark: "#12171e",
  mint: "#ffffff",
  "dark-mint": "#161616",
  "alpha-black": "#0e0900",
};

/**
 * The theme-color for a light and a dark OS scheme. A theme that follows the
 * system keeps one per scheme, so the bar is right as soon as the OS switches;
 * a chosen theme uses its own colour for both.
 */
function themeColors(theme: CachedTheme): { light: string; dark: string } {
  if (theme === "system") return { light: THEME_SURFACE.light, dark: THEME_SURFACE.dark };
  if (theme === "mint-system") return { light: THEME_SURFACE.mint, dark: THEME_SURFACE["dark-mint"] };
  const color = THEME_SURFACE[resolveTheme(theme)];
  return { light: color, dark: color };
}

/** Tint the browser's toolbar and an installed app's status bar (Android) with the theme. */
function applyThemeColor(theme: CachedTheme): void {
  const colors = themeColors(theme);
  for (const scheme of ["light", "dark"] as const) {
    const media = `(prefers-color-scheme: ${scheme})`;
    let meta = document.head.querySelector<HTMLMetaElement>(`meta[name="theme-color"][media="${media}"]`);
    if (!meta) {
      meta = document.createElement("meta");
      meta.setAttribute("name", "theme-color");
      meta.setAttribute("media", media);
      document.head.appendChild(meta);
    }
    meta.setAttribute("content", colors[scheme]);
  }
}

export function applyThemeToDocument(theme: CachedTheme = loadCachedTheme()): void {
  const resolved = resolveTheme(theme);
  const root = document.documentElement;
  root.setAttribute("data-theme", resolved);
  root.setAttribute("data-scheme", colorSchemeFor(resolved));
  applyThemeColor(theme);
}

export function namedThemeOf(theme: CachedTheme): NamedTheme {
  if (theme === "alpha-black") return "alpha-black";
  if (theme === "dark-mint") return "dark-mint";
  if (theme === "mint" || theme === "mint-system") return "mint";
  return "default";
}

export function colorModeOf(theme: CachedTheme): ColorMode {
  if (theme === "system" || theme === "mint-system") return "system";
  if (theme === "dark" || theme === "dark-mint" || theme === "alpha-black") return "dark";
  return "light";
}

export function namedThemeLabel(named: NamedTheme): string {
  if (named === "mint") return "Mint";
  if (named === "dark-mint") return "Dark Mint";
  if (named === "alpha-black") return "ALPHA BLACK";
  return "Default";
}

/** Combine dropdown selection + appearance buttons into a stored theme. */
export function composeTheme(named: NamedTheme, mode: ColorMode): CachedTheme {
  // ALPHA BLACK is dark only: Light or System leaves it for the default theme in that mode.
  if (named === "alpha-black") return mode === "dark" ? "alpha-black" : mode;
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

/** The theme the Theme dropdown sets, keeping the appearance mode where the named theme has it. */
export function themeForNamed(next: NamedTheme, mode: ColorMode): CachedTheme {
  if (next === "dark-mint" || next === "alpha-black") return next;
  if (next === "mint") return mode === "system" ? "mint-system" : "mint";
  return mode;
}

/** The theme the Light / Dark / System buttons set for the named theme shown. */
export function themeForMode(named: NamedTheme, next: ColorMode): CachedTheme {
  if (named === "alpha-black") return composeTheme("alpha-black", next);
  return composeTheme(named === "default" ? "default" : "mint", next);
}
