import { Trans } from "@lingui/react/macro";
import { createRoute } from "@tanstack/react-router";
import { useCallback } from "react";
import { startPractice } from "../api/hooks";
import { AssessmentRunner } from "../assessment/AssessmentRunner";
import { StartGate } from "../assessment/StartGate";
import { BackLink, ButtonLink, Notice, PageHeader, ui } from "../components/ui";
import { rootRoute } from "./root";
import { useTutorRefs } from "../tutor/context";

export const practiceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/lessons/$lessonId/practice",
  component: PracticePage,
});

function PracticePage() {
  const { lessonId } = practiceRoute.useParams();
  useTutorRefs({ screen: "practice", lesson_id: lessonId });
  const start = useCallback(() => startPractice(lessonId), [lessonId]);
  const back = (
    <ButtonLink to="/lessons/$lessonId" params={{ lessonId }} variant="secondary">
      <Trans id="practice.back-to-lesson">Back to the lesson</Trans>
    </ButtonLink>
  );

  return (
    <section className={ui.stack}>
      <PageHeader
        back={
          <BackLink to="/lessons/$lessonId" params={{ lessonId }}>
            <Trans id="practice.back-to-lesson">Back to the lesson</Trans>
          </BackLink>
        }
        title={<Trans id="practice.title">Practice</Trans>}
      />
      <StartGate
        startKey={lessonId}
        start={start}
        preparing={<Trans id="practice.preparing">The practice questions are being written…</Trans>}
        empty={() => (
          <Notice role="status">
            <Trans id="practice.empty">This lesson has no practice questions yet.</Trans>
          </Notice>
        )}
      >
        {(assessment) => <AssessmentRunner assessment={assessment} footer={back} />}
      </StartGate>
    </section>
  );
}
