// Fail when the code uses a message id that is missing from the committed
// catalogs, when an id is not an explicit dotted id, or when a catalog does not
// compile in strict mode (missing translations). Obsolete ids only warn.
// Runs extract/compile against scratch copies, so committed catalogs are untouched.
import { execFileSync } from "node:child_process";
import { cpSync, existsSync, mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { formatter } from "@lingui/format-po";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const catalogDir = join(root, "src", "locales");
const locales = readdirSync(catalogDir, { withFileTypes: true })
  .filter((d) => d.isDirectory())
  .map((d) => d.name);
const sourceLocale = "en";
const ID_PATTERN = /^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)+$/;
const lingui = join(root, "node_modules", ".bin", "lingui");
const po = formatter({ explicitIdAsDefault: true });

async function readCatalog(file, locale) {
  if (!existsSync(file)) return {};
  return (await po.parse(readFileSync(file, "utf8"), { locale, sourceLocale, filename: file })) ?? {};
}

function run(args, dir) {
  execFileSync(lingui, args, {
    cwd: root,
    env: { ...process.env, LINGUI_CATALOG_DIR: dir },
    stdio: ["ignore", "pipe", "inherit"],
  });
}

const scratch = mkdtempSync(join(tmpdir(), "yuo-i18n-check-"));
let failed = false;
try {
  const extracted = join(scratch, "extracted");
  run(["extract", "--clean"], extracted);

  for (const locale of locales) {
    const fromCode = await readCatalog(join(extracted, locale, "messages.po"), locale);
    const committed = await readCatalog(join(catalogDir, locale, "messages.po"), locale);
    const codeIds = Object.keys(fromCode);
    const missing = codeIds.filter((id) => !(id in committed));
    const badIds = codeIds.filter((id) => !ID_PATTERN.test(id));
    const obsolete = Object.keys(committed).filter((id) => !(id in fromCode));

    if (missing.length) {
      failed = true;
      console.error(`[${locale}] ids used in code but missing from the catalog (run npm run i18n:extract):`);
      for (const id of missing) console.error(`  - ${id}`);
    }
    if (badIds.length) {
      failed = true;
      console.error(`[${locale}] messages without an explicit dotted id (add id="area.name"):`);
      for (const id of badIds) console.error(`  - ${id}: ${JSON.stringify(fromCode[id]?.message ?? "")}`);
    }
    // the English catalog keeps the text an id first had: a message reworded in the code under the same id would
    // still show the old words (it happened twice, 2026-11-15), so English must match the code
    if (locale === sourceLocale) {
      const stale = codeIds.filter((id) => id in committed && committed[id].translation !== fromCode[id].translation);
      if (stale.length) {
        failed = true;
        console.error(`[${locale}] English text differs from the code (run npx lingui extract --overwrite):`);
        for (const id of stale) console.error(`  - ${id}`);
      }
    }
    for (const id of obsolete) console.warn(`[${locale}] warning: obsolete id in catalog: ${id}`);
    console.log(`[${locale}] ${codeIds.length} ids in code, ${Object.keys(committed).length} in catalog`);
  }

  // Strict compile of a copy of the committed catalogs: fails on missing translations.
  const compiled = join(scratch, "compiled");
  cpSync(catalogDir, compiled, { recursive: true });
  try {
    run(["compile", "--strict"], compiled);
  } catch {
    failed = true;
    console.error("lingui compile --strict failed (missing translations or invalid ICU)");
  }
} finally {
  rmSync(scratch, { recursive: true, force: true });
}

if (failed) {
  console.error("i18n:check FAILED");
  process.exit(1);
}
console.log("i18n:check OK");
