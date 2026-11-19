import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { MemoryOut, PathOut, ProposalOut, RequestRow, SettingOut, TutorContextIn } from "../api/client";
import { activateLocale } from "../i18n";
import type { OutboxEvent } from "../outbox/events";
import { UUID7_PATTERN } from "../outbox/uuid7";
import { json, mockApi, type Handler } from "../test/mockApi";
import { appRoutes, renderApp } from "../test/renderApp";
import { contextOut, ids, message, nudge } from "../test/tutor";
import { liveReplies } from "./live";

beforeAll(async () => {
  await activateLocale("en");
});
beforeEach(() => {
  liveReplies.clear();
  localStorage.clear();
});
afterEach(() => vi.unstubAllGlobals());

type EventsBody = { device_id: string; events: OutboxEvent[] };

/** Accepts every event; `nudges` are returned in the reply. */
function events(sent: OutboxEvent[], nudges: unknown[] = []): Handler {
  return (_r, body) => {
    const b = body as EventsBody;
    sent.push(...b.events);
    return json({ accepted: b.events.map((e) => e.id), duplicates: [], rejected: {}, graded: {}, outcomes: {}, nudges });
  };
}

const tutorRoutes: Record<string, Handler> = {
  "POST /api/tutor/context": () => json(contextOut()),
  "GET /api/tutor/messages": () => json([]),
  "GET /api/tutor/conversations": () => json([]),
  "GET /api/settings": () => json([]),
};

const dock = () => screen.getByRole("complementary", { name: "Tutor" });

function proposal(over: Partial<ProposalOut> = {}): ProposalOut {
  return {
    id: "0190f000-0000-7000-8000-0000000000b1",
    path_id: ids.path,
    kind: "extra_review",
    rationale: "You missed two questions on joins.",
    change: { skill: "Joins", skill_id: "s1" },
    origin: "tutor",
    status: "pending",
    created_at: "2026-10-28T10:00:00.000Z",
    expires_at: null,
    ...over,
  };
}

const path: PathOut = {
  id: ids.path,
  title: "SQL for analysts",
  subject: "SQL",
  goal: "Reports",
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
      code: "basics",
      title: "Basics",
      skills: [
        {
          id: "s1",
          code: "basics.join",
          title: "Joins",
          summary: "",
          requires: [],
          objectives: [],
          lessons: [{ id: "l1", code: "l1", kind: "core", state: "ready", title: "What a join is", has_draft: false }],
        },
      ],
    },
  ],
};

