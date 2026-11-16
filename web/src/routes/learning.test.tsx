import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { PathOut, ProgressOut } from "../api/client";
import { activateLocale } from "../i18n";
import type { OutboxEvent } from "../outbox/events";
import { json, mockApi, type Handler } from "../test/mockApi";
import type { ReviewHub } from "../review/api";
import { appRoutes, renderApp } from "../test/renderApp";

type EventsBody = { device_id: string; events: OutboxEvent[] };

const path: PathOut = {
  id: "p1",
  title: "SQL for analysts",
  subject: "SQL",
  goal: "Reports",
  status: "active",
  difficulty: "foundational",
  content_lang: "en",
  level_check: "none",
  jobs: [],
  branches: [
    {
      id: "b1",
      code: "basics",
      title: "Basics",
      skills: [
        {
          id: "s1",
          code: "basics.select",
          title: "Selecting rows",
          summary: "",
          requires: [],
          objectives: [],
          lessons: [
            { id: "l1", code: "l1", kind: "core", state: "ready", title: "What a table is" },
            { id: "l9", code: "l9", kind: "remedial", state: "queued", title: null },
          ],
        },
        {
          id: "s2",
          code: "basics.join",
          title: "Joining tables",
          summary: "",
          requires: ["s1"],
          objectives: [],
          lessons: [{ id: "l2", code: "l2", kind: "requested", state: "planned", title: "Self joins" }],
        },
        { id: "s3", code: "basics.where", title: "Filtering", summary: "", requires: [], objectives: [], lessons: [] },
      ],
    },
  ],
};

const progress = (over: Partial<ProgressOut> = {}): ProgressOut => ({
  gamification: "full",
  skills: {
    s1: { state: "needs_review", mastery: 0.9, evidence: 6 },
    s2: { state: "locked", mastery: 0, evidence: 0 },
    s3: { state: "available", mastery: 0.25, evidence: 2 },
  },
  branches: [{ id: "b1", title: "Basics", xp: 120, level: 2 }],
  xp_total: 340,
  streak: 4,
  days: [],
  achievements: [{ key: "first_lesson", unlocked_at: "2026-10-27T10:00:00.000Z" }],
  ...over,
});

/** A review hub with nothing studied; `over` fills in what a test is about. */
const hub = (over: Partial<ReviewHub> = {}): ReviewHub => ({
  path_id: "p1",
  memory: null,
  objectives: 0,
  due: 0,
  fading: 0,
  strong: 0,
  questions: 0,
  writing: 0,
  allowed_today: 50,
  sizes: [],
  open_session: null,
  skills: [],
  branches: [],
  recent: [],
  cards_due: 0,
  ...over,
});

/** A server that accepts everything; `grade` decides per response, `outcome` per finished attempt. */
function events(
  sent: OutboxEvent[],
  grade: (e: OutboxEvent) => object | null,
  outcome: (attemptId: string) => object | null = () => null,
): Handler {
  return (_req, body) => {
    const { events } = body as EventsBody;
    sent.push(...events);
    const graded: Record<string, object> = {};
    const outcomes: Record<string, object> = {};
    for (const e of events) {
      if (e.type === "assessment.response_given") {
        const g = grade(e);
        if (g) graded[e.id] = g;
      }
      if (e.type === "attempt.finished") {
        const id = (e.payload as { attempt_id: string }).attempt_id;
        const o = outcome(id);
        if (o) outcomes[id] = o;
      }
    }
    return json({ accepted: events.map((e) => e.id), duplicates: [], rejected: {}, graded, outcomes });
  };
}

beforeAll(async () => {
  await activateLocale("en");
});
afterEach(() => vi.unstubAllGlobals());

