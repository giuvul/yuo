import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { TutorContextIn, TutorMessage } from "../api/client";
import { activateLocale } from "../i18n";
import { UUID7_PATTERN } from "../outbox/uuid7";
import { json, mockApi, type Handler } from "../test/mockApi";
import { appRoutes, renderApp } from "../test/renderApp";
import { contextOut, FakeEventSource, ids, message, nudge } from "../test/tutor";
import { mergeMessage } from "./api";
import { liveReplies } from "./live";

beforeAll(async () => {
  await activateLocale("en");
});
beforeEach(() => {
  FakeEventSource.instances = [];
  liveReplies.clear();
  localStorage.clear();
});
afterEach(() => vi.unstubAllGlobals());

type Thread = { messages: TutorMessage[] };

/** A home screen with the tutor routes: one thread (`ids.conv`) kept in `thread.messages`. */
function tutorServer(thread: Thread, extra: Record<string, Handler> = {}) {
  return mockApi({
    ...appRoutes,
    "GET /api/paths": () => json([]),
    "POST /api/tutor/context": () => json(contextOut()),
    "GET /api/tutor/messages": (req) => {
      const cid = new URL(req.url).searchParams.get("conversation_id");
      return json(cid === null || cid === ids.conv ? thread.messages : []);
    },
    "GET /api/tutor/conversations": () => json([]),
    "GET /api/settings": () => json([]),
    ...extra,
  });
}

const dock = () => screen.getByRole("complementary", { name: "Tutor" });
const composer = () => within(dock()).getByRole("textbox", { name: "Message to Tutor" });

async function openDock(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: /^Tutor/ }));
  await waitFor(() => expect(composer()).toHaveFocus());
}

describe("tutor dock", () => {
  it("opens from the button and the shortcut, focuses the composer, Esc closes and returns focus", async () => {
    tutorServer({ messages: [] });
    const user = userEvent.setup();
    renderApp("/");

    const button = await screen.findByRole("button", { name: /^Tutor/ });
    expect(button).toHaveAttribute("aria-keyshortcuts", "Control+J Meta+J");
    await openDock(user);
    expect(await within(dock()).findByText("Ask about this lesson: explanations, examples, questions.")).toBeInTheDocument();
    expect(within(dock()).getByText("Path: SQL for analysts")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("complementary", { name: "Tutor" })).toBeNull();
    expect(screen.getByRole("button", { name: /^Tutor/ })).toHaveFocus();

    await user.keyboard("{Control>}j{/Control}");
    await waitFor(() => expect(composer()).toHaveFocus());
    await user.keyboard("{Control>}j{/Control}");
    expect(screen.queryByRole("complementary", { name: "Tutor" })).toBeNull();
  });

  it("sends the screen's references and leaves out a removed chip; the item chip cannot be removed", async () => {
    const bodies: TutorContextIn[] = [];
    tutorServer(
      { messages: [] },
      {
        "POST /api/tutor/context": (_r, body) => {
          const b = body as TutorContextIn;
          bodies.push(b);
          const chips = contextOut().chips.filter((c) => !b.excluded?.includes(c.kind as "lesson"));
          return json(contextOut({ chips: [...chips, { kind: "item", label: "question 2 of 4", n: 2, of: 4 }] }));
        },
      },
    );
    const user = userEvent.setup();
    renderApp("/");
    await openDock(user);
    expect(bodies[0]).toMatchObject({ screen: "home", locale: "en" });

    // closed by default, with the count on its line
    const summary = await within(dock()).findByText(/^What the tutor sees with your next message \(\d+\)$/);
    expect(summary.closest("details")).not.toHaveAttribute("open");
    await user.click(summary);
    expect(summary.closest("details")).toHaveAttribute("open");
    expect(await within(dock()).findByText("Question 2 of 4")).toBeInTheDocument();
    expect(within(dock()).queryByRole("button", { name: "Remove from the context: Question" })).toBeNull();
    await user.click(within(dock()).getByRole("button", { name: "Remove from the context: Lesson" }));
    await waitFor(() => expect(bodies.at(-1)?.excluded).toEqual(["lesson"]));
    await waitFor(() => expect(within(dock()).queryByText("Lesson: What a table is")).toBeNull());
    await user.click(within(dock()).getByRole("button", { name: "Add back: Lesson" }));
    await waitFor(() => expect(bodies.at(-1)?.excluded).toBeUndefined());
  });

  it("says when a test is open and the test rules apply", async () => {
    tutorServer(
      { messages: [] },
      {
        "POST /api/tutor/context": () =>
          json(
            contextOut({
              policy: "test.locked",
              mode: "test_locked",
              checked: true,
              sealed: true,
              sealed_by_open_test: true,
              scope: "attempt",
              chips: [{ kind: "skill", label: "Joins" }],
            }),
          ),
      },
    );
    const user = userEvent.setup();
    renderApp("/");
    await openDock(user);
    expect(await within(dock()).findByText(/^A test is open, so the test rules apply on every screen/)).toBeInTheDocument();
    expect(within(dock()).getByText(/^Locked during the test/)).toBeInTheDocument();
    expect(within(dock()).getByText(/Replies are checked before you see them/)).toBeInTheDocument();
    expect(within(dock()).getByRole("tab", { name: "This thread (Test)" })).toBeInTheDocument();
  });

  it("shows the first-use memory notice once", async () => {
    tutorServer(
      { messages: [] },
      {
        "POST /api/tutor/context": () =>
          json(contextOut({ chips: [{ kind: "memory", label: "on" }] })),
      },
    );
    const user = userEvent.setup();
    renderApp("/");
    await openDock(user);
    expect(await within(dock()).findByText(/The tutor remembers lasting things about you/)).toBeInTheDocument();
    expect(within(dock()).getByRole("link", { name: "Turn memory off" })).toHaveAttribute(
      "href",
      "/settings#setting-tutor-memory",
    );
    await user.click(within(dock()).getByRole("button", { name: "Got it" }));
    expect(within(dock()).queryByText(/The tutor remembers lasting things about you/)).toBeNull();
    expect(localStorage.getItem("yuo.tutor.memory-notice-seen")).toBe("1");
  });
});

