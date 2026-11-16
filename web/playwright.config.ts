import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";

// Install the browser where e2e runs: `npx playwright install --with-deps --only-shell chromium`.
// The browser tests run against the real backend on a scripted model (scripts/e2e_server.py): no
// network, no cost, a fresh database per run, sign-in on (its origin is the preview's; e2e/fixtures.ts
// signs each test in). The app is the production build under `vite preview`, so the service worker and
// the manifest are the real ones.
const port = 4173;
const apiPort = 18775;

// Hosts where `--with-deps` cannot run can unpack the missing system libraries next to the browser
// (`apt-get download` the packages and `dpkg -x` them there); they are picked up from here.
const browsers = process.env["PLAYWRIGHT_BROWSERS_PATH"] ?? join(homedir(), ".cache", "ms-playwright");
const localLibs = join(browsers, "deps", "root", "usr", "lib", "x86_64-linux-gnu");
const env = existsSync(localLibs)
  ? { ...process.env, LD_LIBRARY_PATH: [localLibs, process.env["LD_LIBRARY_PATH"]].filter(Boolean).join(":") }
  : undefined;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false, // one backend, one database: tests build on each other's state
  workers: 1,
  forbidOnly: !!process.env["CI"],
  retries: process.env["CI"] ? 2 : 0,
  reporter: "list",
  use: {
    baseURL: `http://localhost:${port}`,
    trace: "on-first-retry",
    ...(env ? { launchOptions: { env } } : {}),
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `uv run scripts/e2e_server.py --port ${apiPort} --origin http://localhost:${port}`,
      cwd: "..",
      url: `http://127.0.0.1:${apiPort}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npm run build && npx vite preview --port ${port} --strictPort`,
      url: `http://localhost:${port}`,
      env: { YUO_API_URL: `http://127.0.0.1:${apiPort}` },
      reuseExistingServer: !process.env["CI"],
      timeout: 120_000,
    },
  ],
});