describe("proposals", () => {
  it("shows a proposal card in the thread; accepting sends the event and offers the skill's review", async () => {
    const sent: OutboxEvent[] = [];
    const p = proposal();
    mockApi({
      ...appRoutes,
      ...tutorRoutes,
      [`GET /api/proposals/${p.id}`]: () => json(p),
      "GET /api/tutor/messages": () =>
        json([message({ role: "tutor", text: "Want an extra review of joins?", proposal_id: p.id, path_id: ids.path })]),
      "POST /api/events": events(sent),
    });
    const user = userEvent.setup();
    renderApp("/");
    await user.click(await screen.findByRole("button", { name: /^Tutor/ }));
    const card = await within(dock()).findByRole("article", { name: "Suggestion: An extra review" });
    expect(within(card).getByText("You missed two questions on joins.")).toBeInTheDocument();
    expect(within(card).getByText("Review the skill: Joins")).toBeInTheDocument();

    await user.click(within(card).getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(sent.some((e) => e.type === "tutor.proposal_decided")).toBe(true));
    const decided = sent.find((e) => e.type === "tutor.proposal_decided")!;
    expect(decided.payload).toEqual({ proposal_id: p.id, decision: "accepted" });
    expect(decided.id).toMatch(UUID7_PATTERN);
    const start = await within(card).findByRole("link", { name: "Start the review of Joins" });
    // an accepted extra review opens the hub's session focused on that skill
    expect(start).toHaveAttribute("href", `/paths/${ids.path}/review/session?size=5&skill=s1`);
  });

  it("lists proposals on the path view; an accepted lesson shows up in the requests", async () => {
    const sent: OutboxEvent[] = [];
    let decided = false;
    const p = proposal({ kind: "add_lesson", change: { prompt: "Self joins with examples" } });
    const request: RequestRow = {
      id: "r1",
      prompt: "Self joins with examples",
      status: "pending",
      error: null,
      lesson_id: null,
      created_at: "2026-10-28T10:00:00.000Z",
    };
    const { calls } = mockApi({
      ...appRoutes,
      [`GET /api/paths/${ids.path}`]: () => json(path),
      [`GET /api/paths/${ids.path}/progress`]: () => json({ detail: "x" }, 404),
      [`GET /api/paths/${ids.path}/requests`]: () => json(decided ? [request] : []),
      [`GET /api/paths/${ids.path}/proposals`]: () => json([decided ? { ...p, status: "accepted" } : p]),
      "POST /api/events": (r, body) => {
        decided = true;
        return events(sent)(r, body);
      },
    });
    const user = userEvent.setup();
    renderApp(`/paths/${ids.path}`);
    const section = await screen.findByRole("region", { name: "Suggestions from the tutor" });
    const card = within(section).getByRole("article", { name: "Suggestion: Add a lesson" });
    expect(within(card).getByText("Lesson about: Self joins with examples")).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(sent.map((e) => e.type)).toContain("tutor.proposal_decided"));
    expect(
      await screen.findByText("The lesson is requested. It appears under “Your requests” on the path."),
    ).toBeInTheDocument();
    const requests = screen.getByRole("region", { name: "Ask for a lesson" });
    expect(await within(requests).findByText("Self joins with examples")).toBeInTheDocument();
    expect(calls.filter((c) => c.path === `/api/paths/${ids.path}/requests`).length).toBeGreaterThan(1);
  });

  it("declines a proposal and shows the server's reason when it was already decided", async () => {
    const p = proposal();
    mockApi({
      ...appRoutes,
      [`GET /api/paths/${ids.path}`]: () => json({ ...path, branches: [] }),
      [`GET /api/paths/${ids.path}/progress`]: () => json({ detail: "x" }, 404),
      [`GET /api/paths/${ids.path}/proposals`]: () => json([p]),
      "POST /api/events": (_r, body) => {
        const b = body as EventsBody;
        const id = b.events[0]!.id;
        return json({ accepted: [], duplicates: [], rejected: { [id]: "the proposal was already decided" }, graded: {}, outcomes: {} });
      },
    });
    const user = userEvent.setup();
    renderApp(`/paths/${ids.path}`);
    const card = await screen.findByRole("article", { name: "Suggestion: An extra review" });
    await user.click(within(card).getByRole("button", { name: "Decline" }));
    expect(
      await within(card).findByText("This decision was not accepted: the proposal was already decided"),
    ).toBeInTheDocument();
  });
});

