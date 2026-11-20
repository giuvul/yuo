import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { ProbeOut, RecommendationOut } from "../api/client";
import { activateLocale } from "../i18n";
import { json, mockApi } from "../test/mockApi";
import { appRoutes, cliReady, cliStatus, configuredSetup, meState, renderApp } from "../test/renderApp";
import { applyTheme, THEME_KEY } from "../theme";

beforeAll(async () => {
  await activateLocale("en");
});
afterEach(() => {
  vi.unstubAllGlobals();
  applyTheme("system");
});

const fresh = { probed: false, models_chosen: false, profile_done: false, has_path: false, done: false };

const probe = (patch: Partial<ProbeOut> = {}): ProbeOut => ({
  os: "windows",
  os_version: "11",
  arch: "x64",
  cpu: "AMD Ryzen 7",
  cores: 8,
  memory_gb: 32,
  gpus: [],
  disk_free_gb: 412.4,
  clis: {},
  servers: [],
  bench: { cpu_gflops: 351.2, seconds: 1.5 },
  ...patch,
});

const estimate = (low: number, high: number, notional: number) => ({
  low_usd: low,
  high_usd: high,
  notional_usd: notional,
  missing: [],
  lines: [],
  plan_usage:
    notional > 5
      ? [
          {
            cli: "claude-cli",
            plan: "pro",
            label: "Pro",
            window_pct: 52.4,
            week_pct: 3.67,
            lessons_per_window: 38,
            lessons_per_week: 545,
          },
          {
            cli: "claude-cli",
            plan: "max20x",
            label: "Max 20x",
            window_pct: 2.2,
            week_pct: 0.36,
            lessons_per_window: 913,
            lessons_per_week: 5562,
          },
        ]
      : [],
  lessons: 20,
});

const ESTIMATES = {
  claude: estimate(0, 0, 5.76),
  codex: estimate(0, 0, 4.1),
  local: estimate(0, 0, 0),
  open: estimate(0.57, 2.14, 2.14),
};

function recommendation(
  r: Pick<RecommendationOut, "preset" | "reasons" | "needs" | "alternatives">,
  p: ProbeOut,
): RecommendationOut {
  return { ...r, options: [r.preset, ...r.alternatives].map((x) => ({ preset: x, estimate: ESTIMATES[x] })), probe: p };
}

type State = {
  waitlist?: string;
  onboarding: typeof fresh;
  access: {
    openrouter: boolean;
    local_url: string | null;
    local: boolean;
    clis: string[];
    consent: Record<string, boolean>;
  };
};

function wizardRoutes(rec: () => RecommendationOut, state: State, extra: Parameters<typeof mockApi>[0] = {}) {
  return mockApi({
    ...appRoutes,
    "GET /api/setup": () => json({ ...configuredSetup, bindings: {} }),
    "GET /api/paths": () => json([]),
    "GET /api/onboarding": () => json(state.onboarding),
    "POST /api/setup/probe": () => {
      state.onboarding = { ...state.onboarding, probed: true };
      return json(rec().probe);
    },
    "GET /api/setup/recommendation": () => json(rec()),
    "GET /api/setup/access": () => json(state.access),
    "POST /api/setup/preset": (_r, body) => {
      state.onboarding = { ...state.onboarding, models_chosen: true };
      return json({
        ...configuredSetup,
        waitlist_url: state.waitlist ?? null,
        warnings:
          (body as { preset: string }).preset === "claude" ? ["The reviewer is the same model as the writer."] : [],
      });
    },
    "GET /api/setup/consent/claude": () => json({ cli: "claude", version: 2, text: "English original" }),
    "GET /api/settings": () => json([]),
    "PUT /api/settings/video.source": () => new Response(null, { status: 204 }),
    "PUT /api/settings/video.format": () => new Response(null, { status: 204 }),
    ...extra,
  });
}

const user = () => userEvent.setup();

