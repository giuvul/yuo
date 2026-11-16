// The onboarding API (yuo/api/onboarding.py): the machine probe, the recommendation with estimates, AI
// access, subscription consent, the learner's profile, onboarding milestones, updates and the desktop app.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  unwrap,
  ApiError,
  type AccessOut,
  type AiReadyOut,
  type CliId,
  type CliOut,
  type MeIn,
  type MeOut,
  type Preset,
  type ProbeOut,
  type ModelSource,
  type ProviderId,
  type RecommendationOut,
  type UpdateOut,
} from "../api/client";
import { keys } from "../api/hooks";
import { authFetch } from "../auth/api";

export const LOCAL_MODEL = "qwen3.8:27b";
export const LOCAL_DEFAULT_URL = "http://127.0.0.1:11434/v1";

export const m7Keys = {
  probe: ["setup", "probe"] as const,
  recommendation: ["setup", "recommendation"] as const,
  access: ["setup", "access"] as const,
  consent: (cli: string) => ["setup", "consent", cli] as const,
  onboarding: ["onboarding"] as const,
  me: ["me"] as const,
  answers: ["setup", "answers"] as const,
  update: ["update"] as const,
  providers: ["setup", "providers"] as const,
  vendorModels: (provider: string) => ["setup", "vendor-models", provider] as const,
  openRouterModels: ["setup", "openrouter-models"] as const,
  vendorEstimate: (provider: string, main: string, reviewer: string) =>
    ["setup", "estimate-vendor", provider, main, reviewer] as const,
  planMeter: ["setup", "plan-meter"] as const,
  aiReady: ["setup", "ai-ready"] as const,
  cli: (cli: string) => ["setup", "cli", cli] as const,
};

/** Reads this computer (about 2 s on the server). A query, so a re-render or StrictMode runs it once. */
export function useProbe(enabled: boolean) {
  const qc = useQueryClient();
  return useQuery({
    queryKey: m7Keys.probe,
    queryFn: async (): Promise<ProbeOut> => {
      const probe = await unwrap(api.POST("/api/setup/probe"));
      void qc.invalidateQueries({ queryKey: m7Keys.recommendation });
      void qc.invalidateQueries({ queryKey: m7Keys.onboarding });
      return probe;
    },
    enabled,
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  });
}

export function useRecommendation(enabled = true) {
  return useQuery({
    queryKey: m7Keys.recommendation,
    queryFn: () => unwrap(api.GET("/api/setup/recommendation")),
    enabled,
  });
}

export function useAccess() {
  return useQuery({
    queryKey: m7Keys.access,
    queryFn: () => unwrap(api.GET("/api/setup/access")),
    retry: false,
  });
}

export function useConsentText(cli: "claude" | "codex" | null) {
  return useQuery({
    queryKey: m7Keys.consent(cli ?? ""),
    queryFn: () => unwrap(api.GET("/api/setup/consent/{cli}", { params: { path: { cli: cli ?? "claude" } } })),
    enabled: cli !== null,
    staleTime: Number.POSITIVE_INFINITY,
  });
}

function useAccessChanged() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: m7Keys.access });
    void qc.invalidateQueries({ queryKey: m7Keys.recommendation });
  };
}

export function useSetOpenRouterKey() {
  const changed = useAccessChanged();
  return useMutation({
    mutationFn: (key: string) => unwrap(api.PUT("/api/setup/access/openrouter", { body: { key } })),
    onSuccess: changed,
  });
}

export function useRemoveOpenRouterKey() {
  const changed = useAccessChanged();
  return useMutation({
    mutationFn: async () => {
      await unwrap(api.DELETE("/api/setup/access/openrouter") as Promise<{ data?: undefined; error?: unknown; response: Response }>);
    },
    onSuccess: changed,
  });
}

export function useSetLocalServer() {
  const changed = useAccessChanged();
  return useMutation({
    mutationFn: (url: string) => unwrap(api.PUT("/api/setup/access/local", { body: { url } })),
    onSuccess: changed,
  });
}

