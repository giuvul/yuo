// The event outbox: every learning event is written to IndexedDB first, then
// sent to POST /api/events in batches. An event leaves the outbox only once the server has
// persisted it (accepted) or already had it (duplicate). Events the server rejects are moved to a
// separate store with the reason and are not retried. Network and server errors keep the events
// and retry with backoff.
//
// Without a session (401: signed out, device revoked) nothing is dropped: the outbox stops trying,
// reports `signedOut`, and flushes again once the app has signed in (resume). A 403 (refused request)
// keeps the events too and is retried like a server error.
//
// Answers graded later by a server job (short answers) come back `pending`. They are kept in an
// `awaiting` store and sent again every few seconds: the server answers a repeated event as a
// duplicate together with its grade once there is one (no second grade is written).
import { openDB, type DBSchema, type IDBPDatabase } from "idb";
import { deviceLabel } from "../auth/deviceLabel";
import { api, type Graded, type IngestOut, type NudgeOut } from "../api/client";
import { deviceAt, deviceTimeZone, type EventPayloads, type EventType, type OutboxEvent } from "./events";
import { uuid7 } from "./uuid7";

export const BATCH_SIZE = 100;
const FLUSH_INTERVAL_MS = 30_000;
const BACKOFF_BASE_MS = 1_000;
const BACKOFF_MAX_MS = 60_000;
const AWAIT_POLL_MS = 5_000;
/** Stop asking for a pending grade after this long; the server still grades it. */
const AWAIT_MAX_MS = 15 * 60_000;

type RejectedEvent = OutboxEvent & { reason: string; rejected_at: string };
type AwaitingEvent = { event: OutboxEvent; since: number };
export type Outcome = Record<string, unknown>;

interface OutboxSchema extends DBSchema {
  events: { key: string; value: OutboxEvent };
  rejected: { key: string; value: RejectedEvent };
  meta: { key: string; value: string };
  awaiting: { key: string; value: AwaitingEvent };
}

export type FlushResult = {
  accepted: string[];
  duplicates: string[];
  rejected: Record<string, string>;
  graded: Record<string, Graded>;
  /** results of finished skill tests and placements, by attempt id */
  outcomes: Record<string, Outcome>;
  /** tutor suggestions the server made for what this flush showed */
  nudges: NudgeOut[];
  /** the server could not be reached (or failed); the events stay queued */
  offline: boolean;
};

export type OutboxStatus = {
  pending: number;
  rejected: number;
  /** answers waiting for a grade from the server */
  grading: number;
  syncing: boolean;
  /** last flush failed to reach the server */
  offline: boolean;
  /** the server wants a sign-in first (401); events wait for it */
  signedOut: boolean;
};

/** What the server said about one batch. */
type PostOutcome =
  | { kind: "ok"; result: IngestOut }
  | { kind: "unknown_device" }
  /** the whole request failed validation; per-event messages when they can be located */
  | { kind: "invalid"; byIndex: Record<number, string> };

type Transport = {
  registerDevice(): Promise<string>;
  /** Throws on network errors and on responses worth retrying (5xx, unexpected codes). */
  postEvents(deviceId: string, events: OutboxEvent[]): Promise<PostOutcome>;
};

class RetryableError extends Error {
  override name = "RetryableError";
}

/** No session (401): keep everything and wait for a sign-in. */
class SignedOutError extends Error {
  override name = "SignedOutError";
}

function refused(status: number, what: string): never {
  if (status === 401) throw new SignedOutError(`${what}: signed out`);
  throw new RetryableError(`${what}: HTTP ${status}`);
}

const httpTransport: Transport = {
  async registerDevice() {
    const { data, response } = await api.POST("/api/devices", { body: { label: deviceLabel() } });
    const id = data?.device_id;
    if (!response.ok || !id) refused(response.status, "device registration failed");
    return id;
  },
  async postEvents(deviceId, events) {
    const { data, error, response } = await api.POST("/api/events", { body: { device_id: deviceId, events } });
    if (response.ok && data) return { kind: "ok", result: data };
    if (response.status === 404) return { kind: "unknown_device" };
    if (response.status === 422) {
      const byIndex: Record<number, string> = {};
      const detail = (error as { detail?: unknown } | undefined)?.detail;
      if (Array.isArray(detail)) {
        for (const d of detail as { loc?: unknown[]; msg?: string }[]) {
          const loc = d.loc ?? [];
          // FastAPI: ["body", "events", <index>, ...field path]
          if (loc[0] === "body" && loc[1] === "events" && typeof loc[2] === "number") {
            const where = loc.slice(3).join(".");
            byIndex[loc[2]] = `${where ? `${where}: ` : ""}${d.msg ?? "invalid"}`;
          }
        }
      }
      if (Object.keys(byIndex).length) return { kind: "invalid", byIndex };
    }
    refused(response.status, "events upload failed");
  },
};

