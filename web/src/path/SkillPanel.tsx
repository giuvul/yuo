// The panel of the skill selected on the path graph: what it is, how far the learner is, its lessons, what it
// builds on and what it unlocks. A column beside the graph, or a bottom sheet on a narrow screen.
import { Trans, useLingui } from "@lingui/react/macro";
import type { ReactNode, RefObject } from "react";
import { Button as AriaButton } from "react-aria-components";
import type { JobRef, PathOut, ProgressOut } from "../api/client";
import { ArrowRightIcon, CloseIcon } from "../components/icons";
import { SkillStateLabel } from "../components/labels";
import { MasteryBar } from "../components/MasteryBar";
import { Badge, ButtonLink } from "../components/ui";
import { skillTestOffered, unlockedBy, type NodeState, type Skill } from "./graph";
import { LessonRow } from "./LessonRow";
import { NodeDisc, nodeKind, type NodeKind } from "./TreeNode";
import styles from "./SkillPanel.module.css";

type Props = {
  id: string;
  /** a column beside the graph, or a sheet over the bottom of the screen */
  mode: "side" | "sheet";
  titleRef: RefObject<HTMLHeadingElement | null>;
  pathId: string;
  skill: Skill;
  skills: Map<string, Skill>;
  path: PathOut;
  progress: ProgressOut | undefined;
  nodes: Map<string, NodeState>;
  latest: Map<string, JobRef> | undefined;
  onSelect: (skillId: string) => void;
  onClose: () => void;
  renderExtra: ((skillId: string) => ReactNode) | undefined;
};

export function SkillPanel(props: Props) {
  const { id, mode, onClose } = props;
  return (
    <aside
      id={id}
      className={styles.panel}
      data-mode={mode}
      aria-labelledby={`${id}-title`}
      onKeyDown={(e) => {
        if (e.key === "Escape" && !e.defaultPrevented) {
          e.preventDefault();
          onClose();
        }
      }}
    >
      <Selected {...props} />
    </aside>
  );
}

function Selected(props: Props) {
  const { id, titleRef, pathId, skill, skills, path, progress, nodes, latest, onSelect, onClose, renderExtra } = props;
  const { t } = useLingui();
  const sp = progress?.skills[skill.id];
  const state = sp?.state;
  const testable = skillTestOffered(sp);
  const title = skill.title;
  const requires = skill.requires.map((r) => skills.get(r)).filter((s): s is Skill => s !== undefined);
  const unlocks = unlockedBy(path, skill.id);
  const names = requires.map((s) => s.title).join(", ");
  const next = state !== "mastered" && state !== "locked" ? (skill.lessons.find((l) => l.state === "ready") ?? null) : null;
  const lesson = next?.title ?? t({ id: "path.lesson.untitled", message: "Untitled lesson" });
  const node = nodes.get(skill.id);
  const linkKind = (s: Skill) => nodeKind(nodes.get(s.id), progress?.skills[s.id]);

  return (
    <>
      <header className={styles.panelHeader}>
        <h2 id={`${id}-title`} ref={titleRef} tabIndex={-1} className={styles.panelTitle}>
          {title}
        </h2>
        <AriaButton
          className={styles.panelClose}
          onPress={onClose}
          aria-label={t({ id: "path.panel.close.label", message: "Close this skill" })}
        >
          <CloseIcon />
        </AriaButton>
      </header>

      <div className={styles.panelStates}>
        {node === "current" ? (
          <Badge tone="highlight">
            <Trans id="path.skill.current">Learning now</Trans>
          </Badge>
        ) : null}
        {state ? (
          <span className={styles.panelState} data-state={state}>
            <SkillStateLabel value={state} />
          </span>
        ) : null}
      </div>
      {sp && state !== "locked" ? (
        <MasteryBar
          value={sp.mastery}
          done={state === "mastered"}
          label={t({ id: "path.skill.mastery", message: `Mastery of ${title}` })}
        />
      ) : null}
      {skill.summary ? <p className={styles.panelNote}>{skill.summary}</p> : null}
      {skill.objectives && skill.objectives.length > 0 ? (
        <section className={styles.panelSection} aria-labelledby={`${id}-objectives`}>
          <h3 id={`${id}-objectives`} className={styles.panelHeading}>
            <Trans id="path.panel.objectives">You will learn to</Trans>
          </h3>
          <ul className={styles.panelObjectives}>
            {skill.objectives.map((o) => (
              <li key={o.id}>{o.statement}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {state === "locked" && requires.length > 0 ? (
        <p className={styles.panelNote}>
          <Trans id="path.skill.locked">Unlocks after: {names}</Trans>
        </p>
      ) : null}

      {next || testable ? (
        <div className={styles.panelActions}>
          {next ? (
            <ButtonLink
              to="/lessons/$lessonId"
              params={{ lessonId: next.id }}
              small
              aria-label={t({ id: "path.next.continue.label", message: `Continue with “${lesson}”` })}
            >
              <Trans id="path.panel.continue">Continue lesson</Trans>
              <ArrowRightIcon size="1.1em" />
            </ButtonLink>
          ) : null}
          {testable ? (
            <ButtonLink
              to="/paths/$pathId/skills/$skillId/test"
              params={{ pathId, skillId: skill.id }}
              variant="secondary"
              small
              aria-label={t({ id: "path.skill.test.label", message: `Take the skill test: ${title}` })}
            >
              <Trans id="path.skill.test">Take the skill test</Trans>
            </ButtonLink>
          ) : null}
        </div>
      ) : null}

      {skill.lessons.length > 0 ? (
        <section className={styles.panelSection} aria-labelledby={`${id}-lessons`}>
          <h3 id={`${id}-lessons`} className={styles.panelHeading}>
            <Trans id="path.panel.lessons">Lessons</Trans>
          </h3>
          <ul className={styles.panelLessons}>
            {skill.lessons.map((l) => (
              <LessonRow key={l.id} lesson={l} pathId={pathId} job={latest?.get(`lesson:${l.id}`)} />
            ))}
          </ul>
        </section>
      ) : null}

      {requires.length > 0 ? (
        <section className={styles.panelSection} aria-labelledby={`${id}-requires`}>
          <h3 id={`${id}-requires`} className={styles.panelHeading}>
            <Trans id="path.panel.builds-on">Builds on</Trans>
          </h3>
          <ul className={styles.panelLinks}>
            {requires.map((s) => (
              <li key={s.id}>
                <LinkedSkill skill={s} kind={linkKind(s)} onSelect={onSelect} />
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {unlocks.length > 0 ? (
        <section className={styles.panelSection} aria-labelledby={`${id}-unlocks`}>
          <h3 id={`${id}-unlocks`} className={styles.panelHeading}>
            <Trans id="path.panel.unlocks">Unlocks</Trans>
          </h3>
          <ul className={styles.panelLinks}>
            {unlocks.map((s) => (
              <li key={s.id}>
                <LinkedSkill skill={s} kind={linkKind(s)} onSelect={onSelect} />
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {renderExtra ? renderExtra(skill.id) : null}
    </>
  );
}

/** Another skill, as a button that selects its node on the graph. */
function LinkedSkill({ skill, kind, onSelect }: { skill: Skill; kind: NodeKind; onSelect: (id: string) => void }) {
  const { t } = useLingui();
  const title = skill.title;
  return (
    <AriaButton
      className={styles.linked}
      onPress={() => onSelect(skill.id)}
      aria-label={t({ id: "path.panel.show.label", message: `Show on the tree: ${title}` })}
    >
      <NodeDisc kind={kind} small />
      <span>{title}</span>
    </AriaButton>
  );
}
