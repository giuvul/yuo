import { Trans, useLingui } from "@lingui/react/macro";
import { useQueryClient } from "@tanstack/react-query";
import { createRoute, Link } from "@tanstack/react-router";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { ToggleButton, ToggleButtonGroup } from "react-aria-components";
import type { JobRef, PathOut, ProgressOut, SkillProgress } from "../api/client";
import { ACTIVE_JOB_STATUSES, hasActiveJobs, keys, useNext, usePath, useProgress } from "../api/hooks";
import { ErrorNotice } from "../components/ErrorNotice";
import { JobProgressLine } from "../components/JobProgress";
import { DifficultyLabel, JobKindLabel, JobStatusLabel, PathStatusLabel, SkillStateLabel } from "../components/labels";
import { ArrowRightIcon, CheckIcon, LeafIcon, LockIcon, ProgressIcon, SproutIcon } from "../components/icons";
import { LeafWatermark } from "../components/Grove";
import { MasteryBar } from "../components/MasteryBar";
import { Badge, ButtonLink, Notice, Progress, Stepper, ui, Waiting } from "../components/ui";
import { skillNodes, skillTestOffered, type NodeState, type Skill } from "../path/graph";
import { useGrowsOnce } from "../path/grown";
import { FailedJob, LessonRow, WRITING } from "../path/LessonRow";
import { LazyPathGraph } from "../path/LazyPathGraph";
import { readPathView, writePathView, type PathViewMode } from "../path/viewPref";
import { LevelCheck } from "./levelCheck";
import { NEXT_OPEN, NextOffer } from "../path/NextOffer";
import { LessonRequests } from "./requests";
import { rootRoute } from "./root";
import styles from "./pathView.module.css";
import { useTutorRefs } from "../tutor/context";
import { PathProposals } from "../tutor/Proposals";
import { ShareButton } from "../sharing/ExportDialog";
import { useReviewHub, type ReviewHub } from "../review/api";
import { ReviewEntry, SkillReview } from "../review/Hub";

export const pathViewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/paths/$pathId",
  component: PathPage,
});


