/**
 * Scan frontend/public/fonts and generate:
 *   - src/generated/persianFonts.json  (catalog for Settings)
 *   - src/generated/persianFonts.css   (@font-face + chat/image selectors)
 *
 * Drop new .woff2 / .woff files into public/fonts (flat or per-family folders),
 * then rebuild — they appear in Settings → Persian Font automatically.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const FONTS_DIR = path.join(FRONTEND_ROOT, "public", "fonts");
const OUT_DIR = path.join(FRONTEND_ROOT, "src", "generated");
const OUT_JSON = path.join(OUT_DIR, "persianFonts.json");
const OUT_CSS = path.join(OUT_DIR, "persianFonts.css");

const WEIGHT_MAP = {
  thin: 100,
  hairline: 100,
  ultralight: 200,
  extralight: 200,
  light: 300,
  regular: 400,
  normal: 400,
  book: 400,
  roman: 400,
  medium: 500,
  demibold: 600,
  semibold: 600,
  bold: 700,
  extrabold: 800,
  ultrabold: 800,
  black: 900,
  heavy: 900,
};

const FONT_EXT_RE = /\.(woff2|woff)$/i;

function walkFiles(dir) {
  if (!fs.existsSync(dir)) return [];
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name.startsWith(".")) continue;
      out.push(...walkFiles(full));
    } else if (entry.isFile() && FONT_EXT_RE.test(entry.name)) {
      out.push(full);
    }
  }
  return out;
}

function slugify(label) {
  return String(label || "")
    .trim()
    .replace(/([a-z])([A-Z])/g, "$1-$2")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "font";
}

function parseFontFile(filePath) {
  const rel = path.relative(FONTS_DIR, filePath).split(path.sep).join("/");
  const baseName = path.basename(filePath);
  const ext = (baseName.match(FONT_EXT_RE)?.[1] || "woff2").toLowerCase();
  const stem = baseName.replace(FONT_EXT_RE, "");
  const parent = path.basename(path.dirname(filePath));
  const parentIsFontsRoot = path.dirname(filePath) === FONTS_DIR;

  const isVariable = /\[wght\]/i.test(stem) || /-?variable$/i.test(stem);
  if (isVariable) {
    let familyLabel = stem.replace(/\[wght\]/gi, "").replace(/-?variable$/i, "");
    familyLabel = familyLabel.replace(/-+$/, "").trim();
    if (!familyLabel && !parentIsFontsRoot) familyLabel = parent;
    if (!familyLabel) familyLabel = "Persian";
    return {
      rel,
      ext,
      familyLabel,
      variable: true,
      weight: null,
    };
  }

  const weightKeys = Object.keys(WEIGHT_MAP).sort((a, b) => b.length - a.length);
  let familyLabel = stem;
  let weight = 400;
  let matched = false;
  for (const key of weightKeys) {
    const re = new RegExp(`[-_ ](${key})$`, "i");
    const m = stem.match(re);
    if (m) {
      familyLabel = stem.slice(0, m.index).replace(/[-_ ]+$/, "");
      weight = WEIGHT_MAP[key];
      matched = true;
      break;
    }
  }
  if (!matched && !parentIsFontsRoot) {
    familyLabel = parent;
  }
  if (!familyLabel) familyLabel = parentIsFontsRoot ? stem : parent;

  return {
    rel,
    ext,
    familyLabel,
    variable: false,
    weight,
  };
}

function buildCatalog(files) {
  /** @type {Map<string, { id: string, label: string, cssFamily: string, faces: any[], variables: any[] }>} */
  const families = new Map();

  for (const filePath of files) {
    const parsed = parseFontFile(filePath);
    const id = slugify(parsed.familyLabel);
    let fam = families.get(id);
    if (!fam) {
      fam = {
        id,
        label: parsed.familyLabel,
        cssFamily: `AlphaRouterPersian-${parsed.familyLabel.replace(/\s+/g, "")}`,
        faces: [],
        variables: [],
      };
      families.set(id, fam);
    }
    const url = `/fonts/${parsed.rel}`;
    if (parsed.variable) {
      fam.variables.push({ path: url, format: parsed.ext });
    } else {
      fam.faces.push({
        path: url,
        format: parsed.ext,
        weight: parsed.weight ?? 400,
        style: "normal",
      });
    }
  }

  // Prefer woff2 over woff for the same weight; drop duplicate weights.
  for (const fam of families.values()) {
    const byWeight = new Map();
    for (const face of fam.faces) {
      const prev = byWeight.get(face.weight);
      if (!prev || (prev.format !== "woff2" && face.format === "woff2")) {
        byWeight.set(face.weight, face);
      }
    }
    fam.faces = [...byWeight.values()].sort((a, b) => a.weight - b.weight);

    let bestVar = null;
    for (const v of fam.variables) {
      if (!bestVar || (bestVar.format !== "woff2" && v.format === "woff2")) bestVar = v;
    }
    fam.variables = bestVar ? [bestVar] : [];
  }

  return [...families.values()]
    .filter((f) => f.faces.length > 0 || f.variables.length > 0)
    .sort((a, b) => a.label.localeCompare(b.label));
}