describe("sending, the queue and the stream", () => {
  it("sends with a uuid7, shows it queued, keeps the composer enabled, and streams the reply", async () => {
    const thread: Thread = { messages: [] };
    const posted: { id: string; text: string; context: TutorContextIn }[] = [];
    vi.stubGlobal("EventSource", FakeEventSource);
    tutorServer(thread, {
      "POST /api/tutor/messages": (_r, body) => {
        const b = body as (typeof posted)[number];
        posted.push(b);
        const m = message({ id: b.id, text: b.text, status: "queued" });
        thread.messages.push(m);
        return json(m, 202);
      },
    });
    const user = userEvent.setup();
    renderApp("/");
    await openDock(user);
    expect(FakeEventSource.latest().url).toBe("/api/stream");

    await user.type(composer(), "What is a join?{Enter}");
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]!.id).toMatch(UUID7_PATTERN);
    expect(posted[0]!.text).toBe("What is a join?");
    expect(posted[0]!.context).toMatchObject({ screen: "home" });
    const mine = await within(dock()).findByText("What is a join?");
    const bubble = mine.closest("[data-message-id]") as HTMLElement;
    expect(within(bubble).getByText("Queued")).toBeInTheDocument();
    expect(composer()).toBeEnabled();
    expect(composer()).toHaveValue("");

    // the tutor starts the turn: thinking, then writing with streamed text
    const reply = message({ role: "tutor", status: "streaming", text: "", answers: [posted[0]!.id] });
    FakeEventSource.emit("tutor.message", reply);
    expect(await within(dock()).findByText("Thinking…")).toBeInTheDocument();
    expect(within(bubble).queryByText("Queued")).toBeNull(); // the reply settles the question
    expect(await screen.findByText("The tutor is answering.")).toBeInTheDocument();
    FakeEventSource.emit("tutor.progress", { message_id: reply.id, stage: "writing" });
    FakeEventSource.emit("tutor.delta", { message_id: reply.id, text: "A join " });
    FakeEventSource.emit("tutor.delta", { message_id: reply.id, text: "combines rows" });
    expect(within(dock()).getByText("Writing…")).toBeInTheDocument();
    expect(within(dock()).getByText("A join combines rows")).toBeInTheDocument();
    expect(within(dock()).getByText(/^\d+ s$/)).toBeInTheDocument();

    FakeEventSource.emit("tutor.message", { ...reply, status: "done", text: "A join combines rows of two tables." });
    expect(await within(dock()).findByText("A join combines rows of two tables.")).toBeInTheDocument();
    expect(within(dock()).queryByText("Writing…")).toBeNull();
    // one polite announcement for the finished reply, not per token
    expect(screen.getByText("Answer ready: A join combines rows of two tables.")).toBeInTheDocument();
  });

  it("shows the checking stage of a checked reply without streamed text", async () => {
    const reply = message({ role: "tutor", status: "streaming", text: "" });
    vi.stubGlobal("EventSource", FakeEventSource);
    tutorServer({ messages: [reply] });
    const user = userEvent.setup();
    renderApp("/");
    await openDock(user);
    expect(await within(dock()).findByText("Thinking…")).toBeInTheDocument();
    FakeEventSource.emit("tutor.progress", { message_id: reply.id, stage: "checking" });
    expect(within(dock()).getByText("Checking the reply before showing it…")).toBeInTheDocument();
  });

  it("edits and takes back a queued message", async () => {
    const queued = message({ text: "Typo questoin", status: "queued" });
    const thread: Thread = { messages: [queued] };
    const calls = tutorServer(thread);
    const base = calls.fetchMock.getMockImplementation()!;
    const patched: unknown[] = [];
    const deleted: string[] = [];
    calls.fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      if (new URL(request.url).pathname === `/api/tutor/messages/${queued.id}`) {
        if (request.method === "PATCH") {
          const body = (await request.json()) as { text: string };
          patched.push(body);
          return json({ ...queued, text: body.text });
        }
        deleted.push(queued.id);
        thread.messages = [];
        return json({ ...queued, status: "withdrawn" });
      }
      return base(input, init);
    });
    const user = userEvent.setup();
    renderApp("/");
    await openDock(user);

    await user.click(await within(dock()).findByRole("button", { name: "Edit" }));
    const field = within(dock()).getByRole("textbox", { name: "Edit your message" });
    await user.clear(field);
    await user.type(field, "Typo question");
    await user.click(within(dock()).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patched).toEqual([{ text: "Typo question" }]));
    expect(await within(dock()).findByText("Typo question")).toBeInTheDocument();

    await user.click(within(dock()).getByRole("button", { name: "Take back this message" }));
    await waitFor(() => expect(deleted).toEqual([queued.id]));
    await waitFor(() => expect(within(dock()).queryByText("Typo question")).toBeNull());
  });

  it("keeps an unsent message and sends it again with the same id", async () => {
    const thread: Thread = { messages: [] };
    const tries: string[] = [];
    let online = false;
    tutorServer(thread, {
      "POST /api/tutor/messages": (_r, body) => {
        const b = body as { id: string; text: string };
        tries.push(b.id);
        if (!online) return "network-error";
        const m = message({ id: b.id, text: b.text, status: "queued" });
        thread.messages.push(m);
        return json(m, 202);
      },
    });
    const user = userEvent.setup();
    renderApp("/");
    await openDock(user);
    await user.type(composer(), "Hello there{Enter}");
    expect(await within(dock()).findByText(/^Not sent: the server cannot be reached/)).toBeInTheDocument();

    online = true;
    await user.click(within(dock()).getByRole("button", { name: "Send again" }));
    await waitFor(() => expect(tries).toHaveLength(2));
    expect(tries[1]).toBe(tries[0]);
    expect(await within(dock()).findByText("Queued")).toBeInTheDocument();
    expect(within(dock()).queryByText(/^Not sent/)).toBeNull();
  });

  it("renders template replies from the catalog, not from their text", async () => {
    tutorServer({
      messages: [
        message({ text: "Is it b?" }),
        message({ role: "tutor", template: "tutor.guess", text: "server text", guard: "template" }),
        message({ role: "tutor", template: "tutor.blocked", text: "server text 2", guard: "blocked" }),
      ],
    });
    const user = userEvent.setup();
    renderApp("/");
    await openDock(user);
    expect(
      await within(dock()).findByText(
        "I can't say whether that's right until you submit your answer. Want a hint instead, or should I rephrase the question?",
      ),
    ).toBeInTheDocument();
    expect(
      within(dock()).getByText("Let's look at the wording of the question together instead. Which part is unclear?"),
    ).toBeInTheDocument();
    expect(within(dock()).queryByText(/server text/)).toBeNull();
  });

  it("shows why a reply failed and retries it", async () => {
    const question = message({ text: "Explain joins", status: "done" });
    const failed = message({ role: "tutor", status: "failed", error: "budget", answers: [question.id] });
    const thread: Thread = { messages: [question, failed] };
    const calls = tutorServer(thread);
    const retried: string[] = [];
    const base = calls.fetchMock.getMockImplementation()!;
    calls.fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      if (new URL(request.url).pathname === `/api/tutor/messages/${failed.id}/retry`) {
        retried.push(failed.id);
        thread.messages = [{ ...question, status: "queued" }];
        return json({
          requeued: [{ ...question, status: "queued" }],
          retried: { ...failed, status: "withdrawn", retried: true },
        });
      }
      return base(input, init);
    });
    const user = userEvent.setup();
    renderApp("/");
    await openDock(user);
    expect(
      await within(dock()).findByText("The monthly budget cap is reached. Raise it in Settings or wait for next month."),
    ).toBeInTheDocument();
    await user.click(within(dock()).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(retried).toEqual([failed.id]));
    expect(await within(dock()).findByText("Queued")).toBeInTheDocument();
    expect(within(dock()).queryByText(/monthly budget cap/)).toBeNull();
  });

  it("cancels a reply that is being written, shows it as stopped and offers to ask again", async () => {
    const question = message({ text: "Why do joins duplicate rows?" });
    const reply = message({ role: "tutor", status: "streaming", text: "", answers: [question.id] });
    const thread: Thread = { messages: [question, reply] };
    const calls = tutorServer(thread);
    const base = calls.fetchMock.getMockImplementation()!;
    const cancelled: string[] = [];
    calls.fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      if (request.method === "DELETE" && new URL(request.url).pathname === `/api/tutor/messages/${reply.id}`) {
        cancelled.push(reply.id);
        thread.messages = [question, { ...reply, status: "withdrawn" }];
        return json({ ...reply, status: "withdrawn" });
      }
      return base(input, init);
    });
    const user = userEvent.setup();
    renderApp("/");
    await openDock(user);
    await user.click(await within(dock()).findByRole("button", { name: "Stop Tutor's reply" }));
    await waitFor(() => expect(cancelled).toEqual([reply.id]));
    await waitFor(() => expect(within(dock()).queryByText("Thinking…")).toBeNull());
    expect(within(dock()).getByText("You stopped this reply.")).toBeInTheDocument();
    await user.click(within(dock()).getByRole("button", { name: "Ask again" }));
    await waitFor(() => expect(composer()).toHaveValue("Why do joins duplicate rows?"));
  });

  it("shows the All view with a context line per thread", async () => {
    tutorServer(
      {
        messages: [
          message({ text: "About tables", conversation_id: ids.conv }),
          message({ text: "About the path", conversation_id: ids.conv2 }),
        ],
      },
      {
        "GET /api/tutor/conversations": () =>
          json([
            { id: ids.conv, scope: "lesson", scope_ref: ids.lesson, title: "What a table is", created_at: "", last_at: null, messages: 1 },
            { id: ids.conv2, scope: "path", scope_ref: ids.path, title: "SQL for analysts", created_at: "", last_at: null, messages: 1 },
          ]),
      },
    );
    const user = userEvent.setup();
    renderApp("/");
    await openDock(user);
    await user.click(within(dock()).getByRole("tab", { name: "All" }));
    const all = await within(dock()).findByRole("list", { name: "All conversations" });
    expect(await within(all).findByText("Lesson: What a table is")).toBeInTheDocument();
    expect(within(all).getByText("Path: SQL for analysts")).toBeInTheDocument();
    expect(within(all).getByText("About the path")).toBeInTheDocument();
  });

  it("refetches tutor state on reset and job lists on job events", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const thread: Thread = { messages: [] };
    const { calls } = tutorServer(thread);
    const user = userEvent.setup();
    renderApp("/");
    await openDock(user);
    await within(dock()).findByText(/No messages here yet/);

    thread.messages = [message({ text: "Sent from another tab" })];
    FakeEventSource.emit("reset", {});
    expect(await within(dock()).findByText("Sent from another tab")).toBeInTheDocument();

    const jobsBefore = calls.filter((c) => c.path === "/api/jobs").length;
    FakeEventSource.emit("job", { id: "j1", status: "done" });
    await waitFor(() => expect(calls.filter((c) => c.path === "/api/jobs").length).toBeGreaterThan(jobsBefore));
  });

  it("announces a reply that lands while the dock is closed and badges the button", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const reply = message({ role: "tutor", status: "streaming", text: "" });
    tutorServer({ messages: [reply] });
    const user = userEvent.setup();
    renderApp("/");
    await openDock(user);
    await within(dock()).findByText("Thinking…");
    await user.keyboard("{Escape}");
    FakeEventSource.emit("tutor.message", { ...reply, status: "done", text: "Here you go." });
    expect(await screen.findByText("Answer ready: Here you go.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Tutor.*1 new reply$/ })).toBeInTheDocument();
  });
});

