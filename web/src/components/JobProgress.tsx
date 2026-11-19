// What a job is doing and how long it has left, in words (a video lesson that only says
// "in progress" for ten minutes looks stuck). The server reports the step a running job is at, its round, how
// long it has run and how long that kind of job usually takes.
import { msg, plural } from "@lingui/core/macro";
import type { MessageDescriptor } from "@lingui/core";
import { useLingui } from "@lingui/react";
import type { JobRef } from "../api/client";

const STEP: Record<string, MessageDescriptor> = {
  tree_outline: msg({ id: "job.step.tree", message: "Planning the skills" }),
  level_check: msg({ id: "job.step.level-check", message: "Writing the level questions" }),
  research: msg({ id: "job.step.research", message: "Looking up sources" }),
  lesson_body: msg({ id: "job.step.lesson-body", message: "Writing the lesson" }),
  review: msg({ id: "job.step.review", message: "Checking the lesson for mistakes" }),
  items_generate: msg({ id: "job.step.items", message: "Writing practice questions" }),
  items_support: msg({ id: "job.step.items-support", message: "Writing hints and explanations" }),
  blind_solve: msg({ id: "job.step.blind-solve", message: "Checking the answers" }),
  review_bank: msg({ id: "job.step.review-bank", message: "Writing review questions" }),
  translate: msg({ id: "job.step.translate", message: "Translating" }),
  video_script: msg({ id: "job.step.video-script", message: "Writing the script and the scenes" }),
  video_scene: msg({ id: "job.step.video-script", message: "Writing the script and the scenes" }),
  tts: msg({ id: "job.step.narration", message: "Recording the narration" }),
  narration: msg({ id: "job.step.narration", message: "Recording the narration" }),
  stills: msg({ id: "job.step.stills", message: "Drawing sample frames" }),
  video_review: msg({ id: "job.step.video-review", message: "Reviewing the frames and the facts" }),
  render: msg({ id: "job.step.render", message: "Rendering the video" }),
  next_check: msg({ id: "job.step.next", message: "Working out what comes next" }),
  next_directions: msg({ id: "job.step.next", message: "Working out what comes next" }),
  next_grow: msg({ id: "job.step.next-grow", message: "Adding the new skills" }),
};

/** The words for a step code, or null when the web app has none. */
export function stepLabel(code: string | null | undefined, i18n: ReturnType<typeof useLingui>["i18n"]): string | null {
  const d = code ? STEP[code] : undefined;
  return d ? i18n._(d) : null;
}

/** "Rendering the video · draft 2 of at most 4", or null when the job reports no step. */
function jobStep(job: JobRef, i18n: ReturnType<typeof useLingui>["i18n"]): string | null {
  if (job.status !== "running" || !job.step) return null;
  const step = STEP[job.step] ? i18n._(STEP[job.step]!) : null;
  if (!step) return null;
  if (job.round && job.rounds && job.rounds > 1) {
    const n = job.round;
    const of = job.rounds;
    const draft = i18n._(msg({ id: "job.step.round", message: `draft ${n} of at most ${of}` }));
    return `${step} · ${draft}`;
  }
  return step;
}

/** How long it has left, or how long it usually takes; null when there is nothing useful to say. */
export function jobTime(job: JobRef, i18n: ReturnType<typeof useLingui>["i18n"]): string | null {
  const typical = job.typical_s ?? null;
  if (job.status === "running" && typical && job.running_s != null) {
    const left = typical - job.running_s;
    if (left > 90) {
      const min = Math.round(left / 60);
      return i18n._(msg({ id: "job.time.left", message: plural(min, { one: "about # minute left", other: "about # minutes left" }) }));
    }
    if (left > 0) return i18n._(msg({ id: "job.time.almost", message: "about a minute left" }));
    return i18n._(msg({ id: "job.time.longer", message: "taking longer than usual, still working" }));
  }
  if (job.status === "queued" && job.retry_at) {
    const at = i18n.date(new Date(job.retry_at), { timeStyle: "short" });
    return i18n._(msg({ id: "job.time.retry", message: `trying again at ${at}` }));
  }
  if (job.status === "queued" && typical && typical >= 120) {
    const min = Math.round(typical / 60);
    return i18n._(msg({ id: "job.time.typical", message: plural(min, { one: "usually takes about # minute", other: "usually takes about # minutes" }) }));
  }
  return null;
}

/** The step and the time as one quiet line under a job's name. */
export function JobProgressLine({ job, className }: { job: JobRef; className?: string }) {
  const { i18n } = useLingui();
  const parts = [jobStep(job, i18n), jobTime(job, i18n)].filter(Boolean);
  return parts.length ? <span className={className}>{parts.join(" · ")}</span> : null;
}
