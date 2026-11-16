// Generates src/api/schema.d.ts from src/api/openapi.json with openapi-typescript.
// openapi-typescript needs the TypeScript 5 JS API; the app is on TypeScript 7 (no JS API),
// so the generator lives in its own small install: tools/api-types (own lockfile, same
// supply-chain rules). Install it once with: npm ci --prefix tools/api-types
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const cli = join(root, "tools", "api-types", "node_modules", "openapi-typescript", "bin", "cli.js");
if (!existsSync(cli)) {
  console.error("openapi-typescript is not installed. Run: npm ci --prefix tools/api-types");
  process.exit(1);
}
execFileSync(process.execPath, [cli, "src/api/openapi.json", "-o", "src/api/schema.d.ts"], {
  cwd: root,
  stdio: "inherit",
});
