import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  unwrap,
  type Schemas,
  type AssessmentOut,
  type JobRef,
  type JobStarted,
  type PathIn,
  type PathOut,
  type RequestIn,
  type RequestRow,
} from "./client";

export const keys = {
  setup: ["setup"] as const,
  estimate: (lessons: number) => ["estimate", lessons] as const,
  paths: ["paths"] as const,
  home: ["home"] as const,
  path: (id: string) => ["paths", id] as const,
  levelCheck: (pathId: string) => ["paths", pathId, "level-check"] as const,
  preview: (pathId: string) => ["paths", pathId, "preview"] as const,
  next: (pathId: string) => ["paths", pathId, "next"] as const,
  lesson: (id: string) => ["lessons", id] as const,
  progress: (pathId: string) => ["paths", pathId, "progress"] as const,
  requests: (pathId: string) => ["paths", pathId, "requests"] as const,
  notes: (lessonId: string) => ["lessons", lessonId, "notes"] as const,
  jobs: ["jobs"] as const,
  job: (id: string) => ["jobs", id] as const,
  settings: ["settings"] as const,
};

/** Job statuses that mean work is still pending; the path view polls while any job has one. */
export const ACTIVE_JOB_STATUSES = new Set(["queued", "running", "waiting_resource"]);
const PATH_POLL_MS = 3_000;

export function hasActiveJobs(path: PathOut | undefined): boolean {
  return !!path?.jobs.some((j) => ACTIVE_JOB_STATUSES.has(j.status));
}

export function useSetup() {
  return useQuery({
    queryKey: keys.setup,
    queryFn: () => unwrap(api.GET("/api/setup")),
  });
}

export function useEstimate(lessons: number) {
  return useQuery({
    queryKey: keys.estimate(lessons),
    queryFn: () => unwrap(api.GET("/api/estimate", { params: { query: { lessons } } })),
  });
}

export function usePaths() {
  return useQuery({
    queryKey: keys.paths,
    queryFn: () => unwrap(api.GET("/api/paths")),
  });
}

/** The first screen: the next step, what waits today, progress, momentum and one insight, across the paths. */
export function useHome() {
  return useQuery({
    queryKey: keys.home,
    queryFn: () => unwrap(api.GET("/api/home")),
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  });
}

export function useCreatePath() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: PathIn) => unwrap(api.POST("/api/paths", { body })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.paths }),
  });
}

export function usePath(pathId: string) {
  return useQuery({
    queryKey: keys.path(pathId),
    queryFn: () => unwrap(api.GET("/api/paths/{path_id}", { params: { path: { path_id: pathId } } })),
    refetchInterval: (query) => (hasActiveJobs(query.state.data) ? PATH_POLL_MS : false),
    refetchIntervalInBackground: false,
    staleTime: 0,
  });
}

/** Poll while the questions are being written; stop once they are there. */
const LEVEL_CHECK_POLL_MS = 2000;

export function useLevelCheck(pathId: string) {
  return useQuery({
    queryKey: keys.levelCheck(pathId),
    queryFn: () =>
      unwrap(api.GET("/api/paths/{path_id}/level-check", { params: { path: { path_id: pathId } } })),
    refetchInterval: (query) =>
      query.state.data?.status === "preparing" && !query.state.data.failed ? LEVEL_CHECK_POLL_MS : false,
    staleTime: 0,
  });
}

/** Write the questions again after that failed (the model was not reachable, a sign-in was missing). */
export function useRetryLevelCheck(pathId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/paths/{path_id}/level-check/retry", { params: { path: { path_id: pathId } } })),
    onSuccess: (data) => qc.setQueryData(keys.levelCheck(pathId), data),
  });
}

export function useAnswerLevelCheck(pathId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ answers = [], skip = false }: { answers?: (number | null)[]; skip?: boolean }) =>
      unwrap(
        api.POST("/api/paths/{path_id}/level-check", {
          params: { path: { path_id: pathId } },
          body: { answers, skip },
        }),
      ),
    onSuccess: (data) => {
      qc.setQueryData(keys.levelCheck(pathId), data);
      void qc.invalidateQueries({ queryKey: keys.path(pathId) });
      void qc.invalidateQueries({ queryKey: keys.paths });
    },
  });
}

// --- the plan preview ----------------------------------------------------------------------------

