// Draws the PWA icons (PNG) from the app's own SVGs in public/ with the Playwright browser:
// `node scripts/icons.mjs`. Run it after changing an SVG and commit the PNGs (the build does not run it).
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const pub = join(root, "public");
const browsers = process.env["PLAYWRIGHT_BROWSERS_PATH"] ?? join(homedir(), ".cache", "ms-playwright");
const localLibs = join(browsers, "deps", "root", "usr", "lib", "x86_64-linux-gnu");
const env = existsSync(localLibs)
  ? { ...process.env, LD_LIBRARY_PATH: [localLibs, process.env["LD_LIBRARY_PATH"]].filter(Boolean).join(":") }
  : process.env;

const jobs = [
  ["icon.svg", "icon-192.png", 192],
  ["icon.svg", "icon-512.png", 512],
  ["icon-maskable.svg", "apple-touch-icon.png", 180],
  ["icon-maskable.svg", "icon-maskable-512.png", 512],
];

const browser = await chromium.launch({ env });
try {
  for (const [svg, png, size] of jobs) {
    const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
    const data = Buffer.from(readFileSync(join(pub, svg))).toString("base64");
    await page.setContent(
      `<html><body style="margin:0;background:transparent"><img src="data:image/svg+xml;base64,${data}" width="${size}" height="${size}" style="display:block"></body></html>`,
    );
    await page.locator("img").evaluate((img) => img.decode());
    await page.screenshot({ path: join(pub, png), omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } });
    await page.close();
    console.log(`wrote public/${png}`);
  }
} finally {
  await browser.close();
}
