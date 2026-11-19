import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { PathOut } from "../api/client";
import { hasActiveJobs } from "../api/hooks";
import { activateLocale } from "../i18n";
import { json, mockApi } from "../test/mockApi";
import { appRoutes, cliReady, cliSignedOut, renderApp } from "../test/renderApp";

function pathWith(
  lessons: { id: string; state: string; title: string | null; kind?: string }[],
  jobs: PathOut["jobs"] = [],
): PathOut {
  return {
    id: "p1",
    title: "SQL for analysts",
    subject: "SQL",
    goal: "Write reports",
    status: "active",
    difficulty: "foundational",
    content_lang: "en",
    level_check: "none",
    preview: "none",
    origin: "goal",
    jobs,
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
            summary: "SELECT and WHERE",
            requires: [],
            objectives: [],
            lessons: lessons.map((l) => ({ kind: "core", has_draft: false, ...l, code: l.id })),
          },
        ],
      },
    ],
  };
}

describe("path view", () => {
  beforeAll(async () => {
    await activateLocale("en");
  });
  // these are about the list view; the tree (the default) has its own tests in src/path/PathGraph.test.tsx
  beforeEach(() => localStorage.setItem("yuo.path.view", "list"));
  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("polls only while a job is queued, running or waiting", () => {
    const job = (status: string) => ({
      id: "j",
      kind: "lesson",
      status,
      error: null,
      attempt: 1,
      target_kind: "lesson",
      target_id: "l1",
    });
    expect(hasActiveJobs(pathWith([], [job("queued")]))).toBe(true);
    expect(hasActiveJobs(pathWith([], [job("running")]))).toBe(true);
    expect(hasActiveJobs(pathWith([], [job("waiting_resource")]))).toBe(true);
    expect(hasActiveJobs(pathWith([], [job("succeeded"), job("failed")]))).toBe(false);
    expect(hasActiveJobs(undefined)).toBe(false);
  });

  it("shows lesson states, links ready lessons, generates planned ones and refetches", async () => {
    let generated = false;
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () =>
        json(
          generated
            ? pathWith(
                [
                  { id: "l1", state: "ready", title: "What a table is" },
                  { id: "l2", state: "queued", title: "Filtering" },
                ],
                [
                  {
                    id: "j2",
                    kind: "lesson",
                    status: "queued",
                    error: null,
                    attempt: 0,
                    target_kind: "lesson",
                    target_id: "l2",
                  },
                ],
              )
            : pathWith(
                [
                  { id: "l1", state: "ready", title: "What a table is" },
                  { id: "l2", state: "planned", title: "Filtering" },
                  { id: "l3", state: "failed", title: "Sorting" },
                ],
                [
                  {
                    id: "j1",
                    kind: "lesson",
                    status: "failed",
                    error: "lesson_body: invalid output after repair: 3 problems",
                    attempt: 3,
                    target_kind: "lesson",
                    target_id: "l3",
                  },
                ],
              ),
        ),
      "POST /api/lessons/l2/generate": () => {
        generated = true;
        return json({ job_id: "j2" }, 202);
      },
    });
    const user = userEvent.setup();
    renderApp("/paths/p1");

    expect(await screen.findByRole("heading", { level: 1, name: "SQL for analysts" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "What a table is" })).toHaveAttribute("href", "/lessons/l1");
    expect(screen.getByText("Planned")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate “Sorting”" })).toHaveTextContent("Try again");
    const sortingRow = screen.getByText("Sorting").closest("li")!;
    expect(sortingRow).toHaveTextContent(/The model's answer was not usable, even after Yuo asked it to fix it\./);
    expect(screen.getByText("Filtering").closest("li")).not.toHaveTextContent(/not usable/);

    await user.click(screen.getByRole("button", { name: "Generate “Filtering”" }));
    expect(calls.some((c) => c.method === "POST" && c.path === "/api/lessons/l2/generate")).toBe(true);
    expect(await screen.findByText("Queued")).toBeInTheDocument();
    expect(screen.getByText(/Writing a lesson/).closest("li")).toHaveTextContent("waiting to start");
  });
});

