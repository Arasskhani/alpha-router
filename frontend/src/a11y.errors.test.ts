/**
 * Every inline error element is a live region.
 *
 * A red paragraph is visible; it is not announced. Without role="alert" a
 * screen-reader user who submits a form hears nothing when it fails. The four
 * class names below are how this codebase writes an inline error; each element
 * using one must carry a role (alert for a failure, status for a standing
 * notice). scripts/codemods/alert-role-on-errors.py adds it.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (name.endsWith(".tsx") && !name.endsWith(".test.tsx")) out.push(path);
  }
  return out;
}

const ERROR_CLASSES = ["alert alert-error", "error", "form-error", "settings-error"];
const OPEN_TAG = new RegExp(
  `<(?:p|div|span)\\s+className="(?:${ERROR_CLASSES.map((c) => c.replace(/[-/\\^$*+?.()|[\]{}]/g, "\\$&")).join("|")})"([^>]*)>`,
  "g",
);

describe("inline errors", () => {
  it("are live regions a screen reader announces", () => {
    const missing: string[] = [];
    for (const file of walk(join(__dirname))) {
      const source = readFileSync(file, "utf8");
      for (const m of source.matchAll(OPEN_TAG)) {
        if (!/\brole=/.test(m[1])) {
          const line = source.slice(0, m.index).split("\n").length;
          missing.push(`${file.split("/src/")[1]}:${line}`);
        }
      }
    }
    expect(missing, "error elements with no role").toEqual([]);
  });
});
