// The review screens' own primitives (3.2.8): the memory ring, the
// objective leaf, the progress vine and the answer option. Labels come in translated; colour never carries a
// state alone (each has a shape or an icon, and words for screen readers).
import { useId, type CSSProperties, type ReactNode } from "react";
import { CheckIcon, CloseIcon, RepeatIcon } from "../components/icons";
import styles from "./review.module.css";
import { MathText } from "../components/MathText";

const clamp = (v: number) => Math.min(1, Math.max(0, Number.isFinite(v) ? v : 0));
/** useId as a fragment identifier (its punctuation is not safe in `url(#...)`). */
const useSvgId = () => `yuo-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;

const RING_R = 52;
const RING_C = 2 * Math.PI * RING_R;

/**
 * A ring filled to `value` (0..1): pollen while growing, forest once strong. `children` sit in the middle (the
 * number); `label` names the whole for screen readers. `value` null draws the empty track.
 */
export function MemoryRing({
  value,
  label,
  small,
  strongFrom = 0.9,
  children,
}: {
  value: number | null;
  label: string;
  small?: boolean;
  strongFrom?: number;
  children?: ReactNode;
}) {
  const v = value === null ? 0 : clamp(value);
  return (
    <div className={styles.ring} data-small={small || undefined} data-strong={v >= strongFrom || undefined} role="img" aria-label={label}>
      <svg viewBox="0 0 120 120" aria-hidden="true" focusable="false">
        <circle className={styles.ringTrack} cx="60" cy="60" r={RING_R} />
        {v > 0 ? (
          <circle
            className={styles.ringValue}
            cx="60"
            cy="60"
            r={RING_R}
            strokeDasharray={`${v * RING_C} ${RING_C}`}
            style={{ "--yuo-ring-length": RING_C } as CSSProperties}
          />
        ) : null}
      </svg>
      <div className={styles.ringCentre} aria-hidden="true">
        {children}
      </div>
    </div>
  );
}

const LEAF = "M2 14C4 5 13 1.5 22.5 3.5 21.5 13 12 17.5 2 14z";
const LEAF_VEIN = "M3.5 13.5C9 11 15 7.5 20 5";

/**
 * One learning objective as a small leaf, filled from the stem to how well it is remembered (0..1). A due
 * objective carries a pollen dot. Decorative: the statement and the numbers are text beside it.
 */
export function ObjectiveLeaf({ value, due, size = "1.75rem" }: { value: number; due?: boolean; size?: string }) {
  const id = useSvgId();
  const v = clamp(value);
  return (
    <svg
      className={styles.leaf}
      data-due={due || undefined}
      viewBox="0 0 24 20"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
    >
      <clipPath id={id}>
        <rect x="0" y="0" width={2 + v * 20.5} height="20" />
      </clipPath>
      <path className={styles.leafFill} d={LEAF} clipPath={`url(#${id})`} />
      <path className={styles.leafLine} d={LEAF} />
      <path className={styles.leafVein} d={LEAF_VEIN} />
      {due ? <circle className={styles.leafDue} cx="19.5" cy="15.5" r="3.5" /> : null}
    </svg>
  );
}

/** How a question of the session went, for its segment of the vine. */
export type SegmentState = "todo" | "first" | "second" | "revealed" | "saved" | "skipped";
export type Segment = { id: string; state: SegmentState; current?: boolean; reask?: boolean; label: string };

const SEGMENT_ICON: Partial<Record<SegmentState, ReactNode>> = {
  first: <CheckIcon size="0.75rem" />,
  second: <span className={styles.segmentTwo}>2</span>,
  revealed: <CloseIcon size="0.75rem" />,
  saved: <span className={styles.segmentDot} />,
  skipped: <span className={styles.segmentDash} />,
};

/**
 * The session as a vine of segments, one per question: moss with a check (first try), pollen with a "2" (second
 * try), clay with a cross (answer shown); a question asked again is striped and carries a small loop.
 */
export function ProgressVine({ segments, label }: { segments: Segment[]; label: string }) {
  return (
    <ol className={styles.vine} aria-label={label}>
      {segments.map((s) => (
        <li
          key={s.id}
          className={styles.segment}
          data-state={s.state}
          data-current={s.current || undefined}
          data-reask={s.reask || undefined}
          aria-current={s.current ? "step" : undefined}
        >
          {s.reask ? <Stripes /> : null}
          <span className={styles.segmentIcon} aria-hidden="true">
            {SEGMENT_ICON[s.state] ?? (s.reask ? <RepeatIcon size="0.75rem" /> : null)}
          </span>
          <span className="visually-hidden">{s.label}</span>
        </li>
      ))}
    </ol>
  );
}

/** Flat diagonal stripes over a segment (an SVG pattern: no gradients). */
function Stripes() {
  const id = useSvgId();
  return (
    <svg className={styles.stripes} aria-hidden="true" focusable="false">
      <defs>
        <pattern id={id} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="2.5" height="6" fill="currentColor" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill={`url(#${id})`} />
    </svg>
  );
}

export type OptionState = "idle" | "selected" | "tried" | "right" | "wrong" | "other";

/**
 * One answer option as a large button: its key (A to D), the text, and after an answer a mark with words.
 * A tried option is struck through; `note` (why it is right or wrong) sits beneath it.
 */
export function OptionButton({
  letter,
  text,
  state,
  disabled,
  onPress,
  markLabel,
  note,
}: {
  letter: string;
  text: string;
  state: OptionState;
  disabled?: boolean;
  onPress?: () => void;
  /** read after the option: "right answer", "your answer", "tried" */
  markLabel?: string | undefined;
  note?: ReactNode;
}) {
  return (
    <div className={styles.option} data-state={state}>
      <button
        type="button"
        className={styles.optionButton}
        data-option={letter}
        aria-pressed={state === "selected"}
        disabled={disabled}
        onClick={onPress}
      >
        <span className={styles.optionKey} aria-hidden="true">
          {letter}
        </span>
        <span className="visually-hidden">{letter}.</span>{" "}
        <span className={styles.optionText}>
          <MathText text={text} />
        </span>
        {state === "right" || state === "wrong" || state === "tried" ? (
          <span className={styles.optionMark}>
            {state === "right" ? <CheckIcon size="1.1rem" /> : <CloseIcon size="1.1rem" />}
            {markLabel ? <span className={styles.optionMarkText}>{markLabel}</span> : null}
          </span>
        ) : null}
      </button>
      {note ? <p className={styles.optionNote}>{note}</p> : null}
    </div>
  );
}
