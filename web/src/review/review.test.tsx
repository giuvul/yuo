// The review hub, the session player's state machine and the results, against a small stand-in for the server's
// staged grading: a wrong first try gives only that option's rationale, the key comes with the resolution.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { Graded } from "../api/client";
import { activateLocale } from "../i18n";
import type { OutboxEvent } from "../outbox/events";
import { UUID7_PATTERN } from "../outbox/uuid7";
import { json, mockApi, type Handler } from "../test/mockApi";
import { appRoutes, renderApp } from "../test/renderApp";
import { contextOut } from "../test/tutor";
import type { ReviewHub, ReviewItem, ReviewResult, ReviewSession } from "./api";

type EventsBody = { device_id: string; events: OutboxEvent[] };
type Payload = { attempt_id: string; item_version_id: string; answer?: string; kind?: string; level?: number; confidence?: string };

const OPTIONS = [
  { id: "a", text: "Alpha" },
  { id: "b", text: "Beta" },
  { id: "c", text: "Gamma" },
  { id: "d", text: "Delta" },
];
/** The right answer of every question is "b" (Beta, key 2). */
const KEY = "b";
const WHY = Object.fromEntries(OPTIONS.map((o) => [o.id, `Why ${o.text} is ${o.id === KEY ? "right" : "wrong"}`]));

function item(id: string, objective: string, over: Partial<ReviewItem> = {}): ReviewItem {
  return {
    item_version_id: id,
    item_id: `item-${id}`,
    type: "mcq",
    view: { prompt: `Prompt ${id}?`, options: OPTIONS },
    skill_id: "s1",
    skill_title: "Joining tables",
    objectives: [objective],
    cross: false,
    kind: "recall",
    level: 1,
    state: null,
    ...over,
  };
}

function session(over: Partial<ReviewSession> = {}): ReviewSession {
  return {
    assessment_id: "as-1",
    attempt_id: null,
    purpose: "review",
    path_id: "p1",
    size: 3,
    items: [item("q1", "o1"), item("q2", "o2"), item("q3", "o3", { cross: true, kind: "scenario", level: 2 })],
    reserves: [item("r2", "o2"), item("r3", "o3")],
    ...over,
  };
}

const hub = (over: Partial<ReviewHub> = {}): ReviewHub => ({
  path_id: "p1",
  memory: 0.82,
  objectives: 3,
  due: 1,
  fading: 1,
  strong: 1,
  questions: 19,
  writing: 0,
  allowed_today: 50,
  sizes: [5, 10],
  open_session: null,
  skills: [
    {
      id: "s1",
      title: "Joining tables",
      branch_id: "b1",
      retrievability: 0.64,
      due: 1,
      questions: 11,
      objectives: [
        { id: "o1", statement: "Join two tables on a key", retrievability: 0.52, due: true, due_at: "2026-11-10T10:00:00.000Z", reviews: 1 },
        { id: "o2", statement: "Tell an inner join from a left join", retrievability: 0.76, due: false, due_at: "2026-11-20T10:00:00.000Z", reviews: 2 },
      ],
    },
    {
      id: "s2",
      title: "Selecting rows",
      branch_id: "b1",
      retrievability: 0.97,
      due: 0,
      questions: 8,
      objectives: [
        { id: "o3", statement: "Filter rows with WHERE", retrievability: 0.97, due: false, due_at: "2026-12-02T10:00:00.000Z", reviews: 3 },
      ],
    },
  ],
  branches: [{ id: "b1", title: "Basics" }],
  recent: [{ attempt_id: "old", finished_at: "2026-11-11T09:00:00.000Z", answered: 5, first_try: 4 }],
  cards_due: 0,
  ...over,
});

/**
 * The server's side of a review session: staged feedback from the events it was sent. `calls` and `sent` are what
 * the client did; `offline` makes the events endpoint unreachable.
 */