describe("environment wizard", () => {
  it("probes, recommends Claude with its reasons and an estimate for every option, and asks for consent", async () => {
    const p = probe({
      clis: { claude: "2.1.0" },
      servers: [{ name: "ollama", url: "http://127.0.0.1:11434/v1", models: ["nomic-embed-text"] }],
    });
    const rec = recommendation(
      {
        preset: "claude",
        reasons: [{ code: "cli_found", values: { cli: "claude" } }],
        needs: ["consent"],
        alternatives: ["open"],
      },
      p,
    );
    const state: State = {
      onboarding: { ...fresh },
      access: { openrouter: false, local_url: null, local: false, clis: ["claude"], consent: {} },
    };
    const { calls } = wizardRoutes(() => rec, state, {
      "GET /api/setup/cli/claude": () => json(cliReady()),
    });
    const u = user();
    const { router } = renderApp("/");

    await waitFor(() => expect(router.state.location.pathname).toBe("/setup"));
    expect(await screen.findByRole("heading", { level: 2, name: "Your computer" })).toBeInTheDocument();
    expect(screen.getByText("Step 1 of 6")).toBeInTheDocument();
    expect(screen.getByText(/Nothing leaves this computer/)).toBeInTheDocument();
    const steps = screen.getByRole("navigation", { name: "Setup steps" });
    expect(within(steps).getAllByRole("listitem")).toHaveLength(6);
    expect(within(steps).getByText("Your computer").closest("li")).toHaveAttribute("aria-current", "step");

    expect(await screen.findByText("Windows 11")).toBeInTheDocument();
    expect(screen.getByText("32 GB")).toBeInTheDocument();
    expect(screen.getByText("None found that can run AI models")).toBeInTheDocument();
    expect(screen.getByText("412 GB")).toBeInTheDocument();
    expect(screen.getByText("Found (version 2.1.0)")).toBeInTheDocument();
    expect(screen.getByText("Not found")).toBeInTheDocument(); // Codex
    expect(screen.getByText(/Ollama:/)).toHaveTextContent("Ollama: 1 model");
    expect(screen.getByText("About 351 billion calculations a second")).toBeInTheDocument();
    expect(calls.filter((c) => c.path === "/api/setup/probe")).toHaveLength(1);
    await u.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByRole("heading", { level: 2, name: "Recommendation" })).toBeInTheDocument();
    expect(await screen.findByText(/The Claude Code app is on this computer/)).toBeInTheDocument();
    const claude = screen.getByRole("radio", { name: /Claude \(your Claude Code subscription\)/ });
    expect(claude).toBeChecked();
    expect(screen.getByTestId("estimate-claude")).toHaveTextContent(
      "For a typical 20-lesson path: no extra cost, it uses part of your plan's limits:" +
        "Pro: about 38 lessons per 5-hour window; the whole path takes 4% of the weekMax 20x: about 913 lessons per 5-hour window; the whole path takes under 1% of the week",
    );
    expect(screen.getByTestId("estimate-claude")).not.toHaveTextContent("$");
    expect(screen.getByTestId("estimate-open")).toHaveTextContent(
      "For a typical 20-lesson path: about $0.57 to $2.14, billed to you.",
    );
    expect(screen.getByText("Recommended")).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByRole("heading", { level: 2, name: "AI access" })).toBeInTheDocument();
    expect(screen.getByText(/Yuo will run the Claude Code app installed on this computer/)).toBeInTheDocument();
    const apply = screen.getByRole("button", { name: "Use this and continue" });
    expect(apply).toBeDisabled();
    await u.click(screen.getByRole("checkbox", { name: "I agree" }));
    await u.click(apply);
    expect(
      await screen.findByText("Done. Yuo uses Claude (your Claude Code subscription) from now on."),
    ).toBeInTheDocument();
    expect(screen.getByText("The reviewer is the same model as the writer.")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/setup/preset")?.body).toEqual({ preset: "claude", consent: true });
    // the program is asked about once the preset is saved; found and signed in, so the way on is open
    expect(screen.queryByTestId("not-installed-claude")).toBeNull();
    expect(
      await screen.findByRole("heading", { name: "Claude Code is installed and signed in" }),
    ).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByRole("heading", { level: 2, name: "About you" })).toBeInTheDocument();
    expect(screen.getByText("Step 4 of 6")).toBeInTheDocument();
  });

  it("lets a learner pick a subscription whose program is missing, then holds the step until it is ready", async () => {
    const p = probe(); // no Claude Code, no Codex on this computer
    const rec = recommendation(
      { preset: "open", reasons: [{ code: "no_subscription", values: {} }], needs: [], alternatives: ["claude", "codex"] },
      p,
    );
    const state: State = {
      onboarding: { ...fresh, probed: true },
      access: { openrouter: true, local_url: null, local: false, clis: [], consent: {} },
    };
    let status = cliStatus();
    const { calls } = wizardRoutes(() => rec, state, {
      "GET /api/setup/cli/claude": (request) => {
        // "Check again" (fresh) after the learner installed and signed in by hand
        if (new URL(request.url).searchParams.get("fresh") === "true") status = cliReady();
        return json(status);
      },
    });
    const u = user();
    renderApp("/setup");

    expect(await screen.findByRole("heading", { level: 2, name: "Recommendation" })).toBeInTheDocument();
    // listed, not hidden, and it says what will happen
    const claude = await screen.findByRole("radio", { name: /Claude \(your Claude Code subscription\)/ });
    expect(screen.getByTestId("not-installed-claude")).toHaveTextContent(
      "Its program is not on this computer yet. Yuo will help you install it.",
    );
    expect(screen.getByTestId("not-installed-codex")).toBeInTheDocument();
    await u.click(claude);
    await u.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByRole("heading", { level: 2, name: "AI access" })).toBeInTheDocument();
    expect(screen.queryByTestId("cli-claude")).toBeNull(); // consent first
    expect(calls.some((c) => c.path.startsWith("/api/setup/cli/"))).toBe(false);
    await u.click(screen.getByRole("checkbox", { name: "I agree" }));
    await u.click(screen.getByRole("button", { name: "Use this and continue" }));
    expect(calls.find((c) => c.path === "/api/setup/preset")?.body).toEqual({ preset: "claude", consent: true });

    expect(await screen.findByRole("heading", { name: "Claude Code is not installed yet" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Install Claude Code" })).toBeInTheDocument();
    const next = screen.getByRole("button", { name: "Next" });
    expect(next).toBeDisabled();
    expect(next).toHaveAccessibleDescription("Install Claude Code to go on.");

    await u.click(screen.getByRole("button", { name: "Do it yourself" }));
    await u.click(screen.getByRole("button", { name: "Check again" }));
    expect(
      await screen.findByRole("heading", { name: "Claude Code is installed and signed in" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Install Claude Code to go on.")).toBeNull();
    await u.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByRole("heading", { level: 2, name: "About you" })).toBeInTheDocument();
  });

  it("holds a signed-out program at the access step, and lets a program that cannot say go on", async () => {
    const p = probe({ clis: { codex: "0.42.0" } });
    const rec = recommendation(
      { preset: "codex", reasons: [{ code: "cli_found", values: { cli: "codex" } }], needs: [], alternatives: ["open"] },
      p,
    );
    const state: State = {
      onboarding: { ...fresh, probed: true },
      access: { openrouter: false, local_url: null, local: false, clis: ["codex"], consent: { codex: true } },
    };
    const codex = { cli: "codex" as const, name: "Codex", can_install: false, can_login: false, code_login: false };
    let status = cliStatus({ ...codex, installed: true, logged_in: false, reason: "not_logged_in", login_command: "codex login" });
    wizardRoutes(() => rec, state, {
      "GET /api/setup/cli/codex": (request) => {
        if (new URL(request.url).searchParams.get("fresh") === "true") {
          status = { ...status, logged_in: null, ready: true, reason: null };
        }
        return json(status);
      },
    });
    const u = user();
    renderApp("/setup");

    expect(await screen.findByRole("heading", { level: 2, name: "Recommendation" })).toBeInTheDocument();
    await screen.findByRole("radio", { name: /Codex/ });
    expect(screen.queryByTestId("not-installed-codex")).toBeNull();
    await u.click(screen.getByRole("button", { name: "Next" }));
    await u.click(await screen.findByRole("button", { name: "Use this and continue" }));

    expect(await screen.findByRole("heading", { name: "Codex is installed, but not signed in" })).toBeInTheDocument();
    const next = screen.getByRole("button", { name: "Next" });
    expect(next).toBeDisabled();
    expect(next).toHaveAccessibleDescription("Sign in to Codex to go on.");
    await u.click(screen.getByRole("button", { name: "Check again" }));
    expect(await screen.findByText(/Yuo could not confirm the sign-in; it will try/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
  });

  it("explains how to get the local model and connects once the probe finds it", async () => {
    const gpu = { name: "NVIDIA GeForce RTX 4090", memory_gb: 24, kind: "nvidia" };
    let p = probe({ gpus: [gpu] });
    const rec = () =>
      recommendation(
        {
          preset: "local",
          reasons: [
            { code: "no_subscription", values: {} },
            { code: "gpu_memory", values: { gb: 24, min: 24 } },
            { code: "local_free", values: {} },
          ],
          needs: p.servers.length ? [] : ["local_server", "local_model"],
          alternatives: ["open"],
        },
        p,
      );
    const state: State = {
      onboarding: { ...fresh, probed: true },
      access: { openrouter: false, local_url: null, local: false, clis: [], consent: {} },
    };
    const { calls } = wizardRoutes(rec, state, {
      "PUT /api/setup/access/local": () => {
        state.access = { ...state.access, local: true, local_url: "http://127.0.0.1:11434/v1" };
        return json({ models: ["qwen3.8:27b"] });
      },
    });
    const u = user();
    renderApp("/setup");

    expect(await screen.findByRole("heading", { level: 2, name: "Recommendation" })).toBeInTheDocument(); // resumed
    expect(
      await screen.findByText(/Your graphics card has 24 GB of memory. The model needs 24 GB/),
    ).toBeInTheDocument();
    expect(screen.getByText("Running the model on your computer costs nothing per use.")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Qwen 3.8 27B on this computer/ })).toBeChecked();
    expect(screen.getByTestId("estimate-local")).toHaveTextContent("For a typical 20-lesson path: no cost per use.");
    expect(screen.getByTestId("estimate-open")).toHaveTextContent("$0.57 to $2.14");
    await u.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText(/Yuo uses the free Ollama app. It is not running yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /ollama.com\/download/ })).toHaveAttribute("target", "_blank");
    expect(screen.getByText(/find the model qwen3.8:27b and download it. It is about 18 GB/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/terminal|ollama pull|command/i);
    expect(screen.getByRole("button", { name: "Use this and continue" })).toBeDisabled();

    p = probe({
      gpus: [gpu],
      servers: [{ name: "ollama", url: "http://127.0.0.1:11434/v1", models: ["qwen3.8:27b"] }],
    });
    await u.click(screen.getByRole("button", { name: "Check again" }));
    expect(await screen.findByText("The Ollama app is running and has the model qwen3.8:27b.")).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Use this and continue" }));
    expect(await screen.findByText(/Done. Yuo uses Qwen 3.8 27B on this computer/)).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/setup/access/local")?.body).toEqual({ url: "http://127.0.0.1:11434/v1" });
    expect(calls.find((c) => c.path === "/api/setup/preset")?.body).toEqual({ preset: "local", consent: false });
    const order = calls.map((c) => c.path);
    expect(order.indexOf("/api/setup/access/local")).toBeLessThan(order.indexOf("/api/setup/preset"));
  });

  it("takes an OpenRouter key (refused, malformed, then accepted), the profile with the theme, and the first path", async () => {
    const p = probe();
    const rec = () =>
      recommendation(
        {
          preset: "open",
          reasons: [
            { code: "no_subscription", values: {} },
            { code: "no_gpu", values: {} },
            { code: "api_billed", values: {} },
          ],
          needs: state.access.openrouter ? [] : ["openrouter_key"],
          alternatives: [],
        },
        p,
      );
    const state: State = {
      waitlist: "https://waitlist.example/yuo",
      onboarding: { ...fresh, probed: true },
      access: { openrouter: false, local_url: null, local: false, clis: [], consent: {} },
    };
    let me = { ...meState, tz: "UTC", display_name: "Learner" };
    const { calls } = wizardRoutes(rec, state, {
      "PUT /api/setup/access/openrouter": (_r, body) => {
        const key = (body as { key: string }).key;
        if (!key.startsWith("sk-or-")) return json({ detail: "that does not look like an OpenRouter key" }, 422);
        if (key !== "sk-or-v1-good") return json({ detail: "openrouter: the key was refused", kind: "auth" }, 400);
        state.access = { ...state.access, openrouter: true };
        return json({ limit_remaining: 4.5, free_tier: false });
      },
      "GET /api/me": () => json(me),
      "PATCH /api/me": (_r, body) => {
        me = { ...me, ...(body as object) };
        state.onboarding = { ...state.onboarding, profile_done: true };
        return json(me);
      },
      "GET /api/setup": () => json({ ...configuredSetup, waitlist_url: "https://waitlist.example/yuo" }),
      "GET /api/estimate": () => json({ low_usd: 0.57, high_usd: 2.14, notional_usd: 2.14, missing: [], lines: [] }),
      "POST /api/paths": () => {
        state.onboarding = { ...state.onboarding, has_path: true };
        return json({ path_id: "p1", job_id: "j1" });
      },
      "POST /api/onboarding/done": () => {
        state.onboarding = { ...state.onboarding, done: true };
        return json(state.onboarding);
      },
      "GET /api/paths/p1": () =>
        json({
          id: "p1",
          title: "Spanish",
          subject: "Spanish",
          status: "planning",
          difficulty: "foundational",
          content_lang: "en",
          goal: "",
          lessons: [],
          skills: [],
          jobs: [],
        }),
    });
    const u = user();
    const { router } = renderApp("/setup");

    expect(await screen.findByText(/OpenRouter charges your OpenRouter account/)).toBeInTheDocument();
    expect(screen.getByText(/no graphics card that can run the model/)).toBeInTheDocument();
    expect(screen.getByTestId("estimate-open")).toHaveTextContent(
      "For a typical 20-lesson path: about $0.57 to $2.14, billed to you.",
    );
    await u.click(screen.getByRole("button", { name: "Next" }));

    const link = await screen.findByRole("link", { name: /openrouter.ai\/keys/ });
    expect(link).toHaveAttribute("href", "https://openrouter.ai/keys");
    expect(link).toHaveAttribute("target", "_blank");
    const field = screen.getByLabelText(/^OpenRouter key/);
    expect(field).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: "Use this and continue" })).toBeDisabled();

    await u.type(field, "sk-or-v1-wrong");
    await u.click(screen.getByRole("button", { name: "Check and save the key" }));
    expect(await screen.findByText(/OpenRouter did not accept this key/)).toBeInTheDocument();
    await u.clear(field);
    await u.type(field, "not-a-key-at-all");
    await u.click(screen.getByRole("button", { name: "Check and save the key" }));
    expect(
      await screen.findByText(/That does not look like an OpenRouter key. It starts with sk-or-./),
    ).toBeInTheDocument();
    await u.clear(field);
    await u.type(field, "sk-or-v1-good");
    await u.click(screen.getByRole("button", { name: "Check and save the key" }));
    expect(await screen.findByText("Credit left on this key: $4.50")).toBeInTheDocument();
    expect(field).toHaveValue(""); // never shown again

    await waitFor(() => expect(screen.getByRole("button", { name: "Use this and continue" })).toBeEnabled());
    await u.click(screen.getByRole("button", { name: "Use this and continue" }));
    await u.click(await screen.findByRole("button", { name: "Next" }));

    // about you: the time zone comes from the browser when the stored one is UTC; the theme applies at once
    expect(await screen.findByRole("heading", { level: 2, name: "About you" })).toBeInTheDocument();
    const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    expect(screen.getByRole("combobox", { name: "Time zone" })).toHaveValue(browserTz);
    expect(screen.getByText(/sent with every lesson request as information about you/)).toBeInTheDocument();
    await u.click(screen.getByRole("radio", { name: "Dark" }));
    expect(document.documentElement.dataset["theme"]).toBe("dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ theme: "dark" }));

    const name = screen.getByRole("textbox", { name: "Your name" });
    await u.clear(name);
    await u.type(name, "Ada");
    await u.click(screen.getByRole("button", { name: "Session length and interests (optional)" }));
    await u.type(screen.getByRole("textbox", { name: /Your interests/ }), "cycling");
    await u.click(screen.getByRole("button", { name: "Save and continue" }));

    // videos: YouTube first and chosen, with what the learner takes on; a renderer here offers Yuo's own too
    expect(await screen.findByRole("heading", { level: 2, name: "Videos" })).toBeInTheDocument();
    expect(await screen.findByRole("radio", { name: /Videos from YouTube/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Videos made by Yuo/ })).toBeInTheDocument();
    expect(screen.getByText(/You use this at your own risk/)).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Save and continue" }));
    expect(await screen.findByRole("heading", { level: 2, name: "Your first path" })).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/settings/video.source")?.body).toEqual({ value: "youtube", level: "learner" });
    expect(calls.filter((c) => c.method === "PATCH").at(-1)?.body).toEqual({
      display_name: "Ada",
      content_lang: "en",
      ui_lang: "en",
      tz: browserTz,
      session_minutes: 20,
      interests: "cycling",
    });

    // the first path, with the estimate for the bound models, and the optional hosted-version note
    const waitlist = screen.getByRole("link", { name: /Tell us you are interested/ });
    expect(waitlist).toHaveAttribute("href", "https://waitlist.example/yuo");
    expect(waitlist).toHaveAttribute("target", "_blank");
    expect(await screen.findByText(/Estimated cost for 20 lessons/)).toBeInTheDocument();
    await u.type(screen.getByRole("textbox", { name: "Title" }), "Spanish");
    await u.type(screen.getByRole("textbox", { name: "Your goal" }), "Order food");
    await u.click(screen.getByRole("button", { name: "Create path" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/paths/p1"));
    expect(calls.some((c) => c.path === "/api/onboarding/done" && c.method === "POST")).toBe(true);
  });

  it("shows no hosted-version note without a waitlist address, and resumes at the first open milestone", async () => {
    const p = probe();
    const rec = () => recommendation({ preset: "open", reasons: [], needs: [], alternatives: [] }, p);
    const state: State = {
      onboarding: { probed: true, models_chosen: true, profile_done: true, has_path: false, done: false },
      access: { openrouter: true, local_url: null, local: false, clis: [], consent: {} },
    };
    wizardRoutes(rec, state, {
      "GET /api/setup": () => json(configuredSetup),
      "GET /api/estimate": () => json({ low_usd: 0.5, high_usd: 2, notional_usd: 2, missing: [], lines: [] }),
    });
    const u = user();
    renderApp("/setup");
    expect(await screen.findByRole("heading", { level: 2, name: "Videos" })).toBeInTheDocument();
    expect(screen.getByText("Step 5 of 6")).toBeInTheDocument();
    await u.click(await screen.findByRole("radio", { name: /No videos/ }));
    expect(screen.queryByText(/You use this at your own risk/)).toBeNull();
    await u.click(screen.getByRole("button", { name: "Save and continue" }));
    expect(await screen.findByRole("heading", { level: 2, name: "Your first path" })).toBeInTheDocument();
    expect(screen.getByText("Step 6 of 6")).toBeInTheDocument();
    expect(await screen.findByText(/Estimated cost for 20 lessons/)).toBeInTheDocument();
    expect(screen.queryByText(/hosted version/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Finish without a new path" })).not.toBeInTheDocument();
  });
});

describe("answers an AI assistant collected (SETUP.md)", () => {
  const answers = {
    profile: { display_name: "Sam", content_lang: "it", tz: "Europe/Rome", interests: "cycling, cooking" },
    first_path: {
      title: "Statistics for A/B tests",
      goal: "Read and design A/B tests at work",
      goal_type: "practical",
      custom_instructions: "I know basic SQL.",
    },
  };

  it("starts About you from them, and starts empty once the learner says so", async () => {
    const p = probe();
    const rec = () => recommendation({ preset: "open", reasons: [], needs: [], alternatives: [] }, p);
    const state: State = {
      onboarding: { probed: true, models_chosen: true, profile_done: false, has_path: false, done: false },
      access: { openrouter: true, local_url: null, local: false, clis: [], consent: {} },
    };
    const api = wizardRoutes(rec, state, {
      "GET /api/me": () => json({ ...meState, display_name: "Learner", ui_lang: "en", tz: "UTC" }),
      "GET /api/setup/answers": () => json(answers),
      "DELETE /api/setup/answers": () => new Response(null, { status: 204 }),
    });
    renderApp("/setup");
    expect(await screen.findByRole("heading", { level: 2, name: "About you" })).toBeInTheDocument();
    expect(await screen.findByText(/Filled in from the answers your AI assistant collected/)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /name/i })).toHaveValue("Sam");
    expect(screen.getByRole("combobox", { name: "Time zone" })).toHaveValue("Europe/Rome");
    expect(screen.getByRole("textbox", { name: /interests/i })).toHaveValue("cycling, cooking"); // opened

    await user().click(screen.getByRole("button", { name: "Start empty instead" }));
    await waitFor(() => expect(screen.queryByText(/Filled in from the answers/)).not.toBeInTheDocument());
    expect(screen.getByRole("textbox", { name: /name/i })).toHaveValue("Learner");
    expect(api.calls.some((c) => c.method === "DELETE" && c.path === "/api/setup/answers")).toBe(true);
  });

  it("starts the first path from them", async () => {
    const p = probe();
    const rec = () => recommendation({ preset: "open", reasons: [], needs: [], alternatives: [] }, p);
    const state: State = {
      onboarding: { probed: true, models_chosen: true, profile_done: true, has_path: false, done: false },
      access: { openrouter: true, local_url: null, local: false, clis: [], consent: {} },
    };
    wizardRoutes(rec, state, {
      "GET /api/setup": () => json(configuredSetup),
      "GET /api/estimate": () => json({ low_usd: 0.5, high_usd: 2, notional_usd: 2, missing: [], lines: [] }),
      "GET /api/setup/answers": () => json(answers),
    });
    renderApp("/setup");
    await user().click(await screen.findByRole("button", { name: "Save and continue" }));
    expect(await screen.findByRole("heading", { level: 2, name: "Your first path" })).toBeInTheDocument();
    expect(await screen.findByRole("textbox", { name: /Title/ })).toHaveValue("Statistics for A/B tests");
    expect(screen.getByRole("textbox", { name: /Your goal/ })).toHaveValue("Read and design A/B tests at work");
    expect(screen.getByRole("checkbox", { name: /practical|Use it|apply/i })).toBeChecked();
    expect(screen.getByRole("textbox", { name: /Custom instructions/ })).toHaveValue("I know basic SQL.");
  });
});

describe("home and onboarding", () => {
  it("does not trap a learner who already has paths: a link to finish setting up instead", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/onboarding": () =>
        json({ probed: true, models_chosen: true, profile_done: false, has_path: true, done: false }),
      "GET /api/paths": () =>
        json([
          {
            id: "p1",
            title: "SQL",
            subject: "SQL",
            status: "active",
            difficulty: "foundational",
            content_lang: "en",
            created_at: "2026-10-27T10:00:00.000Z",
          },
        ]),
    });
    const { router } = renderApp("/");
    expect(await screen.findByRole("link", { name: "Finish setting up" })).toHaveAttribute("href", "/setup");
    expect(router.state.location.pathname).toBe("/");
  });

  it("leads a new learner without paths to the wizard", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/onboarding": () => json(fresh),
      "GET /api/paths": () => json([]),
      "POST /api/setup/probe": () => json(probe()),
    });
    const { router } = renderApp("/");
    await waitFor(() => expect(router.state.location.pathname).toBe("/setup"));
    expect(await screen.findByRole("heading", { level: 1, name: "Set up Yuo" })).toBeInTheDocument();
  });
});

describe("theme", () => {
  it("sets html[data-theme] for light and dark and removes it for system", () => {
    applyTheme("light");
    expect(document.documentElement.dataset["theme"]).toBe("light");
    applyTheme("dark");
    expect(document.documentElement.dataset["theme"]).toBe("dark");
    applyTheme("system");
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(localStorage.getItem(THEME_KEY)).toBeNull();
  });

  it("applies the theme from the profile on load", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/me": () => json({ ...meState, theme: "dark" }),
      "GET /api/paths": () => json([]),
    });
    renderApp("/");
    await waitFor(() => expect(document.documentElement.dataset["theme"]).toBe("dark"));
  });
});