describe("a lesson that failed its review", () => {
  beforeAll(async () => {
    await activateLocale("en");
  });
  beforeEach(() => localStorage.setItem("yuo.path.view", "list"));
  afterEach(() => localStorage.clear());

  it("can be accepted with the reviewer's feedback", async () => {
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () =>
        json(pathWith([{ id: "l3", state: "failed", title: "Sorting", has_draft: true } as never])),
      "POST /api/lessons/l3/accept": () => json({ job_id: "j9" }, 202),
    });
    const user = userEvent.setup();
    renderApp("/paths/p1");
    await user.click(await screen.findByRole("button", { name: "Accept “Sorting” with the reviewer's feedback" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/api/lessons/l3/accept")).toBe(true));
  });
});

describe("generation while the subscription's program is not ready", () => {
  beforeAll(async () => {
    await activateLocale("en");
  });
  beforeEach(() => localStorage.setItem("yuo.path.view", "list"));
  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("answers a refused Generate with the way to Settings, not the server's text", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () =>
        json(
          pathWith([
            { id: "l1", state: "ready", title: "What a table is" },
            { id: "l2", state: "planned", title: "Filtering" },
          ]),
        ),
      "POST /api/lessons/l2/generate": () =>
        json(
          { detail: "the chosen AI access is not ready", code: "ai_not_ready", cli: "claude", reason: "not_logged_in" },
          409,
        ),
    });
    const user = userEvent.setup();
    renderApp("/paths/p1");

    await user.click(await screen.findByRole("button", { name: "Generate “Filtering”" }));
    const link = await screen.findByRole("link", { name: "Sign in to Claude Code in Settings to continue" });
    expect(link).toHaveAttribute("href", "/settings#cli-claude");
    expect(screen.getByText("Yuo cannot write right now: Claude Code is not signed in.")).toBeInTheDocument();
    expect(screen.queryByText(/the chosen AI access is not ready/)).toBeNull();
  });

  it("warns on Home when there are paths and the program is not installed", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/setup/ai-ready": () =>
        json({ ready: false, clis: [{ ...cliSignedOut(), installed: false, reason: "not_installed" }] }),
      "GET /api/paths": () =>
        json([
          {
            id: "p1",
            title: "SQL",
            subject: "SQL",
            status: "active",
            difficulty: "foundational",
            content_lang: "en",
            created_at: "2026-10-27T10:00:00.000Z",
          },
        ]),
    });
    renderApp("/");
    expect(await screen.findByText("Yuo cannot write right now: Claude Code is not installed.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Install Claude Code in Settings to continue" })).toHaveAttribute(
      "href",
      "/settings#cli-claude",
    );
  });
});

