// The results of a review session: the score, how each answer went, memory per skill before and after with the
// next review date, and what is worth another look. A flawless run gets a leaf, never confetti.
import { Trans, useLingui } from "@lingui/react/macro";
import { useQuery } from "@tanstack/react-query";
import { ErrorNotice } from "../components/ErrorNotice";
import { CountUp, LeafPop } from "../components/Grove";
import { ArrowRightIcon, BoltIcon, BookIcon, CheckIcon, CloseIcon, LeafIcon } from "../components/icons";
import { Button, ButtonLink, Notice, ui, Waiting } from "../components/ui";
import { fetchReviewResult, reviewKeys, useReviewHub, type ReviewResult } from "./api";
import { MemoryRing } from "./primitives";
import styles from "./review.module.css";
import { MathText } from "../components/MathText";

/** A flawless run of at least this many answers gets the leaf. */
const FLAWLESS_FROM = 5;

export function Results({
  pathId,
  attemptId,
  state,
  onRetry,
  onAgain,
}: {
  pathId: string;
  attemptId: string;
  /** whether `attempt.finished` has reached the server */
  state: "sending" | "sent" | "offline";
  onRetry: () => void;
  onAgain: () => void;
}) {
  const result = useQuery({
    queryKey: reviewKeys.result(attemptId),
    queryFn: () => fetchReviewResult(attemptId),
    enabled: state === "sent",
    staleTime: Infinity,
  });
  const hub = useReviewHub(pathId, state === "sent");
  const canAgain = (hub.data?.sizes.length ?? 0) > 0 && (hub.data?.allowed_today ?? 0) > 0;
  const back = (
    <ButtonLink to="/paths/$pathId" params={{ pathId }} variant="secondary">
      <Trans id="review.results.back">Back to the path</Trans>
    </ButtonLink>
  );

  if (state === "offline") {
    return (
      <section className={styles.results}>
        <Notice tone="warning" role="status">
          <Trans id="review.results.offline">
            Your answers are saved. The results appear here when you are back online.
          </Trans>
        </Notice>
        <div className={styles.actions}>
          <Button onPress={onRetry}>
            <Trans id="review.results.retry">Try again</Trans>
          </Button>
          {back}
        </div>
      </section>
    );
  }
  if (state === "sending" || result.isPending) {
    return (
      <Waiting>
        <Trans id="review.results.loading">Adding up your session…</Trans>
      </Waiting>
    );
  }
  if (result.isError) {
    return (
      <section className={styles.results}>
        <ErrorNotice error={result.error} />
        <div className={styles.actions}>{back}</div>
      </section>
    );
  }
  return (
    <ResultsView
      result={result.data}
      footer={
        <>
          {canAgain ? (
            <Button onPress={onAgain}>
              <Trans id="review.results.again">Review again</Trans>
              <ArrowRightIcon />
            </Button>
          ) : null}
          {back}
        </>
      }
    />
  );
}

