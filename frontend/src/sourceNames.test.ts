/**
 * @vitest-environment node
 *
 * No two names in one folder that only case tells apart.
 *
 * Windows and macOS disks ignore case, and the resolver tries .tsx before
 * .ts. Beside Chat.tsx, an import of "./chat" meant for chat.ts gets the
 * component there, while Linux - where CI runs - resolves it as meant: the
 * suite then fails only on a developer's machine, and a build there bundles
 * the wrong module. A folder with an index counts too, since "./chat" can
 * name that index; a folder without one is reached only through its files
 * ("./docs/sections"), which no file beside it can take.
 */
import { existsSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const FRONTEND = join(__dirname, "..");
const ROOTS = ["src", "extension", "scripts"];
const SKIPPED = new Set(["node_modules", "dist", "dist-extension"]);
const INDEXES = ["index.tsx", "index.ts", "index.jsx", "index.mts", "index.mjs", "index.js"];

type Entry = { name: string; isDirectory: boolean };

/** What an import without an extension calls it: "Chat.test.tsx" is "Chat.test"; a folder, its name. */
function importName(entry: Entry): string {
  if (entry.isDirectory) return entry.name;
  const dot = entry.name.lastIndexOf(".");
  return dot > 0 ? entry.name.slice(0, dot) : entry.name;
}

/** The entries of one folder whose import names are the same once case is ignored, spelled differently. */
function caseClashes(entries: Entry[]): string[][] {
  const groups = new Map<string, { spellings: Set<string>; names: string[] }>();
  for (const entry of entries) {
    const spelled = importName(entry);
    const group = groups.get(spelled.toLowerCase()) ?? { spellings: new Set<string>(), names: [] };
    group.spellings.add(spelled);
    group.names.push(entry.isDirectory ? `${entry.name}/` : entry.name);
    groups.set(spelled.toLowerCase(), group);
  }
  return [...groups.values()].filter((group) => group.spellings.size > 1).map((group) => group.names.sort());
}

/** Every folder under `dir`, itself included. */
function folders(dir: string): string[] {
  const found = [dir];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory() && !SKIPPED.has(entry.name)) found.push(...folders(join(dir, entry.name)));
  }
  return found;
}

/** What an import can name in `dir`: its files, and the folders that have an index. */
function importable(dir: string): Entry[] {
  return readdirSync(dir, { withFileTypes: true })
    .filter((entry) => !entry.isDirectory() || INDEXES.some((index) => existsSync(join(dir, entry.name, index))))
    .map((entry) => ({ name: entry.name, isDirectory: entry.isDirectory() }));
}

describe("source file names", () => {
  it("never differ only in case within a folder", () => {
    const clashes = ROOTS.flatMap((root) => folders(join(FRONTEND, root))).flatMap((dir) =>
      caseClashes(importable(dir)).map((names) => `${relative(FRONTEND, dir)}: ${names.join(", ")}`),
    );
    expect(clashes).toEqual([]);
  });

  it("are told apart the way an import names them", () => {
    const file = (name: string): Entry => ({ name, isDirectory: false });
    expect(
      caseClashes([
        file("Chat.tsx"),
        file("chat.ts"),
        file("Chat.test.tsx"),
        file("chat.test.ts"),
        { name: "Icons", isDirectory: true },
        file("icons.ts"),
        // The same name with another extension is not a clash: styles.css beside styles.ts.
        file("styles.css"),
        file("styles.ts"),
      ]),
    ).toEqual([["Chat.tsx", "chat.ts"], ["Chat.test.tsx", "chat.test.ts"], ["Icons/", "icons.ts"]]);
  });
});
