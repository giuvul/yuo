// A skill's node on the path graph (Yuo Brand Identity, 8.3 "Node states"): a filled Forest circle with a check when
// mastered, a Pollen circle for the one to learn now, an outlined Moss circle when open, an outlined circle with a
// lock when locked; a mastered skill that needs review keeps its check and gets a Clay ring and mark. Small marks
// say that a lesson is being written or could not be written. Decorative: the text beside a node names it.
import type { ReactNode } from "react";
import type { SkillProgress } from "../api/client";
import { GrowingSprout } from "../components/Grove";
import { AlertIcon, CheckIcon, LockIcon, RepeatIcon } from "../components/icons";
import type { NodeState, Skill } from "./graph";
import { WRITING } from "./LessonRow";
import styles from "./TreeNode.module.css";

/** How a node looks: the four states of the brand's node set, plus a mastered skill that needs review. */
export type NodeKind = NodeState | "review";
export type Badge = "writing" | "failed" | null;

export function nodeKind(node: NodeState | undefined, progress: SkillProgress | undefined): NodeKind {
  return progress?.state === "needs_review" ? "review" : (node ?? "open");
}

export function lessonBadge(skill: Skill): Badge {
  if (skill.lessons.some((l) => WRITING.has(l.state))) return "writing";
  return skill.lessons.some((l) => l.state === "failed") ? "failed" : null;
}

/** The round node itself (decorative: the button or the text beside it says what it is). */
export function NodeDisc({
  kind,
  current,
  mastery,
  badge,
  small,
}: {
  kind: NodeKind;
  current?: boolean;
  /** 0..1, drawn as an arc on a node that is open */
  mastery?: number;
  badge?: Badge;
  /** a small still copy for a row of text: the legend, a link to another skill */
  small?: boolean;
}) {
  const share = Math.round(Math.min(1, Math.max(0, mastery ?? 0)) * 100);
  return (
    <span
      className={styles.disc}
      data-kind={kind}
      data-current={current || undefined}
      data-small={small || undefined}
      aria-hidden="true"
    >
      {kind === "open" && share > 0 ? (
        <svg className={styles.arc} viewBox="0 0 44 44" focusable="false">
          <circle cx="22" cy="22" r="19" pathLength={100} strokeDasharray={`${share} 100`} transform="rotate(-90 22 22)" />
        </svg>
      ) : null}
      {kind === "done" || kind === "review" ? <CheckIcon size="1.15em" /> : null}
      {kind === "current" ? <span className={styles.dot} /> : null}
      {kind === "locked" ? <LockIcon size="0.95em" /> : null}
      {kind === "review" ? (
        <span className={styles.mark} data-mark="review">
          <RepeatIcon size="1em" />
        </span>
      ) : null}
      {badge === "writing" ? (
        <span className={styles.mark} data-mark="writing">
          <GrowingSprout />
        </span>
      ) : null}
      {badge === "failed" ? (
        <span className={styles.mark} data-mark="failed">
          <AlertIcon size="1.1em" />
        </span>
      ) : null}
    </span>
  );
}

/** What the legend and the design catalogue show: a node that is not a button, with its name under it. */
export function NodeSample({
  kind,
  current,
  mastery,
  badge,
  small,
  children,
}: {
  kind: NodeKind;
  current?: boolean;
  mastery?: number;
  badge?: Badge;
  small?: boolean;
  children: ReactNode;
}) {
  return (
    <span className={styles.sample}>
      <NodeDisc kind={kind} current={current} mastery={mastery} badge={badge} small={small} />
      <span>{children}</span>
    </span>
  );
}
