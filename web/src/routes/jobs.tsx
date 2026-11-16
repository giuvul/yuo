import { Plural, Trans } from "@lingui/react/macro";
import { useLingui } from "@lingui/react";
import { createRoute, Link } from "@tanstack/react-router";
import { ACTIVE_JOB_STATUSES, useJobHistory, useJobs, useRetryJob } from "../api/hooks";
import { Button } from "../components/ui";
import { ErrorNotice } from "../components/ErrorNotice";
import { jobErrorMessage } from "../components/jobError";
import { JobProgressLine } from "../components/JobProgress";
import { JobKindLabel, JobStatusLabel, JobTargetLabel } from "../components/labels";
import { PageHeader, ui } from "../components/ui";
import type { JobDone } from "../api/client";
import { rootRoute } from "./root";
import styles from "./jobs.module.css";
import { useTutorRefs } from "../tutor/context";

/** The failed jobs the list can start again (the others are started again from their own page). */
const RETRYABLE = new Set(["lesson", "rendition"]);

export const jobsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/jobs",
  component: JobsPage,
});

function JobsPage() {
  useTutorRefs({ screen: "jobs" });
  const { i18n } = useLingui();
  const jobs = useJobs();
  const retry = useRetryJob();

  return (
    <section className={ui.stack}>
      <PageHeader
        title={<Trans id="jobs.title">Generation jobs</Trans>}
        meta={
          <p>
            <Trans id="jobs.intro2">What Yuo is working on now, and everything it has done.</Trans>
          </p>
        }
      />
      <h2 className={styles.sectionTitle}>
        <Trans id="jobs.now">Now</Trans>
      </h2>
      {jobs.isPending ? (
        <p className={ui.muted}>
          <Trans id="common.loading">Loading…</Trans>
        </p>
      ) : jobs.isError ? (
        <ErrorNotice error={jobs.error} />
      ) : jobs.data.length === 0 ? (
        <p>
          <Trans id="jobs.none">Nothing is running and nothing failed recently.</Trans>
        </p>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">
                  <Trans id="jobs.col.kind">Job</Trans>
                </th>
                <th scope="col">
                  <Trans id="jobs.col.status">Status</Trans>
                </th>
                <th scope="col">
                  <Trans id="jobs.col.target">For</Trans>
                </th>
                <th scope="col">
                  <Trans id="jobs.col.problem">Problem</Trans>
                </th>
              </tr>
            </thead>
            <tbody>
              {jobs.data.map((j) => (
                <tr key={j.id} data-status={j.status}>
                  <td>
                    <JobKindLabel value={j.kind} />
                  </td>
                  <td>
                    <span className={styles.status} data-status={j.status}>
                      <JobStatusLabel value={j.status} />
                    </span>
                    <JobProgressLine job={j} className={styles.progress} />
                  </td>
                  <td>
                    {j.title && j.lesson_id ? (
                      <Link to="/lessons/$lessonId" params={{ lessonId: j.lesson_id }} className={styles.title}>
                        {j.title}
                      </Link>
                    ) : j.title ? (
                      <span className={styles.title}>{j.title}</span>
                    ) : (
                      <>
                        <JobTargetLabel value={j.target_kind} /> <code className={styles.id}>{j.target_id.slice(-8)}</code>
                      </>
                    )}
                  </td>
                  <td>
                    {j.status === "failed" || (j.error && ACTIVE_JOB_STATUSES.has(j.status)) ? (
                      <>
                        {j.status !== "queued" ? (
                          i18n._(jobErrorMessage(j.error))
                        ) : (
                          <Trans id="jobs.retrying">
                            A step did not work the first time. Yuo tries again by itself; nothing to do for now.
                          </Trans>
                        )}
                        {j.error ? (
                          <details>
                            <summary>
                              <Trans id="jobs.details">Details</Trans>
                            </summary>
                            <code className={styles.raw}>{j.error}</code>
                          </details>
                        ) : null}
                        {j.status === "failed" &&
                        RETRYABLE.has(j.kind) &&
                        // started again already: the new job is in the list
                        !jobs.data.some((o) => o.target_id === j.target_id && ACTIVE_JOB_STATUSES.has(o.status)) ? (
                          <div className={styles.retry}>
                          <Button
                            variant="secondary"
                            small
                            onPress={() => retry.mutate(j.id)}
                            isDisabled={retry.isPending && retry.variables === j.id}
                          >
                            <Trans id="jobs.retry">Try again</Trans>
                          </Button>
                          </div>
                        ) : null}
                      </>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <JobHistory />
    </section>
  );
}

/** Minutes or seconds a finished job took, from its first stage (or its creation) to its end. */
function took(j: JobDone): number | null {
  const start = j.started_at ?? j.created_at;
  if (!j.finished_at || !start) return null;
  const s = (Date.parse(j.finished_at) - Date.parse(start)) / 1000;
  return Number.isFinite(s) && s >= 0 ? s : null;
}

function Took({ seconds }: { seconds: number }) {
  if (seconds < 90) {
    const n = Math.max(1, Math.round(seconds));
    return <Plural id="jobs.took.s" value={n} one="took # second" other="took # seconds" />;
  }
  const n = Math.round(seconds / 60);
  return <Plural id="jobs.took.min" value={n} one="took # minute" other="took # minutes" />;
}

/** Every finished job, newest first, a page at a time. */
function JobHistory() {
  const { i18n } = useLingui();
  const history = useJobHistory();
  const done = history.data?.pages.flatMap((p) => p.jobs) ?? [];

  return (
    <>
      <h2 className={styles.sectionTitle}>
        <Trans id="jobs.history">History</Trans>
      </h2>
      {history.isPending ? (
        <p className={ui.muted}>
          <Trans id="common.loading">Loading…</Trans>
        </p>
      ) : history.isError ? (
        <ErrorNotice error={history.error} />
      ) : done.length === 0 ? (
        <p className={ui.muted}>
          <Trans id="jobs.history.none">No finished jobs yet.</Trans>
        </p>
      ) : (
        <>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">
                    <Trans id="jobs.col.kind">Job</Trans>
                  </th>
                  <th scope="col">
                    <Trans id="jobs.col.result">Result</Trans>
                  </th>
                  <th scope="col">
                    <Trans id="jobs.col.target">For</Trans>
                  </th>
                  <th scope="col">
                    <Trans id="jobs.col.when">When</Trans>
                  </th>
                </tr>
              </thead>
              <tbody>
                {done.map((j) => {
                  const seconds = took(j);
                  return (
                    <tr key={j.id} data-status={j.status}>
                      <td>
                        <JobKindLabel value={j.kind} />
                      </td>
                      <td>
                        <span className={styles.status} data-status={j.resolved ? "resolved" : j.status}>
                          <JobStatusLabel value={j.status} />
                        </span>
                        {j.resolved ? (
                          <span className={styles.progress}>
                            <Trans id="jobs.resolved">done later by another try</Trans>
                          </span>
                        ) : null}
                        {j.error && j.status !== "succeeded" ? (
                          <details className={styles.progress}>
                            <summary>
                              {j.status === "cancelled" ? (
                                <Trans id="jobs.cancelled">Stopped before it finished.</Trans>
                              ) : (
                                i18n._(jobErrorMessage(j.error))
                              )}
                            </summary>
                            <code className={styles.raw}>{j.error}</code>
                          </details>
                        ) : null}
                      </td>
                      <td>
                        {j.title && j.lesson_id ? (
                          <Link to="/lessons/$lessonId" params={{ lessonId: j.lesson_id }} className={styles.title}>
                            {j.title}
                          </Link>
                        ) : j.title ? (
                          <span className={styles.title}>{j.title}</span>
                        ) : (
                          <>
                            <JobTargetLabel value={j.target_kind} /> <code className={styles.id}>{j.target_id.slice(-8)}</code>
                          </>
                        )}
                      </td>
                      <td className={styles.when}>
                        {j.finished_at ? (
                          <time dateTime={j.finished_at}>
                            {i18n.date(new Date(j.finished_at), { dateStyle: "medium", timeStyle: "short" })}
                          </time>
                        ) : null}
                        {seconds != null ? (
                          <span className={styles.progress}>
                            <Took seconds={seconds} />
                          </span>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {history.hasNextPage ? (
            <div>
              <Button variant="secondary" small onPress={() => history.fetchNextPage()} isDisabled={history.isFetchingNextPage}>
                <Trans id="jobs.history.more">Show older</Trans>
              </Button>
            </div>
          ) : null}
        </>
      )}
    </>
  );
}
