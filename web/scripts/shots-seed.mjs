// Seeds the e2e backend with one path through the real screens (as e2e/learner.spec.ts does) and prints its
// URLs as JSON, for scripts/shots.mjs. Needs the same two servers running.
import { chromium } from "@playwright/test";

const WEB = "http://localhost:4173";
const API = "http://127.0.0.1:18775";
const CSRF = { "X-Yuo-Request": "1" };
const browser = await chromium.launch();
const context = await browser.newContext({ baseURL: WEB });
const code = (await (await context.request.get(`${API}/e2e/setup-code`)).json()).code;
await context.request.post("/api/auth/setup", { data: { code, device_label: "Seed" }, headers: CSRF });
const state = await (await context.request.get("/api/auth/state")).json();
if (!state.enrolled) await context.request.put("/api/auth/password", { data: { password: "shots password, long enough" }, headers: CSRF });
// the lesson rows this script waits for are in the list view (the graph is the default)
await context.addInitScript(() => localStorage.setItem("yuo.path.view", "list"));
const page = await context.newPage();
await page.goto("/paths/new");
await page.getByRole("textbox", { name: "Title" }).fill(process.argv[2] ?? "SQL for data analysis");
await page.getByRole("textbox", { name: "Your goal" }).fill(process.argv[3] ?? "Write joins and window functions with confidence");
await page.getByRole("button", { name: "Create path" }).click();
await page.waitForURL(/\/paths\/[0-9a-f-]+$/);
const path = new URL(page.url()).pathname;
for (let n = 1; n <= 8; n++) {
  await page.getByText(`Question ${n} of 8`).waitFor({ timeout: 15000 });
  await page.getByRole("button", { name: n % 3 === 0 ? "I don’t know yet" : `right ${n}` }).click();
}
await page.locator('li[data-state="ready"]').nth(2).waitFor({ timeout: 20000 });
const lesson = await page.locator('li[data-state="ready"] a').first().getAttribute("href");
console.log(JSON.stringify({ path, lesson }));
await browser.close();
