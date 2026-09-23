/**
 * A chart with a negative left margin cuts the start off its axis numbers:
 * the Operations cards showed "2.0" for 12.0 and "500" for 4500. This keeps
 * the next chart from doing it again.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (name.endsWith(".tsx") && !name.endsWith(".test.tsx"))
      out.push(path);
  }
  return out;
}

describe("chart margins", () => {
  it("are never negative on the left, where the axis numbers are", () => {
    const offenders = walk(__dirname).filter((path) =>
      /margin=\{\{[^}]*\bleft:\s*-\d/.test(readFileSync(path, "utf8")),
    );
    expect(offenders).toEqual([]);
  });
});
