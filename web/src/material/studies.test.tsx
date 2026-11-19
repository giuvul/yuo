import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { PathOut } from "../api/client";
import { activateLocale } from "../i18n";
import { json, mockApi } from "../test/mockApi";
import { appRoutes, renderApp } from "../test/renderApp";
import type { CourseOut, StudiesOut } from "./api";

const path: PathOut = {
  id: "p1",
  title: "Mechanical Engineering",
  subject: "Mechanical Engineering",
  goal: "Pass the exams",
  status: "draft",
  difficulty: "intermediate",
  content_lang: "en",
  level_check: "none",
  preview: "none",
  origin: "courses",
  jobs: [],
  branches: [],
};

function course(over: Partial<CourseOut> = {}): CourseOut {
  return {
    id: "c1",
    code: "analysis-1",
    title: "Analysis 1",
    term: null,
    exam_date: null,
    adherence: "only",
    keep_order: true,
    built: false,
    materials: [
      {
        id: "m1",
        course_id: "c1",
        role: "textbook",
        kind: "pdf",
        title: "Analisi",
        file_name: "Analisi.pdf",
        size_bytes: 1000,
        received: 1000,
        pages: 320,
        duration_ms: null,
        state: "read",
        progress: 0,
        error: null,
        chunks: 140,
        tokens: 160000,
        sparse_pages: 2,
        formula_pages: 30,
        vision: null,
        vision_pages: 0,
        vision_total: 0,
        outlined: false,
      },
    ],
    plan: null,
    job_id: null,
    failed: false,
    updates: [],
    ...over,
  };
}

const plan: NonNullable<CourseOut["plan"]> = {
  status: "ready",
  version: 1,
  skills: [
    {
      code: "analysis-1.s1",
      title: "Limits",
      summary: "What a limit is",
      unit: "Chapter 1",
      not_in_material: false,
      requires: [],
      topics: ["m1.t1"],
      sections: 4,
      lessons: [{ code: "analysis-1.s1.l1", title: "Limits" }],
    },
    {
      code: "analysis-1.pre",
      title: "Inequalities refresher",
      summary: "Before chapter 1",
      unit: "Before",
      not_in_material: true,
      requires: [],
      topics: [],
      sections: 0,
      lessons: [{ code: "analysis-1.pre.l1", title: "Refresher" }],
    },
  ],
  skipped: ["Analisi, pp. 300-320: Appendix (not in the exam)"],
  changes: [],
  feedback: [],
  can_undo: false,
};

const studies = (over: Partial<StudiesOut>): StudiesOut => ({
  path_id: "p1",
  title: "Mechanical Engineering",
  status: "collecting",
  courses: [course()],
  links: { requires: [], related: [] },
  estimate: { tokens: 160000, audio_minutes: 0 },
  links_failed: false,
  ...over,
});

