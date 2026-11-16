import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { activateLocale } from "../i18n";
import type { OutboxEvent } from "../outbox/events";
import { UUID7_PATTERN } from "../outbox/uuid7";
import { json, mockApi, type Handler } from "../test/mockApi";
import { appRoutes, renderApp } from "../test/renderApp";

const KEY: Record<string, string> = { iv1: "b", iv2: "a" };

const practice = {
  assessment_id: "0190f000-0000-7000-8000-0000000000a1",
  purpose: "practice",
  items: [
    {
      item_version_id: "iv1",
      type: "mcq",
      view: {
      prompt: "Which join keeps unmatched rows from the left table?",
      options: [
        { id: "a", text: "INNER JOIN" },
        { id: "b", text: "LEFT JOIN" },
        { id: "c", text: "CROSS JOIN" },
        { id: "d", text: "SELF JOIN" },
      ],
      },
    },
    {
      item_version_id: "iv2",
      type: "mcq",
      view: {
      prompt: "What does COUNT(*) count?",
      options: [
        { id: "a", text: "All rows" },
        { id: "b", text: "Non-null values" },
        { id: "c", text: "Distinct values" },
        { id: "d", text: "Columns" },
      ],
      },
    },
  ],
};

type EventsBody = { device_id: string; events: OutboxEvent[] };

/** A server that accepts everything and grades answers like yuo/app/service.py does. */
function server(sent: OutboxEvent[]): Handler {
  return (_req, body) => {
    const { events } = body as EventsBody;
    sent.push(...events);
    const graded: Record<string, object> = {};
    for (const e of events) {
      if (e.type !== "assessment.response_given") continue;
      const p = e.payload as { item_version_id: string; answer: string };
      const correct = KEY[p.item_version_id]!;
      graded[e.id] = {
        score: p.answer === correct ? 1 : 0,
        correct,
        explanation: p.answer === correct ? "It keeps every left row." : "That one drops rows.",
        solution: `The answer is ${correct}.`,
        pending: false,
      };
    }
    return json({ accepted: events.map((e) => e.id), duplicates: [], rejected: {}, graded, outcomes: {} });
  };
}

function baseRoutes(events: Handler): Record<string, Handler> {
  return {
    ...appRoutes,
    "POST /api/lessons/L1/practice": () => json(practice),
    "GET /api/items/iv1/hints/1": () => json({ level: 1, text: "Think about which side is kept.", last: false }),
    "GET /api/items/iv1/hints/2": () => json({ level: 2, text: "LEFT keeps the left side.", last: true }),
    "POST /api/events": events,
  };
}

