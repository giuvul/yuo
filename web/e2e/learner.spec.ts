// One learner through the real backend on a scripted model (scripts/e2e_server.py): create a path,
// read a lesson, practise every item type the first lesson gets, pass the skill test, see the next
// skill unlock and the progress page. The tests share one database and run in order.
import type { Locator, Page, Response } from "@playwright/test";
import { expect, listView, test } from "./fixtures";

type Item = { item_version_id: string; type: string; view: Record<string, unknown> };
type Key = { type: string; answer: unknown };

async function itemsFrom(response: Promise<Response>): Promise<Item[]> {
  const body = (await (await response).json()) as { items?: Item[] };
  return body.items ?? [];
}

/** Click the visible label of a React Aria radio or checkbox (the native input is visually hidden). */
async function pick(input: Locator): Promise<void> {
  await input.locator("xpath=ancestor::label").click();
  await expect(input).toBeChecked();
}

/** Answer the item on screen correctly, the way a learner would: with the mouse and keyboard. */
async function answer(page: Page, item: Item): Promise<void> {
  const key = (await (await page.request.get(`/api/_e2e/key/${item.item_version_id}`)).json()) as Key;
  switch (item.type) {
    case "mcq":
      await pick(page.getByRole("radio", { name: new RegExp(`^${key.answer as string}\\. `) }));
      break;
    case "multi":
      for (const id of key.answer as string[]) {
        await pick(page.getByRole("checkbox", { name: new RegExp(`^${id}\\. `) }));
      }
      break;
    case "cloze":
      for (const [i, text] of (key.answer as string[]).entries()) {
        await page.getByRole("textbox", { name: `Gap ${i + 1}` }).fill(text);
      }
      break;
    case "ordering": {
      const steps = item.view["steps"] as { id: string; text: string }[];
      const order = steps.map((s) => s.id);
      const text = new Map(steps.map((s) => [s.id, s.text]));
      for (const [i, id] of (key.answer as string[]).entries()) {
        for (let j = order.indexOf(id); j > i; j--) {
          await page.getByRole("button", { name: `Move up: ${text.get(id)}` }).click();
          [order[j - 1], order[j]] = [order[j]!, order[j - 1]!];
        }
      }
      break;
    }
    case "matching":
      for (const pair of key.answer as { left: string; right: string }[]) {
        await page.getByRole("button", { name: new RegExp(pair.left) }).click();
        await page.getByRole("option", { name: pair.right, exact: true }).click();
      }
      break;
    case "flashcard":
      await page.getByRole("button", { name: "Show answer" }).click();
      await pick(page.getByRole("radio", { name: "Good" }));
      break;
    case "short_answer":
      await page.getByRole("textbox", { name: /Your answer/ }).fill(key.answer as string);
      break;
    default:
      throw new Error(`no answer for ${item.type}`);
  }
}

test.describe.configure({ mode: "serial" });

// Most tests here read lesson rows and per-skill actions from the path page, so they open it in its list view
// (`listView`); the graph, which is the default, is tested at the end of this file.

const READY = '[data-state="ready"]';
let pathUrl = "";

