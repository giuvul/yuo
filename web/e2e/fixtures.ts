// Sign-in for the browser tests (the e2e backend runs with sign-in on, like the shipped app).
// Every test's browser context starts signed in: a one-time setup code from the e2e backend's test-only
// route (the shipped server prints it to its console) is redeemed through the API, which signs that
// context in as a new device. auth.spec.ts runs first (files run in name order) and enrols the install
// through the real first-run screens; run alone, another file enrols it here with a password.
import { request, test as base, expect, type BrowserContext, type Page } from "@playwright/test";

export const API_PORT = 18775;
export const WEB_PORT = 4173;
export const E2E_PASSWORD = "e2e password, long enough";
export const CSRF = { "X-Yuo-Request": "1" };

/** A fresh one-time setup code (older unused ones stop working). */
export async function setupCode(): Promise<string> {
  const api = await request.newContext();
  try {
    const res = await api.get(`http://127.0.0.1:${API_PORT}/e2e/setup-code`);
    expect(res.ok()).toBe(true);
    return ((await res.json()) as { code: string }).code;
  } finally {
    await api.dispose();
  }
}

/** Signs the context in with a setup code; enrols a password first if nothing is enrolled yet. */
export async function signIn(context: BrowserContext, label = "Playwright"): Promise<void> {
  const res = await context.request.post("/api/auth/setup", {
    data: { code: await setupCode(), device_label: label },
    headers: CSRF,
  });
  expect(res.ok(), await res.text()).toBe(true);
  const state = (await (await context.request.get("/api/auth/state")).json()) as { enrolled: boolean };
  if (!state.enrolled) {
    const put = await context.request.put("/api/auth/password", { data: { password: E2E_PASSWORD }, headers: CSRF });
    expect(put.ok()).toBe(true);
  }
}

/**
 * Opens path pages in their list view (the graph is the default): for tests that read lesson rows and the
 * per-skill actions straight from the page. Sets the viewer's saved choice, as the List switch does.
 */
export async function listView(page: Page): Promise<void> {
  await page.addInitScript(() => localStorage.setItem("yuo.path.view", "list"));
}

export const test = base.extend({
  context: async ({ context }, use) => {
    await signIn(context);
    await use(context);
  },
});

export { expect };