/** Binds a preset; Claude and Codex need the learner's yes to the consent text (409 without it). */
export function useChoosePreset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ preset, consent = false }: { preset: Preset; consent?: boolean }) =>
      unwrap(api.POST("/api/setup/preset", { body: { preset, consent } })),
    onSuccess: (data) => {
      qc.setQueryData(keys.setup, data);
      void qc.invalidateQueries({ queryKey: ["estimate"] });
      void qc.invalidateQueries({ queryKey: m7Keys.onboarding });
      void qc.invalidateQueries({ queryKey: m7Keys.access });
    },
  });
}

// --- direct vendor keys (yuo/setup/providers.py) ----------------------------------------------------

/** The vendors a learner can use with their own key, with where to get one and whether one is saved. */
export function useProviders() {
  return useQuery({
    queryKey: m7Keys.providers,
    queryFn: () => unwrap(api.GET("/api/setup/providers")),
    retry: false,
  });
}

function useVendorChanged() {
  const qc = useQueryClient();
  const changed = useAccessChanged();
  return () => {
    changed();
    void qc.invalidateQueries({ queryKey: m7Keys.providers });
  };
}

/** Checks a key by listing the vendor's models (free); 400 = refused, 422 = wrong format, 502 = unreachable. */
export function useSetVendorKey() {
  const qc = useQueryClient();
  const changed = useVendorChanged();
  return useMutation({
    mutationFn: ({ provider, key }: { provider: ProviderId; key: string }) =>
      unwrap(api.PUT("/api/setup/access/vendor/{provider}", { params: { path: { provider } }, body: { key } })),
    onSuccess: (data, { provider }) => {
      qc.setQueryData(m7Keys.vendorModels(provider), data);
      changed();
    },
  });
}

export function useRemoveVendorKey() {
  const qc = useQueryClient();
  const changed = useVendorChanged();
  return useMutation({
    mutationFn: async (provider: ProviderId) => {
      await unwrap(
        api.DELETE("/api/setup/access/vendor/{provider}", { params: { path: { provider } } }) as Promise<{
          data?: undefined;
          error?: unknown;
          response: Response;
        }>,
      );
    },
    onSuccess: (_d, provider) => {
      qc.removeQueries({ queryKey: m7Keys.vendorModels(provider) });
      changed();
    },
  });
}

/** The models the saved key may use (the server asks the vendor again). */
export function useVendorModels(provider: ProviderId, enabled = true) {
  return useQuery({
    queryKey: m7Keys.vendorModels(provider),
    queryFn: () => unwrap(api.GET("/api/setup/access/vendor/{provider}/models", { params: { path: { provider } } })),
    enabled,
    retry: false,
    staleTime: 60_000,
  });
}

/** OpenRouter's text models with their prices (its public list, cached by the server for a day). */
export function useOpenRouterModels(enabled = true) {
  return useQuery({
    queryKey: m7Keys.openRouterModels,
    queryFn: () => unwrap(api.GET("/api/setup/access/openrouter/models")),
    enabled,
    retry: false,
    staleTime: 10 * 60_000,
  });
}

/** For the chosen vendor models: a typical path's billed range, before they are bound. */
export function useVendorEstimate(provider: ModelSource, main: string, reviewer: string, lessons = 20) {
  return useQuery({
    queryKey: m7Keys.vendorEstimate(provider, main, reviewer),
    queryFn: () =>
      unwrap(api.GET("/api/setup/estimate-vendor", { params: { query: { provider, main, reviewer, lessons } } })),
    enabled: !!main && !!reviewer,
    retry: false,
    staleTime: 60_000,
  });
}

/** Binds a vendor key's models: `main` for every role, `reviewer` for the reviewer. */
export function useChooseVendorModels() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { provider: ModelSource; main: string; reviewer: string }) =>
      unwrap(api.POST("/api/setup/vendor-models", { body })),
    onSuccess: (data) => {
      qc.setQueryData(keys.setup, data);
      void qc.invalidateQueries({ queryKey: ["estimate"] });
      void qc.invalidateQueries({ queryKey: m7Keys.onboarding });
      void qc.invalidateQueries({ queryKey: m7Keys.access });
    },
  });
}

