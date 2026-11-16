// Runs one assessment attempt for every purpose:
// - practice: hints (not for flashcards), feedback after each answer, a summary;
// - review: feedback after each answer, no hints;
// - skill_test / placement: no hints and no per-item feedback (grades are hidden); the result comes
//   in the flush reply's `outcomes[attempt_id]` after attempt.finished.
import { Plural, Trans, useLingui } from "@lingui/react/macro";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError, type AssessmentOut, type Graded, type HintOut, type Item } from "../api/client";
import { fetchHint } from "../api/hooks";
import { ErrorNotice } from "../components/ErrorNotice";
import { LeafPop } from "../components/Grove";
import { ArrowRightIcon, CheckIcon, LeafIcon, QuestionIcon } from "../components/icons";
import { Button, Notice, Progress, ui } from "../components/ui";
import { emptyDraft, toAnswer, type Draft } from "../items/answers";
import { FULL_MARKS, GradeFeedback } from "../items/GradeFeedback";
import { ItemInput, itemPrompt } from "../items/ItemInput";
import { useOutbox } from "../outbox/context";
import type { Outcome } from "../outbox/outbox";
import { uuid7 } from "../outbox/uuid7";
import { useTutorRefs } from "../tutor/context";
import styles from "./assessment.module.css";

type Assessment = AssessmentOut & { assessment_id: string };

/** What happened to the answer to one item. */
type ItemOutcome =
  | { kind: "checking" }
  | { kind: "graded"; graded: Graded }
  | { kind: "saved-offline" }
  | { kind: "saved" }
  | { kind: "rejected"; reason: string };

/** The score of an answered item: a number once graded, null while not (yet) known. */
type Score = number | null;

const isTest = (a: AssessmentOut) => a.purpose === "skill_test" || a.purpose === "placement";

