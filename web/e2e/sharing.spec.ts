// Sharing through the real backend: export a generated path as a package from the "Share or
// export" dialog, import that same file as a new path, and see a broken file refused.
import { readFile } from "node:fs/promises";
import type { APIRequestContext } from "@playwright/test";
import { CSRF, expect, listView, test } from "./fixtures";

type PathOut = {
  id: string;
  title: string;
  branches: { skills: { lessons: { code: string; title: string | null; state: string }[] }[] }[];
};

/** The ready lessons of a path as "code: title", sorted. */
async function readyLessons(request: APIRequestContext, pathId: string): Promise<string[]> {
  const path = (await (await request.get(`/api/paths/${pathId}`)).json()) as PathOut;
  return path.branches
    .flatMap((b) => b.skills.flatMap((s) => s.lessons))
    .filter((l) => l.state === "ready")
    .map((l) => `${l.code}: ${l.title ?? ""}`)
    .sort();
}

test.describe.configure({ mode: "serial" });

const READY = '[data-state="ready"]';
let sourceId = "";
let packageFile = "";

test("share a generated path: preview, then download the package", async ({ page }, testInfo) => {
  const created = await page.request.post("/api/paths", {
    data: { title: "Joins to share", subject: "SQL joins", goal: "Help my team at work with joins" },
    headers: CSRF,
  });
  expect(created.ok()).toBe(true);
  sourceId = ((await created.json()) as { path_id: string }).path_id;
  await listView(page);
  await page.goto(`/paths/${sourceId}`);
  await expect(page.locator(`li${READY}`)).toHaveCount(3, { timeout: 20_000 });

  await page.getByRole("button", { name: "Share or export" }).click();
  const dialog = page.getByRole("dialog", { name: "Share or export this path" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("radio", { name: /Ready to study/ })).toBeChecked();
  await expect(dialog.getByText(/\d+ skills?, .*\d+ lessons?/)).toBeVisible();
  await expect(dialog.getByText("Help my team at work with joins")).toBeVisible();
  await expect(dialog.getByText("Check this before sharing: it often says something about you.")).toBeVisible();
  await expect(dialog.getByText(/code Yuo wrote to make them is never shared/)).toBeVisible();

  // the structure profile has no videos; back to ready to study for the download
  const asked = page.waitForRequest((r) => r.url().endsWith("/export-preview") && r.postDataJSON().profile === "structure");
  await dialog.getByText("Structure and texts").click();
  await asked;
  await dialog.getByText("Ready to study").click();

  const download = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Download" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("Joins-to-share.yuo.zip");
  packageFile = testInfo.outputPath(file.suggestedFilename());
  await file.saveAs(packageFile);
  await expect(dialog.getByText(/Saved as Joins-to-share\.yuo\.zip/)).toBeVisible();
  const bytes = await readFile(packageFile);
  expect(bytes.subarray(0, 2).toString()).toBe("PK");

  await dialog.getByRole("button", { name: "Close" }).click();
  await expect(dialog).toBeHidden();
});

test("the dialog fits a phone screen", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await page.goto(`/paths/${sourceId}`);
  await page.getByRole("button", { name: "Share or export" }).click();
  const dialog = page.getByRole("dialog", { name: "Share or export this path" });
  await dialog.getByText("Choose parts").click();
  await expect(dialog.getByText("Help my team at work with joins")).toBeVisible();
  if (process.env["E2E_SHOTS"]) await page.screenshot({ path: `${process.env["E2E_SHOTS"]}/share-360.png`, fullPage: true });
  const [scroll, width] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(scroll).toBeLessThanOrEqual(width);
  const box = await dialog.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(360);
  // Escape closes it and gives focus back to the button
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("button", { name: "Share or export" })).toBeFocused();
});

test("import the downloaded package as a new path with the same lessons", async ({ page }) => {
  await listView(page);
  expect(packageFile).not.toBe("");
  await page.goto("/paths");
  await page.getByRole("link", { name: "Import a path" }).click();
  await expect(page).toHaveURL(/\/import$/);
  await page.locator('input[type="file"]').setInputFiles(packageFile);

  await expect(page.getByRole("heading", { name: "Joins to share", level: 2 })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Ready to study")).toBeVisible();
  await expect(page.getByText(/Skills and structure, Lesson texts/)).toBeVisible();
  await expect(page.getByText("English")).toBeVisible();
  await expect(page.getByText(/This package is not signed/)).toBeVisible();
  // an export, never imported here: only a new copy is possible
  await expect(page.getByRole("button", { name: "Update that path" })).toHaveCount(0);
  if (process.env["E2E_SHOTS"]) await page.screenshot({ path: `${process.env["E2E_SHOTS"]}/import.png`, fullPage: true });
  await page.getByRole("button", { name: "Import as a new path" }).click();

  await expect(page).toHaveURL(/\/paths\/[0-9a-f-]+$/, { timeout: 15_000 });
  const newId = new URL(page.url()).pathname.split("/").pop()!;
  expect(newId).not.toBe(sourceId);
  await expect(page.getByRole("heading", { name: "Joins to share", level: 1 })).toBeVisible();
  const source = await readyLessons(page.request, sourceId);
  expect(source.length).toBeGreaterThanOrEqual(3);
  // the same lessons (codes and titles), ready to read right away
  expect(await readyLessons(page.request, newId)).toEqual(source);
  await expect(page.locator(`li${READY}`)).toHaveCount(source.length);
  const titles = source.map((s) => s.slice(s.indexOf(": ") + 2));
  expect((await page.locator(`li${READY} a`).allTextContents()).sort()).toEqual(titles.sort());
});

test("a file that is not a package is refused and nothing is imported", async ({ page }) => {
  const before = ((await (await page.request.get("/api/paths")).json()) as unknown[]).length;
  await page.goto("/import");
  await page.locator('input[type="file"]').setInputFiles({
    name: "broken.yuo.zip",
    mimeType: "application/zip",
    buffer: Buffer.from("these bytes are not a zip archive"),
  });
  await expect(page.getByText("Yuo cannot import broken.yuo.zip.")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/^Reason: /)).toBeVisible();
  await expect(page.getByText("Nothing was imported.")).toBeVisible();
  const after = ((await (await page.request.get("/api/paths")).json()) as unknown[]).length;
  expect(after).toBe(before);
});
