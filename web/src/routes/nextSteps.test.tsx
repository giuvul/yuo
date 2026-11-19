import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import type { NextOut, PathOut } from "../api/client";
import { activateLocale } from "../i18n";
import { json, mockApi } from "../test/mockApi";
import { appRoutes, closeApps, renderApp } from "../test/renderApp";

const path: PathOut = {
  id: "p1",
  title: "Jazz piano",
  subject: "Jazz piano",
  goal: "Comp over standards",
  status: "active",
  difficulty: "foundational",
  content_lang: "en",
  level_check: "none",
  preview: "none",
  origin: "goal",
  jobs: [],
  branches: [
    {
      id: "b1",
      code: "chords",
      title: "Chords",
      skills: [
        {
          id: "s1",
          code: "chords.sevenths",
          title: "Seventh chords",
          summary: "Build them",
          requires: [],
          objectives: [],
          lessons: [{ id: "l1", code: "l1", kind: "core", state: "ready", title: "Seventh chords", has_draft: false }],
        },
      ],
    },
  ],
};

const base: NextOut = {
  status: "none",
  available: true,
  completion: 0.75,
  offer: null,
  diagnosis: { lessons_done: 6, lessons_left: 2, finished_branches: ["Chords"], strong: ["Seventh chords"], weak: [], shaky: ["Voice a ii-V-I"] },
  questions: [],
  quiz: [],
  quiz_result: null,
  directions: [],
  chosen: null,
  added: [],
  job_id: null,
  failed: false,
};

const ready: NextOut = {
  ...base,
  status: "ready",
  questions: [{ prompt: "What do you want to play next?", options: ["Ballads", "Up-tempo swing"] }],
  quiz: [
    { prompt: "Which scale fits a G7alt?", options: ["Altered", "Dorian", "Lydian"], topic: "Altered dominants" },
    { prompt: "What is a tritone substitution?", options: ["Db7 for G7", "G7 for C", "Dm7 for G7"], topic: "Substitutions" },
  ],
};

const proposed: NextOut = {
  ...base,
  status: "proposed",
  quiz_result: { right: 1, total: 2, ready: ["Altered dominants"], not_yet: ["Substitutions"] },
  directions: [
    { code: "deeper-reharm", kind: "deeper", title: "Reharmonisation", reason: "You got the altered scale right and want ballads.", preview: ["Tritone subs", "Passing chords"] },
    { code: "apply-tunes", kind: "apply", title: "Comping on three standards", reason: "You asked to play real tunes.", preview: ["Autumn Leaves", "Blue Bossa"] },
  ],
};

beforeAll(async () => {
  await activateLocale("en");
});
afterEach(closeApps);

describe("What next?", () => {
  it("invites the learner on the path page when a branch is finished", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json(path),
      "GET /api/paths/p1/progress": () => json({ skills: {} }),
      "GET /api/paths/p1/proposals": () => json([]),
      "GET /api/paths/p1/requests": () => json([]),
      "GET /api/paths/p1/next": () => json({ ...base, offer: "branch_done" }),
    });
    renderApp("/paths/p1");
    const offer = await screen.findByTestId("next-offer");
    expect(within(offer).getByText(/You finished a branch/)).toBeInTheDocument();
    expect(within(offer).getByRole("link", { name: "Choose what's next" })).toHaveAttribute("href", "/paths/p1/next");
    // the card carries it: no second "What next?" link in the overview
    expect(screen.queryByRole("link", { name: "What next?" })).not.toBeInTheDocument();
  });

  it("offers What next? only from three quarters of the path", async () => {
    let next = { ...base, available: false, completion: 0.4 };
    mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json(path),
      "GET /api/paths/p1/progress": () => json({ skills: {} }),
      "GET /api/paths/p1/proposals": () => json([]),
      "GET /api/paths/p1/requests": () => json([]),
      "GET /api/paths/p1/next": () => json(next),
    });
    const { unmount } = renderApp("/paths/p1");
    expect(await screen.findByRole("link", { name: "See your progress" })).toHaveAttribute("href", "/paths/p1/progress");
    expect(screen.queryByRole("link", { name: "What next?" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("next-offer")).not.toBeInTheDocument();
    unmount();
    next = { ...base, available: true, completion: 0.8 };
    renderApp("/paths/p1");
    expect(await screen.findByRole("link", { name: "What next?" })).toHaveAttribute("href", "/paths/p1/next");
  });

  it("shows what Yuo knows, then the AI-written questions and quiz, and sends the answers", async () => {
    let state: NextOut = base;
    let posted: unknown;
    mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json(path),
      "GET /api/paths/p1/next": () => json(state),
      "POST /api/paths/p1/next": () => {
        state = ready;
        return json(state);
      },
      "POST /api/paths/p1/next/answers": (_req, body) => {
        posted = body;
        state = { ...base, status: "proposing" };
        return json(state);
      },
    });
    const user = userEvent.setup();
    renderApp("/paths/p1/next");
    expect(await screen.findByText("6 lessons studied, 2 still planned")).toBeInTheDocument();
    expect(screen.getByText("Worth another look: Voice a ii-V-I")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Start" }));

    expect(await screen.findByText("What do you want to play next?")).toBeInTheDocument();
    const submit = screen.getByRole("button", { name: "See my directions" });
    expect(submit).toBeDisabled();
    await user.click(screen.getByRole("radio", { name: "Ballads" }));
    await user.type(screen.getAllByLabelText("Or in your own words (optional)")[0]!, "Bill Evans voicings");
    await user.click(screen.getByRole("radio", { name: "Altered" }));
    await user.click(screen.getAllByRole("radio", { name: "I don’t know yet" })[1]!);
    await user.click(submit);
    await waitFor(() =>
      expect(posted).toEqual({ quiz: [0, null], answers: [{ option: 0, text: "Bill Evans voicings" }] }),
    );
    expect(await screen.findByText("Finding directions that fit your answers…")).toBeInTheDocument();
  });

  it("adds a direction only after the learner confirms it", async () => {
    let chosen: unknown;
    mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json(path),
      "GET /api/paths/p1/next": () => json(proposed),
      "POST /api/paths/p1/next/choose": (_req, body) => {
        chosen = body;
        return json({ ...proposed, status: "growing", chosen: "apply-tunes" });
      },
    });
    const user = userEvent.setup();
    renderApp("/paths/p1/next");
    expect(await screen.findByText("Reharmonisation")).toBeInTheDocument();
    expect(screen.getByText(/Quiz: 1 of 2 right\. Ready for: Altered dominants\./)).toBeInTheDocument();
    expect(screen.getByText("Best match")).toBeInTheDocument();
    expect(screen.getByText("Would add: Autumn Leaves, Blue Bossa")).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Choose this direction" })[1]!);
    expect(chosen).toBeUndefined();
    const confirm = screen.getByRole("group", { name: "Comping on three standards" });
    await user.click(within(confirm).getByRole("button", { name: "Add to my path" }));
    await waitFor(() => expect(chosen).toEqual({ code: "apply-tunes" }));
    expect(await screen.findByText("Adding the new branches to your path…")).toBeInTheDocument();
  });

  it("names what was added once the path has grown", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json(path),
      "GET /api/paths/p1/next": () => json({ ...base, status: "done", added: ["Standards in practice"] }),
    });
    renderApp("/paths/p1/next");
    expect(await screen.findByText(/Added to your path: Standards in practice/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the path" })).toBeInTheDocument();
  });
});
