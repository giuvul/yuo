import { readdirSync } from "node:fs";
import { defineConfig } from "@lingui/conf";
import { formatter } from "@lingui/format-po";

// Every folder under src/locales is a shipped locale (src/locales/README.md).
const locales = readdirSync(new URL("./src/locales", import.meta.url), { withFileTypes: true })
  .filter((d) => d.isDirectory())
  .map((d) => d.name)
  .sort();

// Explicit message ids (dotted, e.g. "app.name"), ICU MessageFormat, PO catalogs.
// LINGUI_CATALOG_DIR lets scripts/i18n-check.mjs extract into a scratch dir.
const catalogDir = process.env.LINGUI_CATALOG_DIR ?? "<rootDir>/src/locales";

export default defineConfig({
  sourceLocale: "en",
  locales,
  fallbackLocales: { default: "en" },
  catalogs: [
    {
      path: `${catalogDir}/{locale}/messages`,
      include: ["<rootDir>/src"],
      exclude: ["**/node_modules/**", "**/*.test.*"],
    },
  ],
  format: formatter({ lineNumbers: false, explicitIdAsDefault: true }),
  compileNamespace: "ts",
});