type GradedListener = (responseEventId: string, graded: Graded) => void;
type FlushListener = (result: FlushResult) => void;
type OutcomeListener = (attemptId: string, outcome: Outcome) => void;

type OutboxOptions = {
  dbName?: string;
  transport?: Transport;
  now?: () => Date;
};

function emptyResult(): FlushResult {
  return { accepted: [], duplicates: [], rejected: {}, graded: {}, outcomes: {}, nudges: [], offline: false };
}

function merge(a: FlushResult, b: FlushResult): FlushResult {
  return {
    accepted: [...a.accepted, ...b.accepted],
    duplicates: [...a.duplicates, ...b.duplicates],
    rejected: { ...a.rejected, ...b.rejected },
    graded: { ...a.graded, ...b.graded },
    outcomes: { ...a.outcomes, ...b.outcomes },
    nudges: [...a.nudges, ...b.nudges],
    offline: b.offline,
  };
}

export class Outbox {
  private readonly dbPromise: Promise<IDBPDatabase<OutboxSchema>>;
  private readonly transport: Transport;
  private readonly now: () => Date;
  private status: OutboxStatus = {
    pending: 0,
    rejected: 0,
    grading: 0,
    syncing: false,
    offline: false,
    signedOut: false,
  };
  private readonly statusListeners = new Set<() => void>();
  private readonly gradedListeners = new Set<GradedListener>();
  private readonly flushListeners = new Set<FlushListener>();
  private readonly outcomeListeners = new Set<OutcomeListener>();
  private awaitTimer: ReturnType<typeof setTimeout> | null = null;
  private closed = false;
  private readonly inflight = new Set<Promise<unknown>>();

  /** Keeps track of IndexedDB work so close() can wait for it. */
  private track<T>(p: Promise<T>): Promise<T> {
    this.inflight.add(p);
    void p.finally(() => this.inflight.delete(p)).catch(() => {});
    return p;
  }
  private running: Promise<FlushResult> | null = null;
  private queued: Promise<FlushResult> | null = null;
  private failures = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(options: OutboxOptions = {}) {
    this.transport = options.transport ?? httpTransport;
    this.now = options.now ?? (() => new Date());
    this.dbPromise = openDB<OutboxSchema>(options.dbName ?? "yuo-outbox", 2, {
      upgrade(db, oldVersion) {
        if (oldVersion < 1) {
          db.createObjectStore("events", { keyPath: "id" });
          db.createObjectStore("rejected", { keyPath: "id" });
          db.createObjectStore("meta");
        }
        if (oldVersion < 2) db.createObjectStore("awaiting");
      },
    });
    void this.track(this.refreshCounts());
  }

  // --- queue ---------------------------------------------------------------------------------

  /** Stores the event, then starts a flush in the background. Resolves once the event is stored. */
  enqueue<T extends EventType>(type: T, payload: EventPayloads[T]): Promise<OutboxEvent<T>> {
    if (this.closed) return Promise.reject(new Error("outbox closed"));
    return this.track(this.store(type, payload));
  }

  private async store<T extends EventType>(type: T, payload: EventPayloads[T]): Promise<OutboxEvent<T>> {
    const event: OutboxEvent<T> = {
      id: uuid7(this.now().getTime()),
      type,
      type_version: 1,
      device_at: deviceAt(this.now()),
      tz: deviceTimeZone(),
      payload,
    };
    const db = await this.dbPromise;
    await db.put("events", event as OutboxEvent);
    await this.refreshCounts();
    void this.flush();
    return event;
  }

  async pendingEvents(): Promise<OutboxEvent[]> {
    return (await this.dbPromise).getAll("events");
  }

  async rejectedEvents(): Promise<RejectedEvent[]> {
    return (await this.dbPromise).getAll("rejected");
  }

  async awaitingEvents(): Promise<AwaitingEvent[]> {
    return (await this.dbPromise).getAll("awaiting");
  }

  async isPending(id: string): Promise<boolean> {
    return (await (await this.dbPromise).getKey("events", id)) !== undefined;
  }

  // --- device --------------------------------------------------------------------------------

  async deviceId(): Promise<string> {
    const db = await this.dbPromise;
    const known = await db.get("meta", "device_id");
    if (known) return known;
    const id = await this.transport.registerDevice();
    await db.put("meta", id, "device_id");
    return id;
  }

  private async forgetDevice(): Promise<void> {
    await (await this.dbPromise).delete("meta", "device_id");
  }

  // --- flush ---------------------------------------------------------------------------------

