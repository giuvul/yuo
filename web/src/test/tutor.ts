// Test helpers for the tutor: fixtures and a fake EventSource the tests drive by hand.
import { act } from "@testing-library/react";
import type { NudgeOut, TutorContextOut, TutorMessage } from "../api/client";

export const ids = {
  path: "0190f000-0000-7000-8000-0000000000f1",
  lesson: "0190f000-0000-7000-8000-00000000001a",
  conv: "0190f000-0000-7000-8000-0000000000c1",
  conv2: "0190f000-0000-7000-8000-0000000000c2",
};

export function contextOut(over: Partial<TutorContextOut> = {}): TutorContextOut {
  return {
    policy: "lesson",
    mode: "lesson",
    checked: false,
    sealed: false,
    sealed_by_open_test: false,
    scope: "lesson",
    scope_ref: ids.lesson,
    conversation_id: ids.conv,
    chips: [
      { kind: "path", label: "SQL for analysts" },
      { kind: "lesson", label: "What a table is" },
    ],
    refs: {
      path_id: ids.path,
      skill_id: null,
      lesson_id: ids.lesson,
      lesson_version_id: null,
      attempt_id: null,
      assessment_id: null,
      item_version_id: null,
      item_state: "none",
      position: null,
    },
    ...over,
  };
}

let seq = 0;

export function message(over: Partial<TutorMessage> = {}): TutorMessage {
  seq += 1;
  return {
    id: `0190f000-0000-7000-8000-${String(seq).padStart(12, "0")}`,
    conversation_id: ids.conv,
    role: "learner",
    status: "done",
    text: "Hello",
    template: null,
    error: null,
    proposal_id: null,
    memory_ids: [],
    policy: "lesson",
    guard: null,
    chips: [],
    answers: [],
    created_at: `2026-10-28T10:00:${String(seq % 60).padStart(2, "0")}.000Z`,
    completed_at: null,
    duplicate: false,
    path_id: null,
    retried: false,
    ...over,
  };
}

export function nudge(over: Partial<NudgeOut> = {}): NudgeOut {
  return {
    id: "0190f000-0000-7000-8000-0000000000e1",
    trigger: "repeated_error",
    path_id: ids.path,
    params: { objective: "Use LEFT JOIN to keep rows", misses: 2 },
    level: "coach",
    status: "shown",
    ...over,
  };
}

/** Stands in for the browser's EventSource: `emit` delivers one named server event. */
export class FakeEventSource extends EventTarget {
  static instances: FakeEventSource[] = [];
  readonly url: string;
  closed = false;

  constructor(url: string) {
    super();
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  close(): void {
    this.closed = true;
  }

  static latest(): FakeEventSource {
    const open = FakeEventSource.instances.filter((s) => !s.closed);
    const s = open.at(-1);
    if (!s) throw new Error("no open EventSource");
    return s;
  }

  static emit(kind: string, data: unknown): void {
    act(() => {
      FakeEventSource.latest().dispatchEvent(new MessageEvent(kind, { data: JSON.stringify(data) }));
    });
  }
}
