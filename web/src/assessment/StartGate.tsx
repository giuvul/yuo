import { Trans } from "@lingui/react/macro";
import { useLingui } from "@lingui/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { AssessmentOut } from "../api/client";
import { isJob, useJob, type StartResult } from "../api/hooks";
import { ErrorNotice } from "../components/ErrorNotice";
import { jobErrorMessage } from "../components/jobError";
import { Notice, Waiting, ui } from "../components/ui";

type Props = {
  /** a stable key: the gate starts again when it changes */
  startKey: string;
  start: () => Promise<StartResult>;
  /** shown while the server prepares the items (a job) */
  preparing: ReactNode;
  children: (assessment: AssessmentOut & { assessment_id: string }) => ReactNode;
  /** shown when the server has nothing to ask (no assessment id, e.g. no reviews due) */
  empty?: (assessment: AssessmentOut) => ReactNode;
};

/**
 * Starts an assessment. When the server answers with a job id (items still being written), it
 * shows `preparing`, polls the job, and asks again once the job succeeded.
 */
export function StartGate({ startKey, start, preparing, children, empty }: Props) {
  const { i18n } = useLingui();
  const [assessment, setAssessment] = useState<AssessmentOut | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const startRef = useRef(start);
  startRef.current = start;
  const job = useJob(jobId);

  const run = useRef((onDone?: () => void) => {
    startRef
      .current()
      .then((r) => {
        if (isJob(r)) setJobId(r.job_id);
        else {
          setJobId(null);
          setAssessment(r);
        }
      })
      .catch(setError)
      .finally(onDone);
  });

  // one start per key (the ref also absorbs StrictMode's re-run)
  const startedFor = useRef<string | null>(null);
  useEffect(() => {
    if (startedFor.current === startKey) return;
    startedFor.current = startKey;
    setAssessment(null);
    setJobId(null);
    setError(null);
    run.current();
  }, [startKey]);

  // the job finished: ask for the assessment again
  const retriedFor = useRef<string | null>(null);
  const status = job.data?.status;
  useEffect(() => {
    if (jobId && status === "succeeded" && retriedFor.current !== jobId) {
      retriedFor.current = jobId;
      run.current();
    }
  }, [jobId, status]);

  if (error) return <ErrorNotice error={error} />;
  if (job.isError) return <ErrorNotice error={job.error} />;
  if (jobId) {
    if (status === "failed" || status === "cancelled") {
      return (
        <Notice tone="error">
          <p>
            <Trans id="assessment.prepare.failed">The questions could not be prepared.</Trans>{" "}
            {i18n._(jobErrorMessage(job.data?.error))}
          </p>
        </Notice>
      );
    }
    return (
      <div className={ui.panel}>
        <Waiting>{preparing}</Waiting>
        {status === "waiting_resource" ? (
          <p className={ui.muted}>
            <Trans id="assessment.prepare.waiting">Generation is paused until the budget allows more.</Trans>
          </p>
        ) : null}
      </div>
    );
  }
  if (!assessment) {
    return (
      <Waiting>
        <Trans id="assessment.loading">Preparing your questions…</Trans>
      </Waiting>
    );
  }
  if (assessment.assessment_id === null || assessment.items.length === 0) {
    return empty ? (
      <>{empty(assessment)}</>
    ) : (
      <Notice role="status">
        <Trans id="assessment.empty">There are no questions here yet.</Trans>
      </Notice>
    );
  }
  return <>{children({ ...assessment, assessment_id: assessment.assessment_id })}</>;
}