test("create a path and see the first lessons written", async ({ page }) => {
  await listView(page);
  await page.goto("/");
  await expect(page.getByText("No paths yet.")).toBeVisible();
  await page.getByRole("link", { name: "New path" }).click();
  await page.getByRole("textbox", { name: "Title" }).fill("SQL");
  await page.getByRole("textbox", { name: "Your goal" }).fill("Write joins");
  await expect(page.getByText(/Estimated cost for 20 lessons/)).toBeVisible();
  await page.getByRole("button", { name: "Create path" }).click();
  await expect(page).toHaveURL(/\/paths\/[0-9a-f-]+$/);
  pathUrl = page.url();
  // the level check comes first: eight questions, one at a time, before the path is planned
  await expect(page.getByText("Question 1 of 8")).toBeVisible({ timeout: 15_000 });
  for (let n = 1; n <= 8; n++) {
    await expect(page.getByText(`Question ${n} of 8`)).toBeVisible();
    await page.getByRole("button", { name: n % 3 === 0 ? "I don’t know yet" : `right ${n}` }).click();
  }
  // then the plan, which the learner can change before anything is written
  await expect(page.getByRole("heading", { name: "Your plan" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("button", { name: "Build it" })).toBeEnabled({ timeout: 15_000 });
  await page.getByRole("button", { name: "Build it" }).click();
  // the buffer: three lessons written ahead; the page polls while jobs run
  await expect(page.locator(`li${READY}`)).toHaveCount(3, { timeout: 15_000 });
  await expect(page.getByText(/Unlocks after/).first()).toBeVisible();
});

test("read the first lesson and practise", async ({ page }) => {
  await listView(page);
  await page.goto(pathUrl);
  await page.locator(`li${READY} a`).first().click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.getByText("Lesson marked as done.")).toBeVisible();
  const practice = page.waitForResponse((r) => r.url().includes("/practice") && r.request().method() === "POST");
  await page.getByRole("link", { name: /^Practice \(\d+ questions?\)$/ }).click();
  const items = await itemsFrom(practice);
  expect(items.map((i) => i.type)).toEqual(["mcq", "cloze", "flashcard"]);
  for (const [n, item] of items.entries()) {
    await answer(page, item);
    await page.getByRole("button", { name: "Check answer" }).click();
    await expect(
      page.getByText(item.type === "flashcard" ? "Rating saved." : "Correct.", { exact: false }),
    ).toBeVisible();
    if (n < items.length - 1) await page.getByRole("button", { name: "Next question" }).click();
  }
  await page.getByRole("button", { name: "See results" }).click();
  await expect(page.getByText("All done")).toBeVisible();
});

test("a short answer is graded by the model and the grade reaches the page", async ({ page }) => {
  await listView(page);
  await page.goto(pathUrl);
  await page.locator(`li${READY} a`).nth(2).click(); // every third lesson gets a short answer
  await page.getByRole("button", { name: "Done" }).click();
  const practice = page.waitForResponse((r) => r.url().includes("/practice") && r.request().method() === "POST");
  await page.getByRole("link", { name: /^Practice \(\d+ questions?\)$/ }).click();
  const items = await itemsFrom(practice);
  expect(items.map((i) => i.type)).toContain("short_answer");
  for (const [n, item] of items.entries()) {
    await answer(page, item);
    await page.getByRole("button", { name: "Check answer" }).click();
    if (item.type === "short_answer") {
      // the scripted grader finds 2 of 3 rubric weight met
      await expect(page.getByText("Partly right (67%).")).toBeVisible({ timeout: 15_000 });
      await expect(page.getByText("Kept all left rows; missed the nulls.")).toBeVisible();
    }
    if (n < items.length - 1) await page.getByRole("button", { name: "Next question" }).click();
  }
});

test("pass the skill test and unlock the next skill", async ({ page }) => {
  await listView(page);
  await page.goto(pathUrl);
  const bank = page.waitForResponse(
    async (r) =>
      /\/api\/skills\/[^/]+\/test$/.test(r.url()) && ((await r.json()) as { items?: unknown }).items !== undefined,
    { timeout: 30_000 },
  );
  await page.getByRole("link", { name: "Take the skill test: Select" }).click();
  const items = await itemsFrom(bank);
  expect(items).toHaveLength(5);
  test.info().annotations.push({ type: "test item types", description: items.map((i) => i.type).join(", ") });
  for (const [n, item] of items.entries()) {
    await answer(page, item);
    const last = n === items.length - 1;
    await page.getByRole("button", { name: last ? "Finish the test" : "Save and continue" }).click();
  }
  await expect(page.getByText("Passed. This skill is mastered.")).toBeVisible({ timeout: 15_000 });
  await page.getByRole("link", { name: "Back to the path" }).first().click();
  // the next skill is open; its test is offered once it is started, not at 0%
  const next = page.locator("li", { has: page.getByRole("heading", { level: 3, name: /^Filtering/ }) }).first();
  await expect(next.getByText("Available", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /Take the skill test: Filtering/ })).toHaveCount(0);
});

test("progress shows the mastered skill and the XP", async ({ page }) => {
  await page.goto(pathUrl);
  await page.getByRole("link", { name: "Progress" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByText(/XP/).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: /^Skills mastered: 1 of 4$/ })).toBeVisible();
});

