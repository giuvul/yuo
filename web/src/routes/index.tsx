import { Trans, useLingui } from "@lingui/react/macro";
import { createRoute, Link } from "@tanstack/react-router";
import type { PathSummary } from "../api/client";
import { useLingui as useLinguiRuntime } from "@lingui/react";
import { usePaths, useProgress } from "../api/hooks";
import { ErrorNotice } from "../components/ErrorNotice";
import { ArrowRightIcon, PlusIcon, SproutIcon, UploadIcon } from "../components/icons";
import { LeafWatermark } from "../components/Grove";
import { Seedling } from "../components/illustrations";
import { Badge, ButtonLink, Notice, Progress, ui, Waiting } from "../components/ui";
import { AiReadyWarning } from "../onboarding/AiReady";
import { useOnboarding } from "../onboarding/api";
import { DifficultyLabel, PathStatusLabel } from "../components/labels";
import { rootRoute } from "./root";
import styles from "./index.module.css";
import { useTutorRefs } from "../tutor/context";

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: HomePage,
});

/** Skills mastered of all skills, from the path's progress (nothing while it loads or has no tree yet). */
function PathProgress({ pathId, title }: { pathId: string; title: string }) {
  const { t } = useLingui();
  const progress = useProgress(pathId);
  const skills = Object.values(progress.data?.skills ?? {});
  if (skills.length === 0) return null;
  const mastered = skills.filter((s) => s.state === "mastered").length;
  const total = skills.length;
  return (
    <span className={styles.progress}>
      <Progress
        value={mastered}
        max={total}
        showValue={false}
        label={t({ id: "home.path.progress.label", message: `Skills mastered: ${title}` })}
      />
      <span className={styles.progressText}>
        <Trans id="home.path.progress">
          {mastered} of {total} skills mastered
        </Trans>
      </span>
    </span>
  );
}

function PathCard({ path }: { path: PathSummary }) {
  const { i18n } = useLinguiRuntime();
  const created = i18n.date(new Date(path.created_at), { dateStyle: "medium" });
  return (
    <Link to="/paths/$pathId" params={{ pathId: path.id }} className={styles.pathCard} data-status={path.status}>
      <span className={styles.pathIcon}>
        <SproutIcon size={24} />
      </span>
      <span className={styles.pathBody}>
        <span className={styles.pathTitle}>{path.title}</span>
        <span className={styles.meta}>
          {path.subject && path.subject !== path.title ? <>{path.subject} · </> : null}
          <DifficultyLabel value={path.difficulty} /> · <Trans id="home.path.created">started {created}</Trans>
        </span>
        <PathProgress pathId={path.id} title={path.title} />
      </span>
      <span className={styles.pathSide}>
        <Badge tone={path.status === "active" ? "success" : undefined}>
          <PathStatusLabel value={path.status} />
        </Badge>
        <ArrowRightIcon className={styles.pathArrow} />
      </span>
    </Link>
  );
}

function HomePage() {
  useTutorRefs({ screen: "home" });
  const paths = usePaths();
  const onboarding = useOnboarding();
  const unfinished = onboarding.data !== undefined && !onboarding.data.done && onboarding.data.has_path;
  // the actions sit in the header once there are paths (or the list failed); an empty list has its own
  const headerActions = paths.isError || (paths.data?.length ?? 0) > 0;

  return (
    <section className={ui.stack}>
      <div className={styles.titleRow}>
        <h1 className={ui.pageTitle}>
          <Trans id="home.title">Your paths</Trans>
        </h1>
        {headerActions ? (
          <div className={styles.actions}>
            <ButtonLink to="/import" variant="secondary">
              <UploadIcon size="1.1em" />
              <Trans id="home.import">Import a path</Trans>
            </ButtonLink>
            <ButtonLink to="/paths/new">
              <PlusIcon size="1.1em" />
              <Trans id="home.new-path">New path</Trans>
            </ButtonLink>
          </div>
        ) : null}
      </div>

      {unfinished ? (
        <Notice>
          <Trans id="home.finish-setup">Yuo is not fully set up yet.</Trans>{" "}
          <Link to="/setup">
            <Trans id="home.finish-setup.link">Finish setting up</Trans>
          </Link>
        </Notice>
      ) : null}

      <AiReadyWarning enabled={(paths.data?.length ?? 0) > 0} />

      {paths.isPending ? (
        <Waiting>
          <Trans id="common.loading">Loading…</Trans>
        </Waiting>
      ) : paths.isError ? (
        <ErrorNotice error={paths.error} />
      ) : paths.data.length === 0 ? (
        <div className={`${ui.card} ${styles.empty}`}>
          <LeafWatermark />
          <span className={styles.emptyMark}>
            <Seedling width={72} />
          </span>
          <p className={styles.emptyTitle}>
            <Trans id="home.empty.title">Plant your first path</Trans>
          </p>
          <p className={ui.muted}>
            <Trans id="home.empty">
              No paths yet. Tell Yuo what you want to learn and it plans the lessons for you.
            </Trans>
          </p>
          <div className={styles.emptyActions}>
            <ButtonLink to="/paths/new">
              <PlusIcon size="1.1em" />
              <Trans id="home.new-path">New path</Trans>
            </ButtonLink>
            <ButtonLink to="/import" variant="ghost">
              <UploadIcon size="1.1em" />
              <Trans id="home.import">Import a path</Trans>
            </ButtonLink>
          </div>
        </div>
      ) : (
        <ul className={styles.list}>
          {paths.data.map((p) => (
            <li key={p.id}>
              <PathCard path={p} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
