import { Trans } from "@lingui/react/macro";
import { useQueryClient } from "@tanstack/react-query";
import { createRoute } from "@tanstack/react-router";
import { useCallback } from "react";
import type { PathOut } from "../api/client";
import { keys, startPlacement, usePath } from "../api/hooks";
import { AssessmentRunner } from "../assessment/AssessmentRunner";
import { StartGate } from "../assessment/StartGate";
import styles from "../assessment/assessment.module.css";
import { BackLink, ButtonLink, Notice, PageHeader, ui } from "../components/ui";
import type { Outcome } from "../outbox/outbox";
import { rootRoute } from "./root";
import { useTutorRefs } from "../tutor/context";

export const placementRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/paths/$pathId/placement",
  component: PlacementPage,
});

function PlacementResult({ outcome, path }: { outcome: Outcome; path: PathOut | undefined }) {
  const placed = outcome["placed"];
  if (!placed || typeof placed !== "object") return null;
  const titles = new Map((path?.branches ?? []).flatMap((b) => b.skills).map((s) => [s.id, s.title]));
  const entries = Object.entries(placed as Record<string, string>);
  const mastered = entries.filter(([, r]) => r === "mastered").map(([id]) => titles.get(id) ?? id);
  const count = mastered.length;
  return (
    <div className={styles.result} role="status">
      {count > 0 ? (
        <Notice tone="success" icon={true}>
          <p>
            <Trans id="placement.result.mastered">You already know these skills; they are marked as mastered:</Trans>
          </p>
          <ul>
            {mastered.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </Notice>
      ) : (
        <Notice>
          <Trans id="placement.result.none">No skills were marked as mastered. The path starts from the beginning.</Trans>
        </Notice>
      )}
    </div>
  );
}

function PlacementPage() {
  const { pathId } = placementRoute.useParams();
  useTutorRefs({ screen: "placement", path_id: pathId });
  const qc = useQueryClient();
  const path = usePath(pathId);
  const start = useCallback(() => startPlacement(pathId), [pathId]);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: keys.progress(pathId) });
    void qc.invalidateQueries({ queryKey: keys.path(pathId) });
  };

  return (
    <section className={ui.stack}>
      <PageHeader
        back={
          <BackLink to="/paths/$pathId" params={{ pathId }}>
            <Trans id="placement.back">Back to the path</Trans>
          </BackLink>
        }
        title={<Trans id="placement.title">Placement test</Trans>}
        meta={
          <p>
            <Trans id="placement.intro">
              A few questions per skill. Skills you already know are marked as mastered, so you can skip ahead.
            </Trans>
          </p>
        }
      />
      <StartGate
        startKey={pathId}
        start={start}
        preparing={<Trans id="placement.preparing">Preparing your placement test. This can take a few minutes…</Trans>}
      >
        {(assessment) => (
          <AssessmentRunner
            assessment={assessment}
            onFinished={refresh}
            renderOutcome={(o) => <PlacementResult outcome={o} path={path.data} />}
            footer={
              <ButtonLink to="/paths/$pathId" params={{ pathId }} variant="secondary">
                <Trans id="placement.back">Back to the path</Trans>
              </ButtonLink>
            }
          />
        )}
      </StartGate>
    </section>
  );
}