/** The last plan reading each subscription app reported (the whole account, other devices included). */
export function usePlanMeter(enabled = true) {
  return useQuery({
    queryKey: m7Keys.planMeter,
    queryFn: () => unwrap(api.GET("/api/setup/plan-meter")),
    enabled,
    retry: false,
  });
}

// --- subscription programs: installed? signed in? (yuo/adapters/cli_access.py) ------------------------

const NOTHING_TO_CHECK: AiReadyOut = { ready: true, clis: [] };
/** How often a running install or sign-in is asked about. */
const CLI_POLL_MS = 2_000;

function notManaged(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

/** A program's install or sign-in is under way: its status changes on its own, so it is polled. */
function cliBusy(c: CliOut | null | undefined): boolean {
  if (!c) return false;
  const login = c.login.state;
  const signingIn = login === "running" || login === "waiting_code" || login === "waiting_browser" || login === "waiting_device";
  return c.install.state === "running" || signingIn;
}

/**
 * Can generation start? False when a chosen subscription's program is missing or signed out. A server that
 * does not manage these programs answers 404: then there is nothing to check.
 */
export function useAiReady(enabled = true) {
  return useQuery({
    queryKey: m7Keys.aiReady,
    queryFn: async (): Promise<AiReadyOut> => {
      try {
        return await unwrap(api.GET("/api/setup/ai-ready"));
      } catch (e) {
        if (notManaged(e)) return NOTHING_TO_CHECK;
        throw e;
      }
    },
    enabled,
    retry: false,
    staleTime: 10_000,
  });
}

async function getCli(cli: CliId, fresh: boolean): Promise<CliOut | null> {
  try {
    return await unwrap(
      api.GET("/api/setup/cli/{cli}", { params: { path: { cli }, query: fresh ? { fresh: true } : {} } }),
    );
  } catch (e) {
    if (notManaged(e)) return null;
    throw e;
  }
}

/**
 * One subscription program on the machine that runs Yuo; polled while an install or a sign-in runs.
 * `null`: this server does not manage the programs (404), so there is nothing to check.
 */
export function useCli(cli: CliId | null, initial?: CliOut) {
  const qc = useQueryClient();
  return useQuery({
    queryKey: m7Keys.cli(cli ?? ""),
    queryFn: async () => {
      const before = qc.getQueryData<CliOut | null>(m7Keys.cli(cli ?? ""));
      const now = await getCli(cli ?? "claude", false);
      // it became ready (or stopped being so): what depends on it asks again
      if (before && now && before.ready !== now.ready) void qc.invalidateQueries({ queryKey: m7Keys.aiReady });
      return now;
    },
    enabled: cli !== null,
    initialData: initial,
    retry: false,
    staleTime: 0,
    refetchInterval: (query) => (cliBusy(query.state.data) ? CLI_POLL_MS : false),
  });
}

/** The steps a learner can take for a program; every answer is the program's new status. */
export function useCliActions(cli: CliId) {
  const qc = useQueryClient();
  const path = { params: { path: { cli } } };
  const took = (data: CliOut | null) => {
    qc.setQueryData(m7Keys.cli(cli), data);
    void qc.invalidateQueries({ queryKey: m7Keys.aiReady });
  };
  const install = useMutation({
    mutationFn: () => unwrap(api.POST("/api/setup/cli/{cli}/install", path)),
    onSuccess: took,
  });
  const login = useMutation({
    mutationFn: () => unwrap(api.POST("/api/setup/cli/{cli}/login", path)),
    onSuccess: took,
  });
  const sendCode = useMutation({
    mutationFn: (code: string) => unwrap(api.POST("/api/setup/cli/{cli}/login/code", { ...path, body: { code } })),
    onSuccess: took,
  });
  const cancelLogin = useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/setup/cli/{cli}/login", path)),
    onSuccess: took,
  });
  const check = useMutation({ mutationFn: () => getCli(cli, true), onSuccess: took });
  return { install, login, sendCode, cancelLogin, check };
}

