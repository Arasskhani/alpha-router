/**
 * A table drawn as cards on a phone needs its cells labelled by useTableCards,
 * or every card line loses its label. This checks the pairing in the source,
 * so a new card table cannot ship half-done.
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

const sources = walk(join(__dirname)).map((path) => ({ path, text: readFileSync(path, "utf8") }));
const cardTables = sources.filter((s) => s.text.includes("data-table--cards"));

describe("card tables", () => {
  it("are the seven list pages", () => {
    const names = cardTables.map((s) => s.path.split(/[\\/]/).pop()).sort();
    expect(names).toEqual([
      "ApiKeys.tsx",
      "Connections.tsx",
      "DeletedUsers.tsx",
      "Groups.tsx",
      "Plans.tsx",
      "Roles.tsx",
      "Users.tsx",
    ]);
  });

  it("leave the sticky-first tables' wrappers alone on a desktop", () => {
    const sticky = sources.filter((s) => s.text.includes("data-table--sticky-first"));
    expect(sticky.map((s) => s.path.split(/[\\/]/).pop()).sort()).toEqual(["DatabaseMonitor.tsx", "ProjectUsage.tsx"]);
    for (const { path, text } of sticky) {
      expect(text, path).toMatch(/<div className="table-wrap table-wrap--phone-scroll">\s*<table className="[^"]*data-table--sticky-first/);
    }
  });

  it("each label their cells with useTableCards on the same table", () => {
    for (const { path, text } of cardTables) {
      expect(text, path).toMatch(/const (\w+) = useTableCards<HTMLTableElement>\(\);/);
      const refName = /const (\w+) = useTableCards/.exec(text)?.[1];
      expect(text, path).toMatch(new RegExp(`<table ref=\\{${refName}\\} className="[^"]*data-table--cards`));
    }
  });
});
