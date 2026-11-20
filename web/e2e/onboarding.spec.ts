// The environment wizard through the real backend, on its fakes (scripts/e2e_server.py): a fixed
// probe without a GPU or subscription apps, so the recommendation is Qwen through OpenRouter; the key check
// accepts only "sk-or-v1-e2e". The full wizard: probe, recommendation with the estimate, key
// refused then accepted, the profile with the dark theme, the first path, onboarding done. Then the same
// screens at 360 px, and the wizard with the learner's own Anthropic key (the fake accepts "sk-ant-e2e").
// Onboarding counts as finished when the server starts; these tests undo it first and
// leave the install as the other files expect it (scripted model bound, theme "system", onboarding done).
import { request, type Page } from "@playwright/test";
import { API_PORT, CSRF, expect, test } from "./fixtures";

test.describe.configure({ mode: "serial" });

async function backend(path: string): Promise<void> {
  const api = await request.newContext();
  try {
    const res = await api.post(`http://127.0.0.1:${API_PORT}${path}`, { headers: CSRF });
    expect(res.ok(), await res.text()).toBe(true);
  } finally {
    await api.dispose();
  }
}

async function fits(page: Page, what: string): Promise<void> {
  const [scroll, width] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(scroll, `${what} is ${scroll}px wide`).toBeLessThanOrEqual(width);
}

const step = (page: Page, name: string) => page.getByRole("heading", { level: 2, name });

/** The videos step: YouTube is offered first, with what the learner takes on; chosen and saved. Then put back
 * to videos made by Yuo, as the other files expect. */
async function throughVideos(page: Page, onStep?: (what: string) => Promise<void>): Promise<void> {
  await expect(step(page, "Videos")).toBeVisible();
  const youtube = page.getByRole("radio", { name: /Videos from YouTube/ });
  await youtube.locator("xpath=ancestor::label").click(); // first on a new install; chosen again here
  await expect(youtube).toBeChecked();
  await expect(page.getByText(/You use this at your own risk/)).toBeVisible();
  await onStep?.("videos");
  await page.getByRole("button", { name: "Save and continue" }).click();
}

async function videosMadeByYuo(page: Page): Promise<void> {
  const res = await page.request.put("/api/settings/video.source", {
    data: { value: "generated", level: "learner" },
    headers: CSRF,
  });
  expect(res.ok(), await res.text()).toBe(true);
}

async function throughKey(page: Page, onEachStep?: (what: string) => Promise<void>): Promise<void> {
  await page.goto("/setup");
  await expect(page.getByRole("heading", { level: 1, name: "Set up Yuo" })).toBeVisible();
  await expect(step(page, "Your computer")).toBeVisible();
  await expect(page.getByText("Nothing leaves this computer", { exact: false })).toBeVisible();
  await expect(page.getByText("Windows 11")).toBeVisible();
  await expect(page.getByText("About 351 billion calculations a second")).toBeVisible();
  await onEachStep?.("your computer");
  await page.getByRole("button", { name: "Next" }).click();

  await expect(step(page, "Recommendation")).toBeVisible();
  const open = page.getByRole("radio", { name: /Qwen 3.8 27B through OpenRouter \(pay per use\)/ });
  await expect(open).toBeChecked();
  await expect(page.getByTestId("estimate-open")).toContainText(/For a typical 20-lesson path: about \$\d+\.\d\d to \$\d+\.\d\d, billed to you\./);
  await page.getByRole("button", { name: "Why this one?" }).click(); // the reasons are tucked away
  await expect(page.getByText(/OpenRouter charges your OpenRouter account/)).toBeVisible();
  await onEachStep?.("the recommendation");
  await page.getByRole("button", { name: "Next" }).click();

  await expect(step(page, "AI access")).toBeVisible();
  await expect(page.getByRole("link", { name: /openrouter.ai\/keys/ })).toHaveAttribute("target", "_blank");
  const key = page.getByLabel("OpenRouter key", { exact: true });
  await key.fill("sk-or-v1-wrong");
  await page.getByRole("button", { name: "Check and save the key" }).click();
  await expect(page.getByText(/OpenRouter did not accept this key/)).toBeVisible();
  await key.fill("sk-or-v1-e2e");
  await page.getByRole("button", { name: "Check and save the key" }).click();
  await expect(page.getByText("Credit left on this key: $4.50")).toBeVisible();
  await expect(key).toHaveValue("");
  await onEachStep?.("AI access");
  await page.getByRole("button", { name: "Use this and continue" }).click();
  await expect(page.getByText(/Done. Yuo uses Qwen 3.8 27B through OpenRouter/)).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(step(page, "About you")).toBeVisible();
}

test.beforeAll(async () => {
  await backend("/e2e/onboarding/reset");
});

test.afterAll(async () => {
  await backend("/e2e/models/reset"); // the open preset rebound the roles: the scripted model again
});

