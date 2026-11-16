import { expect, test } from "./fixtures";

test("header shows the app name", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Yuo" })).toBeVisible();
});

test("links styled as buttons keep readable text", async ({ page }) => {
  // the cascade layer order once put component styles below the base `a` colour (accent on accent)
  await page.goto("/");
  const [color, background] = await page
    .getByRole("link", { name: "New path" })
    .evaluate((e) => [getComputedStyle(e).color, getComputedStyle(e).backgroundColor]);
  expect(color).not.toBe(background);
});