describe("path view", () => {
  // the list view; the tree (the default) has its own tests in src/path/PathGraph.test.tsx
  beforeEach(() => localStorage.setItem("yuo.path.view", "list"));
  afterEach(() => localStorage.clear());

  it("shows skill states, mastery, locked prerequisites, test buttons and lesson kinds", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json(path),
      "GET /api/paths/p1/progress": () => json(progress()),
      "GET /api/paths/p1/requests": () => json([]),
    });
    renderApp("/paths/p1");

    expect(await screen.findByText("Needs review")).toBeInTheDocument();
    expect(screen.getByText("Locked")).toBeInTheDocument();
    expect(screen.getByText("Unlocks after: Selecting rows")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Mastery of Selecting rows" })).toHaveAttribute("aria-valuenow", "90");
    expect(screen.getByRole("link", { name: "Take the skill test: Filtering" })).toHaveAttribute(
      "href",
      "/paths/p1/skills/s3/test",
    );
    expect(screen.queryByRole("link", { name: "Take the skill test: Joining tables" })).toBeNull();
    expect(screen.getByText("Extra lesson")).toBeInTheDocument();
    expect(screen.getByText("Requested")).toBeInTheDocument();
    expect(screen.getByText("Level 2")).toBeInTheDocument();
    // not a fresh path: no placement offer
    expect(screen.queryByRole("link", { name: "Take a placement test" })).toBeNull();
  });

  it("offers the skill test only once a skill is started, below its lessons", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json(path),
      "GET /api/paths/p1/progress": () =>
        json(progress({ skills: { ...progress().skills, s3: { state: "available", mastery: 0, evidence: 0 } } })),
      "GET /api/paths/p1/requests": () => json([]),
    });
    renderApp("/paths/p1");
    expect(await screen.findByRole("link", { name: "Take the skill test: Selecting rows" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Take the skill test: Filtering" })).toBeNull();
    expect(screen.getByText(/Pass it and the skill counts as mastered/)).toBeInTheDocument();
  });

  it("offers a placement test on a fresh path", async () => {
    const fresh = progress({
      skills: {
        s1: { state: "available", mastery: 0, evidence: 0 },
        s2: { state: "locked", mastery: 0, evidence: 0 },
        s3: { state: "available", mastery: 0, evidence: 0 },
      },
    });
    mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json(path),
      "GET /api/paths/p1/progress": () => json(fresh),
      "GET /api/paths/p1/requests": () => json([]),
    });
    renderApp("/paths/p1");
    expect(await screen.findByRole("link", { name: "Take a placement test" })).toHaveAttribute(
      "href",
      "/paths/p1/placement",
    );
  });

  it("sends a lesson request and lists it with its status", async () => {
    const rows: object[] = [];
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json(path),
      "GET /api/paths/p1/progress": () => json(progress()),
      "GET /api/paths/p1/requests": () => json(rows),
      "POST /api/paths/p1/requests": (_r, body) => {
        rows.push({
          id: "r1",
          prompt: (body as { prompt: string }).prompt,
          status: "pending",
          lesson_id: null,
          error: null,
          created_at: "2026-10-27T10:00:00.000Z",
        });
        return json({ request_id: "r1", job_id: "j1" }, 202);
      },
    });
    const user = userEvent.setup();
    renderApp("/paths/p1");

    await user.click(await screen.findByRole("button", { name: "Describe the lesson you need" }));
    await user.type(screen.getByRole("textbox", { name: "What should the lesson cover?" }), "Window functions");
    await user.type(
      screen.getByRole("textbox", { name: "Links (optional)" }),
      "https://a.example/one{Enter}{Enter}https://b.example/two",
    );
    await user.click(screen.getByRole("button", { name: "Ask for this lesson" }));

    expect(await screen.findByText(/Request sent/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST" && c.path === "/api/paths/p1/requests")?.body).toEqual({
      prompt: "Window functions",
      links: ["https://a.example/one", "https://b.example/two"],
    });
    const row = (await screen.findByText("Window functions", { selector: "span" })).closest("li")!;
    expect(row).toHaveTextContent("Waiting");
  });
});

