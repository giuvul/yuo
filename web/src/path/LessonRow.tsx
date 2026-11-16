// A lesson's row on the path page: its state, a link when it can be read, "Generate" when it is only planned.
// Shared by the list view and the tree's skill panel.
import { Trans, useLingui } from "@lingui/react/macro";
import { useLingui as useLinguiRuntime } from "@lingui/react";
import { Link } from "@tanstack/react-router";
import type { JobRef, LessonRef } from "../api/client";
import { useGenerateLesson } from "../api/hooks";
import { GenerationError } from "../onboarding/AiReady";
import { jobErrorMessage } from "../components/jobError";
import { JobKindLabel, LessonKindLabel, LessonStateLabel } from "../components/labels";
import { AlertIcon, BookIcon } from "../components/icons";
import { Button, Notice, ui } from "../components/ui";
import styles from "./LessonRow.module.css";

const GENERATABLE = new Set(["planned", "failed"]);
/** Lesson states in which Yuo is writing the lesson. */
export const WRITING = new Set(["queued", "generating", "in_review"]);

function LessonIcon({ state }: { state: string }) {
  if (state === "ready") return <BookIcon className={styles.lessonIconReady} />;
  if (state === "failed") return <AlertIcon className={styles.lessonIconFailed} />;
  if (WRITING.has(state)) return <span className={`${ui.spinner} ${styles.lessonSpinner}`} />;
  return <span className={styles.lessonDot} />;
}

export function LessonRow({ lesson, pathId, job }: { lesson: LessonRef; pathId: string; job: JobRef | undefined }) {
  const { t } = useLingui();
  const generate = useGenerateLesson(pathId);
  const title = lesson.title ?? t({ id: "path.lesson.untitled", message: "Untitled lesson" });

  return (
    <li className={styles.lesson} data-state={lesson.state}>
      <span className={styles.lessonIcon} aria-hidden="true">
        <LessonIcon state={lesson.state} />
      </span>
      {lesson.state === "ready" ? (
        <Link to="/lessons/$lessonId" params={{ lessonId: lesson.id }} className={styles.lessonTitle}>
          {title}
        </Link>
      ) : (
        <span className={styles.lessonTitle}>{title}</span>
      )}
      {lesson.kind !== "core" ? (
        <span className={styles.kind} data-kind={lesson.kind}>
          <LessonKindLabel value={lesson.kind} />
        </span>
      ) : null}
      <span className={styles.state} data-state={lesson.state}>
        <LessonStateLabel value={lesson.state} />
      </span>
      {GENERATABLE.has(lesson.state) ? (
        <Button
          small
          variant="secondary"
          isDisabled={generate.isPending}
          onPress={() => generate.mutate(lesson.id)}
          aria-label={t({ id: "path.lesson.generate.label", message: `Generate “${title}”` })}
        >
          {lesson.state === "failed" ? (
            <Trans id="path.lesson.retry">Try again</Trans>
          ) : (
            <Trans id="path.lesson.generate">Generate</Trans>
          )}
        </Button>
      ) : null}
      {lesson.state === "failed" && job?.status === "failed" ? (
        <div className={styles.lessonError}>
          <FailedJob job={job} />
        </div>
      ) : null}
      {generate.isError ? (
        <div className={styles.lessonError}>
          <GenerationError error={generate.error} />
        </div>
      ) : null}
    </li>
  );
}

export function FailedJob({ job }: { job: JobRef }) {
  const { i18n } = useLinguiRuntime();
  const attempt = job.attempt;
  return (
    <Notice tone="error" role="status">
      <p>
        <strong>
          <JobKindLabel value={job.kind} />
        </strong>
        {": "}
        {i18n._(jobErrorMessage(job.error))}
      </p>
      {job.error ? (
        <details>
          <summary>
            <Trans id="path.job.details">Details (attempt {attempt})</Trans>
          </summary>
          <code className={styles.rawError}>{job.error}</code>
        </details>
      ) : null}
    </Notice>
  );
}
