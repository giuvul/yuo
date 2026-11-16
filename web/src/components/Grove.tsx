// Grove details: the quiet ambient background and the small growth moments ("Motion").
// Everything here is decoration: aria-hidden, never the only carrier of meaning, static under reduced motion.
// Motion is CSS only (transform and opacity for anything that loops); no JS animation loops.
import type { CSSProperties, ReactNode } from "react";
import styles from "./Grove.module.css";

/** The leaf outline used by the decorations (the same shape as the vine's leaves). */
const LEAF = "M2 14C4 5 13 1.5 22.5 3.5 21.5 13 12 17.5 2 14z";
const LEAF_VEIN = "M3.5 13.5C9 11 15 7.5 20 5";

const MOTES = 8;

/**
 * The brand's background patterns behind the whole app (Yuo Brand Identity, section 11): flat botanical leaves
 * (pattern A) sliding very slowly, and a few pollen motes. No gradients. `quiet` (the reading screen)
 * halves it and drops the motes.
 */
export function Ambient({ quiet }: { quiet?: boolean }) {
  return (
    <div className={styles.ambient} data-quiet={quiet || undefined} aria-hidden="true">
      <span className={styles.leaves} />
      <span className={styles.motes}>
        {Array.from({ length: MOTES }, (_, i) => (
          <span key={i} className={styles.mote} />
        ))}
      </span>
    </div>
  );
}

/** A sprout that grows, unfolds its two leaves and starts again: "something is being written". */
export function GrowingSprout({ className }: { className?: string }) {
  return (
    <svg
      className={`${styles.sprout} ${className ?? ""}`}
      viewBox="0 0 24 24"
      width="1.1em"
      height="1.1em"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <g className={styles.sproutPlant}>
        <path className={styles.sproutStem} d="M12 21v-8" />
        <path className={styles.sproutLeafLeft} d="M12 13c0-4-2.5-6.5-7-6.5 0 4 2.5 6.5 7 6.5z" />
        <path className={styles.sproutLeafRight} d="M12 11c0-3.5 2.5-6 6.5-6 0 3.5-2.5 6-6.5 6z" />
      </g>
    </svg>
  );
}

/** An icon that pops in with three small leaves drifting off it, once (a right answer). */
export function LeafPop({ children }: { children: ReactNode }) {
  return (
    <span className={styles.pop}>
      {children}
      <span className={styles.burst} aria-hidden="true">
        <span className={styles.burstLeaf} />
        <span className={styles.burstLeaf} />
        <span className={styles.burstLeaf} />
      </span>
    </span>
  );
}

/** A check that draws itself, then a small leaf unfurls from its tip (a lesson marked as done). */
export function GrowingCheck({ size = "1.25em" }: { size?: string }) {
  return (
    <svg
      className={styles.check}
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path className={styles.checkPath} pathLength={1} d="M4 12.5l4.5 4.5L17.5 8" />
      <path className={styles.checkLeaf} d="M17.5 8c.3-2.4 1.9-3.9 4.2-4.1-.1 2.3-1.8 3.9-4.2 4.1z" />
    </svg>
  );
}

/**
 * A number that counts up from zero on mount (CSS @property, no script). The formatted value stays in the page
 * for screen readers and for the end state; the counter is only drawn while it runs.
 */
export function CountUp({ value, formatted }: { value: number; formatted: string }) {
  const n = Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0;
  return (
    <span className={styles.count} style={{ "--yuo-count-to": n } as CSSProperties}>
      <span className={styles.countFinal}>{formatted}</span>
      <span className={styles.countRun} aria-hidden="true" />
    </span>
  );
}

/** A hand-drawn line with a leaf in the middle, between the reading and what comes after it. */
export function VineDivider() {
  return (
    <div className={styles.divider} aria-hidden="true">
      <svg className={styles.dividerLine} viewBox="0 0 200 12" preserveAspectRatio="none">
        <path d="M1 7C30 3 55 10 90 6S140 4 199 7" vectorEffect="non-scaling-stroke" />
      </svg>
      <svg className={styles.dividerLeaf} viewBox="0 0 24 24">
        <path d={LEAF} />
        <path className={styles.dividerVein} d={LEAF_VEIN} />
      </svg>
      <svg className={`${styles.dividerLine} ${styles.dividerLineEnd}`} viewBox="0 0 200 12" preserveAspectRatio="none">
        <path d="M1 7C30 3 55 10 90 6S140 4 199 7" vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  );
}

/** A large, very faint leaf in the corner of a card (empty states). The card needs `position: relative; isolation: isolate; overflow: hidden`. */
export function LeafWatermark() {
  return (
    <svg className={styles.watermark} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d={LEAF} />
      <path className={styles.watermarkVein} d={LEAF_VEIN} />
    </svg>
  );
}

export { styles as grove };
