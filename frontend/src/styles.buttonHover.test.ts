/**
 * A button variant's own hover colour must win over the base `.btn` hover.
 *
 * `.btn:hover` became `.btn:hover:not(:disabled)` so that disabled buttons
 * stop reacting to the pointer. That also raised it from two classes' worth
 * of specificity to three, above every variant that sets its own hover with
 * two: ghost buttons turned dark teal with dark text on it, danger buttons
 * turned teal instead of darker red, and the login button lost its softer
 * tone. Nothing looked at the cascade, so this test does.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(__dirname, "styles.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

type Specificity = [number, number, number];

/** Enough of the Selectors Level 4 rules for the selectors this file uses. */
function specificity(selector: string): Specificity {
  let a = 0;
  let b = 0;
  let c = 0;
  let rest = selector.replace(/:where\((?:[^()]|\([^()]*\))*\)/g, "");
  const inner: string[] = [];
  rest = rest.replace(/:(?:not|is|has)\(((?:[^()]|\([^()]*\))*)\)/g, (_m, arg: string) => {
    inner.push(arg);
    return "";
  });
  for (const arg of inner) {
    const [x, y, z] = specificity(arg);
    a += x;
    b += y;
    c += z;
  }
  a += (rest.match(/#[\w-]+/g) ?? []).length;
  b += (rest.match(/\.[\w-]+/g) ?? []).length;
  b += (rest.match(/\[[^\]]*\]/g) ?? []).length;
  b += (rest.match(/(?<!:):(?!:)[\w-]+/g) ?? []).length;
  c += (rest.match(/(?:^|[\s>+~])[a-zA-Z][\w-]*/g) ?? []).length;
  c += (rest.match(/::[\w-]+/g) ?? []).length;
  return [a, b, c];
}

function compare(x: Specificity, y: Specificity): number {
  for (let i = 0; i < 3; i += 1) if (x[i] !== y[i]) return x[i] - y[i];
  return 0;
}

/** Every top-level selector that starts with `prefix`, with where its rule starts. */
function rules(prefix: string): Array<{ selector: string; at: number }> {
  const found: Array<{ selector: string; at: number }> = [];
  const re = /([^{}]+)\{/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(css))) {
    for (const part of m[1].split(",")) {
      const selector = part.trim();
      if (selector.startsWith(prefix)) found.push({ selector, at: m.index });
    }
  }
  return found;
}

describe("button hover colours", () => {
  it("keeps the base hover no more specific than a plain `.btn:hover`", () => {
    const base = rules(".btn:hover");
    expect(base).toHaveLength(1);
    expect(compare(specificity(base[0].selector), [0, 2, 0])).toBeLessThanOrEqual(0);
    // Disabled buttons still do not react to the pointer.
    expect(base[0].selector).toContain(":not(:disabled)");
  });

  it.each([".btn-ghost:hover", ".btn-danger:hover", ".login-form__submit:hover", ".data-table .model-toggle-btn:hover"])(
    "lets %s win over the base hover",
    (prefix) => {
      const [base] = rules(".btn:hover");
      const variants = rules(prefix);
      expect(variants.length).toBeGreaterThan(0);
      for (const variant of variants) {
        const order = compare(specificity(variant.selector), specificity(base.selector));
        expect(order > 0 || (order === 0 && variant.at > base.at)).toBe(true);
      }
    },
  );

  it("computes specificity the way the cascade does", () => {
    expect(specificity(".btn:hover:not(:disabled)")).toEqual([0, 3, 0]);
    expect(specificity(".btn:hover:where(:not(:disabled))")).toEqual([0, 2, 0]);
    expect(specificity(".data-table .model-toggle-btn:hover")).toEqual([0, 3, 0]);
    expect(specificity("#id button::before")).toEqual([1, 0, 2]);
  });
});
