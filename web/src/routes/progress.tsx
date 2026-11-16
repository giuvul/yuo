// Progress for one path. `gamification` decides what is shown: off = skill progress only;
// minimal = plus branch levels (tree progress); full = plus XP, streak and achievements.
import { Plural, Trans, useLingui } from "@lingui/react/macro";
import { createRoute } from "@tanstack/react-router";
import { useErasePathData, usePath, useProgress } from "../api/hooks";
import { ConfirmAction } from "../components/ConfirmAction";
import { ErrorNotice } from "../components/ErrorNotice";
import { SkillStateLabel } from "../components/labels";
import { CountUp } from "../components/Grove";
import { MasteryBar } from "../components/MasteryBar";
import { BoltIcon, FlameIcon, LeafIcon, LockIcon, SproutIcon, TrophyIcon } from "../components/icons";
import { Badge, BackLink, PageHeader, ui } from "../components/ui";
import { rootRoute } from "./root";
import styles from "./progress.module.css";
import { useTutorRefs } from "../tutor/context";

export const progressRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/paths/$pathId/progress",
  component: ProgressPage,
});

/** Achievement keys are codes; show them as words until the backend sends titles. */
function achievementName(key: string): string {
  const s = key.replace(/[._-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function ProgressPage() {
  const { t, i18n } = useLingui();
  const { pathId } = progressRoute.useParams();
  useTutorRefs({ screen: "progress", path_id: pathId });
  const path = usePath(pathId);
  const progress = useProgress(pathId);

  if (progress.isPending || path.isPending) {
    return (
      <p className={ui.muted}>
        <Trans id="common.loading">Loading…</Trans>
      </p>
    );
  }
  if (progress.isError) return <ErrorNotice error={progress.error} />;
  if (path.isError) return <ErrorNotice error={path.error} />;

  const p = progress.data;
  const skills = path.data.branches.flatMap((b) => b.skills);
  const mastered = skills.filter((s) => p.skills[s.id]?.state === "mastered").length;
  const total = skills.length;
  const showLevels = p.gamification !== "off" && (p.branches?.length ?? 0) > 0;
  const full = p.gamification === "full";
  const xp = p.xp_total ?? 0;
  const streak = p.streak ?? 0;

  return (
    <section className={styles.page}>
      <PageHeader
        back={
          <BackLink to="/paths/$pathId" params={{ pathId }}>
            {path.data.title}
          </BackLink>
        }
        title={<Trans id="progress.title">Progress</Trans>}
      />

      {full ? (
        <div className={styles.stats}>
          <div className={`${ui.card} ${styles.stat}`}>
            <span className={styles.statIcon} aria-hidden="true">
              <BoltIcon />
            </span>
            <div>
              <p className={styles.statValue}>
                <CountUp value={xp} formatted={i18n.number(xp)} />
              </p>
              <p className={styles.statLabel}>
                <Trans id="progress.xp">XP in total</Trans>
              </p>
            </div>
          </div>
          <div className={`${ui.card} ${styles.stat}`}>
            <span className={styles.statIcon} data-tone="streak" aria-hidden="true">
              <FlameIcon />
            </span>
            <div>
              <p className={styles.statValue}>
                <CountUp value={streak} formatted={i18n.number(streak)} />
              </p>
              <p className={styles.statLabel}>
                <Plural id="progress.streak" value={streak} one="day in a row" other="days in a row" />
              </p>
            </div>
          </div>
        </div>
      ) : null}

      <section className={`${ui.card} ${styles.section}`} aria-labelledby="progress-skills">
        <h2 id="progress-skills" className={styles.heading}>
          <Trans id="progress.skills">
            Skills mastered: {mastered} of {total}
          </Trans>
        </h2>
        <ul className={styles.list}>
          {skills.map((s) => {
            const sp = p.skills[s.id];
            const title = s.title;
            const state = sp?.state;
            return (
              <li key={s.id} className={styles.skillRow} data-state={state}>
                <span className={styles.skillIcon} aria-hidden="true">
                  {state === "mastered" ? <LeafIcon /> : state === "locked" || !sp ? <LockIcon /> : <SproutIcon />}
                </span>
                <span className={styles.skillName}>
                  <span className={styles.skillTitle}>{title}</span>
                  {sp ? (
                    <span className={styles.skillState}>
                      <SkillStateLabel value={sp.state} />
                    </span>
                  ) : null}
                </span>
                {sp ? (
                  <span className={styles.skillBar}>
                    <MasteryBar
                      value={sp.mastery}
                      done={state === "mastered"}
                      label={t({ id: "path.skill.mastery", message: `Mastery of ${title}` })}
                    />
                  </span>
                ) : null}
              </li>
            );
          })}
        </ul>
      </section>

      {showLevels ? (
        <section className={`${ui.card} ${styles.section}`} aria-labelledby="progress-branches">
          <h2 id="progress-branches" className={styles.heading}>
            <Trans id="progress.branches">Branches</Trans>
          </h2>
          <ul className={styles.list}>
            {(p.branches ?? []).map((b) => {
              const level = b.level;
              const bxp = b.xp;
              return (
                <li key={b.id} className={styles.row}>
                  <span className={styles.skillTitle}>{b.title}</span>
                  <span className={styles.rowEnd}>
                    <Badge tone={level > 1 ? "highlight" : undefined}>
                      <Trans id="path.branch.level">Level {level}</Trans>
                    </Badge>
                    {full ? (
                      <span className={styles.xp}>
                        <Trans id="progress.branch.xp">{bxp} XP</Trans>
                      </span>
                    ) : null}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {full ? (
        <section className={`${ui.card} ${styles.section}`} aria-labelledby="progress-achievements">
          <h2 id="progress-achievements" className={styles.heading}>
            <Trans id="progress.achievements">Achievements</Trans>
          </h2>
          {(p.achievements ?? []).length === 0 ? (
            <p className={ui.muted}>
              <Trans id="progress.achievements.none">None yet. Keep going.</Trans>
            </p>
          ) : (
            <ul className={styles.list}>
              {(p.achievements ?? []).map((a) => (
                <li key={a.key} className={styles.row}>
                  <span className={styles.achievement}>
                    <span className={styles.achievementIcon} aria-hidden="true">
                      <TrophyIcon />
                    </span>
                    {achievementName(a.key)}
                  </span>
                  <span className={styles.date}>{i18n.date(new Date(a.unlocked_at), { dateStyle: "medium" })}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}

      <ErasePathData pathId={pathId} />
    </section>
  );
}

/** The learner's data in this path, erased for good; the path and its shared lessons stay. */
function ErasePathData({ pathId }: { pathId: string }) {
  const erase = useErasePathData();
  return (
    <section className={`${ui.card} ${styles.section}`} aria-labelledby="progress-erase">
      <h2 id="progress-erase" className={styles.heading}>
        <Trans id="progress.erase.title">Your data in this path</Trans>
      </h2>
      {erase.isSuccess ? (
        <p role="status">
          <Trans id="progress.erase.done">Deleted. The path starts again from the beginning.</Trans>
        </p>
      ) : (
        <>
          <p className={ui.muted}>
            <Trans id="progress.erase.description">
              Start this path over: your progress, answers, reviews, notes, tutor conversations and lesson requests
              here are deleted for good. The path and its lessons stay; lessons written from your own material are
              written again when you need them.
            </Trans>
          </p>
          <ConfirmAction
            label={<Trans id="progress.erase.button">Delete my data in this path</Trans>}
            question={
              <Trans id="progress.erase.question">
                Delete your progress and everything you wrote in this path? This cannot be undone.
              </Trans>
            }
            confirmLabel={<Trans id="progress.erase.confirm">Delete my data</Trans>}
            pending={erase.isPending}
            onConfirm={() => erase.mutate(pathId)}
          />
        </>
      )}
      {erase.isError ? <ErrorNotice error={erase.error} /> : null}
    </section>
  );
}
