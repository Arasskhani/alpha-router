// Phase 3 lint gate. Flat config (ESLint 9). Rules are the recommended sets of
// each plugin; project-specific relaxations are listed with a reason.
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import jsxA11y from "eslint-plugin-jsx-a11y";
import globals from "globals";

export default tseslint.config(
  { ignores: ["dist/**", "dist-extension/**", "node_modules/**", "src/generated/**", "*.config.*", "scripts/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  jsxA11y.flatConfigs.recommended,
  {
    files: ["src/**/*.{ts,tsx}", "extension/src/**/*.{ts,tsx}"],
    plugins: { "react-hooks": reactHooks },
    languageOptions: {
      globals: { ...globals.browser, ...globals.es2022 },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Baseline (Phase 3): the React Compiler rules shipped with react-hooks 7
      // flag 130+ existing patterns (setState in effects, ref reads in render).
      // They stay visible as warnings; fixing them is Phase 4 ChatPanel work.
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/refs": "warn",
      "react-hooks/purity": "warn",
      "react-hooks/immutability": "warn",
      "react-hooks/exhaustive-deps": "warn",
      // a11y: every label is paired and every autofocus justified in place
      // (see scripts/codemods/pair-labels.py). What is left as warnings is the
      // interaction-role set below; the budget in package.json only goes down.
      // depth 3: label > span > strong > text is how this codebase writes a
      // wrapped checkbox/radio caption; the default of 2 misreads it as unlabelled.
      "jsx-a11y/label-has-associated-control": ["warn", { depth: 3 }],
      "jsx-a11y/no-autofocus": "warn",
      "jsx-a11y/click-events-have-key-events": "warn",
      "jsx-a11y/no-static-element-interactions": "warn",
      "jsx-a11y/no-noninteractive-element-interactions": "warn",
      "jsx-a11y/interactive-supports-focus": "warn",
      "jsx-a11y/media-has-caption": "warn",
      // `_`-prefixed names are the project's convention for intentionally unused values.
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrors: "none" }],
    },
  },
  {
    // The service worker scripts run in a worker, not in a page.
    files: ["public/**/*.js"],
    languageOptions: { sourceType: "script", globals: { ...globals.serviceworker } },
  },
  {
    files: ["src/**/*.test.{ts,tsx}", "src/test/**", "extension/src/**/*.test.{ts,tsx}", "extension/src/test/**"],
    languageOptions: { globals: { ...globals.node } },
  },
  {
    // The browser extension: its pages, service worker and content script all
    // see the WebExtension globals (chrome.*).
    files: ["extension/src/**/*.{ts,tsx}"],
    languageOptions: { globals: { ...globals.webextensions } },
  },
);
