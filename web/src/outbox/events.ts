// Learning event payloads (v1) that the web client sends. The server validates them
// again (yuo/learning/events.py); these types only keep the client honest.

export type EventPayloads = {
  "lesson.started": { lesson_version_id: string; rendition_version_id?: string; seconds: number };
  "lesson.completed": { lesson_version_id: string; rendition_version_id?: string; seconds: number };
  "attempt.started": {
    attempt_id: string;
    assessment_id: string;
    purpose: "practice" | "skill_test" | "placement" | "review";
  };
  "attempt.finished": { attempt_id: string; outcome: "finished" | "abandoned" };
  "assessment.response_given": {
    attempt_id: string;
    item_version_id: string;
    answer: Answer;
    ms_to_answer: number;
    /** review sessions: sent only when the learner marked the answer as a guess */
    confidence?: "sure" | "guessing";
  };
  "item.support_shown": {
    item_version_id: string;
    attempt_id?: string;
    kind: "hint" | "solution" | "explanation";
    level: number;
  };
  /** accept or reject a tutor proposal; the server applies an accepted one */
  "tutor.proposal_decided": { proposal_id: string; decision: "accepted" | "rejected" };
};

export type EventType = keyof EventPayloads;

/** assessment.response_given `answer`, per item type (see src/items/answers.ts). */
export type Answer = string | number | string[] | { left: string; right: string }[];

/** One event as stored in the outbox and sent to POST /api/events. */
export type OutboxEvent<T extends EventType = EventType> = {
  id: string;
  type: T;
  type_version: 1;
  device_at: string;
  tz: string;
  payload: EventPayloads[T];
};

/** UTC `YYYY-MM-DDTHH:MM:SS.sssZ`, the format the server parses. */
export function deviceAt(date: Date = new Date()): string {
  return date.toISOString();
}

export function deviceTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}
