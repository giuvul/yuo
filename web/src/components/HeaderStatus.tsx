import { Plural, Trans } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { hasActiveJob, useJobs } from "../api/hooks";
import { useDueTotal } from "../review/api";
import { GrowingSprout } from "./Grove";
import styles from "./HeaderStatus.module.css";

/**
 * "Reviews" in the main navigation, with "N due": the objectives and cards due across the learner's paths, within
 * today's limit (the hubs are cached and shared with the review pages).
 */
export function ReviewsBadge({
  className,
  icon,
  iconClassName,
}: {
  className?: string;
  icon?: ReactNode;
  iconClassName?: string;
}) {
  const n = useDueTotal();
  return (
    <Link to="/review" className={className ?? styles.link}>
      {icon ? (
        <span className={iconClassName} aria-hidden="true">
          {icon}
        </span>
      ) : null}
      <Trans id="nav.reviews">Reviews</Trans>
      {n > 0 ? (
        <span className={styles.badge}>
          <Plural id="nav.reviews.due" value={n} one="# due" other="# due" />
        </span>
      ) : null}
    </Link>
  );
}

/** Jobs: a growing sprout while something is being generated or graded, a mark when one failed. */
export function JobsIndicator() {
  const jobs = useJobs();
  const active = hasActiveJob(jobs.data);
  const failed = jobs.data?.some((j) => j.status === "failed") ?? false;
  return (
    <Link to="/jobs" className={styles.status} data-active={active || undefined} data-failed={(failed && !active) || undefined}>
      {active ? <GrowingSprout /> : null}
      <span className={styles.statusText}>
        {active ? <Trans id="nav.jobs.active">Generating…</Trans> : <Trans id="nav.jobs">Jobs</Trans>}
      </span>
      {failed && !active ? <span className={`${styles.badge} ${styles.badgeError}`}>!</span> : null}
    </Link>
  );
}