describe("studies from the learner's material", () => {
  beforeAll(async () => {
    await activateLocale("en");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows a course's files, the pages to read from their images, and no token counts", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/estimate": () => json({ detail: "no models" }, 409),
      "GET /api/paths/p1": () => json(path),
      "GET /api/paths/p1/progress": () => json({ skills: {} }),
      "GET /api/studies/p1": () => json(studies({})),
    });
    renderApp("/paths/p1");
    expect(await screen.findByText("Analisi")).toBeInTheDocument();
    expect(screen.getByText(/2 pages have little text: probably formulas or figures/)).toBeInTheDocument();
    expect(screen.getByText(/30 pages have formulas or symbols missing from their text/)).toHaveTextContent(
      /Reading them from their images is recommended/,
    );
    expect(screen.queryByText(/tokens/)).toBeNull();
  });

  it("counts the pages read from their images, and the reading and planning", async () => {
    const reading = course({});
    const m = { ...reading.materials[0]!, state: "reading" as const, vision: "wanted" as const, progress: 0.33, vision_total: 91 };
    const busy = studies({
      status: "drafting",
      courses: [{ ...reading, materials: [m], plan: null }],
      work: { done: 30, total: 120, step: { kind: "file", title: "Analisi", done: 28, total: 100 } },
    });
    mockApi({
      ...appRoutes,
      "GET /api/estimate": () => json({ detail: "no models" }, 409),
      "GET /api/paths/p1": () => json(path),
      "GET /api/paths/p1/progress": () => json({ skills: {} }),
      "GET /api/studies/p1": () => json(busy),
    });
    renderApp("/paths/p1");
    expect(await screen.findByText("Reading pages from their images: 30 of 91")).toBeInTheDocument();
    expect(screen.getByText("Reading Analisi: part 28 of 100")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Reading and planning" })).toHaveAttribute("aria-valuenow", "30");
  });

  it("starts from the files alone and takes the proposed name and courses", async () => {
    const inbox = course({ id: "c0", title: "Your material" });
    const proposal = {
      title: "Mechanical Engineering",
      goal: "Pass the first-year exams.",
      message: "Your physics files are one course and the analysis files another.",
      courses: [
        { title: "Analysis 1", term: "Year 1", files: [{ id: "m1", title: "Analisi", kind: "pdf" }] },
        { title: "Physics 1", term: null, files: [{ id: "m2", title: "Fisica", kind: "pdf" }] },
      ],
    };
    let current = studies({
      title: "My material",
      courses: [inbox],
      arrange: { status: "collecting", proposal: null, rounds: [], error: null, new_files: [] },
    });
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/estimate": () => json({ detail: "no models" }, 409),
      "POST /api/studies": () => json({ path_id: "p1" }, 201),
      "GET /api/paths/p1": () => json(path),
      "GET /api/paths/p1/progress": () => json({ skills: {} }),
      "GET /api/studies/p1": () => json(current),
      "POST /api/studies/p1/arrange": () => {
        current = { ...current, arrange: { status: "ready", proposal, rounds: [], error: null, new_files: [] } };
        return json(current);
      },
      "POST /api/studies/p1/arrange/accept": () => json(studies({})),
      "POST /api/courses/c0/materials": () => json({ ...inbox.materials[0], id: "m9", course_id: "c0", size_bytes: 0 }),
    });
    renderApp("/paths/new");
    const user = userEvent.setup();
    await user.click(await screen.findByText("My own material"));
    expect(calls.some((c) => c.path === "/api/studies")).toBe(false); // nothing is made until files are added
    await user.click(screen.getByText("A goal")); // and the choice can still change
    await user.click(screen.getByText("My own material"));
    expect(screen.getByText("As much as your material holds.")).toBeInTheDocument(); // the size follows the files
    await user.click(screen.getByRole("radio", { name: /Shorter/ }));
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    await user.upload(input, new File([], "Analisi.pdf", { type: "application/pdf" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/studies")).toBe(true));
    expect(calls.find((c) => c.path === "/api/studies")?.body).toMatchObject({ title: "", courses: [], depth: "short" });

    expect(await screen.findByRole("heading", { name: "Add all your material" })).toBeInTheDocument();
    await waitFor(() => // the file chosen on the form is sent to the path's upload
      expect(calls.find((c) => c.path === "/api/courses/c0/materials")?.body).toEqual({ file_name: "Analisi.pdf", size: 0 }),
    );
    await user.click(screen.getByRole("button", { name: /Suggest the courses/ }));
    expect(await screen.findByText(/Your physics files are one course/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Analysis 1" })).toBeInTheDocument();
    expect(screen.getByText("Fisica")).toBeInTheDocument();

    await user.type(screen.getByRole("textbox", { name: /Anything to change/ }), "One course, please");
    await user.click(screen.getByRole("button", { name: "Change the suggestion" }));
    await waitFor(() =>
      expect(calls.filter((c) => c.path === "/api/studies/p1/arrange").map((c) => c.body)).toEqual([
        { feedback: null },
        { feedback: "One course, please" },
      ]),
    );

    const name = screen.getByRole("textbox", { name: "Name of the path" });
    await user.clear(name);
    await user.type(name, "Engineering");
    await user.click(screen.getAllByRole("radio", { name: /Only my material/ })[0]!);
    await user.click(screen.getByRole("button", { name: /Use these courses/ }));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/api/studies/p1/arrange/accept")?.body).toEqual({
        title: "Engineering",
        adherence: ["only", "grounded"],
      }),
    );
  });

  it("reads a PDF's pages with formulas from their images when the learner asks", async () => {
    let current = studies({});
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json(path),
      "GET /api/paths/p1/progress": () => json({ skills: {} }),
      "GET /api/studies/p1": () => json(current),
      "POST /api/materials/m1/read-pages": () => {
        const [c] = current.courses;
        current = studies({ courses: [{ ...c!, materials: [{ ...c!.materials[0]!, state: "reading", vision: "wanted" }] }] });
        return json(current.courses[0]!.materials[0]);
      },
    });
    renderApp("/paths/p1");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Read them from their images" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/materials/m1/read-pages")).toBe(true));
    expect(await screen.findByText(/Reading the pages with formulas and figures/)).toBeInTheDocument();
  });

  it("shows each course's plan and sends feedback for that course", async () => {
    let current = studies({ status: "ready", estimate: null, courses: [course({ plan })] });
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json(path),
      "GET /api/paths/p1/progress": () => json({ skills: {} }),
      "GET /api/studies/p1": () => json(current),
      "POST /api/courses/c1/feedback": () => {
        current = studies({ status: "revising", estimate: null, courses: [course({ plan: { ...plan, status: "revising" } })] });
        return json(current.courses[0]);
      },
    });
    renderApp("/paths/p1");
    expect(await screen.findByText("Inequalities refresher")).toBeInTheDocument();
    expect(screen.getByText("Added by Yuo")).toBeInTheDocument();
    expect(screen.getByText("Chapter 1")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox", { name: /should go deeper in Analysis 1/ }), "Chapter 7 is not in the exam");
    await user.click(screen.getByRole("button", { name: "Change the plan" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/courses/c1/feedback")).toBe(true));
    expect(calls.find((c) => c.path === "/api/courses/c1/feedback")?.body).toEqual({ text: "Chapter 7 is not in the exam" });
    expect(await screen.findByText("Changing the plan…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Build the path/ })).toBeDisabled();
  });

  it("shows what a new recording adds to a built course and applies it on a yes", async () => {
    const book = course().materials[0]!;
    const lecture: CourseOut["materials"][number] = {
      ...book,
      id: "m2",
      role: "lecture",
      kind: "video",
      title: "Lecture 4",
      file_name: "Lecture 4.mp4",
      pages: null,
      duration_ms: 5_400_000,
      state: "read",
      chunks: 0,
      sparse_pages: 0,
      formula_pages: 0,
      vision: null,
      vision_pages: 0,
      vision_total: 0,
    };
    const update = {
      id: "u1",
      at: "2026-11-18T10:00:00.000Z",
      materials: ["Lecture 3"],
      changes: ["Lecture 3's worked examples joined Limits."],
      lessons: [{ id: "l1", title: "Limits" }],
      skills: ["Continuity"],
      status: "pending" as const,
    };
    let current = studies({
      status: "built",
      estimate: null,
      courses: [course({ built: true, plan, materials: [book, lecture], updates: [update] })],
    });
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json({ ...path, status: "active" }),
      "GET /api/paths/p1/progress": () => json({ skills: {} }),
      "GET /api/studies/p1": () => json(current),
      "POST /api/courses/c1/updates/u1/apply": () => {
        current = studies({ status: "built", estimate: null, courses: [course({ built: true, plan })] });
        return json(current.courses[0]);
      },
    });
    renderApp("/paths/p1");
    const user = userEvent.setup();
    await user.click(await screen.findByText("Your material"));
    expect(await screen.findByText("New from Lecture 3")).toBeInTheDocument();
    expect(screen.getByText("Rewrite these lessons with it: Limits")).toBeInTheDocument();
    expect(screen.getByText("Add these skills: Continuity")).toBeInTheDocument();
    expect(screen.getByText("Waiting to be transcribed")).toBeInTheDocument();
    expect(screen.getByText(/0 of 1 recordings transcribed\. Each one adds to the path/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/courses/c1/updates/u1/apply")).toBe(true));
    await waitFor(() => expect(screen.queryByText("New from Lecture 3")).toBeNull());
  });

  it("shows what each file's parts become, and opens the lesson of a taught part", async () => {
    const current = studies({ status: "built", estimate: null, courses: [course({ built: true, plan })] });
    mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json({ ...path, status: "active" }),
      "GET /api/paths/p1/progress": () => json({ skills: {} }),
      "GET /api/studies/p1": () => json(current),
      "GET /api/courses/c1/coverage": () =>
        json({
          course_id: "c1",
          title: "Analysis 1",
          files: [
            {
              material_id: "m1",
              title: "Analisi",
              kind: "pdf",
              role: "textbook",
              ready: true,
              parts: [
                { loc_kind: "page", start: 1, end: 6, where: "pp. 1-6", status: "skipped", skill: null, lesson_id: null, reason: "table of contents" },
                { loc_kind: "page", start: 7, end: 20, where: "pp. 7-20", status: "taught", skill: "Limits", lesson_id: "l1", reason: null },
              ],
            },
          ],
        }),
    });
    renderApp("/paths/p1");
    const user = userEvent.setup();
    await user.click(await screen.findByText("Your material"));
    await user.click(await screen.findByText("What your material covers"));
    expect(await screen.findByText("70% taught")).toBeInTheDocument();
    expect(screen.getByText("Left out: table of contents")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Limits" })).toHaveAttribute("href", "/lessons/l1");
  });

  it("removes a file from a built course after asking", async () => {
    const current = studies({ status: "built", estimate: null, courses: [course({ built: true, plan })] });
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/paths/p1": () => json({ ...path, status: "active" }),
      "GET /api/paths/p1/progress": () => json({ skills: {} }),
      "GET /api/studies/p1": () => json(current),
      "DELETE /api/materials/m1": () => new Response(null, { status: 204 }),
    });
    renderApp("/paths/p1");
    const user = userEvent.setup();
    await user.click(await screen.findByText("Your material"));
    await user.click(await screen.findByRole("button", { name: "Remove" }));
    expect(screen.getByText(/The lessons written from it are written again without it/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove the file" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/api/materials/m1")).toBe(true));
  });
});
