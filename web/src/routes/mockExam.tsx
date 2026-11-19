import { Trans, useLingui } from "@lingui/react/macro";
import { useQueryClient } from "@tanstack/react-query";
import { createRoute, Link } from "@tanstack/react-router";
import { useCallback } from "react";
import { api, unwrap } from "../api/client";
import { keys, usePath, type StartResult } from "../api/hooks";
import { useStudies } from "../material/api";
import { AssessmentRunner } from "../assessment/AssessmentRunner";
import { StartGate } from "../assessment/StartGate";
import styles from "../assessment/assessment.module.css";
import { BackLink, ButtonLink, Notice, PageHeader, Progress, ui } from "../components/ui";
import type { Outcome } from "../outbox/outbox";
import { rootRoute } from "./root";
import { useTutorRefs } from "../tutor/context";

export const mockExamRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/paths/$pathId/courses/$courseId/mock-exam",
  component: MockExamPage,
});

type MockResult = { course_id: string; score: number; pass_mark: number; passed: boolean; skills: Record<string, number> };

function mockOf(o: Outcome): MockResult | null {
  const m = o["mock"];
  return m && typeof m === "object" ? (m as MockResult) : null;
}

function startMock(courseId: string): Promise<StartResult> {
  return unwrap(api.POST("/api/courses/{course_id}/mock-exam", { params: { path: { course_id: courseId } } }));
}

/** The score, and the skills to go back to: those under the pass mark, weakest first. */
function MockResultView({ outcome, pathId }: { outcome: Outcome; pathId: string }) {
  const { t } = useLingui();
  const path = usePath(pathId);
  const mock = mockOf(outcome);
  if (!mock) return null;
  const score = Math.round(mock.score * 100);
  const mark = Math.round(mock.pass_mark * 100);
  const skills = (path.data?.branches ?? []).flatMap((b) => b.skills);
  const weak = Object.entries(mock.skills)
    .filter(([, s]) => s < mock.pass_mark)
    .sort((a, b) => a[1] - b[1])
    .map(([id]) => skills.find((s) => s.id === id))
    .filter((s) => s !== undefined);
  return (
    <div className={styles.result} role="status">
      <Notice tone={mock.passed ? "success" : "warning"} icon={mock.passed ? undefined : true}>
        <p>
          <strong>
            {mock.passed ? (
              <Trans id="mock.passed">You would pass.</Trans>
            ) : (
              <Trans id="mock.failed">Not there yet.</Trans>
            )}
          </strong>
        </p>
        <p>
          <Trans id="mock.score">
            Your score: {score}% (pass mark {mark}%)
          </Trans>
        </p>
      </Notice>
      <div className={styles.scoreBar} data-passed={mock.passed || undefined}>
        <Progress value={score} showValue={false} label={t({ id: "mock.score.bar", message: "Your score" })} />
        <span className={styles.passMark} style={{ insetInlineStart: `${mark}%` }} aria-hidden="true" />
      </div>
      {weak.length ? (
        <>
          <p>
            <Trans id="mock.weak">Go back to these skills before the exam:</Trans>
          </p>
          <ul>
            {weak.map((s) => (
              <li key={s.id}>
                <Link to="/paths/$pathId/skills/$skillId/test" params={{ pathId, skillId: s.id }}>
                  {s.title}
                </Link>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}

function MockExamPage() {
  const { pathId, courseId } = mockExamRoute.useParams();
  useTutorRefs({ screen: "test", path_id: pathId });
  const qc = useQueryClient();
  const start = useCallback(() => startMock(courseId), [courseId]);
  const studies = useStudies(pathId);
  const title = studies.data?.courses.find((c) => c.id === courseId)?.title ?? "";
  return (
    <section className={ui.stack}>
      <PageHeader
        back={
          <BackLink to="/paths/$pathId" params={{ pathId }}>
            <Trans id="mock.back">Back to the path</Trans>
          </BackLink>
        }
        title={
          title ? <Trans id="mock.title">Mock exam: {title}</Trans> : <Trans id="mock.title.plain">Mock exam</Trans>
        }
        meta={
          <p>
            <Trans id="mock.intro">
              Questions from the whole course, in the style of its past exams when you added some. No hints and no
              feedback until the end. It does not change your progress.
            </Trans>
          </p>
        }
      />
      <StartGate
        startKey={courseId}
        start={start}
        preparing={
          <Trans id="mock.preparing">
            Writing the questions for every skill of the course. The first time this can take several minutes…
          </Trans>
        }
      >
        {(assessment) => (
          <AssessmentRunner
            assessment={assessment}
            onFinished={() => void qc.invalidateQueries({ queryKey: keys.path(pathId) })}
            renderOutcome={(o) => <MockResultView outcome={o} pathId={pathId} />}
            footer={
              <ButtonLink to="/paths/$pathId" params={{ pathId }} variant="secondary">
                <Trans id="mock.back">Back to the path</Trans>
              </ButtonLink>
            }
          />
        )}
      </StartGate>
    </section>
  );
}