describe("skill test", () => {
  it("waits for the item bank job, hides per-item grades and shows the result", async () => {
    const sent: OutboxEvent[] = [];
    let starts = 0;
    let jobPolls = 0;
    const test = {
      assessment_id: "as-test",
      purpose: "skill_test",
      items: [
        { item_version_id: "t1", type: "cloze", view: { text: "SELECT {{1}} FROM t", gaps: 1 } },
        {
          item_version_id: "t2",
          type: "ordering",
          view: { prompt: "Order the clauses", steps: [{ id: "b", text: "WHERE" }, { id: "a", text: "FROM" }] },
        },
      ],
    };
    mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json(path),
      "POST /api/skills/s3/test": () => (++starts === 1 ? json({ job_id: "j1" }) : json(test)),
      "GET /api/jobs/j1": () =>
        json({
          id: "j1",
          kind: "test_bank",
          status: ++jobPolls === 1 ? "running" : "succeeded",
          attempt: 1,
          error: null,
          target_kind: "skill",
          target_id: "s3",
          stages: [],
        }),
      "POST /api/events": events(
        sent,
        () => ({ pending: true, hidden: true }),
        () => ({ skill_id: "s3", passed: false, score: 0.5, pass_mark: 0.8 }),
      ),
    });
    const user = userEvent.setup();
    renderApp("/paths/p1/skills/s3/test");

    expect(await screen.findByText(/Preparing your test/)).toBeInTheDocument();
    expect(await screen.findByText("Question 1 of 2", {}, { timeout: 6000 })).toBeInTheDocument();
    expect(starts).toBe(2);
    expect(screen.queryByRole("button", { name: /hint/i })).toBeNull();

    await user.type(screen.getByRole("textbox", { name: "Gap 1" }), "*");
    await user.click(screen.getByRole("button", { name: "Save and continue" }));
    expect(await screen.findByText("Question 2 of 2")).toBeInTheDocument();
    expect(screen.queryByText(/Correct|Not quite/)).toBeNull();
    await user.click(screen.getByRole("button", { name: "Move up: FROM" }));
    await user.click(screen.getByRole("button", { name: "Finish the test" }));

    expect(await screen.findByText("Not passed yet.")).toBeInTheDocument();
    expect(screen.getByText("Your score: 50% (pass mark 80%)")).toBeInTheDocument();
    expect(screen.getByText(/A short extra lesson on what you missed is being prepared/)).toBeInTheDocument();

    const started = sent.find((e) => e.type === "attempt.started")!;
    expect(started.payload).toMatchObject({ assessment_id: "as-test", purpose: "skill_test" });
    const answers = sent.filter((e) => e.type === "assessment.response_given").map((e) => (e.payload as { answer: unknown }).answer);
    expect(answers).toEqual([["*"], ["a", "b"]]);
    expect(sent.at(-1)?.type).toBe("attempt.finished");
  }, 10_000);
});

describe("reviews", () => {
  it("shows the due badge: objectives and cards due across the paths, capped by today's limit", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/paths": () =>
        json([
          { id: "p1", title: "SQL", subject: "SQL", status: "active", difficulty: "foundational", content_lang: "en", created_at: "2026-10-01T10:00:00.000Z" },
          { id: "p2", title: "Git", subject: "Git", status: "active", difficulty: "foundational", content_lang: "en", created_at: "2026-10-02T10:00:00.000Z" },
        ]),
      "GET /api/paths/p1/review": () => json(hub({ due: 4, cards_due: 3, allowed_today: 5 })),
      "GET /api/paths/p2/review": () => json(hub({ path_id: "p2", due: 2, allowed_today: 5 })),
    });
    renderApp("/");
    const link = await screen.findByRole("link", { name: /Reviews/ });
    expect(await within(link).findByText("5 due")).toBeInTheDocument(); // 9 are due, 5 are allowed today
    expect(link).toHaveAttribute("href", "/review");
  });

  it("runs the due cards from the hub's Cards section with immediate feedback and no hints", async () => {
    const sent: OutboxEvent[] = [];
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json(path),
      "GET /api/paths/p1/review": () => json(hub({ cards_due: 2 })),
      "GET /api/items/f1/reveal": () => json({ back: "56" }),
      "POST /api/reviews/start": () =>
        json({
          assessment_id: "as-rev",
          purpose: "review",
          items: [
            { item_version_id: "f1", type: "flashcard", view: { front: "What is 7 × 8?" } },
            {
              item_version_id: "m1",
              type: "matching",
              view: { prompt: "Match", left: ["dog", "cat"], right: ["meow", "woof"] },
            },
          ],
        }),
      "POST /api/events": events(sent, (e) =>
        (e.payload as { item_version_id: string }).item_version_id === "f1"
          ? { pending: false, score: 0.8, correct: "56", explanation: null, solution: null }
          : {
              pending: false,
              score: 0,
              correct: [
                { left: "dog", right: "woof" },
                { left: "cat", right: "meow" },
              ],
              explanation: null,
              solution: "Dogs woof.",
            },
      ),
    });
    const user = userEvent.setup();
    renderApp("/paths/p1/review");

    const cards = (await screen.findByRole("heading", { name: "Cards" })).closest("section")!;
    expect(within(cards).getByText("2 flashcards from your practice are due.")).toBeInTheDocument();
    await user.click(within(cards).getByRole("button", { name: "Review cards" }));
    expect(await screen.findByRole("heading", { name: "What is 7 × 8?" })).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST" && c.path.startsWith("/api/reviews/start"))?.path).toBe(
      "/api/reviews/start?path_id=p1",
    );
    expect(screen.queryByRole("button", { name: /hint/i })).toBeNull();
    expect(screen.getByRole("button", { name: "Check answer" })).toBeDisabled(); // rate only after the flip
    await user.click(screen.getByRole("button", { name: "Show answer" }));
    expect(await screen.findByText("56")).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Good" }));
    await user.click(screen.getByRole("button", { name: "Check answer" }));
    expect(await screen.findByText(/Rating saved/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next question" }));

    await user.click(await screen.findByRole("button", { name: /dog/ }));
    await user.click(await screen.findByRole("option", { name: "meow" }));
    await user.click(screen.getByRole("button", { name: /cat/ }));
    await user.click(await screen.findByRole("option", { name: "woof" }));
    await user.click(screen.getByRole("button", { name: "Check answer" }));
    const fb = (await screen.findByText("Not quite.")).closest("[role=status]")!;
    expect(fb).toHaveTextContent("dog → woof");
    expect(fb).toHaveTextContent("Dogs woof.");
    await user.click(screen.getByRole("button", { name: "See results" }));
    expect(await screen.findByText("You got 0 of 2 right.")).toBeInTheDocument();

    const answers = sent.filter((e) => e.type === "assessment.response_given").map((e) => (e.payload as { answer: unknown }).answer);
    expect(answers).toEqual([
      3,
      [
        { left: "dog", right: "meow" },
        { left: "cat", right: "woof" },
      ],
    ]);
    expect(sent.find((e) => e.type === "attempt.started")?.payload).toMatchObject({ purpose: "review" });
    // turning a card is the normal flow, not help: no support event
    expect(sent.filter((e) => e.type === "item.support_shown")).toEqual([]);
  });

  it("says when no card is due after all", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json(path),
      "GET /api/paths/p1/review": () => json(hub({ cards_due: 1 })),
      "POST /api/reviews/start": () => json({ assessment_id: null, purpose: "review", items: [], due: 0 }),
    });
    const user = userEvent.setup();
    renderApp("/paths/p1/review");
    await user.click(await screen.findByRole("button", { name: "Review cards" }));
    expect(await screen.findByText(/No cards are due right now/)).toBeInTheDocument();
  });
});

