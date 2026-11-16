// Translated labels for API enum values. The API types these as plain strings, so unknown values
// fall back to the raw value instead of failing.
import { msg } from "@lingui/core/macro";
import type { MessageDescriptor } from "@lingui/core";
import { useLingui } from "@lingui/react";
import type { Difficulty, GoalType } from "../api/client";

const DIFFICULTY: Record<Difficulty, MessageDescriptor> = {
  introductory: msg({ id: "difficulty.introductory", message: "Introductory" }),
  foundational: msg({ id: "difficulty.foundational", message: "Foundational" }),
  intermediate: msg({ id: "difficulty.intermediate", message: "Intermediate" }),
  advanced: msg({ id: "difficulty.advanced", message: "Advanced" }),
  expert: msg({ id: "difficulty.expert", message: "Expert" }),
};

export const GOAL_TYPE: Record<GoalType, MessageDescriptor> = {
  exam: msg({ id: "goal-type.exam", message: "Pass an exam" }),
  practical: msg({ id: "goal-type.practical", message: "Use it in practice" }),
  understanding: msg({ id: "goal-type.understanding", message: "Understand it well" }),
  curiosity: msg({ id: "goal-type.curiosity", message: "Out of curiosity" }),
};

const PATH_STATUS: Record<string, MessageDescriptor> = {
  draft: msg({ id: "path.status.draft", message: "Being planned" }),
  active: msg({ id: "path.status.active", message: "Active" }),
  paused: msg({ id: "path.status.paused", message: "Paused" }),
  completed: msg({ id: "path.status.completed", message: "Completed" }),
  archived: msg({ id: "path.status.archived", message: "Archived" }),
};

const LESSON_STATE: Record<string, MessageDescriptor> = {
  planned: msg({ id: "lesson.state.planned", message: "Planned" }),
  queued: msg({ id: "lesson.state.queued", message: "Queued" }),
  generating: msg({ id: "lesson.state.generating", message: "Being written" }),
  in_review: msg({ id: "lesson.state.in-review", message: "In review" }),
  ready: msg({ id: "lesson.state.ready", message: "Ready" }),
  failed: msg({ id: "lesson.state.failed", message: "Failed" }),
};

const JOB_KIND: Record<string, MessageDescriptor> = {
  tree: msg({ id: "job.kind.tree", message: "Planning the path" }),
  lesson: msg({ id: "job.kind.lesson", message: "Writing a lesson" }),
  grade: msg({ id: "job.kind.grade", message: "Grading an answer" }),
  test_bank: msg({ id: "job.kind.test-bank", message: "Preparing a skill test" }),
  placement: msg({ id: "job.kind.placement", message: "Preparing a placement test" }),
  request: msg({ id: "job.kind.request", message: "Planning a requested lesson" }),
  items: msg({ id: "job.kind.items", message: "Writing review questions" }),
  rendition: msg({ id: "job.kind.rendition", message: "Making a video lesson" }),
};

const TARGET_KIND: Record<string, MessageDescriptor> = {
  path: msg({ id: "job.target.path", message: "path" }),
  lesson: msg({ id: "job.target.lesson", message: "lesson" }),
  skill: msg({ id: "job.target.skill", message: "skill" }),
  response: msg({ id: "job.target.response", message: "answer" }),
  lesson_request: msg({ id: "job.target.request", message: "lesson request" }),
  rendition: msg({ id: "job.target.rendition", message: "video" }),
};

const LESSON_KIND: Record<string, MessageDescriptor> = {
  core: msg({ id: "lesson.kind.core", message: "Lesson" }),
  remedial: msg({ id: "lesson.kind.remedial", message: "Extra lesson" }),
  requested: msg({ id: "lesson.kind.requested", message: "Requested" }),
};

export const SKILL_STATE: Record<string, MessageDescriptor> = {
  locked: msg({ id: "skill.state.locked", message: "Locked" }),
  available: msg({ id: "skill.state.available", message: "Available" }),
  in_progress: msg({ id: "skill.state.in-progress", message: "In progress" }),
  mastered: msg({ id: "skill.state.mastered", message: "Mastered" }),
  needs_review: msg({ id: "skill.state.needs-review", message: "Needs review" }),
};

const REQUEST_STATUS: Record<string, MessageDescriptor> = {
  pending: msg({ id: "request.status.pending", message: "Waiting" }),
  running: msg({ id: "request.status.running", message: "Being planned" }),
  done: msg({ id: "request.status.done", message: "Added to the path" }),
  failed: msg({ id: "request.status.failed", message: "Failed" }),
  cancelled: msg({ id: "request.status.cancelled", message: "Cancelled" }),
};

const JOB_STATUS: Record<string, MessageDescriptor> = {
  queued: msg({ id: "job.status.queued", message: "waiting to start" }),
  running: msg({ id: "job.status.running", message: "in progress" }),
  waiting_resource: msg({ id: "job.status.waiting-resource", message: "paused until the budget allows" }),
  succeeded: msg({ id: "job.status.succeeded", message: "done" }),
  failed: msg({ id: "job.status.failed", message: "failed" }),
  cancelled: msg({ id: "job.status.cancelled", message: "cancelled" }),
};

function useLabel(table: Record<string, MessageDescriptor>, value: string): string {
  const { i18n } = useLingui();
  const d = table[value];
  return d ? i18n._(d) : value;
}

export function DifficultyLabel({ value }: { value: string }) {
  return <>{useLabel(DIFFICULTY, value)}</>;
}

export function PathStatusLabel({ value }: { value: string }) {
  return <>{useLabel(PATH_STATUS, value)}</>;
}

export function LessonStateLabel({ value }: { value: string }) {
  return <>{useLabel(LESSON_STATE, value)}</>;
}

export function JobKindLabel({ value }: { value: string }) {
  return <>{useLabel(JOB_KIND, value)}</>;
}

export function JobStatusLabel({ value }: { value: string }) {
  return <>{useLabel(JOB_STATUS, value)}</>;
}

export function JobTargetLabel({ value }: { value: string }) {
  return <>{useLabel(TARGET_KIND, value)}</>;
}

export function LessonKindLabel({ value }: { value: string }) {
  return <>{useLabel(LESSON_KIND, value)}</>;
}

export function SkillStateLabel({ value }: { value: string }) {
  return <>{useLabel(SKILL_STATE, value)}</>;
}

export function RequestStatusLabel({ value }: { value: string }) {
  return <>{useLabel(REQUEST_STATUS, value)}</>;
}