function server(s: ReviewSession, opts: { offline?: boolean; hubOver?: Partial<ReviewHub>; routes?: Record<string, Handler> } = {}) {
  const sent: OutboxEvent[] = [];
  const state: Record<string, { tried: string[]; shown: boolean; hints: number; guessing: boolean }> = {};
  const of = (iv: string) => (state[iv] ??= { tried: [], shown: false, hints: 0, guessing: false });
  const feedback = (iv: string): Graded => {
    const q = of(iv);
    const right = q.tried.at(-1) === KEY;
    const resolved = right || q.shown || q.tried.length >= 2;
    const outcome = right ? (q.tried.length === 1 ? "first" : "second") : resolved ? "revealed" : q.tried.length ? "open" : "new";
    const view: Graded = {
      pending: false,
      hidden: false,
      outcome,
      resolved,
      tries: q.tried.length,
      tried: q.tried,
      hints: q.hints,
      guessing: q.guessing,
      score: outcome === "first" ? 1 : outcome === "second" ? 0.5 : 0,
      rationales: Object.fromEntries(q.tried.map((id) => [id, WHY[id]!])),
    };
    if (!resolved) return view;
    return {
      ...view,
      correct: KEY,
      rationales: WHY,
      solution: `Explanation of ${iv}`,
      concept: "Join conditions",
      revisit: "the section on join keys",
      lesson_id: "L1",
      lesson_title: "Joining two tables",
    };
  };
  const result = (attempt: string): ReviewResult => {
    const items = Object.keys(state)
      .filter((iv) => of(iv).tried.length > 0 || of(iv).shown)
      .map((iv) => ({ item_version_id: iv, prompt: `Prompt ${iv}?`, ...feedback(iv) }));
    const first = items.filter((i) => i.outcome === "first").length;
    return {
      attempt_id: attempt,
      finished: true,
      answered: items.length,
      first_try: first,
      second_try: items.filter((i) => i.outcome === "second").length,
      revealed: items.filter((i) => i.outcome === "revealed" || i.outcome === "open").length,
      score: items.length ? first / items.length : 0,
      xp: 25,
      skills: [{ id: "s1", title: "Joining tables", before: 0.64, after: 0.93, next_due: "2026-11-19T10:00:00.000Z" }],
      items,
    };
  };
  const table: Record<string, Handler> = {
    ...appRoutes,
    "GET /api/paths/p1/review": () => json(hub(opts.hubOver)),
    "POST /api/paths/p1/review/sessions": () => json(s),
    "POST /api/events": (_req, body) => {
      if (opts.offline) return "network-error";
      const { events } = body as EventsBody;
      sent.push(...events);
      const graded: Record<string, Graded> = {};
      const rejected: Record<string, string> = {};
      for (const e of events) {
        const p = e.payload as Payload;
        if (e.type === "assessment.response_given") {
          const q = of(p.item_version_id);
          if (feedback(p.item_version_id).resolved) {
            rejected[e.id] = "this question is already resolved";
            continue;
          }
          q.tried.push(p.answer!);
          q.guessing ||= p.confidence === "guessing";
          graded[e.id] = feedback(p.item_version_id);
        } else if (e.type === "item.support_shown") {
          if (p.kind === "solution") of(p.item_version_id).shown = true;
          else of(p.item_version_id).hints += 1;
        }
      }
      return json({ accepted: events.map((e) => e.id).filter((id) => !(id in rejected)), duplicates: [], rejected, graded, outcomes: {} });
    },
    ...opts.routes,
  };
  // the attempt id is the client's: match those paths by pattern
  const patterns: [RegExp, (m: RegExpMatchArray) => Response][] = [
    [/^GET \/api\/review\/attempts\/([^/]+)\/items\/([^/]+)$/, (m) => json(feedback(m[2]!))],
    [/^GET \/api\/review\/attempts\/([^/]+)$/, (m) => json(result(m[1]!))],
    [/^GET \/api\/items\/([^/]+)\/hints\/(\d)$/, (m) => (Number(m[2]) <= 2 ? json({ level: Number(m[2]), text: `Hint ${m[2]} for ${m[1]}`, last: m[2] === "2" }) : json({ detail: "no such hint" }, 404))],
    [/^POST \/api\/items\/([^/]+)\/report$/, () => new Response(null, { status: 204 })],
  ];
  const routes = new Proxy(table, {
    get(target, key: string) {
      if (target[key]) return target[key];
      const hit = patterns.map(([re, fn]) => [key.match(re), fn] as const).find(([m]) => m);
      return hit ? () => hit[1](hit[0]!) : undefined;
    },
  });
  const { calls } = mockApi(routes);
  const payloads = (type: string) => sent.filter((e) => e.type === type).map((e) => e.payload as Payload);
  return { sent, calls, payloads };
}

const option = (name: string) => screen.getByRole("button", { name: new RegExp(`^[A-D]\\. ${name}`) });
const status = async (text: string | RegExp) => (await screen.findByText(text)).closest("[role=status]") as HTMLElement;

