// A path from the learner's own material: courses, a PDF upload, reading, the plan per course with feedback,
// build, and a lesson that names the pages it comes from. The e2e backend's fake model plans and writes.
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, listView, test } from "./fixtures";

const here = path.dirname(fileURLToPath(import.meta.url));
const shots = process.env["YUO_SHOTS"];

test("a path from my own material, to a lesson built on it", async ({ page }) => {
  test.setTimeout(120_000);
  await listView(page);
  // naming the courses first is not offered in the app for now (the files come first): made through the API
  const made = await page.request.post("/api/studies", {
    headers: { "X-Yuo-Request": "1" },
    data: {
      title: "Mechanical Engineering",
      goal: "",
      courses: [{ title: "Analysis 1", adherence: "only", keep_order: true }],
    },
  });
  expect(made.ok()).toBe(true);
  const { path_id } = (await made.json()) as { path_id: string };
  await page.goto(`/paths/${path_id}`);
  await expect(page).toHaveURL(/\/paths\/[0-9a-f-]+$/);

  // upload: the file is read on this machine first, for free
  await expect(page.getByRole("heading", { name: "Your courses and material" })).toBeVisible();
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Choose files" }).click();
  await (await chooser).setFiles(path.join(here, "assets", "notes.pdf"));
  await expect(page.getByText("8 pages", { exact: true })).toBeVisible({ timeout: 20_000 });
  if (shots) await page.screenshot({ path: `${shots}/2-material.png`, fullPage: true });
  await page.getByRole("button", { name: "Read my material and plan" }).click();

  // the plan per course, changed with feedback before anything is written
  await expect(page.getByRole("heading", { name: "Your plan, course by course" })).toBeVisible();
  await expect(page.getByText("Skill 1").first()).toBeVisible({ timeout: 30_000 });
  if (shots) await page.screenshot({ path: `${shots}/3-plan.png`, fullPage: true });
  await page.getByRole("textbox", { name: /should go deeper in Analysis 1/ }).fill("Add a refresher on inequalities");
  await page.getByRole("button", { name: "Change the plan" }).click();
  await expect(page.getByText("Split the first skill in two.")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Added by Yuo")).toBeVisible();
  if (shots) await page.screenshot({ path: `${shots}/4-revised.png`, fullPage: true });
  await page.getByRole("button", { name: /Build the path/ }).click();

  // built: one branch per course; the first lesson says where in the file it comes from
  await expect(page.getByRole("heading", { name: "Analysis 1" })).toBeVisible({ timeout: 30_000 });
  const lesson = page.locator("li a[href^='/lessons/']").first();
  await expect(lesson).toBeVisible({ timeout: 30_000 });
  await lesson.click();
  await expect(page.getByRole("heading", { name: "From your material" })).toBeVisible({ timeout: 30_000 });
  const source = page.getByRole("link", { name: "notes" });
  await expect(source).toHaveAttribute("href", /\/api\/materials\/[0-9a-f-]+\/file#page=\d+/);
  if (shots) await page.screenshot({ path: `${shots}/5-lesson.png`, fullPage: true });
});
