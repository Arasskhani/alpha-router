/**
 * Build the browser extension into dist-extension/ (run by `npm run build`).
 *
 * Three builds, because an extension is three kinds of code:
 *
 *   pages           sidepanel.html and connected.html with their React/TS
 *                   code; relative asset paths, since they are served from
 *                   chrome-extension://<id>/.
 *   service worker  background.js, one ES module ("type": "module" in the
 *                   manifest).
 *   content script  content.js, one classic script (IIFE): a file injected
 *                   with chrome.scripting cannot be an ES module.
 *
 * Then the manifest template becomes manifest.json and an empty config.json is
 * written. Both are neutral: the Alpharouter server fills in its key, origin,
 * version and site-access mode when someone downloads the extension (see
 * backend/app/services/extension_package.py). A copy built here and loaded as
 * it is belongs to no server and says so.
 *
 * The build checks its own output and fails if a file the manifest names is
 * missing.
 */
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { build } from "vite";

const here = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(here, "..");
const extensionDir = path.join(frontendDir, "extension");
const outDir = path.join(frontendDir, "dist-extension");

// Same order as vite.config.ts: a stale compiled .js twin must never win over
// the TypeScript it shadows.
const resolve = { extensions: [".tsx", ".ts", ".jsx", ".mts", ".mjs", ".js", ".json"] };
const target = "chrome116";
const production = { "process.env.NODE_ENV": JSON.stringify("production") };

async function buildPages() {
  await build({
    configFile: false,
    root: extensionDir,
    base: "./",
    plugins: [react()],
    resolve,
    logLevel: "warn",
    build: {
      outDir,
      emptyOutDir: false,
      target,
      sourcemap: false,
      modulePreload: { polyfill: false },
      rollupOptions: {
        input: {
          sidepanel: path.join(extensionDir, "sidepanel.html"),
          connected: path.join(extensionDir, "connected.html"),
        },
      },
    },
  });
}

async function buildScript(entry, format, fileName) {
  await build({
    configFile: false,
    root: extensionDir,
    publicDir: false,
    resolve,
    define: production,
    logLevel: "warn",
    build: {
      outDir,
      emptyOutDir: false,
      target,
      sourcemap: false,
      lib: {
        entry: path.join(extensionDir, entry),
        formats: [format],
        name: format === "iife" ? "AlpharouterContent" : undefined,
        fileName: () => fileName,
      },
      rollupOptions: { output: { inlineDynamicImports: true } },
    },
  });
}

function writeManifestAndConfig() {
  const template = JSON.parse(fs.readFileSync(path.join(extensionDir, "manifest.template.json"), "utf8"));
  fs.writeFileSync(path.join(outDir, "manifest.json"), `${JSON.stringify(template, null, 2)}\n`);
  const config = { serverUrl: "", serverName: "", extensionVersion: "" };
  fs.writeFileSync(path.join(outDir, "config.json"), `${JSON.stringify(config, null, 2)}\n`);
  return template;
}

/** Every file the manifest refers to, so a broken build fails here and not in a browser. */
function referencedFiles(manifest) {
  const files = new Set(["manifest.json", "config.json", "content.js"]);
  for (const icon of Object.values(manifest.icons ?? {})) files.add(icon);
  for (const icon of Object.values(manifest.action?.default_icon ?? {})) files.add(icon);
  if (manifest.side_panel?.default_path) files.add(manifest.side_panel.default_path);
  if (manifest.background?.service_worker) files.add(manifest.background.service_worker);
  files.add("connected.html");
  return [...files];
}

async function main() {
  fs.rmSync(outDir, { recursive: true, force: true });
  fs.mkdirSync(outDir, { recursive: true });
  await buildPages();
  await buildScript("src/background.ts", "es", "background.js");
  await buildScript("src/content/content.ts", "iife", "content.js");
  const manifest = writeManifestAndConfig();
  const missing = referencedFiles(manifest).filter((file) => !fs.existsSync(path.join(outDir, file)));
  if (missing.length) {
    throw new Error(`the extension build is missing: ${missing.join(", ")}`);
  }
  console.log(`extension built in ${path.relative(process.cwd(), outDir) || outDir}`);
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
});