function ItemCard({
  assessment,
  attemptId,
  item,
  index,
  isLast,
  onScore,
  onNext,
}: {
  assessment: Assessment;
  attemptId: string;
  item: Item;
  index: number;
  isLast: boolean;
  onScore: (index: number, score: Score) => void;
  onNext: () => void;
}) {
  const { t } = useLingui();
  const outbox = useOutbox();
  const test = isTest(assessment);
  const hintsAllowed = assessment.purpose === "practice" && item.type !== "flashcard";
  const shownAt = useRef(Date.now());
  const [draft, setDraft] = useState<Draft>(() => emptyDraft(item));
  const [outcome, setOutcome] = useState<ItemOutcome | null>(null);
  const [hints, setHints] = useState<HintOut[]>([]);
  const [hintError, setHintError] = useState<unknown>(null);
  const [noMoreHints, setNoMoreHints] = useState(false);
  const [loadingHint, setLoadingHint] = useState(false);
  const responseId = useRef<string | null>(null);
  const total = assessment.items.length;
  const number = index + 1;
  const answer = toAnswer(item, draft);
  const prompt = itemPrompt(item);

  // a grade that arrives in a later flush (after being offline, or a model grade)
  useEffect(
    () =>
      outbox.onGraded((id, graded) => {
        if (id !== responseId.current || graded.hidden) return;
        setOutcome({ kind: "graded", graded });
        onScore(index, graded.score ?? null);
      }),
    [outbox, onScore, index],
  );

  const hintsDone = noMoreHints || hints.at(-1)?.last === true;

  const showHint = async () => {
    const level = hints.length + 1;
    setLoadingHint(true);
    setHintError(null);
    try {
      const hint = await fetchHint(item.item_version_id, level);
      setHints((h) => [...h, hint]);
      void outbox.enqueue("item.support_shown", {
        item_version_id: item.item_version_id,
        attempt_id: attemptId,
        kind: "hint",
        level: hint.level,
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setNoMoreHints(true);
      else setHintError(err);
    } finally {
      setLoadingHint(false);
    }
  };

  const submit = async () => {
    if (answer === null || outcome) return;
    const event = await outbox.enqueue("assessment.response_given", {
      attempt_id: attemptId,
      item_version_id: item.item_version_id,
      answer,
      ms_to_answer: Math.max(0, Math.round(Date.now() - shownAt.current)),
    });
    responseId.current = event.id;
    if (test) {
      // tests show nothing per item: the answer is in the outbox, move on
      onScore(index, null);
      onNext();
      return;
    }
    setOutcome({ kind: "checking" });
    const result = await outbox.flush();
    const graded = result.graded[event.id];
    const rejected = result.rejected[event.id];
    if (graded) {
      setOutcome((o) => (o?.kind === "graded" && !o.graded.pending ? o : { kind: "graded", graded }));
      onScore(index, graded.pending ? null : (graded.score ?? null));
    } else if (rejected !== undefined) {
      setOutcome({ kind: "rejected", reason: rejected });
      onScore(index, null);
    } else if (result.duplicates.includes(event.id) || result.accepted.includes(event.id)) {
      setOutcome({ kind: "saved" });
      onScore(index, null);
    } else {
      // still in the outbox; a later flush delivers the grade through onGraded
      setOutcome((o) => (o?.kind === "graded" ? o : { kind: "saved-offline" }));
      onScore(index, null);
    }
  };

  const answered = outcome !== null && outcome.kind !== "checking";
  const checked = outcome?.kind === "graded" && !outcome.graded.pending ? outcome.graded : null;

  return (
    <section className={`${ui.card} ${styles.item}`} aria-labelledby={`q-${item.item_version_id}`}>
      <div className={styles.itemTop}>
        <p className={styles.counter}>
          <Trans id="assessment.progress">
            Question {number} of {total}
          </Trans>
        </p>
        <ol className={styles.dots} aria-hidden="true">
          {assessment.items.map((it, i) => (
            <li key={it.item_version_id} data-state={i < index ? "done" : i === index ? "current" : "todo"} />
          ))}
        </ol>
      </div>
      <h2 id={`q-${item.item_version_id}`} className={styles.prompt}>
        {prompt || t({ id: "assessment.cloze.prompt", message: "Fill in the gaps" })}
      </h2>

      <ItemInput
        item={item}
        draft={draft}
        onChange={setDraft}
        disabled={outcome !== null}
        correct={checked && !checked.hidden ? checked.correct : undefined}
      />

      {hints.length > 0 ? (
        <ol className={styles.hints} aria-label={t({ id: "assessment.hints.label", message: "Hints" })}>
          {hints.map((h) => (
            <li key={h.level}>{h.text}</li>
          ))}
        </ol>
      ) : null}
      {hintError ? <ErrorNotice error={hintError} /> : null}

      {!outcome ? (
        <div className={styles.actions}>
          <Button onPress={() => void submit()} isDisabled={answer === null}>
            {test ? (
              isLast ? (
                <Trans id="assessment.test.finish">Finish the test</Trans>
              ) : (
                <Trans id="assessment.test.next">Save and continue</Trans>
              )
            ) : (
              <>
                <CheckIcon />
                <Trans id="assessment.check">Check answer</Trans>
              </>
            )}
          </Button>
          {hintsAllowed ? (
            <Button variant="ghost" onPress={() => void showHint()} isDisabled={hintsDone || loadingHint}>
              <QuestionIcon />
              {hints.length === 0 ? (
                <Trans id="assessment.hint">Show a hint</Trans>
              ) : hintsDone ? (
                <Trans id="assessment.hint.none">No more hints</Trans>
              ) : (
                <Trans id="assessment.hint.next">Another hint</Trans>
              )}
            </Button>
          ) : null}
        </div>
      ) : null}

      {outcome ? <Feedback item={item} outcome={outcome} /> : null}

      {answered ? (
        <div className={styles.actions}>
          <Button onPress={onNext}>
            {isLast ? (
              <Trans id="assessment.finish">See results</Trans>
            ) : (
              <Trans id="assessment.next">Next question</Trans>
            )}
            <ArrowRightIcon />
          </Button>
        </div>
      ) : null}
    </section>
  );
}

function Feedback({ item, outcome }: { item: Item; outcome: ItemOutcome }) {
  switch (outcome.kind) {
    case "checking":
      return (
        <p className={`${ui.waiting} ${ui.muted}`} role="status">
          <span className={ui.spinner} aria-hidden="true" />
          <Trans id="assessment.checking">Checking…</Trans>
        </p>
      );
    case "saved-offline":
      return (
        <Notice tone="warning" role="status">
          <Trans id="assessment.saved-offline">
            You are offline. Your answer is saved and will be graded when you are back online.
          </Trans>
        </Notice>
      );
    case "saved":
      return (
        <Notice role="status">
          <Trans id="assessment.saved">Your answer is saved.</Trans>
        </Notice>
      );
    case "rejected": {
      const reason = outcome.reason;
      return (
        <Notice tone="error">
          <Trans id="assessment.rejected">This answer could not be recorded: {reason}</Trans>
        </Notice>
      );
    }
    case "graded":
      return <GradeFeedback item={item} graded={outcome.graded} />;
  }
}

function Summary({ scores }: { scores: Score[] }) {
  const { t } = useLingui();
  const graded = scores.filter((s): s is number => s !== null);
  const right = graded.filter((s) => s >= FULL_MARKS).length;
  const total = graded.length;
  const waiting = scores.length - graded.length;
  return (
    <>
      {total > 0 ? (
        <div className={styles.score}>
          <p className={styles.scoreText}>
            <Trans id="assessment.summary.score">
              You got {right} of {total} right.
            </Trans>
          </p>
          <Progress
            value={right}
            max={total}
            showValue={false}
            label={t({ id: "assessment.summary.bar", message: "Answers right" })}
          />
        </div>
      ) : null}
      {waiting > 0 ? (
        <p className={ui.muted}>
          <Plural
            id="assessment.summary.waiting"
            value={waiting}
            one="# answer is still being graded."
            other="# answers are still being graded."
          />
        </p>
      ) : null}
    </>
  );
}

type RunnerProps = {
  assessment: Assessment;
  /** what to show for a test result (skill_test, placement) */
  renderOutcome?: (outcome: Outcome) => ReactNode;
  /** links shown at the end */
  footer?: ReactNode;
  onFinished?: () => void;
};

export function AssessmentRunner({ assessment, renderOutcome, footer, onFinished }: RunnerProps) {
  const outbox = useOutbox();
  const [attemptId] = useState(() => uuid7());
  const [index, setIndex] = useState(0);
  const [scores, setScores] = useState<Record<number, Score>>({});
  const [finished, setFinished] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const test = isTest(assessment);

  // one attempt.started per attempt (the ref also absorbs StrictMode's re-run)
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void outbox.enqueue("attempt.started", {
      attempt_id: attemptId,
      assessment_id: assessment.assessment_id,
      purpose: assessment.purpose,
    });
  }, [outbox, attemptId, assessment]);

  // a test result that arrives in a later flush (after being offline)
  useEffect(
    () =>
      outbox.onOutcome((id, o) => {
        if (id === attemptId) setOutcome(o);
      }),
    [outbox, attemptId],
  );

  const onScore = useCallback((i: number, score: Score) => setScores((s) => ({ ...s, [i]: score })), []);

  const finish = async () => {
    setFinished(true);
    await outbox.enqueue("attempt.finished", { attempt_id: attemptId, outcome: "finished" });
    const result = await outbox.flush();
    const o = result.outcomes[attemptId];
    if (o) setOutcome(o);
    onFinished?.();
  };

  const items = assessment.items;
  const item = items[index];
  const isLast = index === items.length - 1;
  // the tutor resolves its policy from the attempt and the question on screen (server-side)
  useTutorRefs({ attempt_id: attemptId, item_version_id: finished ? null : (item?.item_version_id ?? null) });
  const next = () => {
    if (isLast) void finish();
    else setIndex((i) => i + 1);
  };

  if (finished) {
    return (
      <section className={`${ui.card} ${styles.done}`}>
        <div className={styles.doneHead}>
          <span className={styles.doneMark} aria-hidden="true">
            <LeafPop>
              <LeafIcon />
            </LeafPop>
          </span>
          <h2 className={styles.doneTitle}>
            {test ? (
              <Trans id="assessment.test.done">Test finished</Trans>
            ) : (
              <Trans id="assessment.summary.title">All done</Trans>
            )}
          </h2>
        </div>
        {test ? (
          outcome && renderOutcome ? (
            renderOutcome(outcome)
          ) : (
            <p className={ui.muted} role="status">
              <Trans id="assessment.test.waiting">
                Your answers are saved. The result appears here as soon as they reach the server.
              </Trans>
            </p>
          )
        ) : (
          <Summary scores={items.map((_, i) => scores[i] ?? null)} />
        )}
        {footer ? <div className={styles.actions}>{footer}</div> : null}
      </section>
    );
  }

  return item ? (
    <ItemCard
      key={item.item_version_id}
      assessment={assessment}
      attemptId={attemptId}
      item={item}
      index={index}
      isLast={isLast}
      onScore={onScore}
      onNext={next}
    />
  ) : null;
}
