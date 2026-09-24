/**
 * @vitest-environment happy-dom
 *
 * The browser's toolbar and an installed app's status bar take the chosen
 * theme's surface colour (the topbar's), through the two theme-color metas.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";

import { THEME_SURFACE, applyThemeToDocument, type CachedTheme } from "./themeCache";

const meta = (scheme: "light" | "dark") =>
  document.head.querySelector<HTMLMetaElement>(`meta[name="theme-color"][media="(prefers-color-scheme: ${scheme})"]`)
    ?.content;

beforeEach(() => {
  document.head.innerHTML =
    '<meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">' +
    '<meta name="theme-color" content="#12171e" media="(prefers-color-scheme: dark)">';
  window.matchMedia = ((query: string) => ({ matches: false, media: query })) as typeof window.matchMedia;
});

describe("the theme colour", () => {
  const chosen: Array<[CachedTheme, string]> = [
    ["light", "#ffffff"],
    ["dark", "#12171e"],
    ["mint", "#ffffff"],
    ["dark-mint", "#161616"],
  ];
  for (const [theme, colour] of chosen) {
    it(`is ${colour} under both OS schemes for the ${theme} theme`, () => {
      applyThemeToDocument(theme);
      expect(meta("light")).toBe(colour);
      expect(meta("dark")).toBe(colour);
    });
  }

  it("keeps one colour per OS scheme for a theme that follows the system", () => {
    applyThemeToDocument("system");
    expect([meta("light"), meta("dark")]).toEqual(["#ffffff", "#12171e"]);
    applyThemeToDocument("mint-system");
    expect([meta("light"), meta("dark")]).toEqual(["#ffffff", "#161616"]);
  });

  it("adds the metas if the page has none, and never duplicates them", () => {
    document.head.innerHTML = "";
    applyThemeToDocument("dark");
    applyThemeToDocument("dark");
    expect(document.head.querySelectorAll('meta[name="theme-color"]')).toHaveLength(2);
    expect(meta("light")).toBe("#12171e");
  });

  it("matches each theme's --surface in styles.css", () => {
    const css = readFileSync(join(__dirname, "..", "styles.css"), "utf8");
    const surface = (block: string) => new RegExp(`${block}\\s*\\{[^}]*?--surface:\\s*(#[0-9a-f]{6})`, "i").exec(css)?.[1];
    expect(surface(":root")).toBe(THEME_SURFACE.light);
    expect(surface('\\[data-theme="dark"\\]')).toBe(THEME_SURFACE.dark);
    expect(surface('\\[data-theme="mint"\\]')).toBe(THEME_SURFACE.mint);
    expect(surface('\\[data-theme="dark-mint"\\]')).toBe(THEME_SURFACE["dark-mint"]);
  });
});