describe("tutor memory page", () => {
  it("lists entries with their source and evidence, and adds, edits and deletes", async () => {
    const entries: MemoryOut[] = [
      {
        id: "m1",
        kind: "misconception",
        text: "Thinks LEFT JOIN drops rows",
        source: "tutor",
        evidence_ref: { kind: "message", id: "0190f000-0000-7000-8000-0000000000a9" },
        created_at: "2026-10-27T10:00:00.000Z",
        updated_at: "2026-10-27T10:00:00.000Z",
      },
      {
        id: "m2",
        kind: "goal",
        text: "Interview in November",
        source: "learner",
        evidence_ref: null,
        created_at: "2026-10-27T10:00:00.000Z",
        updated_at: "2026-10-27T10:00:00.000Z",
      },
    ];
    const bodies: Record<string, unknown[]> = { add: [], edit: [] };
    const deleted: string[] = [];
    const evidence = message({ id: "0190f000-0000-7000-8000-0000000000a9", role: "tutor", text: "Noted: left joins keep rows." });
    mockApi({
      ...appRoutes,
      ...tutorRoutes,
      "GET /api/tutor/messages": () => json([evidence]),
      "GET /api/tutor/memory": () => json(entries),
      "POST /api/tutor/memory": (_r, body) => {
        bodies["add"]!.push(body);
        const b = body as { kind: MemoryOut["kind"]; text: string };
        entries.push({ ...entries[1]!, id: "m3", kind: b.kind, text: b.text });
        return json({ memory_id: "m3" }, 201);
      },
      "PATCH /api/tutor/memory/m2": (_r, body) => {
        bodies["edit"]!.push(body);
        entries[1] = { ...entries[1]!, text: (body as { text: string }).text, updated_at: "2026-10-28T10:00:00.000Z" };
        return new Response(null, { status: 204 });
      },
      "DELETE /api/tutor/memory/m1": () => {
        deleted.push("m1");
        entries.splice(0, 1);
        return new Response(null, { status: 204 });
      },
    });
    const user = userEvent.setup();
    renderApp("/tutor/memory");

    const list = await screen.findByRole("list", { name: "Remembered entries" });
    expect(within(list).getByText("Thinks LEFT JOIN drops rows")).toBeInTheDocument();
    expect(within(list).getByText(/Noted by the tutor/)).toBeInTheDocument();
    expect(within(list).getByText(/Written by you/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Turn tutor memory on or off in Settings" })).toHaveAttribute(
      "href",
      "/settings#setting-tutor-memory",
    );

    // the evidence: the dock opens on the "All" view at that message
    await user.click(within(list).getByRole("button", { name: "Show where it was noted" }));
    const noted = await within(dock()).findByText("Noted: left joins keep rows.");
    expect(within(dock()).getByRole("tab", { name: "All" })).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(noted.closest("[data-message-id]")).toHaveFocus());
    await user.click(within(dock()).getByRole("button", { name: "Close the tutor" }));

    await user.click(screen.getByRole("radio", { name: "Preference" }));
    await user.type(screen.getByRole("textbox", { name: /What should it remember/ }), "Python examples");
    await user.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(bodies["add"]).toEqual([{ kind: "preference", text: "Python examples" }]));
    expect(await within(list).findByText("Python examples")).toBeInTheDocument();

    await user.click(within(list).getByRole("button", { name: "Edit: Interview in November" }));
    const field = screen.getByRole("textbox", { name: "Change this entry" });
    await user.clear(field);
    await user.type(field, "Interview on 20 November");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(bodies["edit"]).toEqual([{ text: "Interview on 20 November" }]));
    expect(await within(list).findByText("Interview on 20 November")).toBeInTheDocument();

    await user.click(within(list).getByRole("button", { name: "Delete: Thinks LEFT JOIN drops rows" }));
    await user.click(within(list).getByRole("button", { name: "Delete for good" }));
    await waitFor(() => expect(deleted).toEqual(["m1"]));
    await waitFor(() => expect(within(list).queryByText("Thinks LEFT JOIN drops rows")).toBeNull());
  });
});