/** What Yuo is working on for this path, as one calm line with the jobs underneath. */
function ActiveJobs({ jobs }: { jobs: JobRef[] }) {
  const active = jobs.filter((j) => ACTIVE_JOB_STATUSES.has(j.status));
  if (!active.length) return null;
  return (
    <div className={`${ui.panel} ${styles.working}`}>
      <Waiting>
        <Trans id="path.working">Yuo is working on this path. This page updates by itself.</Trans>
      </Waiting>
      <ul className={styles.jobList}>
        {active.map((j) => (
          <li key={j.id}>
            <span className={styles.jobName}>
              <JobKindLabel value={j.kind} />
              {j.title ? `: ${j.title}` : null}
            </span>{" "}
            {j.status === "running" && j.step ? (
              <JobProgressLine job={j} />
            ) : (
              <>
                <JobStatusLabel value={j.status} />
                <JobProgressLine job={j} className={styles.jobTime} />
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** While the tree is planned (after the level check): where the path is, as three steps. */
function Growing({ checked }: { checked: boolean }) {
  const { t } = useLingui();
  return (
    <section className={`${ui.card} ${styles.growing}`} aria-labelledby="growing-title">
      <LeafWatermark />
      <span className={styles.growingMark} aria-hidden="true">
        <LeafIcon size="2rem" />
      </span>
      <div className={ui.stack}>
        <h2 id="growing-title" className={styles.sectionTitle}>
          <Trans id="path.growing.title">Your path is growing</Trans>
        </h2>
        <Stepper
          vertical
          label={t({ id: "path.growing.steps", message: "Steps" })}
          doneLabel={t({ id: "path.growing.done", message: "(done)" })}
          steps={[
            {
              id: "check",
              state: "done",
              label: checked ? (
                <Trans id="path.growing.checked">Your answers are in</Trans>
              ) : (
                <Trans id="path.growing.start">Starting from the basics</Trans>
              ),
            },
            { id: "plan", state: "current", label: <Trans id="path.growing.plan">Planning the skills and lessons</Trans> },
            { id: "write", state: "todo", label: <Trans id="path.growing.write">Writing your first lessons</Trans> },
          ]}
        />
        <Waiting>
          <Trans id="path.growing.wait">This page updates by itself when the first lessons are ready.</Trans>
        </Waiting>
      </div>
    </section>
  );
}

function SkillHeader({
  pathId,
  skillId,
  title,
  progress,
  prerequisites,
  current,
  hub,
}: {
  pathId: string;
  skillId: string;
  title: string;
  progress: SkillProgress | undefined;
  prerequisites: string[];
  current: boolean;
  hub: ReviewHub | undefined;
}) {
  const { t } = useLingui();
  const state = progress?.state;
  const names = prerequisites.join(", ");
  return (
    <div className={styles.skillHeader}>
      <div className={styles.skillHeading}>
        <h3 className={styles.skillTitle}>{title}</h3>
        {current ? (
          <Badge tone="highlight">
            <Trans id="path.skill.current">Learning now</Trans>
          </Badge>
        ) : null}
        {state ? (
          <span className={styles.skillState} data-state={state}>
            <SkillStateLabel value={state} />
          </span>
        ) : null}
      </div>
      {progress && state !== "locked" ? (
        <MasteryBar value={progress.mastery} label={t({ id: "path.skill.mastery", message: `Mastery of ${title}` })} />
      ) : null}
      {state === "locked" && prerequisites.length > 0 ? (
        <p className={styles.unlocks}>
          <Trans id="path.skill.locked">Unlocks after: {names}</Trans>
        </p>
      ) : null}
      <SkillReview pathId={pathId} hub={hub} skillId={skillId} />
    </div>
  );
}

/** Below a started skill's lessons: the test that checks the whole skill, and what passing it does. */
function SkillTest({ pathId, skillId, title }: { pathId: string; skillId: string; title: string }) {
  const { t } = useLingui();
  return (
    <div className={styles.skillTest}>
      <p className={styles.skillTestText}>
        <Trans id="path.skill.test.about">
          When you feel ready: a short test without hints. Pass it and the skill counts as mastered.
        </Trans>
      </p>
      <ButtonLink
        to="/paths/$pathId/skills/$skillId/test"
        params={{ pathId, skillId }}
        variant="secondary"
        small
        aria-label={t({ id: "path.skill.test.label", message: `Take the skill test: ${title}` })}
      >
        <Trans id="path.skill.test">Take the skill test</Trans>
      </ButtonLink>
    </div>
  );
}

const BUD_ICONS: Record<NodeState, ReactNode> = {
  done: <CheckIcon size="1.1rem" />,
  current: <span className={styles.budDot} />,
  open: null,
  locked: <LockIcon size="0.95rem" />,
};

/** The stem from this bud to the next one: an S-curve that leans left or right, with a leaf where it bulges. */
function Stem({ side, grown }: { side: "left" | "right"; grown: boolean }) {
  const d = side === "right" ? "M20 0 C36 30, 36 70, 20 100" : "M20 0 C4 30, 4 70, 20 100";
  return (
    <>
      <svg className={styles.stem} data-grown={grown || undefined} viewBox="0 0 40 100" preserveAspectRatio="none">
        <path d={d} vectorEffect="non-scaling-stroke" />
      </svg>
      <svg className={styles.leaf} data-side={side} data-grown={grown || undefined} viewBox="0 0 24 24">
        <path d="M2 14C4 5 13 1.5 22.5 3.5 21.5 13 12 17.5 2 14z" />
        <path className={styles.leafVein} d="M3.5 13.5C9 11 15 7.5 20 5" />
      </svg>
    </>
  );
}

/** The list view: one vine per branch, every skill with its lessons. */
function Vine({
  path,
  latest,
  progress,
  nodes,
  hub,
}: {
  path: PathOut;
  latest: Map<string, JobRef>;
  progress: ProgressOut | undefined;
  nodes: Map<string, NodeState>;
  hub: ReviewHub | undefined;
}) {
  const fresh = useGrowsOnce(path.id, path.branches.length > 0);
  if (path.branches.length === 0) {
    return hasActiveJobs(path) ? null : (
      <p className={ui.muted}>
        <Trans id="path.no-branches">This path has no lessons yet.</Trans>
      </p>
    );
  }
  const titles = new Map(path.branches.flatMap((b) => b.skills).map((s) => [s.id, s.title]));
  const levels = new Map((progress?.branches ?? []).map((b) => [b.id, b.level]));
  let n = 0;
  return (
    <div className={styles.tree} data-fresh={fresh || undefined}>
      {path.branches.map((branch) => {
        const level = levels.get(branch.id);
        return (
          <section key={branch.id} className={styles.branch} aria-labelledby={`branch-${branch.id}`}>
            <h2 id={`branch-${branch.id}`} className={styles.branchTitle}>
              {branch.title}
              {level !== undefined ? (
                <span className={styles.level}>
                  <Trans id="path.branch.level">Level {level}</Trans>
                </span>
              ) : null}
            </h2>
            <ol className={styles.vine}>
              {branch.skills.map((skill, i) => {
                const sp = progress?.skills[skill.id];
                const node = nodes.get(skill.id) ?? "open";
                const last = i === branch.skills.length - 1;
                const order = n++;
                const side = order % 2 === 0 ? "right" : "left";
                return (
                  <li
                    key={skill.id}
                    className={styles.node}
                    data-node={node}
                    style={{ "--yuo-order": Math.min(order, 12) } as CSSProperties}
                  >
                    <div className={styles.stemCell} aria-hidden="true">
                      {last ? null : <Stem side={side} grown={node === "done"} />}
                      <span className={styles.bud}>{BUD_ICONS[node]}</span>
                    </div>
                    <div className={styles.skill}>
                      <SkillHeader
                        pathId={path.id}
                        skillId={skill.id}
                        title={skill.title}
                        progress={sp}
                        prerequisites={skill.requires.map((id) => titles.get(id) ?? id)}
                        current={node === "current"}
                        hub={hub}
                      />
                      {skill.summary ? <p className={styles.summary}>{skill.summary}</p> : null}
                      {skill.lessons.length > 0 ? (
                        <ul className={styles.lessons}>
                          {skill.lessons.map((lesson) => (
                            <LessonRow
                              key={lesson.id}
                              lesson={lesson}
                              pathId={path.id}
                              job={latest.get(`lesson:${lesson.id}`)}
                            />
                          ))}
                        </ul>
                      ) : null}
                      {skillTestOffered(sp) ? <SkillTest pathId={path.id} skillId={skill.id} title={skill.title} /> : null}
                    </div>
                  </li>
                );
              })}
            </ol>
          </section>
        );
      })}
    </div>
  );
}

/** Where the learner is: skills mastered, and the next ready lesson of the current skill with "Continue". */
function Overview({ path, progress, current }: { path: PathOut; progress: ProgressOut | undefined; current: Skill | null }) {
  const { t } = useLingui();
  const skills = path.branches.flatMap((b) => b.skills);
  const total = skills.length;
  const mastered = skills.filter((s) => progress?.skills[s.id]?.state === "mastered").length;
  const next = current?.lessons.find((l) => l.state === "ready") ?? null;
  const writing = current?.lessons.some((l) => WRITING.has(l.state)) ?? false;
  const skill = current?.title ?? "";
  const lesson = next?.title ?? t({ id: "path.lesson.untitled", message: "Untitled lesson" });
  const allDone = total > 0 && mastered === total;
  // "What next?" from 75% of the path's lessons done, or once a checkpoint is open; the offer card below
  // carries it when it invites
  const nextState = useNext(path.id).data;
  const whatNext = !!nextState?.available && !nextState.offer && !NEXT_OPEN.has(nextState.status);

  return (
    <section className={`${ui.card} ${styles.overview}`} aria-labelledby="overview-title">
      <div className={styles.overviewMain}>
        <p id="overview-title" className={ui.eyebrow}>
          {allDone ? <Trans id="path.next.done.eyebrow">Path complete</Trans> : <Trans id="path.next.eyebrow">Up next</Trans>}
        </p>
        {allDone ? (
          <p className={styles.nextTitle}>
            <Trans id="path.next.done">You have mastered every skill in this path.</Trans>
          </p>
        ) : current ? (
          <>
            <p className={styles.nextSkill}>{skill}</p>
            {next ? (
              <p className={styles.nextTitle}>{lesson}</p>
            ) : writing ? (
              <Waiting>
                <Trans id="path.next.writing">The next lesson is being written.</Trans>
              </Waiting>
            ) : (
              <p className={ui.muted}>
                <Trans id="path.next.none">Its lessons are not written yet. Generate one below.</Trans>
              </p>
            )}
          </>
        ) : null}
        {progress ? (
          <div className={styles.overviewProgress}>
            <Progress
              value={mastered}
              max={total}
              showValue={false}
              label={t({ id: "path.overview.progress.label", message: "Skills mastered" })}
            />
            <span className={styles.overviewCount}>
              <Trans id="path.overview.progress">
                {mastered} of {total} skills mastered
              </Trans>
            </span>
          </div>
        ) : null}
        <div className={styles.overviewLinks}>
          <Link to="/paths/$pathId/progress" params={{ pathId: path.id }} className={styles.overviewLink}>
            <ProgressIcon size="1em" />
            <Trans id="path.progress.see">See your progress</Trans>
          </Link>
          {whatNext ? (
            <Link to="/paths/$pathId/next" params={{ pathId: path.id }} className={styles.overviewLink}>
              <SproutIcon size="1em" />
              <Trans id="path.next.link">What next?</Trans>
            </Link>
          ) : null}
        </div>
      </div>
      {next && !allDone ? (
        <ButtonLink
          to="/lessons/$lessonId"
          params={{ lessonId: next.id }}
          aria-label={t({ id: "path.next.continue.label", message: `Continue with “${lesson}”` })}
        >
          <Trans id="path.next.continue">Continue</Trans>
          <ArrowRightIcon size="1.1em" />
        </ButtonLink>
      ) : null}
    </section>
  );
}

/** "Tree / List": the path as a graph of skills, or as the list of skills with their lessons. Remembered per viewer. */
function ViewSwitch({ view, onChange }: { view: PathViewMode; onChange: (view: PathViewMode) => void }) {
  const { t } = useLingui();
  return (
    <div className={styles.viewRow}>
      <h2 className={styles.sectionTitle}>
        <Trans id="path.view.title">Skills</Trans>
      </h2>
      <ToggleButtonGroup
        className={styles.viewSwitch}
        selectionMode="single"
        disallowEmptySelection
        selectedKeys={[view]}
        onSelectionChange={(keys) => {
          const next = [...keys][0];
          if (next === "tree" || next === "list") onChange(next);
        }}
        aria-label={t({ id: "path.view.label", message: "Show the skills as" })}
      >
        <ToggleButton id="tree" className={styles.viewOption}>
          <Trans id="path.view.tree">Tree</Trans>
        </ToggleButton>
        <ToggleButton id="list" className={styles.viewOption}>
          <Trans id="path.view.list">List</Trans>
        </ToggleButton>
      </ToggleButtonGroup>
    </div>
  );
}

/** The latest job per kind and target (jobs arrive in creation order). */
function latestJobs(p: PathOut): Map<string, JobRef> {
  const latest = new Map<string, JobRef>();
  for (const j of p.jobs) latest.set(`${j.kind}:${j.target_id}`, j);
  return latest;
}

/** A fresh path: the tree exists and nothing has been learned or tested yet. */
function offersPlacement(path: PathOut, progress: ProgressOut | undefined): boolean {
  if (path.branches.length === 0 || !progress) return false;
  const skills = Object.values(progress.skills);
  return skills.length > 0 && skills.every((s) => s.evidence === 0 && s.state !== "mastered");
}

function PathPage() {
  const { pathId } = pathViewRoute.useParams();
  useTutorRefs({ screen: "tree", path_id: pathId });
  const qc = useQueryClient();
  const path = usePath(pathId);
  const progress = useProgress(pathId);
  // the review hub feeds the Review card and each studied skill's "Review this skill"
  const hub = useReviewHub(pathId, (path.data?.branches.length ?? 0) > 0);

  const [view, setView] = useState<PathViewMode>(readPathView);
  const chooseView = (v: PathViewMode) => {
    setView(v);
    writePathView(v);
  };

  // when generation settles (e.g. a remedial or requested lesson got written), refresh progress
  const active = hasActiveJobs(path.data);
  const wasActive = useRef(active);
  useEffect(() => {
    if (wasActive.current && !active) void qc.invalidateQueries({ queryKey: keys.progress(pathId) });
    wasActive.current = active;
  }, [active, pathId, qc]);

  if (path.isPending) {
    return (
      <Waiting>
        <Trans id="common.loading">Loading…</Trans>
      </Waiting>
    );
  }
  if (path.isError) return <ErrorNotice error={path.error} />;

  const p = path.data;
  const latest = latestJobs(p);
  const treeJob = latest.get(`tree:${p.id}`);
  const failedTreeJob = treeJob?.status === "failed" && p.branches.length === 0 ? treeJob : undefined;
  const waitsForLevelCheck = p.level_check === "preparing" || p.level_check === "ready";
  const planning = !waitsForLevelCheck && p.branches.length === 0 && hasActiveJobs(p);
  const { nodes, current } = skillNodes(p, progress.data);
  const meta = p.subject && p.subject !== p.title ? p.subject : null;
  return (
    <section className={ui.stack}>
      <div className={styles.titleRow}>
        <div className={styles.titleBlock}>
          <h1 className={ui.pageTitle}>{p.title}</h1>
          <p className={styles.meta}>
            {meta ? <>{meta} · </> : null}
            <DifficultyLabel value={p.difficulty} /> · <PathStatusLabel value={p.status} />
          </p>
          {p.goal ? <p className={styles.goal}>{p.goal}</p> : null}
        </div>
        {p.branches.length > 0 ? (
          <div className={styles.titleActions}>
            <ShareButton pathId={pathId} />
          </div>
        ) : null}
      </div>
      {waitsForLevelCheck ? <LevelCheck pathId={pathId} /> : null}
      {planning ? <Growing checked={p.level_check === "done"} /> : null}
      {!waitsForLevelCheck && !planning ? (
        <ActiveJobs jobs={p.branches.length > 0 ? p.jobs.filter((j) => j.kind !== "tree") : p.jobs} />
      ) : null}
      {failedTreeJob && !waitsForLevelCheck ? <FailedJob job={failedTreeJob} /> : null}
      {p.branches.length > 0 ? <Overview path={p} progress={progress.data} current={current} /> : null}
      {p.branches.length > 0 ? <NextOffer pathId={pathId} /> : null}
      {p.level_check === "none" && offersPlacement(p, progress.data) ? (
        <Notice role="status">
          <div className={ui.row}>
            <span>
              <Trans id="path.placement.offer">I already know some of this:</Trans>
            </span>
            <ButtonLink to="/paths/$pathId/placement" params={{ pathId }} small>
              <Trans id="path.placement.start">Take a placement test</Trans>
            </ButtonLink>
          </div>
        </Notice>
      ) : null}
      {p.branches.length > 0 ? <ReviewEntry pathId={pathId} hub={hub.data} /> : null}
      {p.branches.length > 0 ? <ViewSwitch view={view} onChange={chooseView} /> : null}
      {waitsForLevelCheck && p.branches.length === 0 ? null : view === "tree" && p.branches.length > 0 ? (
        <LazyPathGraph
          path={p}
          progress={progress.data}
          latest={latest}
          renderExtra={(skillId) => <SkillReview pathId={pathId} hub={hub.data} skillId={skillId} />}
        />
      ) : (
        <Vine path={p} latest={latest} progress={progress.data} nodes={nodes} hub={hub.data} />
      )}
      <PathProposals pathId={pathId} />
      {p.branches.length > 0 ? <LessonRequests pathId={pathId} /> : null}
    </section>
  );
}