export function useOnboarding(enabled = true) {
  return useQuery({
    queryKey: m7Keys.onboarding,
    queryFn: () => unwrap(api.GET("/api/onboarding")),
    enabled,
    retry: false,
  });
}

export function useFinishOnboarding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/onboarding/done")),
    onSuccess: (data) => qc.setQueryData(m7Keys.onboarding, data),
  });
}

export function useMe(enabled = true) {
  return useQuery({
    queryKey: m7Keys.me,
    queryFn: () => unwrap(api.GET("/api/me")),
    enabled,
    retry: false,
  });
}

/** Answers an AI assistant left for the wizard (SETUP.md); empty when there are none. */
export function useSetupAnswers(enabled = true) {
  return useQuery({
    queryKey: m7Keys.answers,
    queryFn: () => unwrap(api.GET("/api/setup/answers")),
    enabled,
    retry: false,
    staleTime: Infinity, // read once: the steps start from them and the learner changes them there
  });
}

export function useDiscardSetupAnswers() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/setup/answers")),
    onSuccess: () => qc.setQueryData(m7Keys.answers, { profile: null, first_path: null }),
  });
}

export function useUpdateMe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (change: MeIn) => unwrap(api.PATCH("/api/me", { body: change })),
    onSuccess: (me: MeOut) => {
      qc.setQueryData(m7Keys.me, me);
      void qc.invalidateQueries({ queryKey: m7Keys.onboarding });
    },
  });
}

// --- updates ------------------------------------------------------------------------------------

export function useUpdateStatus() {
  return useQuery({
    queryKey: m7Keys.update,
    queryFn: () => unwrap(api.GET("/api/update")),
    retry: false,
  });
}

function useUpdateAction(call: () => Promise<UpdateOut>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: call, onSuccess: (data) => qc.setQueryData(m7Keys.update, data) });
}

export function useCheckForUpdate() {
  return useUpdateAction(() => unwrap(api.POST("/api/update/check")));
}

export function useDownloadUpdate() {
  return useUpdateAction(() => unwrap(api.POST("/api/update/download")));
}

export function useRestartForUpdate() {
  return useMutation({ mutationFn: () => unwrap(api.POST("/api/update/restart")) });
}

/** The version the server answers with; null while it is down (restarting). */
export async function serverVersion(): Promise<string | null> {
  try {
    const res = await globalThis.fetch(new Request(new URL("/api/health", apiBase()), { cache: "no-store" }));
    if (!res.ok) return null;
    const body = (await res.json()) as { version?: unknown };
    return typeof body.version === "string" ? body.version : null;
  } catch {
    return null;
  }
}

function apiBase(): string {
  return typeof location === "undefined" ? "http://localhost" : location.origin;
}

/** Desktop only, so not in the exported OpenAPI document (built without the desktop app). */
export function useQuitDesktop() {
  return useMutation({ mutationFn: () => authFetch<void>("POST", "/api/desktop/quit") });
}

// --- what the chosen option still needs -----------------------------------------------------------

type Need = "consent" | "openrouter_key" | "local_server" | "local_model";

/**
 * What a preset still needs before it can be used, from the probe and the access status: the server's
 * `needs` covers only the recommended preset, the learner may pick another (same rules as recommend.py).
 */
export function needsFor(preset: Preset, probe: ProbeOut, access: AccessOut | undefined): Need[] {
  switch (preset) {
    case "claude":
    case "codex":
      return access?.consent[preset] ? [] : ["consent"];
    case "open":
      return access?.openrouter ? [] : ["openrouter_key"];
    case "local": {
      const server = probe.servers.find((s) => s.name === "ollama");
      const out: Need[] = server ? [] : ["local_server"];
      if (!server?.models.includes(LOCAL_MODEL)) out.push("local_model");
      return out;
    }
  }
}

export type { RecommendationOut };