describe("nudges", () => {
  it("shows a coach nudge as a peek that says why, and opens the tutor with a question on accept", async () => {
    const n = nudge();
    const decided: string[] = [];
    const { fetchMock } = tutorServer({ messages: [] }, { "GET /api/nudges": () => json([n]) });
    const base = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      const m = /^\/api\/nudges\/([^/]+)\/(\w+)$/.exec(new URL(request.url).pathname);
      if (m) {
        decided.push(`${m[1]}:${m[2]}`);
        return new Response(null, { status: 204 });
      }
      return base(input, init);
    });
    const user = userEvent.setup();
    renderApp("/");
    const peek = await screen.findByRole("region", { name: "Suggestion from the tutor" });
    expect(
      within(peek).getByText("You missed “Use LEFT JOIN to keep rows” 2 times in this session. Look at it together?"),
    ).toBeInTheDocument();
    await user.click(within(peek).getByRole("button", { name: "Ask the tutor" }));
    await waitFor(() => expect(decided).toEqual([`${n.id}:accept`]));
    await waitFor(() =>
      expect(composer()).toHaveValue("I keep getting “Use LEFT JOIN to keep rows” wrong. Can you explain it another way?"),
    );
    expect(screen.queryByRole("region", { name: "Suggestion from the tutor" })).toBeNull();
  });

  it("mutes a trigger with Don't suggest this", async () => {
    const decided: string[] = [];
    const { fetchMock } = tutorServer(
      { messages: [] },
      { "GET /api/nudges": () => json([nudge({ trigger: "fast_guessing", params: { answers: 3 } })]) },
    );
    const base = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      const m = /^\/api\/nudges\/[^/]+\/(\w+)$/.exec(new URL(request.url).pathname);
      if (m) {
        decided.push(m[1]!);
        return new Response(null, { status: 204 });
      }
      return base(input, init);
    });
    const user = userEvent.setup();
    renderApp("/");
    const peek = await screen.findByRole("region", { name: "Suggestion from the tutor" });
    expect(within(peek).getByText(/Your last answers came very fast/)).toBeInTheDocument();
    await user.click(within(peek).getByRole("button", { name: "Don't suggest this" }));
    await waitFor(() => expect(decided).toEqual(["mute"]));
    expect(screen.queryByRole("region", { name: "Suggestion from the tutor" })).toBeNull();
  });

  it("shows a quiet nudge as a dot only, and lists it in the dock", async () => {
    tutorServer(
      { messages: [] },
      { "GET /api/nudges": () => json([nudge({ level: "quiet", trigger: "failed_test", params: { skill: "Joins" } })]) },
    );
    const user = userEvent.setup();
    renderApp("/");
    expect(await screen.findByRole("button", { name: /^Tutor.*a suggestion is waiting$/ })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Suggestion from the tutor" })).toBeNull();
    await user.click(screen.getByRole("button", { name: /^Tutor/ }));
    const list = await within(dock()).findByRole("region", { name: "Suggestions" });
    expect(within(list).getByText("The test on Joins did not pass yet. Plan what to study before the retake?")).toBeInTheDocument();
  });

  it("picks up nudges from the stream and from the events reply", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    tutorServer({ messages: [] });
    renderApp("/");
    await screen.findByRole("button", { name: /^Tutor/ });
    FakeEventSource.emit("nudge", nudge({ trigger: "unsent_notes", params: { notes: 3, lesson_id: ids.lesson } }));
    expect(
      await screen.findByText("You left 3 notes on this lesson that you have not asked about. Ask the tutor now?"),
    ).toBeInTheDocument();
  });
});

