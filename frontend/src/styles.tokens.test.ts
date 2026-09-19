/**
 * Every CSS custom property the stylesheet reads must be one it defines.
 *
 * Six tokens were referenced 27 times and defined nowhere - each reference
 * carried an inline fallback, so the fallback *was* the design system, copied
 * by hand, and `--danger` had drifted to four different reds. Once a token is
 * defined here it follows every theme; a fallback never does.
 *
 * This is a gate, not a style opinion: a `var(--x)` with no `--x:` anywhere is
 * either a typo or a token somebody meant to add and did not.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname);

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (/\.(css|tsx?)$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(path);
  }
  return out;
}

const files = walk(SRC);
const css = files.filter((f) => f.endsWith(".css")).map((f) => readFileSync(f, "utf8")).join("\n");
const tsx = files.filter((f) => /\.tsx?$/.test(f)).map((f) => readFileSync(f, "utf8")).join("\n");

/** `--name:` at the start of a declaration, in any rule (themes included). */
const defined = new Set<string>();
for (const m of css.matchAll(/(?:^|[{;\s])(--[a-zA-Z0-9-]+)\s*:/g)) defined.add(m[1]);
// Tokens set from React as inline custom properties count as defined too.
for (const m of tsx.matchAll(/["'`](--[a-zA-Z0-9-]+)["'`]\s*(?:as\s+\w+\s*)?[:\]]/g)) defined.add(m[1]);

/** `var(--name` wherever it appears - stylesheet or inline style strings. */
const referenced = new Map<string, number>();
for (const m of (css + "\n" + tsx).matchAll(/var\(\s*(--[a-zA-Z0-9-]+)/g)) {
  referenced.set(m[1], (referenced.get(m[1]) ?? 0) + 1);
}

describe("design tokens", () => {
  it("defines every token the stylesheet reads", () => {
    const phantom = [...referenced.entries()]
      .filter(([name]) => !defined.has(name))
      .map(([name, count]) => `${name} (${count} reference${count === 1 ? "" : "s"})`)
      .sort();
    expect(phantom, "tokens referenced but defined nowhere").toEqual([]);
  });

  it("does not paper over a token with an inline fallback", () => {
    // A fallback on a *defined* token is a second, competing definition.
    const withFallback = [...css.matchAll(/var\(\s*(--[a-zA-Z0-9-]+)\s*,/g)]
      .map((m) => m[1])
      .filter((name) => defined.has(name) && !name.startsWith("--folder-accent"));
    expect([...new Set(withFallback)].sort(), "defined tokens still carrying fallbacks").toEqual([]);
  });

  it("gives the semantic tokens a value in every theme", () => {
    const themes = ["dark", "mint", "dark-mint"];
    const semantic = ["--danger", "--danger-hover", "--danger-contrast", "--accent-contrast"];
    for (const theme of themes) {
      const block = css.match(new RegExp(`\\[data-theme="${theme}"\\]\\s*\\{([^}]*)\\}`))?.[1] ?? "";
      for (const token of semantic) {
        expect(block, `${token} in [data-theme="${theme}"]`).toMatch(new RegExp(`${token}\\s*:`));
      }
    }
  });
});