function formatSrc(file) {
  const fmt = file.format === "woff2" ? "woff2" : "woff";
  return `url("${file.path}") format("${fmt}")`;
}

function emitCss(families) {
  const lines = [
    "/* AUTO-GENERATED by scripts/generate-persian-fonts.mjs — do not edit. */",
    "/* Drop fonts in public/fonts and rebuild to refresh this file. */",
    "",
  ];

  for (const fam of families) {
    if (fam.faces.length > 0) {
      for (const face of fam.faces) {
        lines.push("@font-face {");
        lines.push(`  font-family: "${fam.cssFamily}";`);
        lines.push(`  src: ${formatSrc(face)};`);
        lines.push(`  font-weight: ${face.weight};`);
        lines.push(`  font-style: ${face.style};`);
        lines.push("  font-display: swap;");
        lines.push("}");
        lines.push("");
      }
    } else if (fam.variables[0]) {
      lines.push("@font-face {");
      lines.push(`  font-family: "${fam.cssFamily}";`);
      lines.push(`  src: ${formatSrc(fam.variables[0])};`);
      lines.push("  font-weight: 100 900;");
      lines.push("  font-style: normal;");
      lines.push("  font-display: swap;");
      lines.push("}");
      lines.push("");
    }

    const sel = [
      `.cgpt-app[data-persian-font="${fam.id}"] .cgpt-msg-inner`,
      `.cgpt-app[data-persian-font="${fam.id}"] .cgpt-composer-input`,
      `.cgpt-app[data-persian-font="${fam.id}"] .cgpt-attach-msg__image figcaption`,
      `.cgpt-app[data-persian-font="${fam.id}"] .cgpt-image-loading__label`,
      `.cgpt-app[data-persian-font="${fam.id}"] .cgpt-msg-model-label`,
    ].join(",\n");
    lines.push(`${sel} {`);
    lines.push(`  font-family: "${fam.cssFamily}", Tahoma, "Segoe UI", sans-serif;`);
    lines.push("}");
    lines.push("");
  }

  // Keep code blocks on monospace even when a Persian font is active.
  lines.push(
    [
      `.cgpt-app[data-persian-font] .cgpt-msg-inner code`,
      `.cgpt-app[data-persian-font] .cgpt-msg-inner pre`,
      `.cgpt-app[data-persian-font] .cgpt-msg-inner .alpha-router-code-block`,
      `.cgpt-app[data-persian-font] .cgpt-msg-inner .alpha-router-code-block__code`,
    ].join(",\n") + " {",
  );
  lines.push('  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;');
  lines.push("}");
  lines.push("");

  return lines.join("\n");
}

function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  fs.mkdirSync(FONTS_DIR, { recursive: true });

  const files = walkFiles(FONTS_DIR);
  const families = buildCatalog(files);

  const manifest = {
    generatedAt: new Date().toISOString(),
    families: families.map((f) => ({
      id: f.id,
      label: f.label,
      cssFamily: f.cssFamily,
      faces: f.faces.length
        ? f.faces
        : f.variables.map((v) => ({
            path: v.path,
            format: v.format,
            weight: "variable",
            style: "normal",
          })),
    })),
  };

  fs.writeFileSync(OUT_JSON, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  fs.writeFileSync(OUT_CSS, emitCss(families), "utf8");

  console.log(
    `[persian-fonts] ${families.length} famil${families.length === 1 ? "y" : "ies"} from ${files.length} file(s) → src/generated/`,
  );
  for (const f of families) {
    const n = f.faces.length || f.variables.length;
    console.log(`  - ${f.label} (${f.id}) · ${n} face(s)`);
  }
}

main();