test("a lesson video plays with captions, toggling them saves the setting, and it downloads", async ({ page }) => {
  await listView(page);
  await page.goto(pathUrl);
  const href = (await page.locator(`li${READY} a`).first().getAttribute("href"))!;
  const lessonId = href.split("/").pop()!;
  // the video job runs in the background after the lesson
  await expect
    .poll(async () => ((await (await page.request.get(`/api/lessons/${lessonId}`)).json()) as { video?: { state: string } }).video?.state, {
      timeout: 30_000,
    })
    .toBe("ready");
  await page.goto(href);
  const player = page.getByRole("group", { name: "Lesson video" });
  await expect(player).toBeVisible();
  const video = player.locator("video");
  await expect(video).toHaveAttribute("poster", /^\/api\/assets\//);
  const track = video.locator('track[kind="captions"]');
  await expect(track).toHaveAttribute("src", /^\/api\/assets\//);
  await expect(track).toHaveAttribute("srclang", /.+/);
  // captions start on (the learner's default) and come from the track, not the picture
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.textTracks[0]?.mode)).toBe("showing");
  for (const name of [/play/i, /seek/i, /volume/i, /playback rate/i, /captions/i, /fullscreen/i]) {
    await expect(player.getByRole("button", { name }).or(player.getByRole("slider", { name })).first()).toBeVisible();
  }

  // toggling captions in the player saves the setting for this learner
  const put = page.waitForRequest((r) => r.url().endsWith("/api/settings/video.captions") && r.method() === "PUT");
  await player.getByRole("button", { name: /captions/i }).click();
  expect((await put).postDataJSON()).toEqual({ value: false, level: "learner" });
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.textTracks[0]?.mode)).not.toBe("showing");
  const settings = (await (await page.request.get("/api/settings")).json()) as { key: string; value: unknown }[];
  expect(settings.find((x) => x.key === "video.captions")?.value).toBe(false);
  await page.reload();
  await expect(page.getByRole("group", { name: "Lesson video" })).toBeVisible();
  await expect
    .poll(() => page.locator("video").evaluate((v: HTMLVideoElement) => v.textTracks[0]?.mode))
    .not.toBe("showing");

  // it plays; opening the tutor pauses it and the tutor gets the time
  const v = page.locator("video");
  await page.getByRole("button", { name: /^play$/i }).click();
  await expect.poll(() => v.evaluate((x: HTMLVideoElement) => x.currentTime), { timeout: 10_000 }).toBeGreaterThan(1);
  const ctx = page.waitForRequest((r) => r.url().endsWith("/api/tutor/context"));
  await page.getByRole("button", { name: /^Tutor/ }).click();
  await expect.poll(() => v.evaluate((x: HTMLVideoElement) => x.paused)).toBe(true);
  expect(((await ctx).postDataJSON() as { video_s?: number }).video_s).toBeGreaterThan(0);
  await page.keyboard.press("Escape");

  // the download: the MP4 with its subtitle track
  const download = page.getByRole("link", { name: "Download video (MP4 with subtitles)" });
  const res = await page.request.get((await download.getAttribute("href"))!);
  expect(res.status()).toBe(200);
  expect(res.headers()["content-type"]).toContain("video/mp4");
  // leave captions on for the tests that follow
  await page.request.put("/api/settings/video.captions", { data: { value: true, level: "learner" } });
});

