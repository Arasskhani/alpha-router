// Remove top-level declarations named in a "file:line name" list (from eslint no-unused-vars).
import { createRequire } from "node:module";
const require = createRequire(process.cwd() + "/");
const ts = require("typescript");
import fs from "node:fs";
const input = fs.readFileSync(0, "utf8").trim().split("\n").filter(Boolean);
const byFile = {};
for (const line of input) {
  const m = line.match(/^(\S+?):(\d+) '([^']+)'/);
  if (!m) continue;
  (byFile[m[1]] ??= new Set()).add(m[3]);
}
let removed = 0;
for (const [file, names] of Object.entries(byFile)) {
  const text = fs.readFileSync(file, "utf8");
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const ranges = [];
  for (const st of sf.statements) {
    let matched = false;
    if (ts.isFunctionDeclaration(st) && st.name && names.has(st.name.text)) matched = true;
    if (ts.isVariableStatement(st)) {
      const decls = st.declarationList.declarations;
      if (decls.length === 1 && ts.isIdentifier(decls[0].name) && names.has(decls[0].name.text)) matched = true;
    }
    if (ts.isClassDeclaration(st) && st.name && names.has(st.name.text)) matched = true;
    if (!matched) continue;
    // include leading comments (JSDoc) that belong to this statement
    const start = st.getFullStart();
    let end = st.getEnd();
    // swallow one trailing newline run
    while (end < text.length && text[end] === "\n") end++;
    ranges.push([start, end, st.name?.text ?? "var"]);
  }
  if (!ranges.length) continue;
  // Clamp overlapping ranges: a statement's full start includes the trivia
  // after the previous statement, which we may already have swallowed.
  ranges.sort((a, b) => a[0] - b[0]);
  for (let i = 0; i < ranges.length - 1; i++) ranges[i][1] = Math.min(ranges[i][1], ranges[i + 1][0]);
  ranges.sort((a, b) => b[0] - a[0]);
  let out = text;
  for (const [s, e] of ranges) out = out.slice(0, s) + "\n" + out.slice(e);
  out = out.replace(/\n{3,}/g, "\n\n");
  fs.writeFileSync(file, out);
  removed += ranges.length;
  console.log(file + ": " + ranges.map((r) => r[2]).join(", "));
}
console.log("removed", removed);
