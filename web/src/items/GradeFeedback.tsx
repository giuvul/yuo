import { Trans } from "@lingui/react/macro";
import type { Graded, Item } from "../api/client";
import { CheckIcon, CloseIcon, LeafIcon } from "../components/icons";
import { grove, LeafPop } from "../components/Grove";
import { Notice } from "../components/ui";
import { correctLines } from "./answers";
import styles from "./items.module.css";

export const FULL_MARKS = 0.999;

/** Feedback for one graded answer: right or not, the right answer, why, and the worked solution. */
export function GradeFeedback({ item, graded }: { item: Item; graded: Graded }) {
  if (graded.pending) {
    return (
      <Notice role="status">
        <Trans id="item.grade.pending">Your answer is being graded. The result appears here when it is ready.</Trans>
      </Notice>
    );
  }
  if (item.type === "flashcard") {
    // the back was shown when the card was turned; nothing more to reveal
    return (
      <Notice tone="success" role="status" icon={<CheckIcon />}>
        <Trans id="item.grade.flashcard.saved">Rating saved. The card comes back when it is due.</Trans>
      </Notice>
    );
  }
  const score = graded.score ?? 0;
  const full = score >= FULL_MARKS;
  const partial = !full && score > 0;
  const lines = correctLines(item, graded.correct);
  const percent = Math.round(score * 100);

  return (
    <Notice
      tone={full ? "success" : partial ? "warning" : "error"}
      role="status"
      icon={
        full ? (
          <LeafPop>
            <LeafIcon />
          </LeafPop>
        ) : partial ? (
          true
        ) : (
          <CloseIcon />
        )
      }
      className={full || partial ? grove.appear : grove.nudge}
    >
      <div className={styles.feedback}>
        <p className={styles.verdict}>
          <strong>
            {full ? (
              <Trans id="item.grade.correct">Correct.</Trans>
            ) : partial ? (
              <Trans id="item.grade.partial">Partly right ({percent}%).</Trans>
            ) : (
              <Trans id="item.grade.incorrect">Not quite.</Trans>
            )}
          </strong>
        </p>
        {lines.length > 0 && !full ? (
          <div className={styles.detail}>
            <p className={styles.label}>
              <Trans id="item.grade.right-answer">The right answer</Trans>
            </p>
            {lines.length === 1 ? (
              <p className={styles.preWrap}>{lines[0]}</p>
            ) : (
              <ul>
                {lines.map((l, i) => (
                  <li key={i}>{l}</li>
                ))}
              </ul>
            )}
          </div>
        ) : null}
        {graded.rationale ? <p className={`${styles.preWrap} ${styles.detail}`}>{graded.rationale}</p> : null}
        {graded.explanation ? <p className={styles.detail}>{graded.explanation}</p> : null}
        {graded.solution ? (
          <div className={styles.detail}>
            <p className={styles.label}>
              <Trans id="item.grade.solution">Solution</Trans>
            </p>
            <p className={styles.preWrap}>{graded.solution}</p>
          </div>
        ) : null}
      </div>
    </Notice>
  );
}