  /**
   * Sends everything queued. One flush runs at a time; a call made while one runs waits for it
   * and then runs once more, so events stored before the call are always covered. The result
   * merges both runs.
   */
  flush(): Promise<FlushResult> {
    if (this.closed) return Promise.resolve(emptyResult());
    if (this.running) {
      this.queued ??= this.running.then(async (first) => {
        this.queued = null;
        return merge(first, await this.flush());
      });
      return this.queued;
    }
    this.running = this.track(this.run()).finally(() => {
      this.running = null;
    });
    return this.running;
  }

  private async run(): Promise<FlushResult> {
    const total = emptyResult();
    const db = await this.dbPromise;
    this.setStatus({ syncing: true });
    try {
      for (;;) {
        const batch = await db.getAll("events", undefined, BATCH_SIZE); // key order = uuid7 = time order
        if (!batch.length) break;
        const outcome = await this.post(batch);
        const removed = await this.apply(batch, outcome, total);
        if (removed === 0) break; // the server did not account for any event: try again later
      }
      await this.recheckAwaiting(total);
      this.failures = 0;
      this.clearRetry();
      this.setStatus({ offline: false, signedOut: false });
    } catch (err) {
      total.offline = true;
      if (err instanceof SignedOutError) {
        // nothing to retry until there is a session again: resume() flushes after the sign-in
        this.clearRetry();
        this.setStatus({ signedOut: true, offline: false });
      } else {
        this.setStatus({ offline: true });
        this.scheduleRetry();
      }
      if (!(err instanceof RetryableError) && !(err instanceof TypeError) && !(err instanceof SignedOutError)) {
        console.warn("outbox flush failed", err);
      }
    } finally {
      await this.refreshCounts();
      this.setStatus({ syncing: false });
    }
    for (const [id, g] of Object.entries(total.graded)) {
      if (g.pending) continue; // listeners only hear about real grades
      for (const l of this.gradedListeners) l(id, g);
    }
    for (const [id, o] of Object.entries(total.outcomes)) for (const l of this.outcomeListeners) l(id, o);
    this.scheduleAwaitCheck();
    for (const l of this.flushListeners) l(total);
    return total;
  }

  /** Sends answers still waiting for a model grade again; the reply carries the grade once it exists. */
  private async recheckAwaiting(total: FlushResult): Promise<void> {
    const db = await this.dbPromise;
    const now = this.now().getTime();
    const waiting = await db.getAll("awaiting", undefined, BATCH_SIZE);
    const fresh: AwaitingEvent[] = [];
    for (const w of waiting) {
      if (now - w.since > AWAIT_MAX_MS) await db.delete("awaiting", w.event.id);
      else if (!(w.event.id in total.graded)) fresh.push(w); // not just answered in this run
    }
    if (!fresh.length) return;
    const outcome = await this.post(fresh.map((w) => w.event));
    if (outcome.kind !== "ok") return;
    const r = outcome.result;
    for (const w of fresh) {
      const g = r.graded[w.event.id];
      if (r.rejected[w.event.id] !== undefined) await db.delete("awaiting", w.event.id);
      else if (g && !g.pending) {
        await db.delete("awaiting", w.event.id);
        total.graded[w.event.id] = g;
      }
    }
  }

  private scheduleAwaitCheck(): void {
    if (this.awaitTimer !== null || this.status.grading === 0 || this.status.signedOut) return;
    this.awaitTimer = setTimeout(() => {
      this.awaitTimer = null;
      void this.flush();
    }, AWAIT_POLL_MS);
  }

  private async post(batch: OutboxEvent[]): Promise<PostOutcome> {
    const outcome = await this.transport.postEvents(await this.deviceId(), batch);
    if (outcome.kind !== "unknown_device") return outcome;
    // the server lost or revoked this device (e.g. a fresh database): register again, once
    await this.forgetDevice();
    const retry = await this.transport.postEvents(await this.deviceId(), batch);
    if (retry.kind === "unknown_device") throw new RetryableError("device not recognised by the server");
    return retry;
  }