/** Poll while the plan is being written or revised. */
const PREVIEW_POLL_MS = 2000;

export function usePreview(pathId: string, enabled = true) {
  return useQuery({
    queryKey: keys.preview(pathId),
    queryFn: () => unwrap(api.GET("/api/paths/{path_id}/preview", { params: { path: { path_id: pathId } } })),
    enabled,
    refetchInterval: (query) => {
      const d = query.state.data;
      return d && (d.status === "drafting" || d.status === "revising") && !d.failed ? PREVIEW_POLL_MS : false;
    },
    staleTime: 0,
  });
}

type PreviewStep = "feedback" | "undo" | "retry" | "build";

export function usePreviewStep(pathId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ step, text = "" }: { step: PreviewStep; text?: string }) => {
      const params = { path: { path_id: pathId } };
      switch (step) {
        case "feedback":
          return unwrap(api.POST("/api/paths/{path_id}/preview/feedback", { params, body: { text } }));
        case "undo":
          return unwrap(api.POST("/api/paths/{path_id}/preview/undo", { params }));
        case "retry":
          return unwrap(api.POST("/api/paths/{path_id}/preview/retry", { params }));
        case "build":
          return unwrap(api.POST("/api/paths/{path_id}/preview/build", { params }));
      }
    },
    onSuccess: (data) => {
      qc.setQueryData(keys.preview(pathId), data);
      void qc.invalidateQueries({ queryKey: keys.path(pathId) });
      void qc.invalidateQueries({ queryKey: keys.paths });
    },
  });
}

// --- "What next?" checkpoint ----------------------------------------------------------------------

/** Statuses where Yuo is writing (questions, directions, new branches): the view polls. */
const NEXT_WRITING = new Set(["preparing", "proposing", "growing"]);

export function useNext(pathId: string, enabled = true) {
  return useQuery({
    queryKey: keys.next(pathId),
    queryFn: () => unwrap(api.GET("/api/paths/{path_id}/next", { params: { path: { path_id: pathId } } })),
    refetchInterval: (query) =>
      query.state.data && NEXT_WRITING.has(query.state.data.status) && !query.state.data.failed
        ? LEVEL_CHECK_POLL_MS
        : false,
    staleTime: 0,
    enabled,
  });
}

type NextStep = "start" | "others" | "dismiss" | "retry";
const NEXT_STEP_URL = {
  start: "/api/paths/{path_id}/next",
  others: "/api/paths/{path_id}/next/others",
  dismiss: "/api/paths/{path_id}/next/dismiss",
  retry: "/api/paths/{path_id}/next/retry",
} as const;

function useNextResult(pathId: string) {
  const qc = useQueryClient();
  return (data: Schemas["NextOut"]) => {
    qc.setQueryData(keys.next(pathId), data);
    if (data.status === "done" || data.status === "dismissed") void qc.invalidateQueries({ queryKey: keys.path(pathId) });
  };
}

/** Open the checkpoint, ask for other directions, close it, or retry a failed step. */
export function useNextStep(pathId: string) {
  const onSuccess = useNextResult(pathId);
  return useMutation({
    mutationFn: (step: NextStep) => unwrap(api.POST(NEXT_STEP_URL[step], { params: { path: { path_id: pathId } } })),
    onSuccess,
  });
}

export function useAnswerNext(pathId: string) {
  const onSuccess = useNextResult(pathId);
  return useMutation({
    mutationFn: (body: Schemas["NextAnswersIn"]) =>
      unwrap(api.POST("/api/paths/{path_id}/next/answers", { params: { path: { path_id: pathId } }, body })),
    onSuccess,
  });
}

export function useChooseNext(pathId: string) {
  const onSuccess = useNextResult(pathId);
  return useMutation({
    mutationFn: (code: string) =>
      unwrap(api.POST("/api/paths/{path_id}/next/choose", { params: { path: { path_id: pathId } }, body: { code } })),
    onSuccess,
  });
}

export function useGenerateLesson(pathId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (lessonId: string) =>
      unwrap(api.POST("/api/lessons/{lesson_id}/generate", { params: { path: { lesson_id: lessonId } } })),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.path(pathId) }),
  });
}

/** Publish a lesson that failed its review as its best draft, with the reviewer's notes shown in it. */
export function useAcceptLesson(pathId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (lessonId: string) =>
      unwrap(api.POST("/api/lessons/{lesson_id}/accept", { params: { path: { lesson_id: lessonId } } })),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.path(pathId) }),
  });
}