test("the full wizard on the open-models option, to the first path", async ({ page }) => {
  await throughKey(page);

  // about you: the dark theme applies at once and wins over the system setting
  await page.emulateMedia({ colorScheme: "light" });
  await page.getByText("Dark", { exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator("body")).toHaveCSS("background-color", "rgb(15, 29, 23)"); // Grove forest-night #0F1D17
  await page.getByRole("textbox", { name: "Your name" }).fill("Ada");
  await page.getByRole("button", { name: "Session length and interests (optional)" }).click();
  await page.getByRole("textbox", { name: /Your interests/ }).fill("cycling and cooking");
  await page.getByRole("button", { name: "Save and continue" }).click();
  await throughVideos(page);
  const source = (await (await page.request.get("/api/settings")).json()) as { key: string; value: unknown }[];
  expect(source.find((x) => x.key === "video.source")?.value).toBe("youtube");
  await videosMadeByYuo(page);

  await expect(step(page, "Your first path")).toBeVisible();
  await expect(page.getByText(/Estimated cost for 20 lessons/)).toBeVisible();
  await page.getByRole("textbox", { name: "Title" }).fill("Spanish");
  await page.getByRole("textbox", { name: "Your goal" }).fill("Order food in a restaurant");
  await page.getByRole("button", { name: "Create path" }).click();
  await expect(page).toHaveURL(/\/paths\/[0-9a-f-]+$/);

  const onboarding = (await (await page.request.get("/api/onboarding")).json()) as Record<string, boolean>;
  expect(onboarding).toMatchObject({ probed: true, models_chosen: true, profile_done: true, has_path: true, done: true });
  const me = (await (await page.request.get("/api/me")).json()) as { display_name: string; theme: string };
  expect(me).toMatchObject({ display_name: "Ada", theme: "dark" });

  // the theme survives a reload (localStorage copy before the API answers), and Home has no setup notice
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.getByRole("link", { name: "Finish setting up" })).toHaveCount(0);
});

test("the wizard fits a phone screen, and Home offers to finish setting up", async ({ page }) => {
  await backend("/e2e/onboarding/reset");
  await page.setViewportSize({ width: 360, height: 740 });
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Finish setting up" })).toBeVisible(); // has paths: not trapped
  await fits(page, "Home");

  await throughKey(page, (what) => fits(page, what));
  await fits(page, "about you");
  await page.getByRole("button", { name: "Save and continue" }).click();
  await throughVideos(page, (what) => fits(page, what));
  await videosMadeByYuo(page);
  await expect(step(page, "Your first path")).toBeVisible();
  await fits(page, "your first path");

  // leave the install as the other files expect it (interests would make later paths personal content)
  expect((await page.request.post("/api/onboarding/done", { headers: CSRF })).ok()).toBe(true);
  expect((await page.request.patch("/api/me", { data: { theme: "system", interests: "" }, headers: CSRF })).ok()).toBe(true);
});

test("the wizard with your own API key from a model vendor, to the first path", async ({ page }) => {
  await backend("/e2e/onboarding/reset");
  await page.setViewportSize({ width: 360, height: 740 }); // the whole flow at phone width
  await page.goto("/setup");
  await expect(step(page, "Your computer")).toBeVisible();
  await expect(page.getByText("Windows 11")).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();

  await expect(step(page, "Recommendation")).toBeVisible();
  const own = page.getByRole("radio", { name: /Your own API key from a model vendor/ });
  await expect(page.getByRole("radio").last()).toHaveAccessibleName(/Your own API key from a model vendor/);
  await own.locator("xpath=ancestor::label").click();
  await expect(own).toBeChecked();
  await fits(page, "the recommendation with the own-key option");
  await page.getByRole("button", { name: "Next" }).click();

  await expect(step(page, "AI access")).toBeVisible();
  await page.getByRole("radio", { name: "Anthropic (Claude)" }).locator("xpath=ancestor::label").click();
  await expect(page.getByRole("link", { name: /Create a key on the Anthropic \(Claude\) website/ })).toHaveAttribute(
    "target",
    "_blank",
  );
  const key = page.getByLabel("Anthropic (Claude) key", { exact: true });
  await key.fill("sk-ant-wrong");
  await page.getByRole("button", { name: "Check key" }).click();
  await expect(page.getByText(/Anthropic \(Claude\) did not accept this key/)).toBeVisible();
  await key.fill("sk-ant-e2e");
  await page.getByRole("button", { name: "Check key" }).click();
  await expect(page.getByText(/Anthropic \(Claude\) accepted the key/)).toBeVisible();

  await expect(page.getByRole("button", { name: /Model that writes lessons and answers$/ })).toContainText("claude-sonnet-5-5");
  await expect(page.getByRole("button", { name: /Model that checks lessons$/ })).toContainText("claude-opus-5-5");
  await expect(page.getByTestId("vendor-estimate")).toContainText(
    /For a typical 20-lesson path: about \$\d+\.\d\d to \$\d+\.\d\d, billed to you by Anthropic \(Claude\)\./,
  );
  await fits(page, "the vendor's models");
  await page.getByRole("button", { name: "Use this and continue" }).click();
  await expect(page.getByText("Done. Yuo uses these models from Anthropic (Claude) from now on.")).toBeVisible();
  await expect(page.getByText(/claude-sonnet-5-5 has not been tested with Yuo/)).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();

  await expect(step(page, "About you")).toBeVisible();
  await page.getByRole("button", { name: "Save and continue" }).click();
  await expect(step(page, "Videos")).toBeVisible(); // chosen before: kept as it is
  await expect(page.getByRole("radio", { name: /Videos made by Yuo|Videos from YouTube/ }).first()).toBeVisible();
  await page.getByRole("button", { name: "Save and continue" }).click();
  await expect(step(page, "Your first path")).toBeVisible();
  await expect(page.getByText(/Estimated cost for 20 lessons/)).toBeVisible();
  await page.getByRole("textbox", { name: "Title" }).fill("Knots");
  await page.getByRole("textbox", { name: "Your goal" }).fill("Tie a bowline");
  await page.getByRole("button", { name: "Create path" }).click();
  await expect(page).toHaveURL(/\/paths\/[0-9a-f-]+$/);

  const setup = (await (await page.request.get("/api/setup")).json()) as { bindings: Record<string, { adapter: string; model: string }> };
  expect(setup.bindings["generator"]).toMatchObject({ adapter: "api:anthropic", model: "claude-sonnet-5-5" });
  expect(setup.bindings["reviewer"]).toMatchObject({ adapter: "api:anthropic", model: "claude-opus-5-5" });
});
