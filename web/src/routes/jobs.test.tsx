// The jobs list in words: what each job is for, the step a running one is at, how long it
// has left, and a calm line for a job that will try again.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it } from "vitest";
import { activateLocale } from "../i18n";
import { json, mockApi } from "../test/mockApi";
import { appRoutes, renderApp } from "../test/renderApp";

beforeAll(async () => {
  await activateLocale("en");
});

const job = {
  attempt: 1,
  error: null,
  title: "Keyboard and Rhythm Foundations",
  step: null,
  round: null,
  rounds: null,
  running_s: null,
  typical_s: 900,
  retry_at: null,
};

describe("the jobs page", () => {
  it("names the lesson, the step and the time left", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/jobs": () =>
        json([
          { ...job, id: "j1", kind: "rendition", status: "running", target_kind: "rendition", target_id: "r1", step: "render", round: 2, rounds: 4, running_s: 300 },
          { ...job, id: "j2", kind: "items", status: "queued", target_kind: "lesson", target_id: "l1", title: "Inner joins", typical_s: 120 },
          { ...job, id: "j3", kind: "rendition", status: "queued", target_kind: "rendition", target_id: "r2", title: "Outer joins", attempt: 2, error: "the render container stopped answering", retry_at: "2099-01-01T10:30:00.000Z" },
          { ...job, id: "j4", kind: "lesson", status: "running", target_kind: "lesson", target_id: "l2", title: "Self joins", step: "review", running_s: 400, typical_s: 240 },
        ]),
    });
    renderApp("/jobs");
    const video = (await screen.findByText("Keyboard and Rhythm Foundations")).closest("tr")!;
    expect(within(video).getByText("Making a video lesson")).toBeInTheDocument();
    expect(video).toHaveTextContent("Rendering the video · draft 2 of at most 4 · about 10 minutes left");
    const items = screen.getByText("Inner joins").closest("tr")!;
    expect(items).toHaveTextContent("Writing review questions");
    expect(items).toHaveTextContent("usually takes about 2 minutes");
    const retry = screen.getByText("Outer joins").closest("tr")!;
    expect(retry).toHaveTextContent(/trying again at/);
    expect(retry).toHaveTextContent("Yuo tries again by itself");
    expect(screen.getByText("Self joins").closest("tr")).toHaveTextContent("Checking the lesson for mistakes · taking longer than usual, still working");
  });

  it("shows each waiting job's place in line and the rule behind the order", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/settings": () => json([{ key: "generation.buffer", value: 5 }]),
      "GET /api/jobs": () =>
        json([
          { ...job, id: "j1", kind: "lesson", status: "queued", target_kind: "lesson", target_id: "l1", title: "Inner joins", turn: 1 },
          { ...job, id: "j2", kind: "rendition", status: "queued", target_kind: "rendition", target_id: "r1", title: "Outer joins", turn: 2 },
        ]),
    });
    renderApp("/jobs");
    const first = (await screen.findByText("Inner joins")).closest("tr")!;
    expect(within(first).getByText("Next in line")).toBeInTheDocument();
    expect(within(screen.getByText("Outer joins").closest("tr")!).getByText("Number 2 in line")).toBeInTheDocument();
    expect(await screen.findByText(/keeps the next 5 lessons of each path written ahead of you/)).toBeInTheDocument();
  });

  it("starts a failed video again from the list, and links its lesson", async () => {
    const api = mockApi({
      ...appRoutes,
      "GET /api/jobs": () =>
        json([
          { ...job, id: "j5", kind: "rendition", status: "failed", target_kind: "rendition", target_id: "r5", title: "Key Layout and Note Names", lesson_id: "L5", attempt: 3, error: "the render container stopped answering" },
          { ...job, id: "j6", kind: "grade", status: "failed", target_kind: "response", target_id: "x", error: "boom" },
        ]),
      "POST /api/jobs/j5/retry": () => json({ job_id: "j7" }, 202),
    });
    renderApp("/jobs");
    const link = await screen.findByRole("link", { name: "Key Layout and Note Names" });
    expect(link).toHaveAttribute("href", "/lessons/L5");
    const buttons = screen.getAllByRole("button", { name: "Try again" });
    expect(buttons).toHaveLength(1); // a grading job is not started again from here
    await userEvent.setup().click(buttons[0]!);
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "/api/jobs/j5/retry")).toBe(true));
  });

  it("keeps finished jobs in a history, newest first, a page at a time", async () => {
    const done = { ...job, attempt: 1, created_at: "2026-11-15T16:50:00.000Z", started_at: "2026-11-15T16:51:00.000Z", resolved: false };
    mockApi({
      ...appRoutes,
      "GET /api/jobs/history": (req) =>
        new URL(req.url).searchParams.get("before")
          ? json({ jobs: [{ ...done, id: "h3", kind: "lesson", status: "succeeded", target_kind: "lesson", target_id: "l9", title: "Rests", lesson_id: "L9", finished_at: "2026-11-14T09:00:00.000Z" }], next: null })
          : json({
              jobs: [
                { ...done, id: "h1", kind: "rendition", status: "succeeded", target_kind: "rendition", target_id: "r5", title: "Key Layout and Note Names", lesson_id: "L5", finished_at: "2026-11-15T18:39:43.000Z", started_at: "2026-11-15T18:27:50.000Z" },
                { ...done, id: "h2", kind: "rendition", status: "failed", target_kind: "rendition", target_id: "r5", title: "Key Layout and Note Names", lesson_id: "L5", finished_at: "2026-11-15T17:40:00.000Z", error: "ENOSPC: no space left on device, write", resolved: true },
              ],
              next: "2026-11-15T17:40:00.000Z|h2",
            }),
    });
    renderApp("/jobs");
    expect(await screen.findByRole("heading", { name: "History" })).toBeInTheDocument();
    const rows = (await screen.findAllByRole("link", { name: "Key Layout and Note Names" })).map((l) => l.closest("tr")!);
    expect(rows[0]).toHaveTextContent("done");
    expect(rows[0]).toHaveTextContent("took 12 minutes");
    expect(rows[1]).toHaveTextContent("failed");
    expect(rows[1]).toHaveTextContent("done later by another try");
    expect(rows[1]).toHaveTextContent("There was not enough space to put the video together.");
    await userEvent.setup().click(screen.getByRole("button", { name: "Show older" }));
    expect(await screen.findByRole("link", { name: "Rests" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show older" })).not.toBeInTheDocument();
  });

  it("pauses only the videos until tomorrow morning", async () => {
    const puts: unknown[] = [];
    mockApi({
      ...appRoutes,
      "PUT /api/generation/pause": (_request, body) => {
        puts.push(body);
        return json({ paused: true, scope: "videos", until: (body as { until: string }).until, waiting: 2, finishing: [] });
      },
    });
    const u = userEvent.setup();
    renderApp("/jobs");
    expect(await screen.findByRole("heading", { name: "Pause writing ahead" })).toBeInTheDocument();
    await u.click(screen.getByRole("radio", { name: "Only videos" }));
    await u.click(screen.getByRole("radio", { name: "Until tomorrow morning" }));
    await u.click(screen.getByRole("button", { name: "Pause" }));
    expect(await screen.findByRole("heading", { name: "Writing ahead is paused" })).toBeInTheDocument();
    const body = puts[0] as { scope: string; until: string };
    expect(body.scope).toBe("videos");
    const until = new Date(body.until);
    expect(until.getHours()).toBe(7);
    expect(until.getTime()).toBeGreaterThan(Date.now());
    expect(screen.getByText(/Videos wait; lessons and questions keep coming/)).toHaveTextContent("2 jobs wait.");
    expect(screen.getByRole("link", { name: /Paused/ })).toHaveAttribute("href", "/jobs"); // the header says so too
  });

  it("says what is still finishing and resumes", async () => {
    let paused = true;
    mockApi({
      ...appRoutes,
      "GET /api/jobs": () =>
        json([{ ...job, id: "j1", kind: "lesson", status: "queued", target_kind: "lesson", target_id: "l1", title: "Inner joins", error: "paused" }]),
      "GET /api/generation/pause": () =>
        json(
          paused
            ? {
                paused: true,
                scope: "all",
                until: null,
                waiting: 3,
                finishing: [{ job_id: "j9", kind: "rendition", step: "video_scene", step_s: 130, typical_s: 330 }],
              }
            : { paused: false, scope: null, until: null, waiting: 0, finishing: [] },
        ),
      "PUT /api/generation/pause": () => {
        paused = false;
        return json({ paused: false, scope: null, until: null, waiting: 0, finishing: [] });
      },
    });
    const u = userEvent.setup();
    renderApp("/jobs");
    const finishing = await screen.findByText(/Still finishing one step: Writing the script and the scenes/);
    expect(finishing).toHaveTextContent("It usually takes about 6 minutes (2 so far).");
    expect(finishing).toHaveTextContent("what it wrote is kept");
    expect(screen.getByText("Inner joins").closest("tr")).toHaveTextContent("Paused: it goes on from where it stopped");
    await u.click(screen.getByRole("button", { name: "Resume now" }));
    expect(await screen.findByRole("heading", { name: "Pause writing ahead" })).toBeInTheDocument();
  });
});
