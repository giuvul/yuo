import { Plural, Trans, useLingui } from "@lingui/react/macro";
import { createRoute, Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import type { LessonOut } from "../api/client";
import { useGenerateLesson, useLesson, useNoteMutations, useNotes } from "../api/hooks";
import { MathText } from "../components/MathText";
import { ErrorNotice } from "../components/ErrorNotice";
import { LessonStateLabel } from "../components/labels";
import { ArrowRightIcon, CheckIcon, ChevronRightIcon, ClockIcon, PencilIcon, SparkleIcon } from "../components/icons";
import { grove, GrowingCheck, VineDivider } from "../components/Grove";
import { BackLink, Button, ButtonLink, Notice, PageHeader, ui } from "../components/ui";
import { LessonBody } from "../lesson/BlockRenderer";
import { NotesErrors, NotesFor } from "../lesson/Notes";
import { useOutbox } from "../outbox/context";
import { rootRoute } from "./root";
import styles from "./lessonReader.module.css";
import { useTutorActions, useTutorRefs, useTutorState } from "../tutor/context";
import { SelectionAsk } from "../tutor/SelectionAsk";
import { LessonVideo } from "../video/LessonVideo";
import { LessonSources } from "../material/LessonSources";

export const lessonRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/lessons/$lessonId",
  component: LessonPage,
});

function Reader({ lesson }: { lesson: LessonOut & { version_id: string } }) {
  const outbox = useOutbox();
  const bodyRef = useRef<HTMLDivElement>(null);
  const startedAt = useRef<number | null>(null);
  const [done, setDone] = useState(false);
  const versionId = lesson.version_id;

  // one lesson.started per opened lesson version (the ref also absorbs StrictMode's re-run)
  const startedFor = useRef<string | null>(null);
  useEffect(() => {
    if (startedFor.current === versionId) return;
    startedFor.current = versionId;
    startedAt.current = Date.now();
    setDone(false);
    void outbox.enqueue("lesson.started", { lesson_version_id: versionId, seconds: 0 });
  }, [outbox, versionId]);

  const finish = () => {
    const seconds = Math.max(0, Math.round((Date.now() - (startedAt.current ?? Date.now())) / 1000));
    void outbox.enqueue("lesson.completed", { lesson_version_id: versionId, seconds });
    setDone(true);
  };

  const notes = useNotes(lesson.id);
  const noteOps = useNoteMutations(lesson.id);
  const noteList = (notes.data ?? []).filter((n) => !n.lesson_version_id || n.lesson_version_id === versionId);
  const minutes = lesson.est_minutes ?? 0;
  const items = lesson.practice_items;

  return (
    <article className={styles.article}>
      <PageHeader
        back={
          <>
            <BackLink to="/paths/$pathId" params={{ pathId: lesson.path_id }}>
              {lesson.path_title}
            </BackLink>
            <ChevronRightIcon size="0.9em" className={styles.crumbSep} />
            <span>{lesson.skill_title}</span>
          </>
        }
        title={lesson.title}
        meta={
          minutes > 0 ? (
            <span className={styles.metaItem}>
              <ClockIcon />
              <Plural id="lesson.minutes" value={minutes} one="About # minute" other="About # minutes" />
            </span>
          ) : null
        }
      />

      {lesson.review_notes?.length ? <ReviewNotes lesson={lesson} /> : null}

      <LessonVideo lesson={lesson} />

      <div ref={bodyRef} className={styles.body}>
        <LessonBody
          body={lesson.body}
          after={(bid) => <NotesFor bid={bid} notes={noteList} versionId={versionId} m={noteOps} />}
        />
      </div>
      <SelectionAsk root={bodyRef} />
      <LessonSources sources={lesson.sources ?? []} />

      <VineDivider />

      <section className={styles.lessonNotes} aria-labelledby="lesson-notes">
        <h2 id="lesson-notes" className={styles.notesTitle}>
          <Trans id="notes.title">Notes on this lesson</Trans>
        </h2>
        <NotesErrors m={noteOps} />
        <NotesFor bid={null} notes={noteList} versionId={versionId} m={noteOps} />
      </section>

      <footer className={styles.footer}>
        {done ? (
          <>
            <Notice tone="success" role="status" icon={<GrowingCheck />} className={grove.appear}>
              <Trans id="lesson.done.message">Lesson marked as done.</Trans>
            </Notice>
            <div className={styles.nextActions}>
              {items > 0 ? (
                <ButtonLink to="/lessons/$lessonId/practice" params={{ lessonId: lesson.id }}>
                  <PencilIcon />
                  <Plural id="lesson.practice" value={items} one="Practice (# question)" other="Practice (# questions)" />
                  <ArrowRightIcon />
                </ButtonLink>
              ) : null}
              <ButtonLink to="/paths/$pathId" params={{ pathId: lesson.path_id }} variant="secondary">
                <Trans id="lesson.back-to-path">Back to the path</Trans>
              </ButtonLink>
            </div>
          </>
        ) : (
          <div className={styles.nextActions}>
            <Button onPress={finish}>
              <CheckIcon />
              <Trans id="lesson.done">Done</Trans>
            </Button>
          </div>
        )}
        <TutorInvite />
      </footer>
    </article>
  );
}

