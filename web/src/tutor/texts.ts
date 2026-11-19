// Every fixed text of the tutor UI that depends on a server value (policy, template, error, chip,
// nudge trigger, proposal kind, memory kind). Template replies are rendered from here by their id,
// never from the message text, so they follow the learner's language.
import { msg } from "@lingui/core/macro";
import type { MessageDescriptor } from "@lingui/core";
import type {
  ChipKind,
  ConversationOut,
  MemoryKind,
  MemoryOut,
  ProposalOut,
  TutorPolicyId,
  TutorTemplate,
} from "../api/client";
import type { Stage } from "./live";

export const TEMPLATES: Record<TutorTemplate, MessageDescriptor> = {
  "tutor.guess": msg({
    id: "tutor.guess",
    message:
      "I can't say whether that's right until you submit your answer. Want a hint instead, or should I rephrase the question?",
  }),
  "tutor.guess.test": msg({
    id: "tutor.guess.test",
    message: "I can't say whether that's right during the test. I can rephrase the question or explain a word in it.",
  }),
  "tutor.blocked": msg({
    id: "tutor.blocked",
    message: "Let's look at the wording of the question together instead. Which part is unclear?",
  }),
  "tutor.review": msg({
    id: "tutor.review",
    message:
      "Try to recall it first: the review works best without help. If the card is broken or unclear, tell me what is wrong with it.",
  }),
  "tutor.review.coach": msg({
    id: "tutor.review.coach",
    message:
      "I can't say whether that's right: finding it yourself is what makes the review work. Give it a try, or ask me for a hint or a guiding question.",
  }),
};

/** What the tutor may do now, in plain words (the dock shows why it is quiet). */
export const POLICIES: Record<TutorPolicyId, MessageDescriptor> = {
  free: msg({
    id: "tutor.policy.free",
    message: "Ask anything about your path. The tutor can suggest changes; you decide whether to make them.",
  }),
  lesson: msg({ id: "tutor.policy.lesson", message: "Ask about this lesson: explanations, examples, questions." }),
  "practice.before_attempt": msg({
    id: "tutor.policy.practice-before",
    message:
      "You have not answered this question yet, so the tutor gives guiding questions and hints, not the answer.",
  }),
  "practice.after_attempt": msg({
    id: "tutor.policy.practice-after",
    message: "You answered this question: the tutor can explain the solution and your answer.",
  }),
  "test.locked": msg({
    id: "tutor.policy.test-locked",
    message: "Locked during the test: the tutor only explains the wording of a question and helps with the app.",
  }),
  "test.hints": msg({
    id: "tutor.policy.test-hints",
    message:
      "Test with hints: the tutor may give one small nudge per question, and that answer then counts as helped.",
  }),
  placement: msg({
    id: "tutor.policy.placement",
    message: "Locked during the placement test: the tutor only explains the wording of a question.",
  }),
  "test.debrief": msg({
    id: "tutor.policy.test-debrief",
    message: "The test is over: talk about its topics and what to study next. Its answers stay hidden for a retake.",
  }),
  "review.before_recall": msg({
    id: "tutor.policy.review-before",
    message: "Recall it on your own first. Before you answer, the tutor only takes reports of a broken card.",
  }),
  "review.after_recall": msg({
    id: "tutor.policy.review-after",
    message: "You answered this card: the tutor can explain it and offer a memory aid.",
  }),
  setup: msg({
    id: "tutor.policy.setup",
    message: "Help with settings and setup. The tutor explains the choices; you change them yourself.",
  }),
  "review.coach": msg({
    id: "tutor.policy.review-coach",
    message:
      "No spoilers: until this question is resolved, the tutor coaches your recall and explains options you already tried, never the answer.",
  }),
  "review.resolved": msg({
    id: "tutor.policy.review-resolved",
    message: "This question is resolved: the tutor can explain the answer and each option freely.",
  }),
};

/** The policy that keeps the answer out of the tutor's replies during a review question. */
export const NO_SPOILERS_POLICY: TutorPolicyId = "review.coach";

// kept for callers that look a plain string up: the same entries as above
export const REVIEW_POLICIES: Record<string, MessageDescriptor> = POLICIES;
export const REVIEW_TEMPLATES: Record<string, MessageDescriptor> = TEMPLATES;

const ERRORS: Record<string, MessageDescriptor> = {
  budget: msg({
    id: "tutor.error.budget",
    message: "The monthly budget cap is reached. Raise it in Settings or wait for next month.",
  }),
  quota: msg({
    id: "tutor.error.quota",
    message: "The model provider's quota or rate limit is used up. Try again later or pick other models in Setup.",
  }),
  auth: msg({
    id: "tutor.error.auth",
    message: "The model provider did not accept the credentials. Check them in Setup.",
  }),
  timeout: msg({ id: "tutor.error.timeout", message: "The model took too long to answer." }),
  transport: msg({ id: "tutor.error.transport", message: "The model could not be reached." }),
  empty: msg({ id: "tutor.error.empty", message: "The model returned an empty reply." }),
  error: msg({ id: "tutor.error.other", message: "Something went wrong while answering." }),
};

