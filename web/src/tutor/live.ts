// What the event stream says about replies still being written: the stage (`tutor.progress`) and
// the text streamed so far (`tutor.delta`, unchecked modes only). Kept outside the query cache:
// it changes per token and is dropped once the final message arrives.
import { useSyncExternalStore } from "react";

export type Stage = "thinking" | "writing" | "checking";

type LiveReply = {
  stage: Stage | null;
  text: string;
  /** when this tab first heard of the reply (ms), for the elapsed time */
  since: number;
};

export class LiveReplies {
  private readonly replies = new Map<string, LiveReply>();
  private readonly listeners = new Set<() => void>();
  private readonly now: () => number;

  constructor(now: () => number = Date.now) {
    this.now = now;
  }

  private entry(id: string): LiveReply {
    return this.replies.get(id) ?? { stage: null, text: "", since: this.now() };
  }

  /** Remember when a pending reply was first seen, so the elapsed time survives re-renders. */
  seen(id: string): LiveReply {
    const known = this.replies.get(id);
    if (known) return known;
    const e = this.entry(id);
    this.replies.set(id, e);
    return e;
  }

  progress(id: string, stage: Stage): void {
    this.replies.set(id, { ...this.entry(id), stage });
    this.emit();
  }

  delta(id: string, text: string): void {
    const e = this.entry(id);
    this.replies.set(id, { ...e, stage: e.stage ?? "writing", text: e.text + text });
    this.emit();
  }

  done(id: string): void {
    if (this.replies.delete(id)) this.emit();
  }

  clear(): void {
    this.replies.clear();
    this.emit();
  }

  get(id: string): LiveReply | undefined {
    return this.replies.get(id);
  }

  subscribe = (l: () => void): (() => void) => {
    this.listeners.add(l);
    return () => this.listeners.delete(l);
  };

  private version = 0;
  getVersion = (): number => this.version;

  private emit(): void {
    this.version++;
    for (const l of this.listeners) l();
  }
}

export const liveReplies = new LiveReplies();

/** The live state of one reply; re-renders on every change to any reply (they are few). */
export function useLiveReply(id: string, store: LiveReplies = liveReplies): LiveReply | undefined {
  useSyncExternalStore(store.subscribe, store.getVersion, store.getVersion);
  return store.get(id);
}
