/**
 * @vitest-environment happy-dom
 */
import { describe, expect, it } from "vitest";

import {
  NAMED_THEMES,
  applyThemeToDocument,
  colorModeOf,
  isCachedTheme,
  namedThemeLabel,
  namedThemeOf,
  themeForMode,
  themeForNamed,
} from "./themeCache";

describe("the ALPHA BLACK theme", () => {
  it("is offered in the Theme dropdown under its name", () => {
    expect(NAMED_THEMES).toEqual(["default", "mint", "dark-mint", "alpha-black"]);
    expect(namedThemeLabel("alpha-black")).toBe("ALPHA BLACK");
    expect(isCachedTheme("alpha-black")).toBe(true);
  });

  it("is a dark theme on the document", () => {
    applyThemeToDocument("alpha-black");
    expect(document.documentElement.getAttribute("data-theme")).toBe("alpha-black");
    expect(document.documentElement.getAttribute("data-scheme")).toBe("dark");
    expect(namedThemeOf("alpha-black")).toBe("alpha-black");
    expect(colorModeOf("alpha-black")).toBe("dark");
  });

  it("is chosen from the dropdown whatever the appearance mode", () => {
    for (const mode of ["light", "dark", "system"] as const) {
      expect(themeForNamed("alpha-black", mode)).toBe("alpha-black");
    }
  });

  it("is left for the default theme by Light or System, and kept by Dark", () => {
    expect(themeForMode("alpha-black", "dark")).toBe("alpha-black");
    expect(themeForMode("alpha-black", "light")).toBe("light");
    expect(themeForMode("alpha-black", "system")).toBe("system");
  });
});

describe("the other themes keep their choices", () => {
  it("maps the dropdown as before", () => {
    expect(themeForNamed("default", "dark")).toBe("dark");
    expect(themeForNamed("mint", "system")).toBe("mint-system");
    expect(themeForNamed("mint", "light")).toBe("mint");
    expect(themeForNamed("dark-mint", "light")).toBe("dark-mint");
  });

  it("maps the appearance buttons as before", () => {
    expect(themeForMode("default", "system")).toBe("system");
    expect(themeForMode("mint", "dark")).toBe("dark-mint");
    expect(themeForMode("dark-mint", "light")).toBe("mint");
  });
});
