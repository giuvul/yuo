// Review through the real backend on the scripted model: study a lesson, open the path's review hub once its
// questions are written, play a whole Quick session (a wrong try then the right one, "Show answer", then answers
// with the keyboard only) and read the results. The whole run is on a phone-sized screen and never scrolls sideways.
import type { Page } from "@playwright/test";
import { CSRF, expect, listView, test } from "./fixtures";

type Option = { id: string; text: string };
type Item = { item_version_id: string; view: { prompt: string; options: Option[] }; objectives: string[] };
type Session = { assessment_id: string | null; attempt_id: string | null; items: Item[]; reserves: Item[] };
type Hub = { memory: number | null; questions: number; sizes: number[]; writing: number };

const READY = '[data-state="ready"]';

async function fits(page: Page, what: string): Promise<void> {
  const [scroll, width] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(scroll, `${what} is ${scroll}px wide`).toBeLessThanOrEqual(width);
}

/** The question on screen (its heading carries the item version id) with the position of its right answer. */
async function current(page: Page, session: Session): Promise<{ item: Item; right: number; wrong: number }> {
  const id = await page.locator('h2[id^="review-q-"]').getAttribute("id");
  const item = [...session.items, ...session.reserves].find((i) => `review-q-${i.item_version_id}` === id);
  expect(item, `question ${id} is part of the session`).toBeTruthy();
  const key = (await (await page.request.get(`/api/_e2e/key/${item!.item_version_id}`)).json()) as { answer: string };
  const right = item!.view.options.findIndex((o) => o.id === key.answer);
  expect(right).toBeGreaterThanOrEqual(0);
  return { item: item!, right, wrong: right === 0 ? 1 : 0 };
}

const option = (page: Page, index: number) => page.locator(`button[data-option="${"ABCD"[index]}"]`);

test("study a lesson, then play a Quick review session to its results on a phone", async ({ page }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 390, height: 844 });
  const created = await page.request.post("/api/paths", {
    data: { title: "Joins to review", subject: "SQL joins", goal: "Remember joins for good" },
    headers: CSRF,
  });
  expect(created.ok()).toBe(true);
  const pathId = ((await created.json()) as { path_id: string }).path_id;

  // nothing studied yet: the hub explains itself
  await page.goto(`/paths/${pathId}/review`);
  await expect(page.getByRole("heading", { name: "Nothing to review yet" })).toBeVisible();

  // study the first lesson
  await listView(page);
  await page.goto(`/paths/${pathId}`);
  await expect(page.locator(`li${READY}`)).toHaveCount(3, { timeout: 20_000 });
  await page.locator(`li${READY} a`).first().click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.getByText("Lesson marked as done.")).toBeVisible();

  // its questions are written by a background job: wait until the hub has some
  // the review bank is a background job: on a busy CI machine it waits behind the other tests' lessons
  await expect
    .poll(async () => ((await (await page.request.get(`/api/paths/${pathId}/review`)).json()) as Hub).questions, { timeout: 90_000 })
    .toBeGreaterThan(0);

  // the path page now carries the Review card, which leads to the hub
  await page.goto(`/paths/${pathId}`);
  const card = page.locator("section", { has: page.getByRole("heading", { name: "Review", exact: true }) });
  await card.getByRole("link", { name: "Open review" }).click();
  await expect(page).toHaveURL(new RegExp(`/paths/${pathId}/review$`));
  await expect(page.getByRole("img", { name: /^Memory: \d+%$/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Memory by skill" })).toBeVisible();
  await fits(page, "the review hub");

  const started = page.waitForResponse((r) => r.url().endsWith("/review/sessions") && r.request().method() === "POST");
  await page.getByRole("link", { name: "Quick 5" }).click();
  const session = (await (await started).json()) as Session;
  expect(session.items).toHaveLength(5);
  await expect(page.getByText("Question 1 of 5")).toBeVisible();
  await fits(page, "the player");

  // 1: a wrong try shows why that option is wrong and nothing else; the second try is right
  let q = await current(page, session);
  await option(page, q.wrong).click();
  await page.getByRole("button", { name: "Check answer" }).click();
  await expect(page.getByText("Not quite. One more try.")).toBeVisible();
  await expect(option(page, q.wrong)).toBeDisabled();
  await expect(page.getByText("Right answer")).toHaveCount(0);
  await fits(page, "the player after a wrong try");
  await option(page, q.right).click();
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("Right on the second try.")).toBeVisible();
  await expect(option(page, q.right)).toContainText("Right answer");
  await fits(page, "the resolved question");
  await page.getByRole("button", { name: "Next", exact: true }).click();

  // 2: a wrong try, then "Show answer"
  await expect(page.getByText("Question 2 of 5")).toBeVisible();
  q = await current(page, session);
  const shown = q.item;
  await option(page, q.wrong).click();
  await page.getByRole("button", { name: "Check answer" }).click();
  await expect(page.getByText("Not quite. One more try.")).toBeVisible();
  await page.getByRole("button", { name: "Show answer" }).click();
  await expect(page.getByText("Here is the answer.")).toBeVisible();
  await expect(option(page, q.right)).toContainText("Right answer");
  await page.getByRole("button", { name: "Next", exact: true }).click();

  // 3 to 5, and any question asked again: the keyboard only (a digit or a letter chooses, Enter checks and goes on)
  let asked = 2;
  for (;;) {
    asked += 1;
    await expect(page.getByText(new RegExp(`^Question ${asked} of \\d+$`))).toBeVisible();
    q = await current(page, session);
    await page.keyboard.press(asked % 2 ? String(q.right + 1) : "abcd"[q.right]!);
    await expect(option(page, q.right)).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.press("Enter");
    await expect(page.getByText("Right, first try.")).toBeVisible();
    if (await page.getByRole("button", { name: "See results" }).isVisible()) break;
    await page.keyboard.press("Enter");
  }
  // the reserve of the revealed question's objective was asked again, if the bank had one
  const reserve = session.reserves.some((r) => r.objectives.some((o) => shown.objectives.includes(o)));
  expect(asked).toBe(reserve ? 6 : 5);
  await page.keyboard.press("Enter"); // the feedback stays until "See results", which has the focus

  await expect(page.getByRole("heading", { name: "Session done" })).toBeVisible();
  await expect(page.locator("dl > div", { hasText: "First try" }).locator("dd")).toHaveText(String(asked - 2));
  await expect(page.locator("dl > div", { hasText: "Second try" }).locator("dd")).toHaveText("1");
  await expect(page.locator("dl > div", { hasText: "Shown" }).locator("dd")).toHaveText("1");
  const again = page.locator("div", { has: page.getByRole("heading", { name: "Worth another look" }) }).last();
  await expect(again.getByText(shown.view.prompt)).toBeVisible();
  await expect(again.getByRole("link", { name: /^Lesson: / })).toHaveAttribute("href", /\/lessons\/[0-9a-f-]+$/);
  await fits(page, "the results");

  // back in the hub the session is listed, and nothing is left open
  await page.getByRole("link", { name: "Back to the path" }).click();
  await page.getByRole("link", { name: "Open review" }).click();
  await expect(page.getByText(new RegExp(`^${asked - 2} of ${asked} right on the first try$`))).toBeVisible();
  await expect(page.getByRole("link", { name: /Continue your session/ })).toHaveCount(0);
});
