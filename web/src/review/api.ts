// The review hub and its sessions: memory per learning objective, a session of questions with staged
// feedback, the results. Answers and help go through the outbox as events; these calls only read.
import { useQueries, useQuery } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "../api/client";
import { usePaths } from "../api/hooks";

export type ReviewHub = Schemas["ReviewHubOut"];
export type HubSkill = ReviewHub["skills"][number];
export type ReviewSession = Schemas["ReviewSessionOut"];
export type ReviewItem = Schemas["ReviewItem"];
export type ReviewResult = Schemas["ReviewResultOut"];
export type ReviewSize = Schemas["ReviewSessionIn"]["size"];
type ReviewFocus = { skill?: string | undefined; branch?: string | undefined };

export const SIZES: ReviewSize[] = [5, 10, 20];

export function isSize(n: unknown): n is ReviewSize {
  return n === 5 || n === 10 || n === 20;
}

export const reviewKeys = {
  hub: (pathId: string) => ["paths", pathId, "review"] as const,
  result: (attemptId: string) => ["review", "result", attemptId] as const,
};

/** Poll gently while the questions of a lesson are being written; otherwise once a minute. */
const WRITING_POLL_MS = 4_000;
const HUB_POLL_MS = 60_000;

function fetchHub(pathId: string): Promise<ReviewHub> {
  return unwrap(api.GET("/api/paths/{path_id}/review", { params: { path: { path_id: pathId } } }));
}

export function useReviewHub(pathId: string, enabled = true) {
  return useQuery({
    queryKey: reviewKeys.hub(pathId),
    queryFn: () => fetchHub(pathId),
    enabled,
    staleTime: 10_000,
    refetchInterval: (q) => ((q.state.data?.writing ?? 0) > 0 ? WRITING_POLL_MS : HUB_POLL_MS),
    refetchIntervalInBackground: false,
  });
}

/** What a hub offers today: objectives and cards due, within the daily limit. */
function hubDue(hub: ReviewHub | undefined): number {
  return hub ? Math.min(hub.due + hub.cards_due, hub.allowed_today) : 0;
}

/** Every path with its hub (shared with the hub pages through the query cache), for the chooser. */
export function usePathHubs() {
  const paths = usePaths();
  const rows = paths.data ?? [];
  const hubs = useQueries({
    queries: rows.map((p) => ({
      queryKey: reviewKeys.hub(p.id),
      queryFn: () => fetchHub(p.id),
      staleTime: 60_000,
      refetchInterval: 5 * 60_000,
      refetchIntervalInBackground: false,
    })),
  });
  return { paths, rows: rows.map((path, i) => ({ path, hub: hubs[i]?.data })) };
}

/**
 * What is due across the learner's paths, for the header: the hubs come from the shared cache, the list of paths
 * from a slow query of its own, so the header never keeps the pages' own list of paths from refreshing.
 */
export function useDueTotal(): number {
  const paths = useQuery({
    queryKey: ["review", "paths"],
    queryFn: () => unwrap(api.GET("/api/paths")),
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
    refetchIntervalInBackground: false,
  });
  const hubs = useQueries({
    queries: (paths.data ?? []).map((p) => ({
      queryKey: reviewKeys.hub(p.id),
      queryFn: () => fetchHub(p.id),
      staleTime: 60_000,
      refetchInterval: 5 * 60_000,
      refetchIntervalInBackground: false,
    })),
  });
  const allowed = Math.min(...hubs.map((h) => h.data?.allowed_today ?? Infinity));
  return Math.min(
    hubs.reduce((sum, h) => sum + hubDue(h.data), 0),
    allowed,
  );
}

export function startReviewSession(pathId: string, size: ReviewSize, focus: ReviewFocus = {}): Promise<ReviewSession> {
  return unwrap(
    api.POST("/api/paths/{path_id}/review/sessions", {
      params: { path: { path_id: pathId } },
      body: { size, skill_id: focus.skill ?? null, branch_id: focus.branch ?? null },
    }),
  );
}

/** What the learner may see about a question now (after "Show answer": the resolved feedback). */
export function fetchReviewFeedback(attemptId: string, itemVersionId: string) {
  return unwrap(
    api.GET("/api/review/attempts/{attempt_id}/items/{item_version_id}", {
      params: { path: { attempt_id: attemptId, item_version_id: itemVersionId } },
    }),
  );
}

export function fetchReviewResult(attemptId: string): Promise<ReviewResult> {
  return unwrap(api.GET("/api/review/attempts/{attempt_id}", { params: { path: { attempt_id: attemptId } } }));
}

/** Retires a question the learner found wrong or unclear. */
export async function reportItem(itemId: string, reason: string): Promise<void> {
  await unwrap(
    api.POST("/api/items/{item_id}/report", { params: { path: { item_id: itemId } }, body: { reason } }) as Promise<{
      data?: undefined;
      error?: unknown;
      response: Response;
    }>,
  );
}
