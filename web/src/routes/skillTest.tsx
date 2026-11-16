import { Trans, useLingui } from "@lingui/react/macro";
import { useQueryClient } from "@tanstack/react-query";
import { createRoute } from "@tanstack/react-router";
import { useCallback } from "react";
import { keys, startSkillTest, usePath } from "../api/hooks";
import { AssessmentRunner } from "../assessment/AssessmentRunner";
import { StartGate } from "../assessment/StartGate";
import styles from "../assessment/assessment.module.css";
import { BackLink, ButtonLink, Notice, PageHeader, Progress, ui } from "../components/ui";
import type { Outcome } from "../outbox/outbox";
import { rootRoute } from "./root";
import { useTutorRefs } from "../tutor/context";

export const skillTestRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/paths/$pathId/skills/$skillId/test",
  component: SkillTestPage,
});

type TestResult = { skill_id: string; passed: boolean; score: number; pass_mark: number };

function isTestResult(o: Outcome): o is TestResult {
  return typeof o["passed"] === "boolean" && typeof o["score"] === "number" && typeof o["pass_mark"] === "number";
}

function TestResultView({ outcome }: { outcome: Outcome }) {
  const { t } = useLingui();
  if (!isTestResult(outcome)) return null;
  const score = Math.round(outcome.score * 100);
  const mark = Math.round(outcome.pass_mark * 100);
  return (
    <div className={styles.result} role="status">
      <Notice tone={outcome.passed ? "success" : "warning"} icon={outcome.passed ? undefined : true}>
        <p>
          <strong>
            {outcome.passed ? (
              <Trans id="skill-test.passed">Passed. This skill is mastered.</Trans>
            ) : (
              <Trans id="skill-test.failed">Not passed yet.</Trans>
            )}
          </strong>
        </p>
        <p>
          <Trans id="skill-test.score">
            Your score: {score}% (pass mark {mark}%)
          </Trans>
        </p>
      </Notice>
      <div className={styles.scoreBar} data-passed={outcome.passed || undefined}>
        <Progress value={score} showValue={false} label={t({ id: "skill-test.score.bar", message: "Your score" })} />
        <span className={styles.passMark} style={{ insetInlineStart: `${mark}%` }} aria-hidden="true" />
      </div>
      {outcome.passed ? null : (
        <p>
          <Trans id="skill-test.remedial">
            A short extra lesson on what you missed is being prepared. It appears in the path as an extra lesson.
          </Trans>
        </p>
      )}
    </div>
  );
}

function SkillTestPage() {
  const { pathId, skillId } = skillTestRoute.useParams();
  useTutorRefs({ screen: "test", path_id: pathId, skill_id: skillId });
  const qc = useQueryClient();
  const path = usePath(pathId);
  const start = useCallback(() => startSkillTest(skillId), [skillId]);
  const skill = path.data?.branches.flatMap((b) => b.skills).find((s) => s.id === skillId);
  const title = skill?.title ?? "";
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: keys.progress(pathId) });
    void qc.invalidateQueries({ queryKey: keys.path(pathId) });
  };

  return (
    <section className={ui.stack}>
      <PageHeader
        back={
          <BackLink to="/paths/$pathId" params={{ pathId }}>
            <Trans id="skill-test.back">Back to the path</Trans>
          </BackLink>
        }
        title={
          title ? (
            <Trans id="skill-test.title">Skill test: {title}</Trans>
          ) : (
            <Trans id="skill-test.title.plain">Skill test</Trans>
          )
        }
        meta={
          <p>
            <Trans id="skill-test.intro">
              No hints and no feedback until the end: this checks what you can do on your own.
            </Trans>
          </p>
        }
      />
      <StartGate
        startKey={skillId}
        start={start}
        preparing={<Trans id="skill-test.preparing">Preparing your test. This can take a minute…</Trans>}
      >
        {(assessment) => (
          <AssessmentRunner
            assessment={assessment}
            onFinished={refresh}
            renderOutcome={(o) => <TestResultView outcome={o} />}
            footer={
              <ButtonLink to="/paths/$pathId" params={{ pathId }} variant="secondary">
                <Trans id="skill-test.back">Back to the path</Trans>
              </ButtonLink>
            }
          />
        )}
      </StartGate>
    </section>
  );
}