export function errorText(error: string | null): MessageDescriptor {
  return ERRORS[error ?? "error"] ?? ERRORS["error"]!;
}

export const STAGES: Record<Stage, MessageDescriptor> = {
  thinking: msg({ id: "tutor.stage.thinking", message: "Thinking…" }),
  writing: msg({ id: "tutor.stage.writing", message: "Writing…" }),
  checking: msg({ id: "tutor.stage.checking", message: "Checking the reply before showing it…" }),
};

export const CHIP_KINDS: Record<ChipKind, MessageDescriptor> = {
  path: msg({ id: "tutor.chip.kind.path", message: "Path" }),
  skill: msg({ id: "tutor.chip.kind.skill", message: "Skill" }),
  lesson: msg({ id: "tutor.chip.kind.lesson", message: "Lesson" }),
  item: msg({ id: "tutor.chip.kind.item", message: "Question" }),
  selection: msg({ id: "tutor.chip.kind.selection", message: "Selected text" }),
  notes: msg({ id: "tutor.chip.kind.notes", message: "Notes" }),
  memory: msg({ id: "tutor.chip.kind.memory", message: "Tutor memory" }),
  material: msg({ id: "tutor.chip.kind.material", message: "Your material" }),
};

export const SCOPES: Record<ConversationOut["scope"], MessageDescriptor> = {
  lesson: msg({ id: "tutor.scope.lesson", message: "Lesson" }),
  skill: msg({ id: "tutor.scope.skill", message: "Skill" }),
  path: msg({ id: "tutor.scope.path", message: "Path" }),
  attempt: msg({ id: "tutor.scope.attempt", message: "Test" }),
  general: msg({ id: "tutor.scope.general", message: "General" }),
};

export const PROPOSAL_KINDS: Record<ProposalOut["kind"], MessageDescriptor> = {
  add_lesson: msg({ id: "tutor.proposal.kind.add-lesson", message: "Add a lesson" }),
  change_prerequisites: msg({ id: "tutor.proposal.kind.prerequisites", message: "Change the order of skills" }),
  extra_review: msg({ id: "tutor.proposal.kind.extra-review", message: "An extra review" }),
  change_difficulty: msg({ id: "tutor.proposal.kind.difficulty", message: "Change the difficulty" }),
  other: msg({ id: "tutor.proposal.kind.other", message: "A suggestion" }),
};

export const PROPOSAL_STATUS: Record<ProposalOut["status"], MessageDescriptor> = {
  pending: msg({ id: "tutor.proposal.status.pending", message: "Waiting for your decision" }),
  accepted: msg({ id: "tutor.proposal.status.accepted", message: "Accepted" }),
  rejected: msg({ id: "tutor.proposal.status.rejected", message: "Declined" }),
  expired: msg({ id: "tutor.proposal.status.expired", message: "Expired" }),
};

export const DIFFICULTIES: Record<string, MessageDescriptor> = {
  foundational: msg({ id: "tutor.proposal.difficulty.foundational", message: "Foundational" }),
  intermediate: msg({ id: "tutor.proposal.difficulty.intermediate", message: "Intermediate" }),
  advanced: msg({ id: "tutor.proposal.difficulty.advanced", message: "Advanced" }),
};

export const MEMORY_KINDS: Record<MemoryKind, MessageDescriptor> = {
  preference: msg({ id: "tutor.memory.kind.preference", message: "Preference" }),
  misconception: msg({ id: "tutor.memory.kind.misconception", message: "Misconception" }),
  goal: msg({ id: "tutor.memory.kind.goal", message: "Goal" }),
  fact: msg({ id: "tutor.memory.kind.fact", message: "Fact" }),
};

export const MEMORY_SOURCES: Record<MemoryOut["source"], MessageDescriptor> = {
  tutor: msg({ id: "tutor.memory.source.tutor", message: "Noted by the tutor" }),
  learner: msg({ id: "tutor.memory.source.learner", message: "Written by you" }),
  system: msg({ id: "tutor.memory.source.system", message: "Added by Yuo" }),
};

/** Names of suggestion kinds, for the muted-triggers setting. */
export const TRIGGER_NAMES: Record<string, MessageDescriptor> = {
  repeated_error: msg({ id: "tutor.trigger.repeated-error", message: "Repeated mistakes on one idea" }),
  fast_guessing: msg({ id: "tutor.trigger.fast-guessing", message: "Answering very fast" }),
  unsent_notes: msg({ id: "tutor.trigger.unsent-notes", message: "Notes not asked about yet" }),
  failed_test: msg({ id: "tutor.trigger.failed-test", message: "A skill test not passed" }),
};