function ResultsView({ result, footer }: { result: ReviewResult; footer?: React.ReactNode }) {
  const { t, i18n } = useLingui();
  const { answered, first_try: first, second_try: second, revealed, xp } = result;
  const percent = Math.round(result.score * 100);
  const flawless = answered >= FLAWLESS_FROM && first === answered;
  const again = result.items.filter((i) => i.outcome === "revealed" || i.outcome === "open");
  const pct = (v: number) => i18n.number(v, { style: "percent", maximumFractionDigits: 0 });
  const date = (iso: string) => i18n.date(new Date(iso), { dateStyle: "medium" });

  return (
    <section className={styles.results} aria-labelledby="review-results-title">
      <div className={`${ui.card} ${styles.resultsTop}`}>
        <MemoryRing
          value={answered > 0 ? result.score : null}
          strongFrom={1}
          label={t({ id: "review.results.ring", message: `${first} of ${answered} right on the first try` })}
        >
          <span className={styles.ringNumber}>
            <CountUp value={percent} formatted={String(percent)} />
            <span className={styles.ringUnit}>%</span>
          </span>
          <span className={styles.ringCaption}>
            <Trans id="review.results.ring.caption">first try</Trans>
          </span>
        </MemoryRing>
        <div className={styles.resultsMain}>
          <h2 id="review-results-title" className={styles.resultsTitle}>
            {flawless ? (
              <>
                <LeafPop>
                  <LeafIcon />
                </LeafPop>
                <Trans id="review.results.flawless">Every answer right, first try</Trans>
              </>
            ) : (
              <Trans id="review.results.title">Session done</Trans>
            )}
          </h2>
          <dl className={styles.counts}>
            <div>
              <dt>
                <span className={styles.countMark} data-state="first" aria-hidden="true">
                  <CheckIcon size="0.7rem" />
                </span>
                <Trans id="review.results.first">First try</Trans>
              </dt>
              <dd>{first}</dd>
            </div>
            <div>
              <dt>
                <span className={styles.countMark} data-state="second" aria-hidden="true">
                  2
                </span>
                <Trans id="review.results.second">Second try</Trans>
              </dt>
              <dd>{second}</dd>
            </div>
            <div>
              <dt>
                <span className={styles.countMark} data-state="revealed" aria-hidden="true">
                  <CloseIcon size="0.7rem" />
                </span>
                <Trans id="review.results.shown">Shown</Trans>
              </dt>
              <dd>{revealed}</dd>
            </div>
            {xp !== null ? (
              <div>
                <dt>
                  <BoltIcon size="0.9rem" />
                  <Trans id="review.results.xp">XP</Trans>
                </dt>
                <dd>+{xp}</dd>
              </div>
            ) : null}
          </dl>
        </div>
      </div>

      {result.skills.length > 0 ? (
        <div className={`${ui.card} ${styles.section}`}>
          <h3 className={styles.sectionTitle}>
            <Trans id="review.results.memory">Memory</Trans>
          </h3>
          <ul className={styles.skillRows}>
            {result.skills.map((s) => {
              const before = pct(s.before);
              const after = s.after === null ? null : pct(s.after);
              const due = s.next_due ? date(s.next_due) : null;
              return (
                <li key={s.id}>
                  <span className={styles.skillRowTitle}>{s.title}</span>
                  <span className={styles.change}>
                    {after === null ? (
                      before
                    ) : (
                      <>
                        <span className="visually-hidden">
                          <Trans id="review.results.change">
                            from {before} to {after}
                          </Trans>
                        </span>
                        <span className={styles.changeBefore} aria-hidden="true">
                          {before}
                        </span>
                        <ArrowRightIcon size="0.9em" />
                        <span aria-hidden="true">{after}</span>
                      </>
                    )}
                  </span>
                  {due ? (
                    <span className={styles.skillRowNext}>
                      <Trans id="review.results.next">Next review: {due}</Trans>
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      {again.length > 0 ? (
        <div className={`${ui.card} ${styles.section}`}>
          <h3 className={styles.sectionTitle}>
            <Trans id="review.results.another-look">Worth another look</Trans>
          </h3>
          <ul className={styles.again}>
            {again.map((i) => {
              const revisit = i.revisit;
              const lesson = i.lesson_title;
              return (
                <li key={i.item_version_id}>
                  <p className={styles.againPrompt}>
                    <MathText text={i.prompt} />
                  </p>
                  {i.concept ? <p className={styles.againMeta}>{i.concept}</p> : null}
                  {revisit ? (
                    <p className={styles.againMeta}>
                      <Trans id="review.feedback.revisit">Look again: {revisit}</Trans>
                    </p>
                  ) : null}
                  {i.outcome === "open" ? (
                    <p className={styles.againMeta}>
                      <Trans id="review.results.open">Not right on the one try it got.</Trans>
                    </p>
                  ) : null}
                  {i.lesson_id ? (
                    <p>
                      <ButtonLink to="/lessons/$lessonId" params={{ lessonId: i.lesson_id }} variant="secondary" small>
                        <BookIcon />
                        {lesson ? (
                          <Trans id="review.feedback.lesson">Lesson: {lesson}</Trans>
                        ) : (
                          <Trans id="review.feedback.lesson.plain">Open the lesson</Trans>
                        )}
                      </ButtonLink>
                    </p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      {footer ? <div className={styles.actions}>{footer}</div> : null}
    </section>
  );
}