describe("settings for the tutor", () => {
  const setting = (key: string, value: unknown, over: Partial<SettingOut> = {}): SettingOut => ({
    key,
    cfg: "CFG-34",
    value,
    default: value,
    source: null,
    levels: ["installation", "learner"],
    explanation: `About ${key}`,
    example: "",
    suggestion: "",
    impact: ["learning"],
    weakens_learning: null,
    ...over,
  });

  it("edits muted suggestions, proactivity, the name and the memory switch", async () => {
    const puts: { key: string; body: unknown }[] = [];
    const handler =
      (key: string): Handler =>
      (_r, body) => {
        puts.push({ key, body });
        return new Response(null, { status: 204 });
      };
    mockApi({
      ...appRoutes,
      "GET /api/settings": () =>
        json([
          setting("tutor.proactivity", "coach"),
          setting("tutor.name", "Tutor"),
          setting("tutor.memory", true),
          setting("tutor.muted_triggers", []),
        ]),
      "PUT /api/settings/tutor.muted_triggers": handler("tutor.muted_triggers"),
      "PUT /api/settings/tutor.name": handler("tutor.name"),
    });
    const user = userEvent.setup();
    renderApp("/settings");

    const muted = (await screen.findByRole("heading", { name: "Suggestions you turned off" })).closest("li")!;
    expect(within(muted as HTMLElement).getByText(/Now: None/)).toBeInTheDocument();
    await user.click(within(muted as HTMLElement).getByRole("checkbox", { name: "Answering very fast" }));
    await user.click(within(muted as HTMLElement).getByRole("button", { name: "Save Suggestions you turned off" }));
    await waitFor(() =>
      expect(puts).toContainEqual({ key: "tutor.muted_triggers", body: { value: ["fast_guessing"], level: "learner" } }),
    );

    const proactivity = screen.getByRole("heading", { name: "Tutor suggestions" }).closest("li") as HTMLElement;
    expect(within(proactivity).getByText(/Now: Coach \(a short offer now and then\)/)).toBeInTheDocument();

    const name = screen.getByRole("heading", { name: "Tutor's name" }).closest("li") as HTMLElement;
    const input = within(name).getByRole("textbox", { name: "Tutor's name" });
    expect(input.tagName).toBe("INPUT"); // one line, not a text area
    await user.clear(input);
    await user.type(input, "Ada");
    await user.click(within(name).getByRole("button", { name: "Save Tutor's name" }));
    await waitFor(() => expect(puts).toContainEqual({ key: "tutor.name", body: { value: "Ada", level: "learner" } }));

    const memory = document.getElementById("setting-tutor-memory")!;
    expect(within(memory).getByRole("switch", { name: "Tutor memory" })).toBeChecked();
    expect(within(memory).getByRole("link", { name: "See and edit what the tutor remembers" })).toHaveAttribute(
      "href",
      "/tutor/memory",
    );
  });
});

