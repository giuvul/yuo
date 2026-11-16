import { msg } from "@lingui/core/macro";
import type { MessageDescriptor } from "@lingui/core";

// Job errors arrive as technical text from the runner (yuo/generation). These patterns turn the
// known ones into plain words; anything else gets a generic sentence, with the raw text shown
// behind a "details" toggle.
const PATTERNS: [RegExp, MessageDescriptor][] = [
  [
    /budget cap/i,
    msg({
      id: "job.error.budget",
      message: "The monthly spending limit is reached, so generation is paused until it allows more.",
    }),
  ],
  [
    /no adapter configured|no model bound/i,
    msg({ id: "job.error.no-model", message: "No model is set up for this step. Choose a preset in Setup." }),
  ],
  [
    /invalid output after repair/i,
    msg({
      id: "job.error.invalid-output",
      message: "The model's answer was not usable, even after Yuo asked it to fix it.",
    }),
  ],
  [/failed review/i, msg({ id: "job.error.review", message: "The lesson did not pass the quality review." })],
  [
    /already running/i,
    msg({ id: "job.error.busy", message: "The same step was already running. Yuo will try again." }),
  ],
  [
    /ENOSPC|no space left/i,
    msg({ id: "job.error.disk-full", message: "There was not enough space to put the video together." }),
  ],
  [
    /render container stopped answering|cannot be made here: no_container/i,
    msg({ id: "job.error.renderer-away", message: "The part of Yuo that makes videos was not answering." }),
  ],
  [
    /scene module never compiled/i,
    msg({ id: "job.error.video-code", message: "The video's scenes could not be built; the reading lesson has it all." }),
  ],
  [
    /timed? ?out|timeout/i,
    msg({ id: "job.error.timeout", message: "The model took too long to answer." }),
  ],
  [
    /rate limit|429/i,
    msg({ id: "job.error.rate-limit", message: "The model provider asked Yuo to slow down. Try again later." }),
  ],
];

const GENERIC = msg({ id: "job.error.generic", message: "Something went wrong while generating." });

export function jobErrorMessage(error: string | null | undefined): MessageDescriptor {
  if (!error) return GENERIC;
  return PATTERNS.find(([re]) => re.test(error))?.[1] ?? GENERIC;
}
