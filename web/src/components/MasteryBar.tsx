import { ProgressBar } from "react-aria-components";
import styles from "./MasteryBar.module.css";

/**
 * A small accessible bar for a 0..1 value (skill mastery): pollen while growing, forest when full or when the skill
 * is `done` (mastered by its test, whatever the number says).
 */
export function MasteryBar({ value, label, done }: { value: number; label: string; done?: boolean }) {
  const v = Math.min(1, Math.max(0, Number.isFinite(value) ? value : 0));
  return (
    <ProgressBar className={v >= 1 || done ? `${styles.bar} ${styles.full}` : styles.bar} value={v * 100} aria-label={label}>
      {({ percentage }) => (
        <>
          <span className={styles.track}>
            <span className={styles.fill} style={{ inlineSize: `${percentage ?? 0}%` }} />
          </span>
          <span className={styles.value}>{Math.round(percentage ?? 0)}%</span>
        </>
      )}
    </ProgressBar>
  );
}