/** Rename a path, change its goal or exam date, archive it or bring it back. */
export function useUpdatePath() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ pathId, body }: { pathId: string; body: Schemas["PathPatch"] }) =>
      unwrap(api.PATCH("/api/paths/{path_id}", { params: { path: { path_id: pathId } }, body })),
    onSettled: () => qc.invalidateQueries(),
  });
}

/** Delete a path with everything in it. */
export function useDeletePath() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (pathId: string) => unwrap(api.DELETE("/api/paths/{path_id}", { params: { path: { path_id: pathId } } })),
    onSuccess: (_, pathId) => {
      qc.removeQueries({ queryKey: keys.path(pathId) });
      return qc.invalidateQueries();
    },
  });
}

/** Start a failed lesson or video job again from the jobs list. */
export function useRetryJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => unwrap(api.POST("/api/jobs/{job_id}/retry", { params: { path: { job_id: jobId } } })),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.jobs }),
  });
}

/** Make a lesson's video again after it failed; the lesson then shows it being made. */
export function useVideoAgain(lessonId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/lessons/{lesson_id}/video", { params: { path: { lesson_id: lessonId } } })),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.lesson(lessonId) }),
  });
}

/** Video states that change on their own; the lesson polls while its video is in one (stream fallback). */
const VIDEO_MAKING = new Set(["queued", "generating", "in_review"]);
const VIDEO_POLL_MS = 5_000;

export function useLesson(lessonId: string) {
  return useQuery({
    queryKey: keys.lesson(lessonId),
    queryFn: () => unwrap(api.GET("/api/lessons/{lesson_id}", { params: { path: { lesson_id: lessonId } } })),
    refetchInterval: (q) => (VIDEO_MAKING.has(q.state.data?.video?.state ?? "") ? VIDEO_POLL_MS : false),
  });
}

// --- assessments -------------------------------------------------------------------------------

export type StartResult = AssessmentOut | JobStarted;

export function isJob(r: StartResult): r is JobStarted {
  return "job_id" in r && typeof r.job_id === "string";
}

export function startPractice(lessonId: string): Promise<StartResult> {
  return unwrap(api.POST("/api/lessons/{lesson_id}/practice", { params: { path: { lesson_id: lessonId } } }));
}

export function startSkillTest(skillId: string): Promise<StartResult> {
  return unwrap(api.POST("/api/skills/{skill_id}/test", { params: { path: { skill_id: skillId } } }));
}

export function startPlacement(pathId: string): Promise<StartResult> {
  return unwrap(api.POST("/api/paths/{path_id}/placement", { params: { path: { path_id: pathId } } }));
}

export function startReviews(pathId: string | null, skillId: string | null = null): Promise<StartResult> {
  const query: { path_id?: string; skill_id?: string } = {};
  if (pathId) query.path_id = pathId;
  if (skillId) query.skill_id = skillId;
  return unwrap(api.POST("/api/reviews/start", { params: { query } }));
}

const JOB_POLL_MS = 2_000;

export function useJob(jobId: string | null) {
  return useQuery({
    queryKey: keys.job(jobId ?? ""),
    queryFn: () => unwrap(api.GET("/api/jobs/{job_id}", { params: { path: { job_id: jobId ?? "" } } })),
    enabled: jobId !== null,
    staleTime: 0,
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status === undefined || ACTIVE_JOB_STATUSES.has(status) ? JOB_POLL_MS : false;
    },
  });
}

// --- progress, jobs ------------------------------------------------------------------

export function useProgress(pathId: string) {
  return useQuery({
    queryKey: keys.progress(pathId),
    queryFn: () => unwrap(api.GET("/api/paths/{path_id}/progress", { params: { path: { path_id: pathId } } })),
    staleTime: 5_000,
  });
}

export function hasActiveJob(jobs: JobRef[] | undefined): boolean {
  return !!jobs?.some((j) => ACTIVE_JOB_STATUSES.has(j.status));
}

/** Finished jobs, newest first, a page at a time (keep the executed ones in a history).
 * Under the jobs key, so whatever refreshes the jobs list refreshes the history too. */
