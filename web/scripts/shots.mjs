// Screenshots of the built app for design review (not a test): each page at 1200 px light and 390 px dark.
//
//   node scripts/shots.mjs <out dir> name=/url [name=/url@anon] [name=/url@full] ...
//
// Needs the e2e backend and the preview running (see playwright.config.ts):
//   uv run scripts/e2e_server.py --port 18775 --origin http://localhost:4173        (in the project root)
//   YUO_API_URL=http://127.0.0.1:18775 npx vite preview --port 4173 --strictPort    (in web/)
// "@anon" opens the page signed out; "@full" captures the whole page instead of the first screen.
// An optional `SHOTS_SETUP=<module>` exports `default async (page, name)` to prepare a page before its shot.
import { mkdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { chromium } from "@playwright/test";

const [out, ...specs] = process.argv.slice(2);
if (!out || !specs.length) throw new Error("usage: node scripts/shots.mjs <out dir> name=/url ...");
mkdirSync(out, { recursive: true });
const WEB = "http://localhost:4173";
const API = "http://127.0.0.1:18775";
const CSRF = { "X-Yuo-Request": "1" };
const setup = process.env.SHOTS_SETUP ? (await import(resolve(process.env.SHOTS_SETUP))).default : null;

const browser = await chromium.launch();
for (const [width, height, scheme] of [[1200, 900, "light"], [390, 844, "dark"]]) {
  for (const spec of specs) {
    const [name, rest] = spec.split("=");
    const [url, ...flags] = rest.split("@");
    const context = await browser.newContext({ viewport: { width, height }, colorScheme: scheme, baseURL: WEB, reducedMotion: "reduce" });
    if (!flags.includes("anon")) {
      const code = (await (await context.request.get(`${API}/e2e/setup-code`)).json()).code;
      await context.request.post("/api/auth/setup", { data: { code, device_label: "Shots" }, headers: CSRF });
      const state = await (await context.request.get("/api/auth/state")).json();
      if (!state.enrolled) await context.request.put("/api/auth/password", { data: { password: "shots password, long enough" }, headers: CSRF });
    }
    const page = await context.newPage();
    await page.goto(url, { waitUntil: "networkidle" });
    if (setup) await setup(page, name);
    await page.waitForTimeout(400);
    await page.screenshot({ path: join(out, `${name}-${width}-${scheme}.png`), fullPage: flags.includes("full") });
    await context.close();
  }
}
await browser.close();
console.log(`shots: wrote ${specs.length * 2} files to ${out}`);