/** The tutor, offered where a question comes up: at the end of the reading (it opens the dock). */
function TutorInvite() {
  const { t } = useLingui();
  const tutor = useTutorActions();
  const state = useTutorState();
  if (state.open) return null;
  return (
    <button type="button" className={styles.tutorInvite} onClick={() => tutor.open()}>
      <span className={styles.tutorInviteIcon} aria-hidden="true">
        <SparkleIcon />
      </span>
      <span className={styles.tutorInviteText}>
        <span className={styles.tutorInviteTitle}>
          {t({ id: "lesson.tutor.invite.title", message: "Questions about this lesson?" })}
        </span>
        <span className={styles.tutorInviteBody}>
          {t({
            id: "lesson.tutor.invite.body",
            message: "Ask the tutor for an explanation, an example or a quick check of what you understood.",
          })}
        </span>
      </span>
      <ChevronRightIcon className={styles.tutorInviteChevron} />
    </button>
  );
}

function LessonPage() {
  const { lessonId } = lessonRoute.useParams();
  useTutorRefs({ screen: "reading", lesson_id: lessonId });
  const lesson = useLesson(lessonId);

  if (lesson.isPending) {
    return (
      <p className={ui.muted}>
        <Trans id="common.loading">Loading…</Trans>
      </p>
    );
  }
  if (lesson.isError) return <ErrorNotice error={lesson.error} />;

  const l = lesson.data;
  const versionId = l.version_id;
  if (!versionId || !l.body) {
    return (
      <Notice role="status">
        <p>
          <Trans id="lesson.not-ready">This lesson is not ready yet.</Trans>{" "}
          <LessonStateLabel value={l.state} />
        </p>
        <Link to="/paths/$pathId" params={{ pathId: l.path_id }}>
          <Trans id="lesson.back-to-path">Back to the path</Trans>
        </Link>
      </Notice>
    );
  }
  return <Reader lesson={{ ...l, version_id: versionId }} />;
}

/**
 * A lesson accepted without passing its review: what the reviewer found that may be wrong, each with its
 * correction, so the learner reads it with care; it can be written again.
 */
function ReviewNotes({ lesson }: { lesson: LessonOut }) {
  const again = useGenerateLesson(lesson.path_id);
  const notes = lesson.review_notes ?? [];
  return (
    <Notice tone="warning" icon={true} role="note">
      <p>
        <strong>
          <Trans id="lesson.review-notes.title">Accepted without passing its review.</Trans>
        </strong>{" "}
        <Trans id="lesson.review-notes.intro">The reviewer found what may be wrong in it:</Trans>
      </p>
      <ul>
        {notes.map((n, i) => (
          <li key={i}>
            “<MathText text={n.claim} />”: <MathText text={n.correction} />
          </li>
        ))}
      </ul>
      <div className={ui.row}>
        <Button
          small
          variant="secondary"
          isDisabled={again.isPending || again.isSuccess}
          onPress={() => again.mutate(lesson.id)}
        >
          <Trans id="lesson.review-notes.again">Write it again</Trans>
        </Button>
      </div>
      {again.isSuccess ? (
        <p>
          <Trans id="lesson.review-notes.queued">A new version is being written; this one stays until it is ready.</Trans>
        </p>
      ) : null}
      {again.isError ? <ErrorNotice error={again.error} /> : null}
    </Notice>
  );
}
