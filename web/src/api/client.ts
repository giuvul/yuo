import createClient from "openapi-fetch";
import { sessionLost } from "../auth/session";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type SetupOut = Schemas["SetupOut"];
export type EstimateOut = Schemas["EstimateOut"];
export type PathIn = Schemas["PathIn"];
export type PathOut = Schemas["PathOut"];
export type LevelCheckOut = Schemas["LevelCheckOut"];
export type PreviewOut = Schemas["PreviewOut"];
export type PlanTree = Schemas["PlanTree"];
export type NextOut = Schemas["NextOut"];
export type NextDirection = Schemas["NextDirectionOut"];
export type PathSummary = Schemas["PathSummary"];
export type JobRef = Schemas["JobRef"];
export type JobDone = Schemas["JobDone"];
export type GenerationPause = Schemas["GenerationPause"];
export type PauseIn = Schemas["PauseIn"];
export type LessonRef = Schemas["LessonRef"];
export type LessonOut = Schemas["LessonOut"];
export type AssessmentOut = Schemas["AssessmentOut"];
export type Item = AssessmentOut["items"][number];
export type ItemType = Item["type"];
export type JobStarted = Schemas["JobStarted"];
export type ProgressOut = Schemas["ProgressOut"];
export type SkillProgress = Schemas["SkillProgress"];
export type SkillState = SkillProgress["state"];
export type DueOut = Schemas["DueOut"];
export type NoteOut = Schemas["NoteOut"];
export type RequestRow = Schemas["RequestRow"];
export type RequestIn = Schemas["RequestIn"];
export type SettingOut = Schemas["SettingOut"];
export type JobOut = Schemas["JobOut"];
export type HintOut = Schemas["HintOut"];
export type IncomingEvent = Schemas["IncomingEvent"];
export type IngestOut = Schemas["IngestOut"];
export type Graded = Schemas["Graded"];
export type TutorContextIn = Schemas["TutorContextIn"];
export type TutorContextOut = Schemas["TutorContextOut"];
export type TutorPolicyId = TutorContextOut["policy"];
export type Chip = Schemas["Chip"];
export type ChipKind = Chip["kind"];
export type TutorMessage = Schemas["TutorMessageOut"];
export type TutorTemplate = NonNullable<TutorMessage["template"]>;
export type ConversationOut = Schemas["ConversationOut"];
export type MemoryOut = Schemas["MemoryOut"];
export type MemoryKind = MemoryOut["kind"];
export type ProposalOut = Schemas["ProposalOut"];
export type NudgeOut = Schemas["NudgeOut"];
export type Preset = Schemas["PresetIn"]["preset"];
export type Difficulty = NonNullable<PathIn["difficulty"]>;
export type GoalType = NonNullable<PathIn["goal_type"]>;
// --- the environment wizard, AI access, the learner's profile, updates
export type ProbeOut = Schemas["ProbeOut"];
export type RecommendationOut = Schemas["RecommendationOut"];
export type PresetEstimate = Schemas["PresetEstimateOut"];
export type PlanUsage = Schemas["PlanUsageOut"];
export type Reason = Schemas["ReasonOut"];
export type AccessOut = Schemas["AccessOut"];
export type KeyOut = Schemas["KeyOut"];
export type MeOut = Schemas["MeOut"];
export type SetupAnswersOut = Schemas["SetupAnswersOut"];
export type SetupAnswersProfile = NonNullable<SetupAnswersOut["profile"]>;
export type SetupAnswersPath = NonNullable<SetupAnswersOut["first_path"]>;
export type MeIn = Schemas["MeIn"];
export type Theme = MeOut["theme"];
export type OnboardingOut = Schemas["OnboardingOut"];
export type UpdateOut = Schemas["UpdateOut"];
export type ProviderOut = Schemas["ProviderOut"];
export type ProviderId = ProviderOut["id"];
/** Where chosen models come from: a direct vendor key, or the OpenRouter key (Settings > Your own API keys). */
export type ModelSource = ProviderId | "openrouter";
export type OpenRouterModel = Schemas["OpenRouterModelOut"];
export type MeterOut = Schemas["MeterOut"];
export type PlanMeterOut = Schemas["PlanMeterOut"];
export type CliOut = Schemas["CliOut"];
export type CliId = CliOut["cli"];
export type AiReadyOut = Schemas["AiReadyOut"];

// The dev server proxies /api to the backend; in production the API serves the SPA, so one origin.
// openapi-fetch builds a Request, which needs an absolute URL outside a browser (tests).
const baseUrl = typeof location === "undefined" ? "http://localhost" : location.origin;

export const api = createClient<paths>({
  baseUrl,
  // looked up per call so tests can stub globalThis.fetch after import
  fetch: (request) => globalThis.fetch(request),
});

/** The CSRF header: the server refuses POST/PUT/PATCH/DELETE without it (403). */
export const CSRF_HEADER = "X-Yuo-Request";
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

api.use({
  onRequest({ request }) {
    if (UNSAFE.has(request.method)) request.headers.set(CSRF_HEADER, "1");
    return request;
  },
  onResponse({ request, response }) {
    // a 401 outside the sign-in routes: the session ended (signed out elsewhere, device revoked, expired)
    if (response.status === 401 && !new URL(request.url).pathname.startsWith("/api/auth/")) sessionLost();
    return response;
  },
});

/** What a JSON error body may say beside `detail` (409 `ai_not_ready`: which program, and why). */
type ApiErrorExtra = { code?: string; cli?: string; reason?: string };

/** An HTTP error from the API, with FastAPI's `detail` flattened to text. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  /** a machine-readable kind, e.g. "ai_not_ready" */
  readonly code: string | null;
  readonly cli: string | null;
  readonly reason: string | null;

  constructor(status: number, detail: unknown, extra: ApiErrorExtra = {}) {
    super(detailText(detail) ?? `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.code = extra.code ?? null;
    this.cli = extra.cli ?? null;
    this.reason = extra.reason ?? null;
  }
}

/** A generation start refused because a subscription's program is missing or signed out (409). */
export function isAiNotReady(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 409 && error.code === "ai_not_ready";
}

function extraOf(body: unknown): ApiErrorExtra {
  if (!body || typeof body !== "object") return {};
  const b = body as Record<string, unknown>;
  const text = (v: unknown) => (typeof v === "string" ? v : undefined);
  return { code: text(b["code"]), cli: text(b["cli"]), reason: text(b["reason"]) };
}

function detailText(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : null))
      .filter((m): m is string => m !== null);
    return msgs.length ? msgs.join("; ") : null;
  }
  return null;
}

type FetchResult<T> = { data?: T; error?: unknown; response: Response };

/** Returns the data of a successful call or throws an ApiError. Network failures throw as fetch does. */
export async function unwrap<T>(call: Promise<FetchResult<T>>): Promise<T> {
  const { data, error, response } = await call;
  if (!response.ok || error !== undefined) {
    const detail = error && typeof error === "object" && "detail" in error ? (error as { detail: unknown }).detail : error;
    throw new ApiError(response.status, detail, extraOf(error));
  }
  return data as T;
}
