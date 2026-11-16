// Review: one hub per path, its session player with the results, and a small chooser behind the header's
// "Reviews" tab that lists the paths with what is due (with one path it goes straight to that hub).
import { Plural, Trans } from "@lingui/react/macro";
import { useQuery } from "@tanstack/react-query";
import { createRoute, Link, Navigate } from "@tanstack/react-router";
import { useState } from "react";
import { usePath } from "../api/hooks";
import { ErrorNotice } from "../components/ErrorNotice";
import { LeafIcon } from "../components/icons";
import { Seedling } from "../components/illustrations";
import { BackLink, ButtonLink, Notice, PageHeader, ui, Waiting } from "../components/ui";
import { isSize, startReviewSession, usePathHubs, useReviewHub, type ReviewSize } from "../review/api";
import { Hub } from "../review/Hub";
import { ReviewPlayer } from "../review/Player";
import styles from "../review/review.module.css";
import { useTutorRefs } from "../tutor/context";
import { rootRoute } from "./root";

export const reviewChooserRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/review",
  component: ChooserPage,
});

export const reviewHubRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/paths/$pathId/review",
  component: HubPage,
});

type SessionSearch = { size?: ReviewSize; skill?: string; branch?: string };

export const reviewSessionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/paths/$pathId/review/session",
  // `skill` / `branch`: a focused session (a skill's "Review this skill", an accepted extra review)
  validateSearch: (search: Record<string, unknown>): SessionSearch => {
    const out: SessionSearch = {};
    const size = Number(search["size"]);
    if (isSize(size)) out.size = size;
    if (typeof search["skill"] === "string" && search["skill"]) out.skill = search["skill"];
    if (typeof search["branch"] === "string" && search["branch"]) out.branch = search["branch"];
    return out;
  },
  component: SessionPage,
});

function ChooserPage() {
  useTutorRefs({ screen: "review" });
  const { paths, rows } = usePathHubs();
  if (paths.isPending) {
    return (
      <Waiting>
        <Trans id="common.loading">Loading…</Trans>
      </Waiting>
    );
  }
  if (paths.isError) return <ErrorNotice error={paths.error} />;
  const only = rows.length === 1 ? rows[0] : undefined;
  if (only) return <Navigate to="/paths/$pathId/review" params={{ pathId: only.path.id }} replace />;
  return (
    <section className={ui.stack}>
      <PageHeader
        title={<Trans id="review.chooser.title">Reviews</Trans>}
        meta={
          <p>
            <Trans id="review.chooser.intro">What you studied, brought back just before you would forget it.</Trans>
          </p>
        }
      />
      {rows.length === 0 ? (
        <div className={`${ui.card} ${styles.empty}`}>
          <Seedling width={112} />
          <p className={ui.muted}>
            <Trans id="review.chooser.none">You have no paths yet. Reviews start once you have finished a lesson.</Trans>
          </p>
          <ButtonLink to="/paths/new">
            <Trans id="review.chooser.new">Create a path</Trans>
          </ButtonLink>
        </div>
      ) : (
        <ul className={styles.pathList}>
          {rows.map(({ path, hub }) => {
            const due = hub ? hub.due + hub.cards_due : 0;
            return (
              <li key={path.id}>
                <Link to="/paths/$pathId/review" params={{ pathId: path.id }} className={`${ui.card} ${styles.pathRow}`}>
                  <span className={styles.pathName}>{path.title}</span>
                  <span className={ui.muted}>
                    {!hub ? null : hub.memory === null ? (
                      <Trans id="review.chooser.nothing">Nothing studied yet</Trans>
                    ) : due > 0 ? (
                      <Plural id="review.chooser.due" value={due} one="# due" other="# due" />
                    ) : (
                      <Trans id="review.chooser.fresh">All fresh</Trans>
                    )}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function HubPage() {
  const { pathId } = reviewHubRoute.useParams();
  useTutorRefs({ screen: "review", path_id: pathId });
  const path = usePath(pathId);
  const hub = useReviewHub(pathId);
  return (
    <section className={ui.stack}>
      <PageHeader
        back={
          <BackLink to="/paths/$pathId" params={{ pathId }}>
            {path.data?.title ?? <Trans id="review.back.path">Path</Trans>}
          </BackLink>
        }
        title={<Trans id="review.hub.title">Review</Trans>}
        meta={
          <p>
            <Trans id="review.chooser.intro">What you studied, brought back just before you would forget it.</Trans>
          </p>
        }
      />
      {hub.isPending ? (
        <Waiting>
          <Trans id="common.loading">Loading…</Trans>
        </Waiting>
      ) : hub.isError ? (
        <ErrorNotice error={hub.error} />
      ) : (
        <Hub pathId={pathId} hub={hub.data} />
      )}
    </section>
  );
}

function SessionPage() {
  const { pathId } = reviewSessionRoute.useParams();
  // keys the validation left out keep their raw value from the URL (`?size=7`): check again before asking
  const search = reviewSessionRoute.useSearch();
  const size = isSize(search.size) ? search.size : 10;
  const skill = typeof search.skill === "string" && search.skill ? search.skill : undefined;
  const branch = typeof search.branch === "string" && search.branch ? search.branch : undefined;
  // "Review again" asks for another session; an unfinished one always comes back first
  const [run, setRun] = useState(0);
  const session = useQuery({
    queryKey: ["review", "session", pathId, size, skill ?? null, branch ?? null, run],
    queryFn: () => startReviewSession(pathId, size, { skill, branch }),
    staleTime: Infinity,
    gcTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const hubLink = (
    <BackLink to="/paths/$pathId/review" params={{ pathId }} activeOptions={{ exact: true }}>
      <Trans id="review.hub.title">Review</Trans>
    </BackLink>
  );
  const data = session.data;
  return (
    <section className={ui.stack}>
      <PageHeader back={hubLink} title={<Trans id="review.session.title">Review session</Trans>} />
      {session.isPending ? (
        <Waiting>
          <Trans id="review.session.preparing">Choosing your questions…</Trans>
        </Waiting>
      ) : session.isError ? (
        <ErrorNotice error={session.error} />
      ) : data && data.assessment_id !== null ? (
        <ReviewPlayer
          key={data.assessment_id}
          pathId={pathId}
          session={{ ...data, assessment_id: data.assessment_id }}
          onAgain={() => setRun((n) => n + 1)}
        />
      ) : (
        <>
          <NothingToAsk pathId={pathId} />
          <div>
            <ButtonLink to="/paths/$pathId/review" params={{ pathId }} variant="secondary">
              <Trans id="review.session.back">Back to the review</Trans>
            </ButtonLink>
          </div>
        </>
      )}
    </section>
  );
}

/** The server had nothing to ask: say whether it is today's limit or the choice. */
function NothingToAsk({ pathId }: { pathId: string }) {
  const hub = useReviewHub(pathId);
  return (
    <Notice role="status" icon={<LeafIcon />}>
      {hub.data?.allowed_today === 0 ? (
        <Trans id="review.hub.limit">You reached today's review limit. More reviews come tomorrow.</Trans>
      ) : (
        <Trans id="review.session.none">There is nothing to review here right now.</Trans>
      )}
    </Notice>
  );
}
