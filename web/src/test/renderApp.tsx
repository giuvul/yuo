import "fake-indexeddb/auto";
import { QueryClient } from "@tanstack/react-query";
import { createMemoryHistory } from "@tanstack/react-router";
import { render } from "@testing-library/react";
import type { CliOut } from "../api/client";
import { App } from "../App";
import type { AuthState } from "../auth/api";
import { Outbox } from "../outbox/outbox";
import { createAppRouter } from "../router";
import { json, type Handler } from "./mockApi";

let n = 0;
const live: Outbox[] = [];

/** Closes the outboxes of rendered apps (their retry and grade timers). */
export async function closeApps() {
  while (live.length) await live.pop()?.close();
}

/** Renders the whole app at `path` with a fresh outbox database and no query retries. */
export function renderApp(path: string) {
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }));
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
  const outbox = new Outbox({ dbName: `app-test-${Date.now()}-${++n}` });
  live.push(outbox);
  const view = render(<App router={router} queryClient={queryClient} outbox={outbox} />);
  return { ...view, router, queryClient, outbox };
}

export const configuredSetup = {
  learner_id: "0190f000-0000-7000-8000-0000000000aa",
  bindings: { generator: { adapter: "claude-cli", model: "sonnet" } },
  warnings: [],
  desktop: false,
  waitlist_url: null,
};

export const signedInState: AuthState = {
  signed_in: true,
  desktop: false,
  enrolled: true,
  methods: ["passkey"],
  device_id: "0190f000-0000-7000-8000-0000000000d1",
  recovery_codes_left: 10,
};

const onboardedState = { probed: true, models_chosen: true, profile_done: true, has_path: true, done: true };

export const meState = {
  display_name: "Ada",
  ui_lang: "en",
  content_lang: "en",
  tz: "Europe/Berlin",
  theme: "system" as const,
  session_minutes: 20,
  interests: "",
};

/** Answers for what every screen asks (sign-in state, header: reviews due, jobs). Spread before test routes. */
export const appRoutes: Record<string, Handler> = {
  "GET /api/auth/state": () => json(signedInState),
  "GET /api/setup": () => json(configuredSetup),
  "GET /api/jobs": () => json([]),
  "GET /api/generation/pause": () => json({ paused: false, scope: null, until: null, waiting: 0, finishing: [] }),
  "GET /api/jobs/history": () => json({ jobs: [], next: null }),
  "GET /api/reviews": () => json({ due: 0, allowed_today: 50, item_version_ids: [] }),
  "POST /api/devices": () => json({ device_id: "0190f000-0000-7000-8000-0000000000d1" }),
  "GET /api/nudges": () => json([]),
  "GET /api/onboarding": () => json(onboardedState),
  "GET /api/me": () => json(meState),
  "GET /api/setup/access": () =>
    json({ openrouter: false, local_url: null, local: false, clis: [], consent: {}, vendors: [] }),
  "GET /api/setup/providers": () => json([]),
  "GET /api/setup/plan-meter": () => json({ claude: null, codex: null }),
  "GET /api/setup/ai-ready": () => json({ ready: true, clis: [] }),
  "GET /api/update": () =>
    json({ current: "1.0.0", feed: false, latest: null, published_at: null, notes_url: null, available: false, staged: null, can_install: false, container: false, image: null }),
};

/** A subscription program's status as GET /api/setup/cli/{cli} gives it (Claude Code on Linux, not installed). */
export const cliStatus = (patch: Partial<CliOut> = {}): CliOut => ({
  cli: "claude",
  name: "Claude Code",
  needed: true,
  installed: false,
  version: null,
  logged_in: null,
  account: null,
  ready: false,
  reason: "not_installed",
  detail: null,
  os: "linux",
  container: false,
  can_install: true,
  can_login: true,
  code_login: true,
  install_command: "curl -fsSL https://claude.ai/install.sh | bash",
  login_command: "claude auth login",
  docs_url: "https://docs.claude.com/en/docs/claude-code/setup",
  install: { state: "idle", url: null, code: null, error: null },
  login: { state: "idle", url: null, code: null, error: null },
  ...patch,
});

export const cliSignedOut = (patch: Partial<CliOut> = {}): CliOut =>
  cliStatus({ installed: true, version: "2.1.0", logged_in: false, reason: "not_logged_in", ...patch });

export const cliReady = (patch: Partial<CliOut> = {}): CliOut =>
  cliSignedOut({ logged_in: true, ready: true, reason: null, account: "Max plan", ...patch });