describe("mergeMessage", () => {
  it("replaces by id, drops withdrawn messages, keeps order, and settles answered questions", () => {
    const a = message({ status: "queued", created_at: "2026-10-28T10:00:01.000Z" });
    const b = message({ status: "queued", created_at: "2026-10-28T10:00:02.000Z" });
    const r = message({ role: "tutor", status: "streaming", answers: [a.id], created_at: "2026-10-28T10:00:03.000Z" });
    let list = mergeMessage(mergeMessage([], b), a);
    expect(list.map((m) => m.id)).toEqual([a.id, b.id]);
    list = mergeMessage(list, r);
    expect(list.map((m) => m.status)).toEqual(["done", "queued", "streaming"]);
    list = mergeMessage(list, { ...b, status: "withdrawn" });
    expect(list.map((m) => m.id)).toEqual([a.id, r.id]);
    // a cancelled reply stays (shown as stopped); a retried failed reply leaves
    list = mergeMessage(list, { ...r, status: "withdrawn" });
    expect(list.map((m) => m.status)).toEqual(["done", "withdrawn"]);
    list = mergeMessage(list, { ...r, status: "withdrawn", retried: true });
    expect(list.map((m) => m.id)).toEqual([a.id]);
  });
});

describe("erasing a conversation", () => {
  it("is offered under a thread with messages, asks once, and empties the thread", async () => {
    const thread: Thread = { messages: [message({ text: "What is a join?" }), message({ role: "tutor", text: "A join pairs rows." })] };
    const api = tutorServer(thread, {
      [`DELETE /api/tutor/conversations/${ids.conv}`]: () => {
        thread.messages = [];
        return json({ counts: { conversation: 1, message: 2 } });
      },
    });
    const user = userEvent.setup();
    renderApp("/");
    await openDock(user);
    expect(await within(dock()).findByText("A join pairs rows.")).toBeInTheDocument();
    await user.click(within(dock()).getByRole("button", { name: "Delete this conversation" }));
    await user.click(within(dock()).getByRole("button", { name: "Delete the conversation" }));
    await waitFor(() => expect(within(dock()).queryByText("A join pairs rows.")).toBeNull());
    expect(api.calls.filter((c) => c.method === "DELETE").map((c) => c.path)).toEqual([`/api/tutor/conversations/${ids.conv}`]);
    expect(within(dock()).queryByRole("button", { name: "Delete this conversation" })).toBeNull();
  });
});
