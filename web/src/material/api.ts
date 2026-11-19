import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, CSRF_HEADER, unwrap, type Schemas } from "../api/client";
import { keys } from "../api/hooks";

export type StudiesOut = Schemas["StudiesOut"];
export type CourseOut = Schemas["CourseOut"];
export type MaterialOut = Schemas["MaterialOut"];
export type CoursePlanOut = Schemas["CoursePlanOut"];
export type CourseUpdateOut = Schemas["CourseUpdateOut"];
export type CourseIn = Schemas["CourseIn"];
export type Adherence = CourseOut["adherence"];
export type MaterialRole = NonNullable<Schemas["MaterialIn"]["role"]>;

export const studiesKey = (pathId: string) => ["paths", pathId, "studies"] as const;

const BUSY = new Set(["uploading", "reading", "transcribing", "digesting", "outlining"]);
const POLL_MS = 2500;

export const isRecording = (m: MaterialOut) => m.kind === "audio" || m.kind === "video";

/** A recording read but not transcribed yet: it waits for the ones before it. */
export const awaitsTranscription = (m: MaterialOut) => isRecording(m) && m.state === "read" && m.chunks === 0;

/** Still working: files being read or transcribed, or a plan being written: the view polls. */
export function studiesBusy(s: StudiesOut | undefined): boolean {
  if (!s) return false;
  if (s.arrange?.status === "working") return true;
  if (s.status === "drafting" || s.status === "revising") return !s.links_failed || s.status === "revising";
  return s.courses.some(
    (c) =>
      c.plan?.status === "revising" ||
      c.plan?.status === "drafting" ||
      c.materials.some((m) => (BUSY.has(m.state) && m.state !== "uploading") || awaitsTranscription(m)),
  );
}

export function useStudies(pathId: string, enabled = true) {
  return useQuery({
    queryKey: studiesKey(pathId),
    queryFn: () => unwrap(api.GET("/api/studies/{path_id}", { params: { path: { path_id: pathId } } })),
    enabled,
    refetchInterval: (q) => (studiesBusy(q.state.data) ? POLL_MS : false),
    staleTime: 0,
  });
}

export function useCreateStudies() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["StudiesIn"]) => unwrap(api.POST("/api/studies", { body })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.paths }),
  });
}

function useRefresh(pathId: string) {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: studiesKey(pathId) });
    void qc.invalidateQueries({ queryKey: keys.path(pathId) });
  };
}

export function useStudiesStep(pathId: string) {
  const qc = useQueryClient();
  const refresh = useRefresh(pathId);
  return useMutation({
    mutationFn: (step: "start" | "build" | "links") => {
      const params = { path: { path_id: pathId } };
      if (step === "start") return unwrap(api.POST("/api/studies/{path_id}/start", { params }));
      if (step === "build") return unwrap(api.POST("/api/studies/{path_id}/build", { params }));
      return unwrap(api.POST("/api/studies/{path_id}/links/retry", { params }));
    },
    onSuccess: (data) => {
      qc.setQueryData(studiesKey(pathId), data);
      refresh();
      void qc.invalidateQueries({ queryKey: keys.paths });
    },
  });
}

export function useAddCourse(pathId: string) {
  const refresh = useRefresh(pathId);
  return useMutation({
    mutationFn: (body: CourseIn) =>
      unwrap(api.POST("/api/studies/{path_id}/courses", { params: { path: { path_id: pathId } }, body })),
    onSuccess: refresh,
  });
}

export function useCourseChange(pathId: string) {
  const refresh = useRefresh(pathId);
  return useMutation({
    mutationFn: ({ id, change }: { id: string; change: Schemas["CourseChangeIn"] }) =>
      unwrap(api.PATCH("/api/courses/{course_id}", { params: { path: { course_id: id } }, body: change })),
    onSuccess: refresh,
  });
}

export function useArchiveCourse(pathId: string) {
  const refresh = useRefresh(pathId);
  return useMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/api/courses/{course_id}", { params: { path: { course_id: id } } })),
    onSuccess: refresh,
  });
}

export function useCourseStep(pathId: string) {
  const refresh = useRefresh(pathId);
  return useMutation({
    mutationFn: ({ id, step, text = "" }: { id: string; step: "feedback" | "undo" | "retry"; text?: string }) => {
      const params = { path: { course_id: id } };
      if (step === "feedback") return unwrap(api.POST("/api/courses/{course_id}/feedback", { params, body: { text } }));
      if (step === "undo") return unwrap(api.POST("/api/courses/{course_id}/undo", { params }));
      return unwrap(api.POST("/api/courses/{course_id}/retry", { params }));
    },
    onSuccess: refresh,
  });
}

