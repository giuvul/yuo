// The installable app in the production build: the web app manifest, the service
// worker registering and precaching the shell, and nothing from /api in its caches.
import { expect, test } from "./fixtures";

test("the manifest and the service worker register; the shell is precached, /api is not", async ({ page }) => {
  await page.goto("/paths");
  await expect(page.getByRole("heading", { level: 1, name: "Your paths" })).toBeVisible();

  const href = await page.locator('link[rel="manifest"]').getAttribute("href");
  expect(href).toBe("/manifest.webmanifest");
  const manifest = (await (await page.request.get(href!)).json()) as {
    name: string;
    short_name: string;
    start_url: string;
    display: string;
    icons: { src: string; sizes: string; purpose?: string }[];
  };
  expect(manifest).toMatchObject({ name: "Yuo", short_name: "Yuo", start_url: "/", display: "standalone" });
  expect(manifest.icons.map((i) => `${i.sizes} ${i.purpose ?? "any"}`)).toEqual(
    expect.arrayContaining(["192x192 any", "512x512 any", "512x512 maskable"]),
  );
  for (const icon of manifest.icons) {
    const res = await page.request.get(`/${icon.src}`);
    expect(res.ok(), icon.src).toBe(true);
  }

  const script = await page.evaluate(async () => (await navigator.serviceWorker.ready).active?.scriptURL);
  expect(script).toMatch(/\/sw\.js$/);
  // the precache fills while the worker installs; the shell is there once it is active
  await expect
    .poll(async () =>
      page.evaluate(async () => {
        const urls: string[] = [];
        for (const name of await caches.keys()) {
          for (const r of await (await caches.open(name)).keys()) urls.push(new URL(r.url).pathname);
        }
        return urls;
      }),
    )
    .toEqual(expect.arrayContaining(["/index.html", "/manifest.webmanifest"]));
  // sign-in and learning data never come from a cache
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Your paths" })).toBeVisible();
  const cached = await page.evaluate(async () => {
    const urls: string[] = [];
    for (const name of await caches.keys()) {
      for (const r of await (await caches.open(name)).keys()) urls.push(new URL(r.url).pathname);
    }
    return urls;
  });
  expect(cached.filter((u) => u.startsWith("/api"))).toEqual([]);
});