  /** Applies a batch outcome to the stores; returns how many events left the queue. */
  private async apply(batch: OutboxEvent[], outcome: PostOutcome, total: FlushResult): Promise<number> {
    const db = await this.dbPromise;
    const at = deviceAt(this.now());
    const tx = db.transaction(["events", "rejected", "awaiting"], "readwrite");
    const events = tx.objectStore("events");
    const rejectedStore = tx.objectStore("rejected");
    let removed = 0;

    if (outcome.kind === "invalid") {
      for (const [index, reason] of Object.entries(outcome.byIndex)) {
        const event = batch[Number(index)];
        if (!event) continue;
        await rejectedStore.put({ ...event, reason, rejected_at: at });
        await events.delete(event.id);
        total.rejected[event.id] = reason;
        removed++;
      }
    } else if (outcome.kind === "ok") {
      const r = outcome.result;
      const inBatch = new Map(batch.map((e) => [e.id, e]));
      for (const id of [...r.accepted, ...r.duplicates]) {
        if (!inBatch.has(id)) continue;
        await events.delete(id);
        removed++;
      }
      for (const [id, reason] of Object.entries(r.rejected)) {
        const event = inBatch.get(id);
        if (!event) continue;
        await rejectedStore.put({ ...event, reason, rejected_at: at });
        await events.delete(id);
        removed++;
      }
      const awaiting = tx.objectStore("awaiting");
      for (const [id, g] of Object.entries(r.graded)) {
        const event = inBatch.get(id);
        // hidden grades (tests) are never shown per item, so there is nothing to wait for
        if (event && g.pending && !g.hidden) await awaiting.put({ event, since: this.now().getTime() }, id);
      }
      total.accepted.push(...r.accepted);
      total.duplicates.push(...r.duplicates);
      Object.assign(total.rejected, r.rejected);
      Object.assign(total.graded, r.graded);
      Object.assign(total.outcomes, r.outcomes ?? {});
      total.nudges.push(...(r.nudges ?? []));
    }
    await tx.done;
    return removed;
  }

  private scheduleRetry(): void {
    this.failures += 1;
    const ceiling = Math.min(BACKOFF_MAX_MS, BACKOFF_BASE_MS * 2 ** (this.failures - 1));
    const delay = ceiling / 2 + Math.random() * (ceiling / 2);
    this.clearRetry();
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      void this.flush();
    }, delay);
  }

  private clearRetry(): void {
    if (this.retryTimer !== null) clearTimeout(this.retryTimer);
    this.retryTimer = null;
  }

  /** Flush on `online`, every 30 s, and once now. Returns a stop function. */
  start(): () => void {
    const onOnline = () => {
      this.failures = 0;
      void this.flush();
    };
    window.addEventListener("online", onOnline);
    const timer = setInterval(() => {
      if (this.status.pending > 0 && !this.retryTimer && !this.status.signedOut) void this.flush();
    }, FLUSH_INTERVAL_MS);
    void this.flush();
    return () => {
      window.removeEventListener("online", onOnline);
      clearInterval(timer);
      this.clearRetry();
    };
  }

  /**
   * Signed in (again): the session's device is the one events count for. Clears `signedOut` and sends
   * whatever waited.
   */
  async resume(deviceId?: string | null): Promise<FlushResult> {
    if (this.closed) return emptyResult();
    if (deviceId) await this.track((async () => (await this.dbPromise).put("meta", deviceId, "device_id"))());
    this.failures = 0;
    this.setStatus({ signedOut: false });
    return this.flush();
  }

  // --- status and listeners --------------------------------------------------------------------

  getStatus = (): OutboxStatus => this.status;

  subscribe = (listener: () => void): (() => void) => {
    this.statusListeners.add(listener);
    return () => this.statusListeners.delete(listener);
  };

  onGraded(listener: GradedListener): () => void {
    this.gradedListeners.add(listener);
    return () => this.gradedListeners.delete(listener);
  }

  /** Results of finished skill tests and placements, as the server sends them. */
  onOutcome(listener: OutcomeListener): () => void {
    this.outcomeListeners.add(listener);
    return () => this.outcomeListeners.delete(listener);
  }

  onFlush(listener: FlushListener): () => void {
    this.flushListeners.add(listener);
    return () => this.flushListeners.delete(listener);
  }

  private async refreshCounts(): Promise<void> {
    const db = await this.dbPromise;
    const [pending, rejected, grading] = await Promise.all([
      db.count("events"),
      db.count("rejected"),
      db.count("awaiting"),
    ]);
    this.setStatus({ pending, rejected, grading });
  }

  private setStatus(patch: Partial<OutboxStatus>): void {
    const next = { ...this.status, ...patch };
    if (
      next.pending === this.status.pending &&
      next.rejected === this.status.rejected &&
      next.grading === this.status.grading &&
      next.syncing === this.status.syncing &&
      next.offline === this.status.offline &&
      next.signedOut === this.status.signedOut
    ) {
      return;
    }
    this.status = next;
    for (const l of this.statusListeners) l();
  }

  async close(): Promise<void> {
    this.closed = true;
    this.clearRetry();
    if (this.awaitTimer !== null) clearTimeout(this.awaitTimer);
    this.awaitTimer = null;
    while (this.inflight.size) await Promise.allSettled([...this.inflight]);
    (await this.dbPromise).close();
  }
}