/** Chooses an option and sends it with the button on screen ("Check answer" or "Try again"). */
async function answer(user: ReturnType<typeof userEvent.setup>, name: string, button = "Check answer") {
  await user.click(option(name));
  await user.click(screen.getByRole("button", { name: button }));
}

beforeAll(async () => {
  await activateLocale("en");
});
afterEach(() => vi.unstubAllGlobals());

describe("review hub", () => {
  it("shows memory, what is due, the sessions on offer, each skill's objectives and recent sessions", async () => {
    server(session());
    renderApp("/paths/p1/review");

    expect(await screen.findByRole("img", { name: "Memory: 82%" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "1 idea is due for review" })).toBeInTheDocument();
    // only the sizes the server offers
    expect(screen.getByRole("link", { name: "Quick 5" })).toHaveAttribute("href", "/paths/p1/review/session?size=5");
    expect(screen.getByRole("link", { name: "Standard 10" })).toHaveAttribute("href", "/paths/p1/review/session?size=10");
    expect(screen.queryByRole("link", { name: /Deep/ })).toBeNull();

    // weakest skill first, each objective with its statement, memory and a due mark in words
    const cards = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(cards).toEqual(["Joining tables", "Selecting rows"]);
    const due = screen.getByText("Join two tables on a key").closest("li")!;
    expect(due).toHaveTextContent("52% remembered");
    expect(due).toHaveTextContent("Due");
    expect(screen.getByText("Filter rows with WHERE").closest("li")).toHaveTextContent(/97% remembered · next review/);
    expect(screen.getByRole("link", { name: "Review this skill: Joining tables" })).toHaveAttribute(
      "href",
      "/paths/p1/review/session?size=5&skill=s1",
    );
    expect(screen.getByText("4 of 5 right on the first try")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Cards" })).toBeNull(); // no cards due
  });

  it("offers to continue an open session instead of a new one", async () => {
    server(session(), { hubOver: { open_session: { assessment_id: "as-1", attempt_id: "att-1", size: 5, answered: 2 } } });
    renderApp("/paths/p1/review");
    expect(await screen.findByRole("link", { name: "Continue your session (2 of 5)" })).toHaveAttribute(
      "href",
      "/paths/p1/review/session",
    );
    expect(screen.queryByRole("link", { name: /Quick/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /Review this skill/ })).toBeNull();
  });

  it("explains itself before anything was studied, says when questions are being written or today's limit is reached", async () => {
    server(session(), { hubOver: { memory: null, objectives: 0, skills: [], sizes: [], recent: [], questions: 0 } });
    const first = renderApp("/paths/p1/review");
    expect(await screen.findByRole("heading", { name: "Nothing to review yet" })).toBeInTheDocument();
    expect(screen.getByText(/Finish a lesson and its ideas appear here/)).toBeInTheDocument();
    first.unmount();

    server(session(), { hubOver: { sizes: [], questions: 0, writing: 2 } });
    const second = renderApp("/paths/p1/review");
    expect(await screen.findByText(/Writing your review questions/)).toBeInTheDocument();
    second.unmount();

    server(session(), { hubOver: { allowed_today: 0 } });
    renderApp("/paths/p1/review");
    expect(await screen.findByText(/You reached today's review limit/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Quick/ })).toBeNull();
  });

  it("the Reviews tab goes straight to the hub when there is one path, and lists them when there are more", async () => {
    const one = { id: "p1", title: "SQL", subject: "SQL", status: "active", difficulty: "foundational", content_lang: "en", created_at: "2026-10-01T10:00:00.000Z" };
    server(session(), { routes: { "GET /api/paths": () => json([one]) } });
    const first = renderApp("/review");
    await waitFor(() => expect(first.router.state.location.pathname).toBe("/paths/p1/review"));
    first.unmount();

    server(session(), {
      routes: {
        "GET /api/paths": () => json([one, { ...one, id: "p2", title: "Git" }]),
        "GET /api/paths/p2/review": () => json(hub({ path_id: "p2", memory: null, due: 0 })),
      },
    });
    renderApp("/review");
    expect(await screen.findByRole("link", { name: /SQL.*1 due/ })).toHaveAttribute("href", "/paths/p1/review");
    expect(await screen.findByRole("link", { name: /Git.*Nothing studied yet/ })).toHaveAttribute("href", "/paths/p2/review");
  });
});

describe("review player", () => {
  it("a wrong first try shows only that option's rationale, then the second try resolves it", async () => {
    const { payloads, calls } = server(session());
    const user = userEvent.setup();
    renderApp("/paths/p1/review/session?size=5");

    expect(await screen.findByRole("heading", { name: "Prompt q1?" })).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/paths/p1/review/sessions")?.body).toEqual({ size: 5, skill_id: null, branch_id: null });
    expect(screen.getByText("Question 1 of 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check answer" })).toBeDisabled(); // nothing chosen yet
    expect(screen.queryByRole("button", { name: "Show answer" })).toBeNull();

    await answer(user, "Alpha");
    expect(await status("Not quite. One more try.")).toBeInTheDocument();
    // the tried option: struck out (disabled, marked "Tried") with its rationale; nothing about the others
    expect(option("Alpha")).toBeDisabled();
    expect(option("Alpha")).toHaveTextContent("Tried");
    expect(screen.getByText("Why Alpha is wrong")).toBeInTheDocument();
    expect(screen.queryByText(/Why Beta/)).toBeNull();
    expect(screen.queryByText("Right answer")).toBeNull();
    expect(screen.queryByText(/Explanation of q1/)).toBeNull();
    expect(screen.getByRole("button", { name: "Show answer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeDisabled(); // choose another option first

    await answer(user, "Beta", "Try again");
    const fb = await status("Right on the second try.");
    expect(fb).toHaveTextContent("You were sure: worth a closer look.");
    expect(fb).toHaveTextContent("Explanation of q1");
    expect(fb).toHaveTextContent("Join conditions");
    expect(fb).toHaveTextContent("Look again: the section on join keys");
    expect(within(fb).getByRole("link", { name: "Lesson: Joining two tables" })).toHaveAttribute("href", "/lessons/L1");
    expect(option("Beta")).toHaveTextContent("Right answer");
    expect(option("Alpha")).toHaveTextContent("Your answer");
    for (const o of OPTIONS) expect(screen.getByText(WHY[o.id]!)).toBeInTheDocument(); // every rationale now
    expect(screen.getByText("Question 1: right on the second try")).toBeInTheDocument(); // the vine, in words

    // exactly as other assessments: one attempt.started, answers as events, no confidence unless guessing
    const [started] = payloads("attempt.started") as unknown as { attempt_id: string; assessment_id: string; purpose: string }[];
    expect(started).toMatchObject({ assessment_id: "as-1", purpose: "review" });
    expect(started!.attempt_id).toMatch(UUID7_PATTERN);
    const answers = payloads("assessment.response_given");
    expect(answers.map((a) => a.answer)).toEqual(["a", "b"]);
    expect(answers.every((a) => a.attempt_id === started!.attempt_id && !("confidence" in a))).toBe(true);

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByRole("heading", { name: "Prompt q2?" })).toBeInTheDocument();
  });

  it("two wrong tries reveal the answer; a third answer is not offered", async () => {
    const { payloads } = server(session());
    const user = userEvent.setup();
    renderApp("/paths/p1/review/session");

    await screen.findByRole("heading", { name: "Prompt q1?" });
    await answer(user, "Alpha");
    await status("Not quite. One more try.");
    await answer(user, "Gamma", "Try again");
    const fb = await status("Here is the answer.");
    expect(fb).toHaveTextContent("You were sure: worth a closer look.");
    expect(option("Beta")).toHaveTextContent("Right answer");
    expect(screen.getByText("Question 1: answer shown")).toBeInTheDocument();
    for (const o of OPTIONS) expect(option(o.text)).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Check answer|Try again/ })).toBeNull();
    expect(payloads("assessment.response_given")).toHaveLength(2);
  });

  it("“Show answer” records the reveal and fetches the resolved feedback", async () => {
    const { payloads, calls } = server(session());
    const user = userEvent.setup();
    renderApp("/paths/p1/review/session");

    await screen.findByRole("heading", { name: "Prompt q1?" });
    await answer(user, "Delta");
    await status("Not quite. One more try.");
    await user.click(screen.getByRole("button", { name: "Show answer" }));
    expect(await status("Here is the answer.")).toHaveTextContent("Explanation of q1");
    expect(option("Beta")).toHaveTextContent("Right answer");

    const attempt = payloads("attempt.started")[0]!.attempt_id;
    expect(payloads("item.support_shown")).toEqual([{ item_version_id: "q1", attempt_id: attempt, kind: "solution", level: 0 }]);
    expect(calls.some((c) => c.method === "GET" && c.path === `/api/review/attempts/${attempt}/items/q1`)).toBe(true);
    expect(payloads("assessment.response_given")).toHaveLength(1); // the reveal is not an answer
  });

  it("gives two hints at most, each recorded as help", async () => {
    const { payloads, calls } = server(session());
    const user = userEvent.setup();
    renderApp("/paths/p1/review/session");

    await screen.findByRole("heading", { name: "Prompt q1?" });
    await user.click(screen.getByRole("button", { name: "Hint" }));
    expect(await screen.findByText("Hint 1 for q1")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Another hint" }));
    expect(await screen.findByText("Hint 2 for q1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "No more hints" })).toBeDisabled();

    await waitFor(() => expect(payloads("item.support_shown")).toHaveLength(2));
    const attempt = payloads("attempt.started")[0]!.attempt_id;
    expect(payloads("item.support_shown")).toEqual([
      { item_version_id: "q1", attempt_id: attempt, kind: "hint", level: 1 },
      { item_version_id: "q1", attempt_id: attempt, kind: "hint", level: 2 },
    ]);
    expect(calls.some((c) => c.path.endsWith("/hints/3"))).toBe(false); // the third rung is not for review
  });

  it("sends the guessing flag only when the toggle is on, and is plain about a sure wrong answer", async () => {
    const { payloads } = server(session());
    const user = userEvent.setup();
    renderApp("/paths/p1/review/session");

    await screen.findByRole("heading", { name: "Prompt q1?" });
    await user.click(screen.getByRole("switch", { name: "I'm guessing" }));
    await answer(user, "Alpha");
    await status("Not quite. One more try.");
    await answer(user, "Beta", "Try again");
    const fb = await status("Right on the second try.");
    expect(fb).not.toHaveTextContent("You were sure"); // a guess is not held against them
    await user.click(screen.getByRole("button", { name: "Next" }));

    await screen.findByRole("heading", { name: "Prompt q2?" });
    expect(screen.getByRole("switch", { name: "I'm guessing" })).not.toBeChecked(); // per question
    await answer(user, "Beta");
    await status("Right, first try.");
    const answers = payloads("assessment.response_given");
    expect(answers.filter((a) => a.item_version_id === "q1").every((a) => a.confidence === "guessing")).toBe(true);
    expect("confidence" in answers.find((a) => a.item_version_id === "q2")!).toBe(false);
  });

  it("asks a reserve only for an objective whose question was revealed, then shows the results", async () => {
    const { payloads, sent } = server(session());
    const user = userEvent.setup();
    renderApp("/paths/p1/review/session");

    await screen.findByRole("heading", { name: "Prompt q1?" });
    await answer(user, "Beta");
    await status("Right, first try.");
    await user.click(screen.getByRole("button", { name: "Next" }));

    await screen.findByRole("heading", { name: "Prompt q2?" }); // objective o2: revealed
    await answer(user, "Alpha");
    await status("Not quite. One more try.");
    await user.click(screen.getByRole("button", { name: "Show answer" }));
    await status("Here is the answer.");
    await user.click(screen.getByRole("button", { name: "Next" }));

    await screen.findByRole("heading", { name: "Prompt q3?" });
    expect(screen.getByText("Scenario")).toBeInTheDocument();
    expect(screen.getByText("Connects lessons")).toBeInTheDocument();
    expect(screen.getByText("Level 2")).toBeInTheDocument();
    expect(screen.queryByText("Asked again")).toBeNull();
    await answer(user, "Beta");
    await status("Right, first try.");
    // not the end: the reserve of o2 comes, marked as asked again; o3 was not revealed, so r3 never shows
    expect(screen.queryByRole("button", { name: "See results" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByRole("heading", { name: "Prompt r2?" })).toBeInTheDocument();
    expect(screen.getByText("Asked again")).toBeInTheDocument();
    expect(screen.getByText("Question 4 of 4")).toBeInTheDocument();
    await answer(user, "Beta");
    // on the last question the feedback stays until "See results"
    expect(await status("Right, first try.")).toBeInTheDocument();
    expect(sent.some((e) => e.type === "attempt.finished")).toBe(false);
    await user.click(screen.getByRole("button", { name: "See results" }));

    expect(await screen.findByRole("heading", { name: "Session done" })).toBeInTheDocument();
    const attempt = payloads("attempt.started")[0]!.attempt_id;
    expect(sent.at(-1)).toMatchObject({ type: "attempt.finished", payload: { attempt_id: attempt, outcome: "finished" } });
    expect(payloads("assessment.response_given").map((a) => a.item_version_id)).toEqual(["q1", "q2", "q3", "r2"]);
    expect(screen.getByRole("img", { name: "3 of 4 right on the first try" })).toBeInTheDocument();
    expect(screen.getByText("First try").closest("div")).toHaveTextContent("3");
    expect(screen.getByText("Shown").closest("div")).toHaveTextContent("1");
    expect(screen.getByText("XP").closest("div")).toHaveTextContent("+25");
    expect(screen.getByText("Joining tables").closest("li")).toHaveTextContent(/from 64% to 93%.*Next review:/);
    const again = screen.getByRole("heading", { name: "Worth another look" }).closest("div")!;
    expect(within(again).getByText("Prompt q2?")).toBeInTheDocument();
    expect(within(again).getByRole("link", { name: "Lesson: Joining two tables" })).toHaveAttribute("href", "/lessons/L1");
    expect(screen.getByRole("link", { name: "Back to the path" })).toHaveAttribute("href", "/paths/p1");
    expect(screen.getByRole("button", { name: "Review again" })).toBeInTheDocument();
  });

  it("without a reveal there is no reserve, and a flawless run of five gets its own title", async () => {
    const five = session({ size: 5, items: ["q1", "q2", "q3", "q4", "q5"].map((id, i) => item(id, `o${i + 1}`)) });
    const { sent } = server(five);
    const user = userEvent.setup();
    renderApp("/paths/p1/review/session?size=5");

    for (const [n, id] of ["q1", "q2", "q3", "q4", "q5"].entries()) {
      await screen.findByRole("heading", { name: `Prompt ${id}?` });
      await answer(user, "Beta");
      await status("Right, first try.");
      await user.click(screen.getByRole("button", { name: n === 4 ? "See results" : "Next" }));
    }
    expect(await screen.findByRole("heading", { name: "Every answer right, first try" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Worth another look" })).toBeNull();
    expect(sent.filter((e) => e.type === "assessment.response_given")).toHaveLength(5);
  }, 15_000);

  it("resumes a session: restores each question's state and does not start the attempt again", async () => {
    const first: Graded = { pending: false, hidden: false, outcome: "first", resolved: true, tries: 1, tried: ["b"], hints: 0, guessing: false, score: 1, correct: KEY, rationales: WHY, solution: "Explanation of q1" };
    const open: Graded = { pending: false, hidden: false, outcome: "open", resolved: false, tries: 1, tried: ["c"], hints: 1, guessing: false, score: 0, rationales: { c: WHY["c"]! } };
    const resumed = session({
      attempt_id: "att-1",
      items: [item("q1", "o1", { state: first }), item("q2", "o2", { state: open }), item("q3", "o3", { state: { pending: false, hidden: false, outcome: "new", resolved: false, tries: 0, tried: [], hints: 0 } })],
    });
    const { payloads } = server(resumed);
    const user = userEvent.setup();
    renderApp("/paths/p1/review/session");

    // the first unresolved question, with its wrong try and its hint back in place
    expect(await screen.findByRole("heading", { name: "Prompt q2?" })).toBeInTheDocument();
    expect(screen.getByText("Question 2 of 3")).toBeInTheDocument();
    expect(screen.getByText("Question 1: right on the first try")).toBeInTheDocument();
    expect(option("Gamma")).toBeDisabled();
    expect(screen.getByText("Why Gamma is wrong")).toBeInTheDocument();
    expect(await screen.findByText("Hint 1 for q2")).toBeInTheDocument();
    expect(await status("Not quite. One more try.")).toBeInTheDocument();

    await answer(user, "Beta", "Try again");
    await screen.findByText(/Explanation of q2/);
    expect(payloads("attempt.started")).toEqual([]);
    expect(payloads("assessment.response_given")).toEqual([
      expect.objectContaining({ attempt_id: "att-1", item_version_id: "q2", answer: "b" }),
    ]);
    expect(payloads("item.support_shown")).toEqual([]); // reading the old hint again is not new help
  });

  it("is played with the keyboard: 1-4 or A-D choose, Enter checks and goes on, H gives a hint", async () => {
    const { payloads } = server(session());
    const user = userEvent.setup();
    renderApp("/paths/p1/review/session");

    await screen.findByRole("heading", { name: "Prompt q1?" });
    await user.keyboard("1");
    expect(option("Alpha")).toHaveAttribute("aria-pressed", "true");
    await user.keyboard("{Enter}");
    await status("Not quite. One more try.");
    await user.keyboard("1{Enter}"); // the tried option cannot be chosen again: nothing is sent
    await user.keyboard("h");
    expect(await screen.findByText("Hint 1 for q1")).toBeInTheDocument();
    await user.keyboard("b");
    expect(option("Beta")).toHaveAttribute("aria-pressed", "true");
    await user.keyboard("{Enter}");
    await status("Right on the second try.");
    expect(payloads("assessment.response_given").map((a) => a.answer)).toEqual(["a", "b"]);
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("heading", { name: "Prompt q2?" })).toBeInTheDocument();
  });

  it("offline: the answer is kept, counts as one try, and the session moves on", async () => {
    const { sent } = server(session(), { offline: true });
    const user = userEvent.setup();
    renderApp("/paths/p1/review/session");

    await screen.findByRole("heading", { name: "Prompt q1?" });
    await answer(user, "Alpha");
    expect(await status("Saved. You will see the feedback when you are back online.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Try again|Check answer/ })).toBeNull(); // one try
    expect(screen.getByText("Question 1: answer saved")).toBeInTheDocument();
    expect(sent).toEqual([]); // still in the outbox
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByRole("heading", { name: "Prompt q2?" })).toBeInTheDocument();
  });

  it("a reported question is retired and skipped", async () => {
    const { calls, payloads } = server(session());
    const user = userEvent.setup();
    renderApp("/paths/p1/review/session");

    await screen.findByRole("heading", { name: "Prompt q1?" });
    await user.click(screen.getByRole("button", { name: "More for this question" }));
    await user.click(await screen.findByRole("menuitem", { name: "Report question" }));
    const dialog = await screen.findByRole("dialog", { name: "Report this question" });
    await user.type(within(dialog).getByRole("textbox", { name: /What is wrong with it/ }), "Two options are right");
    await user.click(within(dialog).getByRole("button", { name: "Report and skip" }));

    expect(await screen.findByRole("heading", { name: "Prompt q2?" })).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/items/item-q1/report")?.body).toEqual({ reason: "Two options are right" });
    expect(screen.getByText("Question 1: reported")).toBeInTheDocument();
    expect(payloads("assessment.response_given")).toEqual([]);
  });

  it("tells the tutor which attempt and question are on screen; the dock says “No spoilers” while coaching", async () => {
    const coach = { ...contextOut({ mode: "review", scope: "attempt", checked: true }), policy: "review.coach" };
    const { calls, payloads } = server(session(), {
      routes: {
        "POST /api/tutor/context": () => json(coach),
        "GET /api/tutor/messages": () => json([]),
        "GET /api/tutor/conversations": () => json([]),
      },
    });
    const user = userEvent.setup();
    renderApp("/paths/p1/review/session");

    await screen.findByRole("heading", { name: "Prompt q1?" });
    await user.keyboard("t");
    const dock = await screen.findByRole("complementary", { name: /Tutor/ });
    expect(await within(dock).findByText("No spoilers")).toBeInTheDocument();
    expect(within(dock).getByText(/never the answer/)).toBeInTheDocument();
    const attempt = payloads("attempt.started")[0]!.attempt_id;
    const context = calls.filter((c) => c.path === "/api/tutor/context").at(-1)!.body;
    expect(context).toMatchObject({ screen: "review", path_id: "p1", attempt_id: attempt, item_version_id: "q1" });
  });

  it("falls back to a standard session when the URL names a size that does not exist", async () => {
    const { calls } = server(session());
    renderApp("/paths/p1/review/session?size=7");
    await screen.findByRole("heading", { name: "Prompt q1?" });
    expect(calls.find((c) => c.path === "/api/paths/p1/review/sessions")?.body).toEqual({ size: 10, skill_id: null, branch_id: null });
  });

  it("says so when there is nothing to ask", async () => {
    server(session({ assessment_id: null, items: [], reserves: [], size: 0 }));
    renderApp("/paths/p1/review/session?skill=s9");
    expect(await screen.findByText("There is nothing to review here right now.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to the review" })).toHaveAttribute("href", "/paths/p1/review");
  });
});