describe("screens publish their context", () => {
  it("the reader offers to ask about a selection and sends it with its block id", async () => {
    const bodies: TutorContextIn[] = [];
    mockApi({
      ...appRoutes,
      ...tutorRoutes,
      "POST /api/tutor/context": (_r, body) => {
        bodies.push(body as TutorContextIn);
        return json(contextOut({ chips: [{ kind: "selection", label: "A join combines rows." }] }));
      },
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
          sources: [],
        }),
      "GET /api/lessons/L1/notes": () => json([]),
      "POST /api/events": events([]),
    });
    const user = userEvent.setup();
    renderApp("/lessons/L1");
    const para = await screen.findByText("A join combines rows.");
    act(() => {
      const range = document.createRange();
      range.selectNodeContents(para);
      const sel = window.getSelection()!;
      sel.removeAllRanges();
      sel.addRange(range);
      document.dispatchEvent(new Event("selectionchange"));
    });
    await user.click(await screen.findByRole("button", { name: "Ask the tutor about this" }));
    await waitFor(() =>
      expect(bodies.at(-1)).toMatchObject({
        screen: "reading",
        lesson_id: "L1",
        selection: { text: "A join combines rows.", bid: "b2" },
      }),
    );
    expect(await within(dock()).findByText("Selected: “A join combines rows.”")).toBeInTheDocument();
    await user.click(within(dock()).getByRole("button", { name: "Remove from the context: Selected text" }));
    await waitFor(() => expect(bodies.at(-1)?.selection).toBeUndefined());
  });

  it("practice sends the attempt and the question on screen", async () => {
    const bodies: TutorContextIn[] = [];
    mockApi({
      ...appRoutes,
      ...tutorRoutes,
      "POST /api/tutor/context": (_r, body) => {
        bodies.push(body as TutorContextIn);
        return json(contextOut({ policy: "practice.before_attempt", mode: "practice", checked: true }));
      },
      "POST /api/lessons/L1/practice": () =>
        json({
          assessment_id: "0190f000-0000-7000-8000-0000000000a1",
          purpose: "practice",
          items: [
            {
              item_version_id: "iv1",
              type: "mcq",
              view: { prompt: "Which join keeps left rows?", options: [{ id: "a", text: "LEFT" }, { id: "b", text: "INNER" }] },
            },
          ],
        }),
      "POST /api/events": events([]),
    });
    const user = userEvent.setup();
    renderApp("/lessons/L1/practice");
    await screen.findByRole("heading", { name: "Which join keeps left rows?" });
    await user.click(screen.getByRole("button", { name: /^Tutor/ }));
    expect(
      await within(dock()).findByText(/You have not answered this question yet, so the tutor gives guiding questions/),
    ).toBeInTheDocument();
    const last = bodies.at(-1)!;
    expect(last).toMatchObject({ screen: "practice", lesson_id: "L1", item_version_id: "iv1" });
    expect(last.attempt_id).toMatch(UUID7_PATTERN);
  });

  it("accepting an unsent-notes suggestion attaches only the notes not asked about yet", async () => {
    const bodies: TutorContextIn[] = [];
    const note = (id: string, sent: string | null) => ({
      id,
      text: `note ${id}`,
      bid: null,
      lesson_version_id: "lv1",
      sent_message_id: sent,
      created_at: "x",
      updated_at: "x",
    });
    mockApi({
      ...appRoutes,
      ...tutorRoutes,
      "GET /api/paths": () => json([]),
      "GET /api/nudges": () => json([nudge({ trigger: "unsent_notes", params: { notes: 1, lesson_id: "L1" } })]),
      "GET /api/lessons/L1/notes": () => json([note("n1", null), note("n2", "0190f000-0000-7000-8000-0000000000aa")]),
      "POST /api/tutor/context": (_r, body) => {
        bodies.push(body as TutorContextIn);
        return json(contextOut({ chips: [{ kind: "notes", label: "1", n: 1 }] }));
      },
    });
    const { fetchMock } = { fetchMock: vi.mocked(globalThis.fetch) };
    const base = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      if (/^\/api\/nudges\/[^/]+\/accept$/.test(new URL(request.url).pathname)) return new Response(null, { status: 204 });
      return base(input, init);
    });
    const user = userEvent.setup();
    renderApp("/");
    const peek = await screen.findByRole("region", { name: "Suggestion from the tutor" });
    await user.click(within(peek).getByRole("button", { name: "Ask the tutor" }));
    await waitFor(() => expect(bodies.at(-1)).toMatchObject({ lesson_id: "L1", note_ids: ["n1"] }));
    expect(await within(dock()).findByText("1 note")).toBeInTheDocument();
  });

  it("shows a nudge that came back in the events reply", async () => {
    const { outbox } = (() => {
      mockApi({
        ...appRoutes,
        ...tutorRoutes,
        "GET /api/paths": () => json([]),
        "POST /api/events": events([], [nudge({ trigger: "failed_test", params: { skill: "Joins", skill_id: "s1" } })]),
      });
      return renderApp("/");
    })();
    await screen.findByRole("button", { name: /^Tutor/ });
    await act(async () => {
      await outbox.enqueue("lesson.completed", { lesson_version_id: "lv1", seconds: 30 });
      await outbox.flush();
    });
    const peek = await screen.findByRole("region", { name: "Suggestion from the tutor" });
    expect(within(peek).getByText("The test on Joins did not pass yet. Plan what to study before the retake?")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(within(peek).getByRole("button", { name: "Not now" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Suggestion from the tutor" })).toBeNull());
  });
});