describe("new path", () => {
  beforeAll(async () => {
    await activateLocale("en");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows the estimate and creates the path", async () => {
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/estimate": () =>
        json({
          low_usd: 0.12,
          high_usd: 0.4,
          notional_usd: 3.5,
          missing: [],
          lines: [
            {
              unit: "review",
              count: 20,
              adapter: "claude-cli",
              model: "opus",
              low: 1.5,
              high: 1.5,
              billed: false,
              source: "shipped",
            },
          ],
          plan_usage: [
            {
              cli: "claude-cli",
              plan: "pro",
              label: "Pro",
              window_pct: 31.8,
              week_pct: 2.2,
              lessons_per_window: 62,
              lessons_per_week: 897,
            },
          ],
        }),
      "POST /api/paths": () => json({ path_id: "p9", job_id: "j9" }, 201),
      "GET /api/paths/p9": () => json({ ...pathWith([]), id: "p9", title: "Statistics", branches: [] }),
    });
    const user = userEvent.setup();
    const { router } = renderApp("/paths/new");

    expect(await screen.findByText("about $0.12–$0.40 billed")).toBeInTheDocument();
    expect(
      screen.getByText("No extra cost on your subscription; it uses part of your plan's limits:"),
    ).toBeInTheDocument();
    expect(screen.getByText("Pro: about 62 lessons per 5-hour window; the whole path takes 2% of the week")).toBeInTheDocument();
    expect(screen.queryByText(/\$3\.50/)).not.toBeInTheDocument();
    expect(calls.find((c) => c.path.startsWith("/api/estimate"))?.path).toBe("/api/estimate?lessons=20");

    await user.type(screen.getByRole("textbox", { name: "Title" }), "Statistics");
    expect(screen.queryByRole("textbox", { name: "Subject" })).toBeNull();
    await user.type(screen.getByRole("textbox", { name: "Your goal" }), "Read a report");
    await user.click(screen.getByRole("radio", { name: "Pass an exam" }));
    expect(screen.queryByRole("radio", { name: "Introductory" })).toBeNull(); // the level check sets it
    await user.click(screen.getByRole("button", { name: "More options" })); // custom instructions are tucked away
    await user.type(screen.getByRole("textbox", { name: /Custom instructions/ }), "Use R");
    expect(screen.getByText(/5 of 1000 characters/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create path" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/paths/p9"));
    expect(calls.find((c) => c.method === "POST" && c.path === "/api/paths")?.body).toEqual({
      title: "Statistics",
      subject: "",
      difficulty: "foundational",
      goal: "Read a report",
      goal_type: "exam",
      custom_instructions: "Use R",
      level_check: true,
      preview: true,
    });
  });

  const noEstimate = { "GET /api/estimate": () => json({ detail: "no models" }, 409) };

  it("checks the subscription's program before the form: the card to fix it, and no Create path until then", async () => {
    let status = cliSignedOut();
    const { calls } = mockApi({
      ...appRoutes,
      ...noEstimate,
      "GET /api/setup/ai-ready": () => json({ ready: status.ready, clis: [status] }),
      "GET /api/setup/cli/claude": () => json(status),
      "POST /api/setup/cli/claude/login": () => {
        status = cliReady();
        return json(status, 202);
      },
    });
    const user = userEvent.setup();
    renderApp("/paths/new");

    expect(await screen.findByText(/Before Yuo can write your path:/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Claude Code is installed, but not signed in" })).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Title" }), "Statistics");
    await user.type(screen.getByRole("textbox", { name: "Your goal" }), "Read a report");
    expect(screen.getByRole("button", { name: "Create path" })).toBeDisabled();

    // fixed right here: the notice goes and the path can be created
    await user.click(screen.getByRole("button", { name: "Sign in to Claude Code" }));
    await waitFor(() => expect(screen.queryByText(/Before Yuo can write your path:/)).toBeNull());
    expect(screen.getByRole("button", { name: "Create path" })).toBeEnabled();
    expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue("Statistics"); // nothing typed is lost
    expect(calls.some((c) => c.method === "POST" && c.path === "/api/paths")).toBe(false);
  });

  it("turns a 409 ai_not_ready on Create path into the program's card, not a raw error", async () => {
    let signedOut = false;
    mockApi({
      ...appRoutes,
      ...noEstimate,
      "GET /api/setup/ai-ready": () => (signedOut ? json({ ready: false, clis: [cliSignedOut()] }) : json({ ready: true, clis: [] })),
      "GET /api/setup/cli/claude": () => json(cliSignedOut()),
      "POST /api/paths": () => {
        signedOut = true; // the sign-in ended after the page was opened
        return json(
          { detail: "the chosen AI access is not ready", code: "ai_not_ready", cli: "claude", reason: "not_logged_in" },
          409,
        );
      },
    });
    const user = userEvent.setup();
    const { router } = renderApp("/paths/new");

    await user.type(await screen.findByRole("textbox", { name: "Title" }), "Statistics");
    await user.type(screen.getByRole("textbox", { name: "Your goal" }), "Read a report");
    await user.click(screen.getByRole("button", { name: "Create path" }));

    expect(
      await screen.findByRole("heading", { name: "Claude Code is installed, but not signed in" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in to Claude Code" })).toBeInTheDocument();
    expect(screen.queryByText(/the chosen AI access is not ready/)).toBeNull();
    expect(screen.queryByText(/The server could not do this/)).toBeNull();
    expect(router.state.location.pathname).toBe("/paths/new");
    await waitFor(() => expect(screen.getByRole("button", { name: "Create path" })).toBeDisabled());
  });

  it("treats a server without the program checks (404) as nothing to check", async () => {
    const { calls } = mockApi({
      ...appRoutes,
      ...noEstimate,
      "GET /api/setup/ai-ready": () => json({ detail: "Not Found" }, 404),
    });
    renderApp("/paths/new");
    await waitFor(() => expect(calls.some((c) => c.path === "/api/setup/ai-ready")).toBe(true));
    expect(await screen.findByRole("button", { name: "Create path" })).toBeEnabled();
    expect(screen.queryByText(/Before Yuo can write your path:/)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says what is wrong when the level check questions failed because the program is signed out", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/setup/ai-ready": () => json({ ready: false, clis: [cliSignedOut()] }),
      "GET /api/paths/p1": () => json({ ...pathWith([]), status: "draft", branches: [], level_check: "preparing" }),
      "GET /api/paths/p1/progress": () => json({ skills: {} }),
      "GET /api/paths/p1/proposals": () => json([]),
      "GET /api/paths/p1/level-check": () =>
        json({ status: "preparing", questions: [], result: null, job_id: "j1", failed: true }),
    });
    renderApp("/paths/p1");

    const notice = await screen.findByRole("alert");
    await waitFor(() => expect(notice).toHaveTextContent("Claude Code is not signed in."));
    expect(notice).toHaveTextContent("The questions could not be written.");
    expect(screen.getByRole("link", { name: "Sign in to Claude Code in Settings to continue" })).toHaveAttribute(
      "href",
      "/settings#cli-claude",
    );
    expect(screen.getByRole("button", { name: "Skip it and start from the basics" })).toBeInTheDocument();
  });

  it("asks the level check questions one at a time before the path is planned", async () => {
    const questions = [
      { prompt: "What does SELECT do?", options: ["Reads rows", "Deletes rows", "Adds a table"], topic: "Basics" },
      { prompt: "What is a window function?", options: ["A view", "A per-row aggregate", "A lock"], topic: "Windows" },
    ];
    let posted: unknown;
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json({ ...pathWith([]), status: "draft", branches: [], level_check: "ready" }),
      "GET /api/paths/p1/progress": () => json({ skills: {} }),
      "GET /api/paths/p1/proposals": () => json([]),
      "GET /api/paths/p1/level-check": () =>
        json({ status: "ready", questions, result: null, job_id: "j1", failed: false }),
      "POST /api/paths/p1/level-check": (_req, body) => {
        posted = body;
        return json({ status: "done", questions, result: null, job_id: "j1", failed: false });
      },
    });
    const user = userEvent.setup();
    renderApp("/paths/p1");

    expect(await screen.findByText("What does SELECT do?")).toBeInTheDocument();
    expect(screen.getByText("Question 1 of 2")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reads rows" }));
    expect(await screen.findByText("What is a window function?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "I don’t know yet" }));
    await waitFor(() => expect(posted).toEqual({ answers: [0, null], skip: false }));
    expect(calls.some((c) => c.method === "POST" && c.path === "/api/paths/p1/level-check")).toBe(true);
  });

  it("shows the plan before it is built, sends the learner's changes and builds it", async () => {
    const tree = {
      branches: [
        {
          code: "basics",
          title: "Basics",
          skills: [
            { code: "basics.select", title: "Selecting rows", summary: "SELECT and WHERE", requires: [], objectives: [], lessons: [{ code: "l1", title: "First query" }] },
            { code: "basics.join", title: "Joins", summary: "Combine tables", requires: ["basics.select"], objectives: [], lessons: [{ code: "l2", title: "Inner joins" }] },
          ],
        },
      ],
    };
    const view = (status: string, extra = {}) => ({ status, version: 1, tree, changes: [], feedback: [], job_id: null, failed: false, ...extra });
    const posted: { path: string; body: unknown }[] = [];
    let current = view("ready");
    mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json({ ...pathWith([]), status: "draft", branches: [], preview: "ready" }),
      "GET /api/paths/p1/progress": () => json({ skills: {} }),
      "GET /api/paths/p1/proposals": () => json([]),
      "GET /api/paths/p1/preview": () => json(current),
      "POST /api/paths/p1/preview/feedback": (_req, body) => {
        posted.push({ path: "feedback", body });
        current = view("ready", { version: 2, changes: ["Added a part on window functions."], feedback: ["add windows"] });
        return json(current);
      },
      "POST /api/paths/p1/preview/build": () => {
        posted.push({ path: "build", body: null });
        return json(view("built"));
      },
    });
    const user = userEvent.setup();
    renderApp("/paths/p1");

    expect(await screen.findByText("Joins")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Your plan" })).toBeInTheDocument();
    expect(screen.getByText("After: Selecting rows")).toBeInTheDocument();
    expect(screen.getByText("1 branch · 2 skills · 2 lessons")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change the plan" })).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: /Anything missing/ }), "add windows");
    await user.click(screen.getByRole("button", { name: "Change the plan" }));
    expect(await screen.findByText("Added a part on window functions.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Build it" }));
    await waitFor(() => expect(posted.map((p) => p.path)).toEqual(["feedback", "build"]));
    expect(posted[0]?.body).toEqual({ text: "add windows" });
  });

  it("lets the learner skip the level check while the questions are written", async () => {
    let posted: unknown;
    mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json({ ...pathWith([]), status: "draft", branches: [], level_check: "preparing" }),
      "GET /api/paths/p1/progress": () => json({ skills: {} }),
      "GET /api/paths/p1/proposals": () => json([]),
      "GET /api/paths/p1/level-check": () =>
        json({ status: "preparing", questions: [], result: null, job_id: "j1", failed: false }),
      "POST /api/paths/p1/level-check": (_req, body) => {
        posted = body;
        return json({ status: "skipped", questions: [], result: null, job_id: "j1", failed: false });
      },
    });
    const user = userEvent.setup();
    renderApp("/paths/p1");

    expect(await screen.findByText(/Writing a few questions/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Skip it and start from the basics" }));
    await waitFor(() => expect(posted).toEqual({ answers: [], skip: true }));
  });
});
