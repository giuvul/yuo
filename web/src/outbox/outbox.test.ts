import "fake-indexeddb/auto";
import { afterEach, describe, expect, it, vi } from "vitest";
import { json, mockApi, type Handler } from "../test/mockApi";
import type { OutboxEvent } from "./events";
import { BATCH_SIZE, Outbox } from "./outbox";
import { UUID7_PATTERN } from "./uuid7";

let n = 0;
const open: Outbox[] = [];

function makeOutbox() {
  const outbox = new Outbox({ dbName: `outbox-test-${++n}` });
  open.push(outbox);
  return outbox;
}

type EventsBody = { device_id: string; events: OutboxEvent[] };

function ingest(fn: (ids: string[]) => object): Handler {
  return (_req, body) => {
    const ids = (body as EventsBody).events.map((e) => e.id);
    return json({ accepted: [], duplicates: [], rejected: {}, graded: {}, outcomes: {}, ...fn(ids) });
  };
}

const device: Handler = () => json({ device_id: "0190f000-0000-7000-8000-000000000001" });

const started = { lesson_version_id: "lv1", seconds: 0 };

afterEach(async () => {
  while (open.length) await open.pop()?.close();
  vi.unstubAllGlobals();
});

describe("outbox", () => {
  it("stores an event with the wire shape before sending", async () => {
    mockApi({ "POST /api/devices": () => "network-error", "POST /api/events": () => "network-error" });
    const outbox = makeOutbox();
    const event = await outbox.enqueue("lesson.started", started);

    expect(event.id).toMatch(UUID7_PATTERN);
    expect(event.type_version).toBe(1);
    expect(event.device_at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
    expect(event.tz).toBeTruthy();
    expect(await outbox.pendingEvents()).toEqual([event]);
  });

  it("removes accepted events after a successful flush and registers the device once", async () => {
    const { calls } = mockApi({
      "POST /api/devices": device,
      "POST /api/events": ingest((ids) => ({ accepted: ids })),
    });
    const outbox = makeOutbox();
    await outbox.enqueue("lesson.started", started);
    await outbox.flush();
    await outbox.enqueue("lesson.completed", { ...started, seconds: 42 });
    const result = await outbox.flush();

    expect(await outbox.pendingEvents()).toEqual([]);
    expect(outbox.getStatus()).toMatchObject({ pending: 0, offline: false });
    expect(result.offline).toBe(false);
    expect(calls.filter((c) => c.path === "/api/devices")).toHaveLength(1);
    const posts = calls.filter((c) => c.path === "/api/events");
    expect(posts.length).toBeGreaterThanOrEqual(2);
    expect((posts[0]!.body as EventsBody).device_id).toBe("0190f000-0000-7000-8000-000000000001");
  });

  it("removes duplicates", async () => {
    mockApi({ "POST /api/devices": device, "POST /api/events": ingest((ids) => ({ duplicates: ids })) });
    const outbox = makeOutbox();
    const e = await outbox.enqueue("lesson.started", started);
    const result = await outbox.flush();

    expect(result.duplicates).toContain(e.id);
    expect(await outbox.pendingEvents()).toEqual([]);
    expect(await outbox.rejectedEvents()).toEqual([]);
  });

  it("moves rejected events aside with the reason and does not resend them", async () => {
    const { calls } = mockApi({
      "POST /api/devices": device,
      "POST /api/events": ingest((ids) => ({ rejected: Object.fromEntries(ids.map((id) => [id, "payload: bad"])) })),
    });
    const outbox = makeOutbox();
    const e = await outbox.enqueue("lesson.started", started);
    await outbox.flush();
    const postsBefore = calls.filter((c) => c.path === "/api/events").length;
    await outbox.flush();

    expect(await outbox.pendingEvents()).toEqual([]);
    const rejected = await outbox.rejectedEvents();
    expect(rejected).toHaveLength(1);
    expect(rejected[0]).toMatchObject({ id: e.id, type: "lesson.started", reason: "payload: bad" });
    expect(outbox.getStatus().rejected).toBe(1);
    expect(calls.filter((c) => c.path === "/api/events")).toHaveLength(postsBefore);
  });

  it("keeps events on a network error and reports offline", async () => {
    mockApi({ "POST /api/devices": device, "POST /api/events": () => "network-error" });
    const outbox = makeOutbox();
    const e = await outbox.enqueue("lesson.started", started);
    const result = await outbox.flush();

    expect(result.offline).toBe(true);
    expect((await outbox.pendingEvents()).map((x) => x.id)).toEqual([e.id]);
    expect(outbox.getStatus()).toMatchObject({ pending: 1, offline: true });
  });

  it("keeps events on a server error", async () => {
    mockApi({ "POST /api/devices": device, "POST /api/events": () => json({ detail: "boom" }, 500) });
    const outbox = makeOutbox();
    await outbox.enqueue("lesson.started", started);
    const result = await outbox.flush();

    expect(result.offline).toBe(true);
    expect(await outbox.pendingEvents()).toHaveLength(1);
  });

  it("sends in batches of at most 100, oldest first", async () => {
    mockApi({ "POST /api/devices": () => "network-error" });
    const outbox = makeOutbox();
    const ids: string[] = [];
    for (let i = 0; i < BATCH_SIZE + 30; i++) ids.push((await outbox.enqueue("lesson.started", started)).id);

    const { calls } = mockApi({
      "POST /api/devices": device,
      "POST /api/events": ingest((batch) => ({ accepted: batch })),
    });
    await outbox.flush();

    const sizes = calls
      .filter((c) => c.path === "/api/events")
      .map((c) => (c.body as EventsBody).events.length);
    expect(Math.max(...sizes)).toBeLessThanOrEqual(BATCH_SIZE);
    const sent = calls
      .filter((c) => c.path === "/api/events")
      .flatMap((c) => (c.body as EventsBody).events.map((e) => e.id));
    expect(sent).toEqual(ids);
    expect(await outbox.pendingEvents()).toEqual([]);
  });

  it("registers again when the server does not know the device", async () => {
    let devices = 0;
    let first = true;
    mockApi({
      "POST /api/devices": () => json({ device_id: `0190f000-0000-7000-8000-00000000000${++devices}` }),
      "POST /api/events": (req, body) => {
        if (first) {
          first = false;
          return json({ detail: "device" }, 404);
        }
        return ingest((ids) => ({ accepted: ids }))(req, body);
      },
    });
    const outbox = makeOutbox();
    await outbox.enqueue("lesson.started", started);
    await outbox.flush();

    expect(devices).toBe(2);
    expect(await outbox.pendingEvents()).toEqual([]);
  });

  it("returns grades for answers and tells listeners", async () => {
    const graded = { score: 1, correct: "b", explanation: "because", solution: "b it is" };
    mockApi({
      "POST /api/devices": device,
      "POST /api/events": ingest((ids) => ({ accepted: ids, graded: { [ids[0]!]: graded } })),
    });
    const outbox = makeOutbox();
    const seen: string[] = [];
    outbox.onGraded((id) => seen.push(id));
    const e = await outbox.enqueue("assessment.response_given", {
      attempt_id: "a1",
      item_version_id: "iv1",
      answer: "b",
      ms_to_answer: 1200,
    });
    const result = await outbox.flush();

    expect(result.graded[e.id]).toEqual(graded);
    expect(seen).toContain(e.id);
  });

  it("returns the existing grade for a duplicate answer (reply lost, then retried)", async () => {
    const graded = { score: 0, correct: "a", explanation: null, solution: "a" };
    let calls = 0;
    mockApi({
      "POST /api/devices": device,
      "POST /api/events": (req, body) => {
        calls += 1;
        // first try: the server stores the event but the reply never arrives
        if (calls === 1) return "network-error";
        return ingest((ids) => ({ duplicates: ids, graded: { [ids[0]!]: graded } }))(req, body);
      },
    });
    const outbox = makeOutbox();
    const seen: Record<string, unknown> = {};
    outbox.onGraded((id, g) => (seen[id] = g));
    const e = await outbox.enqueue("assessment.response_given", {
      attempt_id: "a1",
      item_version_id: "iv1",
      answer: "c",
      ms_to_answer: 900,
    });
    // enqueue's own flush hits the lost reply; this one retries and gets a duplicate
    const result = await outbox.flush();

    expect(calls).toBe(2);
    expect(result.duplicates).toContain(e.id);
    expect(result.graded[e.id]).toEqual(graded);
    expect(seen[e.id]).toEqual(graded);
    expect(await outbox.pendingEvents()).toEqual([]);
  });

  it("re-sends a model-graded answer until its grade is in, then stops", async () => {
    const final = { pending: false, hidden: false, score: 0.5, correct: "x", explanation: null, solution: null, rationale: "Half." };
    let ready = false;
    const stored = new Set<string>();
    mockApi({
      "POST /api/devices": device,
      "POST /api/events": (req, body) => {
        const ids = (body as EventsBody).events.map((e) => e.id);
        const graded = Object.fromEntries(ids.map((id) => [id, ready ? final : { pending: true }]));
        const fresh = ids.filter((id) => !stored.has(id));
        for (const id of ids) stored.add(id);
        return ingest(() => ({ accepted: fresh, duplicates: ids.filter((id) => !fresh.includes(id)), graded }))(req, body);
      },
    });
    const outbox = makeOutbox();
    const seen: string[] = [];
    outbox.onGraded((id) => seen.push(id));
    const e = await outbox.enqueue("assessment.response_given", {
      attempt_id: "a1",
      item_version_id: "sa1",
      answer: "Because.",
      ms_to_answer: 5000,
    });
    const first = await outbox.flush();

    expect(first.graded[e.id]?.pending).toBe(true);
    expect(await outbox.pendingEvents()).toEqual([]); // the event itself is stored on the server
    expect((await outbox.awaitingEvents()).map((w) => w.event.id)).toEqual([e.id]);
    expect(outbox.getStatus().grading).toBe(1);
    expect(seen).toEqual([]); // a pending grade is not a grade

    await outbox.flush(); // re-sent, still pending: keeps waiting
    expect((await outbox.awaitingEvents()).map((w) => w.event.id)).toEqual([e.id]);
    ready = true; // the grading job finished on the server
    const done = await outbox.flush();
    expect(done.graded[e.id]).toEqual(final);
    expect(seen).toEqual([e.id]);
    expect(await outbox.awaitingEvents()).toEqual([]);
    expect(outbox.getStatus().grading).toBe(0);
  });

  it("does not wait for hidden test grades and reports test outcomes", async () => {
    const outcome = { skill_id: "s1", passed: true, score: 1, pass_mark: 0.8 };
    mockApi({
      "POST /api/devices": device,
      "POST /api/events": (req, body) => {
        const events = (body as EventsBody).events;
        const ids = events.map((e) => e.id);
        const graded = Object.fromEntries(
          events.filter((e) => e.type === "assessment.response_given").map((e) => [e.id, { pending: true, hidden: true }]),
        );
        const finished = events.find((e) => e.type === "attempt.finished");
        const outcomes = finished ? { a1: outcome } : {};
        return ingest(() => ({ accepted: ids, graded, outcomes }))(req, body);
      },
    });
    const outbox = makeOutbox();
    const heard: [string, unknown][] = [];
    outbox.onOutcome((id, o) => heard.push([id, o]));
    await outbox.enqueue("assessment.response_given", { attempt_id: "a1", item_version_id: "t1", answer: "a", ms_to_answer: 1 });
    await outbox.enqueue("attempt.finished", { attempt_id: "a1", outcome: "finished" });
    const result = await outbox.flush();

    expect(await outbox.awaitingEvents()).toEqual([]);
    expect(result.outcomes["a1"]).toEqual(outcome);
    expect(heard).toEqual([["a1", outcome]]);
  });

  it("survives a reload: a new instance on the same database still has the events", async () => {
    mockApi({ "POST /api/devices": () => "network-error" });
    const name = `outbox-test-reload-${++n}`;
    const a = new Outbox({ dbName: name });
    const e = await a.enqueue("lesson.started", started);
    await a.close();
    const b = new Outbox({ dbName: name });
    open.push(b);
    expect((await b.pendingEvents()).map((x) => x.id)).toEqual([e.id]);
  });
});

describe("outbox without a session", () => {
  it("keeps events on 401, says signed out, does not retry, and flushes after the sign-in", async () => {
    let signedIn = false;
    const { calls } = mockApi({
      "POST /api/devices": () => (signedIn ? device(new Request("http://x"), undefined) : json({ detail: "sign in first" }, 401)),
      "POST /api/events": (req, body) =>
        signedIn ? ingest((ids) => ({ accepted: ids }))(req, body) : json({ detail: "sign in first" }, 401),
      "GET /api/auth/state": () => json({ signed_in: false }),
    });
    const outbox = makeOutbox();
    await outbox.enqueue("lesson.started", started);
    const first = await outbox.flush();

    expect(first.offline).toBe(true);
    expect(await outbox.pendingEvents()).toHaveLength(1);
    expect(await outbox.rejectedEvents()).toEqual([]);
    expect(outbox.getStatus()).toMatchObject({ pending: 1, signedOut: true, offline: false });
    const before = calls.length;
    await new Promise((r) => setTimeout(r, 1_200)); // past the first backoff: nothing is retried
    expect(calls.length).toBe(before);

    signedIn = true;
    const after = await outbox.resume("0190f000-0000-7000-8000-0000000000d9");
    expect(after.accepted).toHaveLength(1);
    expect(await outbox.pendingEvents()).toEqual([]);
    expect(outbox.getStatus()).toMatchObject({ pending: 0, signedOut: false });
    const post = calls.filter((c) => c.path === "/api/events").at(-1)!;
    expect((post.body as EventsBody).device_id).toBe("0190f000-0000-7000-8000-0000000000d9");
  });

  it("keeps events on 403 and retries them like a server error", async () => {
    mockApi({ "POST /api/devices": device, "POST /api/events": () => json({ detail: "cross-site request refused" }, 403) });
    const outbox = makeOutbox();
    await outbox.enqueue("lesson.started", started);
    const result = await outbox.flush();
    expect(result.offline).toBe(true);
    expect(await outbox.pendingEvents()).toHaveLength(1);
    expect(await outbox.rejectedEvents()).toEqual([]);
    expect(outbox.getStatus()).toMatchObject({ offline: true, signedOut: false });
  });

  it("sends the CSRF header on its requests", async () => {
    const { fetchMock } = mockApi({
      "POST /api/devices": device,
      "POST /api/events": ingest((ids) => ({ accepted: ids })),
    });
    const outbox = makeOutbox();
    await outbox.enqueue("lesson.started", started);
    await outbox.flush();
    const requests = fetchMock.mock.calls.map((c) => c[0] as Request);
    expect(requests.length).toBeGreaterThan(0);
    for (const r of requests) expect(r.headers.get("X-Yuo-Request")).toBe("1");
  });
});