test("settings: closed sections by topic, a search, and their explanations", async ({ page }) => {
  await page.goto("/settings");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByText(/Default: /).first()).toBeHidden(); // every section starts closed
  await page.getByText("This installation", { exact: true }).click();
  const installation = page.locator("#installation");
  await expect(installation.getByText(/budget/i).first()).toBeVisible();
  await expect(installation.getByText(/Default: /).first()).toBeVisible();
  await expect(page.getByText(/CFG-\d/)).toHaveCount(0);
  await page.getByRole("searchbox", { name: "Find a setting" }).fill("captions");
  await expect(page.getByRole("switch", { name: "Video captions" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Tutor's name" })).toHaveCount(0);
});

const TUTOR_REPLY = "Good question. Think about which rows the result keeps, then look at the lesson's second example.";

/** Opens the dock with the floating button and returns the panel. */
async function openTutor(page: Page): Promise<Locator> {
  await page.getByRole("button", { name: /^Tutor/ }).click();
  const dock = page.getByRole("complementary", { name: "Tutor" });
  await expect(dock).toBeVisible();
  await expect(dock.getByRole("textbox", { name: "Message to Tutor" })).toBeFocused();
  return dock;
}

test("ask the tutor about a lesson and a selected passage", async ({ page }) => {
  await listView(page);
  await page.goto(pathUrl);
  await page.locator(`li${READY} a`).first().click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  // select the first paragraph: the reader offers to ask about it
  await page.locator("[data-bid] p").first().evaluate((p) => {
    const range = document.createRange();
    range.selectNodeContents(p);
    const sel = window.getSelection()!;
    sel.removeAllRanges();
    sel.addRange(range);
  });
  await page.getByRole("button", { name: "Ask the tutor about this" }).click();
  const dock = page.getByRole("complementary", { name: "Tutor" });
  // the context chips sit in a section that starts closed
  await dock.getByText(/What the tutor sees with your next message/).click();
  await expect(dock.getByText(/^Selected: “/)).toBeVisible();
  await expect(dock.getByText("Ask about this lesson: explanations, examples, questions.")).toBeVisible();
  await dock.getByRole("textbox", { name: "Message to Tutor" }).fill("What does this paragraph mean?");
  await dock.getByRole("button", { name: "Send" }).click();
  await expect(dock.getByText(TUTOR_REPLY)).toBeVisible({ timeout: 15_000 });
  await expect(dock.getByText(/^Asked with: .*Selected: “/)).toBeVisible();
  // the selection was for that message only
  await expect(dock.getByText(/^Selected: “/)).toHaveCount(0);
  // Esc closes the dock and focus returns to the page
  await page.keyboard.press("Escape");
  await expect(dock).toHaveCount(0);
  // the shortcut opens it again, on the same thread
  await page.keyboard.press("Control+j");
  await expect(page.getByRole("complementary", { name: "Tutor" }).getByText(TUTOR_REPLY)).toBeVisible();
});

test("in practice, a guess before answering gets the guess reply", async ({ page }) => {
  await listView(page);
  await page.goto(pathUrl);
  await page.locator(`li${READY} a`).first().click();
  const practice = page.waitForResponse((r) => r.url().includes("/practice") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Done" }).click();
  await page.getByRole("link", { name: /^Practice \(\d+ questions?\)$/ }).click();
  const items = await itemsFrom(practice);
  expect(items[0]?.type).toBe("mcq");
  await expect(page.getByRole("button", { name: "Check answer" })).toBeVisible();
  const dock = await openTutor(page);
  await expect(dock.getByText(/You have not answered this question yet/)).toBeVisible();
  await dock.getByText(/What the tutor sees with your next message/).click();
  await expect(dock.getByText("Question 1 of 3")).toBeVisible();
  await dock.getByRole("textbox", { name: "Message to Tutor" }).fill("Is it b?");
  await page.keyboard.press("Enter");
  await expect(
    dock.getByText("I can't say whether that's right until you submit your answer.", { exact: false }),
  ).toBeVisible({ timeout: 15_000 });
  // practice shares the lesson's thread: the earlier answer is there, and no new model reply
  await expect(dock.getByText(TUTOR_REPLY)).toHaveCount(1);
});

test("the tutor's memory page and its setting", async ({ page }) => {
  await page.goto("/tutor/memory");
  await expect(page.getByRole("heading", { level: 1, name: "Tutor memory" })).toBeVisible();
  await page.getByRole("textbox", { name: "What should it remember?" }).fill("I am preparing for an interview.");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText("I am preparing for an interview.")).toBeVisible();
  await expect(page.getByText(/Written by you/)).toBeVisible();
  await page.getByRole("link", { name: "Turn tutor memory on or off in Settings" }).click();
  await expect(page).toHaveURL(/\/settings#setting-tutor-memory$/);
  await expect(page.locator("#setting-tutor-memory").getByRole("switch", { name: "Tutor memory" })).toBeChecked();
});

test("during a skill test the tutor says it is locked", async ({ page }) => {
  await listView(page);
  await page.goto(pathUrl);
  const bank = page.waitForResponse(
    async (r) =>
      /\/api\/skills\/[^/]+\/test$/.test(r.url()) && ((await r.json()) as { items?: unknown }).items !== undefined,
    { timeout: 30_000 },
  );
  // Filtering is not started, so its list row offers no test: open the test page itself
  const tree = (await (await page.request.get(`/api${new URL(pathUrl).pathname}`)).json()) as {
    branches: { skills: { id: string; title: string }[] }[];
  };
  const filtering = tree.branches.flatMap((b) => b.skills).find((x) => x.title.startsWith("Filtering"))!;
  await page.goto(`${pathUrl}/skills/${filtering.id}/test`);
  await itemsFrom(bank);
  await expect(page.getByRole("button", { name: "Save and continue" })).toBeVisible();
  const dock = await openTutor(page);
  await expect(dock.getByText(/^Locked during the test/)).toBeVisible();
  // a test thread: no lesson or memory chips
  await expect(dock.getByText(/^Lesson: /)).toHaveCount(0);
  await expect(dock.getByRole("button", { name: /Remove from the context: Tutor memory/ })).toHaveCount(0);
  // the open test applies on other screens too
  await page.goto(pathUrl);
  const again = await openTutor(page);
  await expect(again.getByText(/A test is open, so the test rules apply on every screen/)).toBeVisible();
});

test("pages fit a phone screen without sideways scrolling", async ({ page }) => {
  await listView(page);
  await page.setViewportSize({ width: 360, height: 740 });
  const lesson = await page.goto(pathUrl).then(() => page.locator(`li${READY} a`).first().getAttribute("href"));
  const fits = async (what: string) => {
    const [scroll, width] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    expect(scroll, `${what} is ${scroll}px wide`).toBeLessThanOrEqual(width);
  };
  for (const url of ["/", pathUrl, lesson!, `${lesson!}/practice`, "/settings", "/settings/devices", "/jobs", "/review", `${pathUrl}/review`, "/tutor/memory", "/import"]) {
    await page.goto(url);
    await page.waitForLoadState("networkidle");
    await fits(url);
  }
  // the dock as a bottom sheet, with a conversation in it
  await page.goto(lesson!);
  const dock = await openTutor(page);
  await dock.getByRole("tab", { name: "All" }).click(); // the open test seals "this thread"
  await expect(dock.getByText(TUTOR_REPLY)).toBeVisible();
  await fits("the open tutor");
  const box = await dock.boundingBox();
  expect(box!.width).toBeLessThanOrEqual(360);
});

// --- the path as a graph (the default view) -----------------------------------------------------------------

/** The canvas's pan and zoom, as the library writes it on its viewport layer. */
const viewOf = (graph: Locator) =>
  graph.locator(".react-flow__viewport").evaluate((el) => (el as HTMLElement).style.transform);
const loadedGraphCode = (page: Page) =>
  page.evaluate(() => performance.getEntriesByType("resource").some((r) => /\/PathGraph-[^/]+\.js$/.test(r.name)));

test("the path opens as a graph: arrow keys move, Enter opens the skill, Esc returns focus", async ({ page }) => {
  await page.goto(pathUrl);
  const graph = page.getByRole("group", { name: "Skills" });
  await expect(graph).toBeVisible();
  await expect(page.getByRole("radio", { name: "Tree" })).toBeChecked();
  await expect(page.locator(`li${READY}`)).toHaveCount(0); // lessons live in the skill's panel
  const skills = graph.locator("button[data-skill]");
  await expect(skills).toHaveCount(4);
  // a real name on every node: the state and the mastery, and what it needs
  const select = graph.getByRole("button", { name: /^Select, mastered, mastery \d+%/ });
  const filtering = graph.getByRole("button", { name: /^Filtering, .*needs: Select/ });
  const inner = graph.getByRole("button", { name: /^Inner joins, locked/ });
  const outer = graph.getByRole("button", { name: /^Outer joins, locked/ });
  await expect(select).toBeVisible();
  // the canvas's own controls have names too, and the list is announced as the alternative
  for (const name of ["Zoom in", "Zoom out", "Fit the whole tree", "Full screen"]) {
    await expect(graph.getByRole("button", { name, exact: true })).toBeVisible();
  }
  await expect(graph).toHaveAccessibleDescription(/A list view is available/);
  // a small path is framed whole on open: every skill is inside the canvas
  const canvas = (await graph.boundingBox())!;
  for (const box of await skills.evaluateAll((els) => els.map((e) => e.getBoundingClientRect().toJSON()))) {
    expect(box.left).toBeGreaterThanOrEqual(canvas.x);
    expect(box.right).toBeLessThanOrEqual(canvas.x + canvas.width);
    expect(box.top).toBeGreaterThanOrEqual(canvas.y);
    expect(box.bottom).toBeLessThanOrEqual(canvas.y + canvas.height);
  }

  // the opening frame, once it has settled: "Show the whole tree" comes back to it
  let whole = "";
  await expect
    .poll(async () => {
      const before = whole;
      whole = await viewOf(graph);
      return whole === before;
    })
    .toBe(true);

  // one tab stop; the arrows move along a branch and round the ring of branches
  await expect(graph.locator('button[data-skill][tabindex="0"]')).toHaveCount(1);
  await select.focus();
  await page.keyboard.press("ArrowRight");
  await expect(filtering).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(outer).toBeFocused();
  await page.keyboard.press("Home");
  await expect(inner).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await expect(select).toBeFocused();
  await page.keyboard.press("End");
  await expect(filtering).toBeFocused();
  await expect(graph.locator('button[data-skill][tabindex="0"]')).toHaveCount(1);
  await expect(filtering).toHaveAttribute("tabindex", "0");

  // Enter opens the panel beside the canvas, with the skill's lessons and actions
  await page.keyboard.press("Enter");
  const panel = page.getByRole("complementary", { name: "Filtering" });
  await expect(panel).toBeVisible();
  await expect(filtering).toHaveAttribute("aria-expanded", "true");
  await expect(panel.getByRole("progressbar", { name: "Mastery of Filtering" })).toBeVisible();
  await expect(panel.getByRole("link", { name: "Take the skill test: Filtering" })).toHaveCount(0); // not started yet
  await expect(panel.locator("li[data-state]").first()).toBeVisible();
  await expect(panel.getByRole("button", { name: "Show on the tree: Select" })).toBeVisible();
  // beside the canvas, not over it: the canvas makes room for it (with no skill chosen there is no panel), and
  // the chosen skill stays in sight
  const panelBox = await panel.boundingBox();
  const narrower = (await graph.boundingBox())!;
  expect(narrower.width).toBeLessThan(canvas.width);
  expect(panelBox!.x).toBeGreaterThanOrEqual(narrower.x + narrower.width);
  await expect
    .poll(async () => {
      const b = (await filtering.boundingBox())!;
      return b.x >= narrower.x && b.x + b.width <= narrower.x + narrower.width;
    })
    .toBe(true);
  // the route to the skill is lit (pollen links from the start through its hub); a skill that is neither on it
  // nor linked to the skill steps back
  await expect(select).not.toHaveAttribute("data-off", /.*/);
  await expect(outer).toHaveAttribute("data-off", /.*/);
  await expect(graph.locator('path[data-lit="route"]')).toHaveCount(3); // start > hub > Select > Filtering

  // Esc closes it and focus is back on the node
  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  await expect(filtering).toBeFocused();
  await expect(filtering).toHaveAttribute("aria-expanded", "false");
  await expect(graph.locator('path[data-lit="route"]')).toHaveCount(0);

  // "unlocks" selects that node; a chip frames its branch and the whole tree comes back
  await filtering.click();
  await page.getByRole("complementary", { name: "Filtering" }).getByRole("button", { name: /^Show on the tree: / }).last().click();
  await expect(page.getByRole("complementary", { name: "Filtering" })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await page.getByRole("radiogroup", { name: "Show one branch" }).getByRole("radio").first().click();
  await expect(page.getByRole("button", { name: "Show the whole tree" })).toBeVisible();
  await expect(graph.locator("button[data-dim]")).toHaveCount(2);
  await expect.poll(() => viewOf(graph)).not.toBe(whole); // the view moved to that branch
  await page.getByRole("button", { name: "Show the whole tree" }).click();
  await expect(graph.locator("button[data-dim]")).toHaveCount(0);
  await expect.poll(() => viewOf(graph)).toBe(whole);
});

test("the graph's canvas zooms and pans, and a dragged node springs back", async ({ page }) => {
  await page.goto(pathUrl);
  const graph = page.getByRole("group", { name: "Skills" });
  const select = graph.getByRole("button", { name: /^Select, mastered/ });
  await expect(select).toBeVisible();
  await graph.evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 100));
  const zoomOf = async () => Number(/scale\(([\d.]+)\)/.exec(await viewOf(graph))?.[1]);
  /** The view once an animated move has ended: two readings in a row that agree. */
  const settled = async () => {
    let last = "";
    await expect
      .poll(async () => {
        const now = await viewOf(graph);
        const same = now === last;
        last = now;
        return same;
      }, { intervals: [200] })
      .toBe(true);
    return last;
  };
  const zoom = await zoomOf();

  await graph.getByRole("button", { name: "Zoom in", exact: true }).click();
  await expect.poll(zoomOf).toBeGreaterThan(zoom);
  await graph.getByRole("button", { name: "Fit the whole tree", exact: true }).click();
  await expect.poll(zoomOf).toBeCloseTo(zoom, 1);

  // dragging the background pans the canvas. The start point is looked up when the drag begins (the page above
  // the canvas may still have settled since the test opened it): a spot of bare canvas, inside the window
  const before = await settled();
  const bare = await graph.evaluate((el) => {
    const r = el.getBoundingClientRect();
    for (let y = r.top + 24; y < Math.min(r.bottom, innerHeight) - 120; y += 16) {
      for (let x = r.left + 24; x < r.right - 120; x += 16) {
        const corners = [document.elementFromPoint(x, y), document.elementFromPoint(x + 70, y + 50)];
        if (corners.every((c) => c?.classList.contains("react-flow__pane"))) return { x, y };
      }
    }
    return null;
  });
  expect(bare, "a spot of bare canvas to drag").not.toBeNull();
  await page.mouse.move(bare!.x, bare!.y);
  await page.mouse.down();
  await page.mouse.move(bare!.x + 60, bare!.y + 40, { steps: 6 });
  await page.mouse.up();
  const panned = await viewOf(graph);
  expect(panned).not.toBe(before);
  expect(panned).toContain(`scale(${/scale\(([\d.]+)\)/.exec(before)![1]})`); // moved, not zoomed
  await graph.getByRole("button", { name: "Fit the whole tree", exact: true }).click();
  await expect.poll(zoomOf).toBeCloseTo(zoom, 1);

  // the wheel over the canvas zooms it and leaves the page where it is
  await settled();
  const scrolled = await page.evaluate(() => window.scrollY);
  const box = (await graph.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.wheel(0, -240);
  await expect.poll(zoomOf).toBeGreaterThan(zoom + 0.05);
  expect(await page.evaluate(() => window.scrollY)).toBe(scrolled);
  await graph.getByRole("button", { name: "Fit the whole tree", exact: true }).click();
  await expect.poll(zoomOf).toBeCloseTo(zoom, 1);

  // a node can be dragged aside; it is decoration: released, it settles back where the layout put it
  // (first let the page come to rest after the wheel, with the node on screen and clear of the header)
  await graph.evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 100));
  let lastY = -1;
  await expect
    .poll(async () => {
      const y = await page.evaluate(() => window.scrollY);
      const same = y === lastY;
      lastY = y;
      return same;
    }, { intervals: [150] })
    .toBe(true);
  const home = (await select.boundingBox())!;
  const grab = { x: home.x + home.width / 2, y: home.y + 20 };
  await page.mouse.move(grab.x, grab.y);
  await page.mouse.down();
  await page.mouse.move(grab.x + 70, grab.y + 10, { steps: 8 });
  const moved = (await select.boundingBox())!;
  expect(moved.x - home.x).toBeGreaterThan(40);
  await page.mouse.up();
  const away = async () => Math.abs((await select.boundingBox())!.x - home.x);
  await expect.poll(away, { timeout: 10_000 }).toBeLessThan(4);
  // and then the simulation stops: nothing in the canvas changes any more
  const changes = () =>
    graph.evaluate(
      (el) =>
        new Promise<number>((resolve) => {
          let n = 0;
          const observer = new MutationObserver((list) => (n += list.length));
          observer.observe(el, { subtree: true, attributes: true, childList: true });
          setTimeout(() => {
            observer.disconnect();
            resolve(n);
          }, 500);
        }),
    );
  await expect.poll(changes, { timeout: 10_000 }).toBe(0);
  await expect(page.getByRole("complementary", { name: "Select" })).toHaveCount(0); // a drag is not a click
});

test("the List switch is remembered across a reload; the graph's code loads only for the graph", async ({ page }) => {
  await page.goto(pathUrl);
  await expect(page.getByRole("group", { name: "Skills" })).toBeVisible();
  expect(await loadedGraphCode(page)).toBe(true);
  await page.getByRole("radio", { name: "List" }).click();
  await expect(page.locator(`li${READY}`).first()).toBeVisible();
  await expect(page.getByRole("group", { name: "Skills" })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("radio", { name: "List" })).toBeChecked();
  await expect(page.locator(`li${READY}`).first()).toBeVisible();
  await expect(page.getByText(/Unlocks after/).first()).toBeVisible();
  expect(await loadedGraphCode(page)).toBe(false); // the list does not pay for the graph library
  await page.getByRole("radio", { name: "Tree" }).click();
  await expect(page.getByRole("group", { name: "Skills" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("radio", { name: "Tree" })).toBeChecked();
  await expect(page.getByRole("group", { name: "Skills" })).toBeVisible();
});

test("the graph fits a phone: no sideways scrolling, the skill opens as a bottom sheet", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(pathUrl);
  const graph = page.getByRole("group", { name: "Skills" });
  await expect(graph).toBeVisible(); // the graph is the default on a phone too
  const fits = async (what: string) => {
    const [scroll, width] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    expect(scroll, `${what} is ${scroll}px wide`).toBeLessThanOrEqual(width);
  };
  await fits("the graph");
  // the canvas is inside the screen and leaves page above and below it to scroll by
  const canvas = (await graph.boundingBox())!;
  expect(canvas.x).toBeGreaterThanOrEqual(0);
  expect(canvas.x + canvas.width).toBeLessThanOrEqual(390);
  expect(canvas.height).toBeLessThanOrEqual(844 * 0.71);
  // on open the skill to learn now and its name are in view
  const filtering = graph.getByRole("button", { name: /^Filtering/ });
  await expect(filtering).toHaveAttribute("data-kind", "current");
  const now = (await filtering.boundingBox())!;
  expect(now.x).toBeGreaterThanOrEqual(canvas.x);
  expect(now.x + now.width).toBeLessThanOrEqual(canvas.x + canvas.width);
  expect(now.y).toBeGreaterThanOrEqual(canvas.y);
  expect(now.y + now.height).toBeLessThanOrEqual(canvas.y + canvas.height);

  await filtering.click();
  const sheet = page.getByRole("complementary", { name: "Filtering" });
  await expect(sheet).toBeVisible();
  await expect(sheet.getByRole("heading", { name: "Filtering" })).toBeFocused();
  // it slides up and then sits on the bottom edge
  await expect.poll(async () => Math.round(((b) => b!.y + b!.height)(await sheet.boundingBox()))).toBe(844);
  const sheetBox = (await sheet.boundingBox())!;
  expect(sheetBox.width).toBeLessThanOrEqual(390);
  // the canvas moves the node into the part that stays in sight above the sheet
  const nodeBottom = async () => ((b) => b!.y + b!.height)(await filtering.boundingBox());
  await expect.poll(nodeBottom).toBeLessThanOrEqual(sheetBox.y);
  expect((await filtering.boundingBox())!.y).toBeGreaterThanOrEqual(0);
  await fits("the open sheet");
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
  await expect(filtering).toBeFocused();

  // a framed branch still fits
  await page.getByRole("radiogroup", { name: "Show one branch" }).getByRole("radio").last().click();
  await expect(page.getByRole("button", { name: "Show the whole tree" })).toBeVisible();
  await fits("a framed branch");
  // and so does the smallest phone
  await page.setViewportSize({ width: 320, height: 640 });
  await page.getByRole("button", { name: "Show the whole tree" }).click();
  await fits("the graph at 320 px");
  const small = (await graph.boundingBox())!;
  expect(small.x + small.width).toBeLessThanOrEqual(320);
});