/** Yes or no to what new files add to a built course. */
export function useCourseUpdate(pathId: string) {
  const refresh = useRefresh(pathId);
  return useMutation({
    mutationFn: ({ courseId, updateId, accept }: { courseId: string; updateId: string; accept: boolean }) => {
      const params = { path: { course_id: courseId, update_id: updateId } };
      return accept
        ? unwrap(api.POST("/api/courses/{course_id}/updates/{update_id}/apply", { params }))
        : unwrap(api.POST("/api/courses/{course_id}/updates/{update_id}/dismiss", { params }));
    },
    onSuccess: refresh,
  });
}

export function useMaterialChange(pathId: string) {
  const refresh = useRefresh(pathId);
  return useMutation({
    mutationFn: ({ id, role, title }: { id: string; role?: MaterialRole; title?: string }) =>
      unwrap(api.PATCH("/api/materials/{material_id}", { params: { path: { material_id: id } }, body: { role, title } })),
    onSuccess: refresh,
  });
}

/** Read a PDF's pages with little text (formulas, figures) from their images, with the generation model. */
export function useReadPages(pathId: string) {
  const refresh = useRefresh(pathId);
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.POST("/api/materials/{material_id}/read-pages", { params: { path: { material_id: id } } })),
    onSuccess: refresh,
  });
}

/** Ask for the path's name and courses, proposed from the files added so far, or for a change to them. */
export function useArrange(pathId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (feedback: string | null) =>
      unwrap(api.POST("/api/studies/{path_id}/arrange", { params: { path: { path_id: pathId } }, body: { feedback } })),
    onSuccess: (data) => qc.setQueryData(studiesKey(pathId), data),
  });
}

/** Take the proposed courses: they are made and the files move into them. */
export function useAcceptArrangement(pathId: string) {
  const qc = useQueryClient();
  const refresh = useRefresh(pathId);
  return useMutation({
    mutationFn: (body: Schemas["ArrangeAcceptIn"]) =>
      unwrap(api.POST("/api/studies/{path_id}/arrange/accept", { params: { path: { path_id: pathId } }, body })),
    onSuccess: (data) => {
      qc.setQueryData(studiesKey(pathId), data);
      refresh();
      void qc.invalidateQueries({ queryKey: keys.paths });
    },
  });
}

/** Read or transcribe a file that failed again, from what was uploaded. */
export function useRetryMaterial(pathId: string) {
  const refresh = useRefresh(pathId);
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.POST("/api/materials/{material_id}/retry", { params: { path: { material_id: id } } })),
    onSuccess: refresh,
  });
}

export function useDeleteMaterial(pathId: string) {
  const refresh = useRefresh(pathId);
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/api/materials/{material_id}", { params: { path: { material_id: id } } })),
    onSuccess: refresh,
  });
}

/** A part of a file per request: small enough for any proxy, large enough to be quick. */
export const PART = 8 * 1024 * 1024;
const RETRIES = 5;

/**
 * Upload one file in parts. A dropped connection resumes from the bytes the server has (it answers 409 with
 * the offset it expects); `onProgress` gets the bytes received so far.
 */
export async function uploadFile(
  courseId: string,
  file: File,
  onProgress: (received: number, material: MaterialOut) => void,
  signal?: AbortSignal,
): Promise<MaterialOut> {
  let m = await unwrap(
    api.POST("/api/courses/{course_id}/materials", {
      params: { path: { course_id: courseId } },
      body: { file_name: file.name, size: file.size },
    }),
  );
  onProgress(0, m);
  let offset = 0;
  let failures = 0;
  while (offset < file.size) {
    const part = file.slice(offset, offset + PART);
    let res: Response;
    try {
      res = await globalThis.fetch(new URL(`/api/materials/${m.id}/upload?offset=${offset}`, location.origin), {
        method: "PUT",
        body: part,
        headers: { [CSRF_HEADER]: "1", "content-type": "application/octet-stream" },
        credentials: "same-origin",
        signal,
      });
    } catch (e) {
      if (signal?.aborted || ++failures > RETRIES) throw e;
      await new Promise((r) => setTimeout(r, 1000 * failures));
      offset = await receivedSoFar(m.id, offset);
      continue;
    }
    if (res.status === 409) {
      offset = await receivedSoFar(m.id, offset);
      continue;
    }
    if (!res.ok) {
      let detail: unknown = null;
      try {
        detail = ((await res.json()) as { detail?: unknown }).detail;
      } catch {
        // not JSON
      }
      throw new ApiError(res.status, detail);
    }
    m = (await res.json()) as MaterialOut;
    offset = m.received;
    failures = 0;
    onProgress(offset, m);
  }
  return m;
}

async function receivedSoFar(id: string, fallback: number): Promise<number> {
  try {
    const m = await unwrap(api.GET("/api/materials/{material_id}", { params: { path: { material_id: id } } }));
    return m.received;
  } catch {
    return fallback;
  }
}

export const ACCEPT =
  ".pdf,.pptx,.docx,.md,.txt,.mp3,.m4a,.wav,.ogg,.opus,.flac,.aac,.mp4,.mkv,.mov,.webm,.avi,.m4v";