describe("practice", () => {
  beforeAll(async () => {
    await activateLocale("en");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("runs an attempt: hints, answers graded from the flush, results", async () => {
    const sent: OutboxEvent[] = [];
    const { calls } = mockApi(baseRoutes(server(sent)));
    const user = userEvent.setup();
    const { outbox } = renderApp("/lessons/L1/practice");

    expect(await screen.findByText(practice.items[0]!.view.prompt)).toBeInTheDocument();
    expect(screen.getByText("Question 1 of 2")).toBeInTheDocument();

    // hint ladder
    await user.click(screen.getByRole("button", { name: "Show a hint" }));
    expect(await screen.findByText("Think about which side is kept.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Another hint" }));
    expect(await screen.findByText("LEFT keeps the left side.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "No more hints" })).toBeDisabled();

    // right answer
    await user.click(screen.getByRole("radio", { name: "b. LEFT JOIN" }));
    await user.click(screen.getByRole("button", { name: "Check answer" }));
    expect(await screen.findByText("Correct.")).toBeInTheDocument();
    expect(screen.getByText("It keeps every left row.")).toBeInTheDocument();
    expect(screen.getByText("The answer is b.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next question" }));

    // wrong answer
    expect(await screen.findByText("Question 2 of 2")).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "b. Non-null values" }));
    await user.click(screen.getByRole("button", { name: "Check answer" }));
    expect(await screen.findByText("Not quite.")).toBeInTheDocument();
    expect(screen.getByText("Not quite.").closest("[role=status]")).toHaveTextContent("The right answera. All rows");
    await user.click(screen.getByRole("button", { name: "See results" }));

    expect(await screen.findByText("You got 1 of 2 right.")).toBeInTheDocument();
    await act(() => outbox.flush());

    // the API never saw an answer key request, and the events have the catalog shape
    expect(calls.filter((c) => c.path === "/api/lessons/L1/practice")).toHaveLength(1);
    const byType = (t: string) => sent.filter((e) => e.type === t);
    const started = byType("attempt.started");
    expect(started).toHaveLength(1);
    const attemptId = (started[0]!.payload as { attempt_id: string }).attempt_id;
    expect(attemptId).toMatch(UUID7_PATTERN);
    expect(started[0]!.payload).toEqual({
      attempt_id: attemptId,
      assessment_id: practice.assessment_id,
      purpose: "practice",
    });
    expect(byType("item.support_shown").map((e) => e.payload)).toEqual([
      { item_version_id: "iv1", attempt_id: attemptId, kind: "hint", level: 1 },
      { item_version_id: "iv1", attempt_id: attemptId, kind: "hint", level: 2 },
    ]);
    const responses = byType("assessment.response_given").map((e) => e.payload as Record<string, unknown>);
    expect(responses.map((r) => [r["item_version_id"], r["answer"], r["attempt_id"]])).toEqual([
      ["iv1", "b", attemptId],
      ["iv2", "b", attemptId],
    ]);
    for (const r of responses) expect(typeof r["ms_to_answer"]).toBe("number");
    expect(byType("attempt.finished").map((e) => e.payload)).toEqual([
      { attempt_id: attemptId, outcome: "finished" },
    ]);
    for (const e of sent) {
      expect(e.id).toMatch(UUID7_PATTERN);
      expect(e.type_version).toBe(1);
      expect(e.device_at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
    }
    expect(await outbox.pendingEvents()).toEqual([]);
  });

  it("saves the answer while offline and shows the grade once it syncs", async () => {
    let online = false;
    const sent: OutboxEvent[] = [];
    const accept = server(sent);
    mockApi(baseRoutes((req, body) => (online ? accept(req, body) : "network-error")));
    const user = userEvent.setup();
    const { outbox } = renderApp("/lessons/L1/practice");

    await screen.findByText(practice.items[0]!.view.prompt);
    await user.click(screen.getByRole("radio", { name: "b. LEFT JOIN" }));
    await user.click(screen.getByRole("button", { name: "Check answer" }));

    expect(await screen.findByText(/Your answer is saved and will be graded when you are back online/)).toBeInTheDocument();
    expect(await screen.findByText("2 pending")).toBeInTheDocument(); // attempt.started + the answer

    online = true;
    await act(() => outbox.flush());

    await waitFor(() => expect(screen.getByText("Correct.")).toBeInTheDocument());
    expect(await screen.findByText("Synced")).toBeInTheDocument();
  });

  it("shows the grade when the reply was lost and the retry comes back as a duplicate", async () => {
    const sent: OutboxEvent[] = [];
    const grade = server(sent);
    const stored = new Set<string>();
    let dropReply = true;
    mockApi(
      baseRoutes(async (req, body) => {
        const { events } = body as EventsBody;
        const res = (await grade(req, body)) as Response;
        const out = (await res.json()) as { accepted: string[]; graded: Record<string, object> };
        const hasAnswer = events.some((e) => e.type === "assessment.response_given");
        if (hasAnswer && dropReply) {
          for (const e of events) stored.add(e.id);
          dropReply = false;
          return "network-error"; // stored on the server, reply lost
        }
        const duplicates = out.accepted.filter((id) => stored.has(id));
        return json({
          accepted: out.accepted.filter((id) => !stored.has(id)),
          duplicates,
          rejected: {},
          graded: out.graded, // the backend returns the existing grade for duplicates too
        });
      }),
    );
    const user = userEvent.setup();
    const { outbox } = renderApp("/lessons/L1/practice");

    await screen.findByText(practice.items[0]!.view.prompt);
    await user.click(screen.getByRole("radio", { name: "a. INNER JOIN" }));
    await user.click(screen.getByRole("button", { name: "Check answer" }));
    // the first upload of the answer fails after the server stored it; the retry is a duplicate
    expect(await screen.findByText("Not quite.")).toBeInTheDocument();
    expect(dropReply).toBe(false);
    expect(screen.getByText("Not quite.").closest("[role=status]")).toHaveTextContent("The right answerb. LEFT JOIN");
    expect(await outbox.pendingEvents()).toEqual([]);
  });

  it("shows a short answer as being graded, then the model's grade from a re-send", async () => {
    let graded = false;
    const seen = new Set<string>();
    mockApi({
      ...baseRoutes((_req, body) => {
        const { events } = body as EventsBody;
        const g: Record<string, object> = {};
        for (const e of events) {
          if (e.type !== "assessment.response_given") continue;
          g[e.id] = graded
            ? { pending: false, score: 0.5, correct: "Indexes avoid full scans.", explanation: null, solution: null, rationale: "You named speed but not scans." }
            : { pending: true };
        }
        const fresh = events.filter((e) => !seen.has(e.id)).map((e) => e.id);
        for (const e of events) seen.add(e.id);
        return json({
          accepted: fresh,
          duplicates: events.map((e) => e.id).filter((id) => !fresh.includes(id)),
          rejected: {},
          graded: g,
          outcomes: {},
        });
      }),
      "POST /api/lessons/L1/practice": () =>
        json({
          assessment_id: "as-sa",
          purpose: "practice",
          items: [{ item_version_id: "sa1", type: "short_answer", view: { prompt: "Why index a table?" } }],
        }),
    });
    const user = userEvent.setup();
    const { outbox } = renderApp("/lessons/L1/practice");

    await user.type(await screen.findByRole("textbox", { name: /Your answer/ }), "It is faster.");
    await user.click(screen.getByRole("button", { name: "Check answer" }));
    expect(await screen.findByText(/Your answer is being graded/)).toBeInTheDocument();

    graded = true; // the grading job finished on the server
    await act(() => outbox.flush());
    expect(await screen.findByText("Partly right (50%).")).toBeInTheDocument();
    expect(screen.getByText("You named speed but not scans.")).toBeInTheDocument();
    expect(screen.getByText("Indexes avoid full scans.")).toBeInTheDocument();
  });

  it("explains when practice cannot start", async () => {
    mockApi({
      ...baseRoutes(() => json({ accepted: [], duplicates: [], rejected: {}, graded: {}, outcomes: {} })),
      "POST /api/lessons/L1/practice": () => "network-error",
    });
    renderApp("/lessons/L1/practice");
    expect(await screen.findByText(/cannot be reached/)).toBeInTheDocument();
  });
});