export function useJobHistory() {
  return useInfiniteQuery({
    queryKey: [...keys.jobs, "history"],
    queryFn: ({ pageParam }) => unwrap(api.GET("/api/jobs/history", { params: { query: { before: pageParam ?? undefined, limit: 30 } } })),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next ?? undefined,
    refetchInterval: 60_000,
  });
}

export function useJobs() {
  return useQuery({
    queryKey: keys.jobs,
    queryFn: () => unwrap(api.GET("/api/jobs")),
    staleTime: 0,
    refetchInterval: (q) => (hasActiveJob(q.state.data) ? PATH_POLL_MS : 30_000),
  });
}

// --- lesson requests --------------------------------------------------------------------------

const OPEN_REQUEST = new Set(["pending", "running"]);

export function hasOpenRequest(rows: RequestRow[] | undefined): boolean {
  return !!rows?.some((r) => OPEN_REQUEST.has(r.status));
}

export function useRequests(pathId: string) {
  return useQuery({
    queryKey: keys.requests(pathId),
    queryFn: () => unwrap(api.GET("/api/paths/{path_id}/requests", { params: { path: { path_id: pathId } } })),
    staleTime: 0,
    refetchInterval: (q) => (hasOpenRequest(q.state.data) ? PATH_POLL_MS : false),
  });
}

export function useCreateRequest(pathId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: RequestIn) =>
      unwrap(api.POST("/api/paths/{path_id}/requests", { params: { path: { path_id: pathId } }, body })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.requests(pathId) });
      void qc.invalidateQueries({ queryKey: keys.jobs });
    },
  });
}

// --- notes ------------------------------------------------------------------------------------

export function useNotes(lessonId: string) {
  return useQuery({
    queryKey: keys.notes(lessonId),
    queryFn: () => unwrap(api.GET("/api/lessons/{lesson_id}/notes", { params: { path: { lesson_id: lessonId } } })),
  });
}

export function useNoteMutations(lessonId: string) {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: keys.notes(lessonId) });
  const create = useMutation({
    mutationFn: (body: Schemas["NoteIn"]) =>
      unwrap(api.POST("/api/notes", { body })),
    onSuccess: refresh,
  });
  const edit = useMutation({
    mutationFn: ({ id, text }: { id: string; text: string }) =>
      noContent(api.PATCH("/api/notes/{note_id}", { params: { path: { note_id: id } }, body: { text } })),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: string) => noContent(api.DELETE("/api/notes/{note_id}", { params: { path: { note_id: id } } })),
    onSuccess: refresh,
  });
  return { create, edit, remove };
}

// --- settings ---------------------------------------------------------------------------------

export function useSettings() {
  return useQuery({
    queryKey: keys.settings,
    queryFn: () => unwrap(api.GET("/api/settings", { params: { query: {} } })),
  });
}

export function usePutSetting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ key, value }: { key: string; value: unknown }) =>
      noContent(api.PUT("/api/settings/{key}", { params: { path: { key } }, body: { value, level: "learner" } })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.settings });
      // gamification, review caps and pass marks change what other screens show
      void qc.invalidateQueries({ queryKey: ["paths"] });
    },
  });
}

/** For 204 responses: throws an ApiError on failure, resolves to nothing on success. */
async function noContent(call: Promise<{ error?: unknown; response: Response }>): Promise<void> {
  await unwrap(call as Promise<{ data?: undefined; error?: unknown; response: Response }>);
}

/** The back of a flashcard: the normal flip, not help (no item.support_shown). */
export function fetchReveal(itemVersionId: string) {
  return unwrap(
    api.GET("/api/items/{item_version_id}/reveal", { params: { path: { item_version_id: itemVersionId } } }),
  );
}

export function fetchHint(itemVersionId: string, level: number) {
  return unwrap(
    api.GET("/api/items/{item_version_id}/hints/{level}", {
      params: { path: { item_version_id: itemVersionId, level } },
    }),
  );
}

// --- erasure ------------------------------------------------------------------------------

/** Erase the learner's data in one path; the path and its shared lessons stay. Everything is read again. */
export function useErasePathData() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (pathId: string) =>
      unwrap(api.DELETE("/api/paths/{path_id}/personal-data", { params: { path: { path_id: pathId } } })),
    onSuccess: () => qc.invalidateQueries(),
  });
}

/** Erase which videos were watched and how much of each. */
export function useEraseVideoHistory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/me/video-history")),
    onSuccess: () => qc.invalidateQueries(),
  });
}