describe("notes", () => {
  it("adds, edits and deletes a note on a block", async () => {
    type Note = { id: string; text: string; bid: string | null; lesson_version_id: string; created_at: string; updated_at: string };
    const notes: Note[] = [];
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/lessons/L1": () =>
        json({
          id: "L1",
          state: "ready",
          path_id: "p1",
          skill_id: "s1",
          version_id: "lv1",
          title: "Joins",
          body: [
            { type: "heading", bid: "b1", level: 1, text: "Joins" },
            { type: "paragraph", bid: "b2", inlines: [{ text: "A join combines rows." }] },
          ],
          est_minutes: 5,
          lang: "en",
          skill_title: "Joining",
          path_title: "SQL",
          practice_items: 0,
        }),
      "GET /api/lessons/L1/notes": () => json(notes),
      "POST /api/notes": (_r, body) => {
        const b = body as Note;
        notes.push({ ...b, id: "n1", created_at: "x", updated_at: "x" });
        return json({ note_id: "n1" }, 201);
      },
      "PATCH /api/notes/n1": (_r, body) => {
        notes[0]!.text = (body as { text: string }).text;
        return new Response(null, { status: 204 });
      },
      "DELETE /api/notes/n1": () => {
        notes.splice(0, 1);
        return new Response(null, { status: 204 });
      },
      "POST /api/events": events([], () => null),
    });
    const user = userEvent.setup();
    renderApp("/lessons/L1");

    await screen.findByText("A join combines rows.");
    const paragraph = screen.getByText("A join combines rows.").closest("[data-bid]")!;
    await user.click(within(paragraph as HTMLElement).getByRole("button", { name: "Add a note here" }));
    await user.type(screen.getByRole("textbox", { name: "Note on this part" }), "Remember LEFT JOIN");
    await user.click(screen.getByRole("button", { name: "Save note" }));

    expect(await screen.findByText("Remember LEFT JOIN")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST" && c.path === "/api/notes")?.body).toEqual({
      text: "Remember LEFT JOIN",
      bid: "b2",
      lesson_version_id: "lv1",
    });

    await user.click(screen.getByRole("button", { name: "Edit" }));
    const box = screen.getByRole("textbox", { name: "Edit note" });
    await user.clear(box);
    await user.type(box, "LEFT keeps the left rows");
    await user.click(screen.getByRole("button", { name: "Save note" }));
    expect(await screen.findByText("LEFT keeps the left rows")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ text: "LEFT keeps the left rows" });

    await user.click(screen.getByRole("button", { name: "Delete note" }));
    await waitFor(() => expect(screen.queryByText("LEFT keeps the left rows")).toBeNull());
    expect(calls.some((c) => c.method === "DELETE" && c.path === "/api/notes/n1")).toBe(true);
  });
});

