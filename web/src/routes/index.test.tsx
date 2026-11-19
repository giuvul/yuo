import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { activateLocale } from "../i18n";
import { json, mockApi } from "../test/mockApi";
import { appRoutes, configuredSetup, renderApp } from "../test/renderApp";

const PATH = {
  id: "p1",
  title: "SQL for analysts",
  subject: "SQL",
  status: "active",
  difficulty: "foundational",
  content_lang: "en",
  created_at: "2026-10-27T10:00:00.000Z",
};

describe("home", () => {
  beforeAll(async () => {
    await activateLocale("en");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows the next step, what waits today and how it goes", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 18, 9, 0));
    mockApi({
      ...appRoutes,
      "GET /api/paths": () => json([PATH]),
      "GET /api/home": () =>
        json({
          next_step: {
            kind: "lesson",
            path_id: "p1",
            path_title: "Calculus",
            lesson_id: "l4",
            skill_id: "s4",
            title: "The chain rule",
            place: "Calculus 1",
            index: 4,
            count: 6,
            minutes: 8,
            started: true,
          },
          lessons_ready: 2,
          exam: { course_id: "c1", path_id: "p1", title: "Calculus 1", days: 9, built: true },
          today: [
            { kind: "fading", path_id: "p1", skills: ["Limits", "Kinematics"], count: 2 },
            { kind: "lesson_draft", path_id: "p1", lesson_id: "l9", title: "Derivative at a point" },
            { kind: "transcribing", path_id: "p1", title: "Lecture 3", percent: 64 },
            { kind: "arrange_ready", path_id: "p2", title: "My material", count: 3 },
          ],
          progress: { score: 88, delta: 4, status: "on_track", mastered: 10, skills: 12 },
          momentum: { streak: 6, xp_week: 420, achievement: { key: "mastered_triads", unlocked_at: "2026-11-17" } },
          insight: { kind: "time_of_day", part: "morning", percent: 91 },
        }),
    });
    renderApp("/");

    expect(await screen.findByRole("heading", { level: 1, name: "Good morning" })).toBeInTheDocument();
    expect(await screen.findByText(/2 new lessons ready/)).toBeInTheDocument();
    expect(screen.getByText(/exam in 9 days/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Continue: The chain rule/ })).toHaveAttribute("href", "/lessons/l4");
    expect(screen.getByText(/Lesson 4 of 6/)).toBeInTheDocument();
    expect(screen.getByText("2 skills fading: Limits, Kinematics")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Refresh" })).toHaveAttribute("href", "/paths/p1/review");
    expect(screen.getByRole("button", { name: "Accept with feedback" })).toBeInTheDocument();
    expect(screen.getByText("Lecture 3 is being transcribed (64%)")).toBeInTheDocument();
    expect(screen.getByText("New suggestion: your files could form 3 courses")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Mastery 88 of 100" })).toBeInTheDocument();
    expect(screen.getByText("+4 pts this week")).toBeInTheDocument();
    expect(screen.getByText("6 days")).toBeInTheDocument();
    expect(screen.getByText("420 XP")).toBeInTheDocument();
    expect(screen.getByText("Mastered triads")).toBeInTheDocument();
    expect(screen.getByText(/You answer best in the morning/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Paths" })).toHaveAttribute("href", "/paths");
    vi.useRealTimers();
  });

  it("lists paths and offers a new one", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/paths": () => json([PATH]),
    });
    renderApp("/paths");

    expect(await screen.findByRole("heading", { level: 1, name: "Your paths" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: /SQL for analysts/ })).toHaveAttribute("href", "/paths/p1");
    expect(screen.getByRole("link", { name: "New path" })).toHaveAttribute("href", "/paths/new");
    expect(screen.getByRole("link", { name: "Yuo" })).toBeInTheDocument();
    expect(screen.getByText("Synced")).toBeInTheDocument();
  });

  it("renames, archives and deletes a path from its menu", async () => {
    let paths = [{ ...PATH, goal: "Write queries" }];
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/paths": () => json(paths),
      "PATCH /api/paths/p1": (_req, body) => {
        paths = [{ ...paths[0]!, ...(body as Record<string, string>) }];
        return json(paths[0]);
      },
      "DELETE /api/paths/p1": () => {
        paths = [];
        return json({ counts: { path: 1 } });
      },
    });
    renderApp("/paths");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Actions for SQL for analysts" }));
    await user.click(screen.getByRole("menuitem", { name: "Rename or edit" }));
    const name = screen.getByRole("textbox", { name: "Name" });
    await user.clear(name);
    await user.type(name, "SQL in practice");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ title: "SQL in practice" }),
    );
    expect(await screen.findByRole("link", { name: /SQL in practice/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Actions for SQL in practice" }));
    await user.click(screen.getByRole("menuitem", { name: "Archive" }));
    expect(await screen.findByRole("heading", { name: "Archived" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Actions for SQL in practice" }));
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    expect(screen.getByRole("heading", { name: "Delete “SQL in practice”?" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete the path" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/api/paths/p1")).toBe(true));
    expect(await screen.findByText("Plant your first path")).toBeInTheDocument();
  });

  it("goes to setup while no models are bound", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/setup": () => json({ ...configuredSetup, bindings: {} }),
      "GET /api/paths": () => json([]),
    });
    const { router } = renderApp("/");

    await waitFor(() => expect(router.state.location.pathname).toBe("/setup"));
    expect(await screen.findByRole("heading", { level: 1, name: "Set up Yuo" })).toBeInTheDocument();
  });
});
