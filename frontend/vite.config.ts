import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function generatePersianFonts() {
  const script = path.join(__dirname, "scripts", "generate-persian-fonts.mjs");
  const result = spawnSync(process.execPath, [script], {
    cwd: __dirname,
    stdio: "inherit",
  });
  if (result.status !== 0) {
    throw new Error("generate-persian-fonts.mjs failed");
  }
}

/** Regenerates the Persian font catalog from public/fonts on build / dev start. */
function persianFontsPlugin(): Plugin {
  const fontsDir = path.join(__dirname, "public", "fonts");
  let regenerating = false;

  const run = () => {
    if (regenerating) return;
    regenerating = true;
    try {
      generatePersianFonts();
    } finally {
      regenerating = false;
    }
  };

  return {
    name: "alpha-router-persian-fonts",
    buildStart() {
      run();
    },
    configureServer(server) {
      run();
      server.watcher.add(fontsDir);
      const onFontsChange = (file: string) => {
        const normalized = file.replace(/\\/g, "/");
        if (!normalized.includes("/public/fonts/") && !normalized.endsWith("/public/fonts")) {
          return;
        }
        // Ignore our own generated outputs.
        if (normalized.includes("/src/generated/")) return;
        run();
        server.ws.send({ type: "full-reload" });
      };
      server.watcher.on("add", onFontsChange);
      server.watcher.on("unlink", onFontsChange);
      server.watcher.on("change", onFontsChange);
    },
  };
}

export default defineConfig({
  plugins: [persianFontsPlugin(), react()],
  build: { outDir: "dist" },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
      },
    },
  },
});