describe("settings", () => {
  const setting = (key: string, over: object = {}) => ({
    key,
    cfg: "CFG-00",
    levels: ["installation", "learner"],
    value: null,
    source: null,
    default: null,
    explanation: `About ${key}.`,
    example: "An example.",
    suggestion: "A suggestion.",
    impact: ["learning"],
    weakens_learning: null,
    ...over,
  });

  it("edits learner values, shows server errors, hides the preset and keeps installation values read-only", async () => {
    const values: Record<string, unknown> = { gamification: "full", "skill_test.pass_mark": 0.8 };
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/settings": () =>
        json([
          setting("model.preset", { levels: ["installation"], value: "claude" }),
          setting("gamification", { value: values["gamification"], default: "full", source: "learner" }),
          setting("skill_test.pass_mark", { value: values["skill_test.pass_mark"], default: 0.8 }),
          setting("budget.cap_usd_month", { levels: ["installation"], value: 10, impact: ["cost"] }),
          setting("mastery.decay", { value: true, default: true, weakens_learning: "Without decay, forgotten skills stay mastered." }),
        ]),
      "PUT /api/settings/gamification": (_r, body) => {
        values["gamification"] = (body as { value: unknown }).value;
        return new Response(null, { status: 204 });
      },
      "PUT /api/settings/skill_test.pass_mark": () =>
        json({ detail: "skill_test.pass_mark must be between 0.5 and 1" }, 422),
    });
    const user = userEvent.setup();
    renderApp("/settings");

    expect(await screen.findByRole("heading", { name: "Game elements" })).toBeInTheDocument();
    expect(screen.queryByText(/model\.preset/)).toBeNull();
    const budget = screen.getByRole("heading", { name: "Monthly budget cap" }).closest("li")!;
    expect(budget).toHaveTextContent("This is set for the whole installation.");
    expect(screen.getByText(/Without decay, forgotten skills stay mastered\./)).toBeInTheDocument();

    const game = screen.getByRole("heading", { name: "Game elements" }).closest("li")!;
    expect(game).toHaveTextContent("Now: Full (XP, streaks, levels) (your setting)");
    await user.click(within(game as HTMLElement).getByRole("button", { name: /Full \(XP, streaks, levels\)/ }));
    await user.click(await screen.findByRole("option", { name: "Off" }));
    await user.click(within(game as HTMLElement).getByRole("button", { name: "Save Game elements" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT" && c.path === "/api/settings/gamification")?.body).toEqual({
        value: "off",
        level: "learner",
      }),
    );
    expect(
      await within(screen.getByRole("heading", { name: "Game elements" }).closest("li") as HTMLElement).findByText(/Now: Off/),
    ).toBeInTheDocument();

    const mark = screen.getByRole("heading", { name: "Skill test pass mark" }).closest("li") as HTMLElement;
    await user.click(within(mark).getByRole("button", { name: /Increase/ }));
    await user.click(within(mark).getByRole("button", { name: "Save Skill test pass mark" }));
    expect(await within(mark).findByText(/must be between 0.5 and 1/)).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/settings/skill_test.pass_mark")?.body).toEqual({ value: 0.85, level: "learner" });
  });
});

describe("erasing a path's data", () => {
  it("asks once, erases, and says the path starts again", async () => {
    const api = mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json(path),
      "GET /api/paths/p1/progress": () => json(progress()),
      "DELETE /api/paths/p1/personal-data": () => json({ counts: { learning_event: 12 } }),
    });
    const user = userEvent.setup();
    renderApp("/paths/p1/progress");
    await user.click(await screen.findByRole("button", { name: "Delete my data in this path" }));
    expect(api.calls.some((c) => c.method === "DELETE")).toBe(false); // not before the confirmation
    const ask = screen.getByRole("group", { name: /Delete your progress and everything you wrote/ });
    await user.click(within(ask).getByRole("button", { name: "Delete my data" }));
    expect(await screen.findByText("Deleted. The path starts again from the beginning.")).toBeInTheDocument();
    expect(api.calls.filter((c) => c.method === "DELETE").map((c) => c.path)).toEqual(["/api/paths/p1/personal-data"]);
  });

  it("can be cancelled", async () => {
    const api = mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json(path),
      "GET /api/paths/p1/progress": () => json(progress()),
    });
    const user = userEvent.setup();
    renderApp("/paths/p1/progress");
    await user.click(await screen.findByRole("button", { name: "Delete my data in this path" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Delete my data in this path" })).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "DELETE")).toBe(false);
  });
});
