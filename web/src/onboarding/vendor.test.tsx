import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { ProviderOut, RecommendationOut } from "../api/client";
import { activateLocale } from "../i18n";
import { json, mockApi } from "../test/mockApi";
import { appRoutes, configuredSetup, renderApp } from "../test/renderApp";

beforeAll(async () => {
  await activateLocale("en");
});
afterEach(() => {
  vi.unstubAllGlobals();
});

const anthropic = (connected = false): ProviderOut => ({
  id: "anthropic",
  label: "Anthropic (Claude)",
  keys_url: "https://console.anthropic.com/settings/keys",
  key_prefix: "sk-ant-",
  suggested_main: "claude-sonnet-5-5",
  suggested_reviewer: "claude-opus-5-5",
  connected,
});

const openai = (connected = false): ProviderOut => ({
  id: "openai",
  label: "OpenAI",
  keys_url: "https://platform.openai.com/api-keys",
  key_prefix: "sk-",
  suggested_main: null,
  suggested_reviewer: null,
  connected,
});

const CLAUDE_MODELS = ["claude-haiku-5-5", "claude-opus-5-5", "claude-sonnet-5-5"];

const vendorEstimate = (missing: string[] = []) => ({
  low_usd: 1.2,
  high_usd: 4.8,
  notional_usd: 4.8,
  missing,
  lines: [],
  plan_usage: [],
  lessons: 20,
});

const openEstimate = { ...vendorEstimate(), low_usd: 0.57, high_usd: 2.14 };

function recommendation(): RecommendationOut {
  const probe = {
    os: "windows",
    os_version: "11",
    arch: "x64",
    cpu: "x",
    cores: 8,
    memory_gb: 16,
    gpus: [],
    disk_free_gb: 100,
    clis: {},
    servers: [],
    bench: { cpu_gflops: 100, seconds: 1 },
  };
  return {
    preset: "open",
    reasons: [{ code: "api_billed", values: {} }],
    needs: ["openrouter_key"],
    alternatives: [],
    options: [{ preset: "open", estimate: openEstimate }],
    probe,
  };
}

const UNTESTED = "claude-sonnet-5-5 has not been tested with Yuo; lessons may not come out as expected.";

const user = () => userEvent.setup();

const modelButton = (name: RegExp) => screen.getByRole("button", { name });
const MAIN = /Model that writes lessons and answers$/;
const REVIEWER = /Model that checks lessons$/;

describe("own API key in the wizard", () => {
  it("is the last option, checks the key (refused, malformed, accepted), preselects, estimates and applies", async () => {
    let providers = [anthropic(), openai()];
    let onboarding = { probed: true, models_chosen: false, profile_done: false, has_path: false, done: false };
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/setup": () => json({ ...configuredSetup, bindings: {} }),
      "GET /api/paths": () => json([]),
      "GET /api/onboarding": () => json(onboarding),
      "GET /api/setup/recommendation": () => json(recommendation()),
      "GET /api/setup/providers": () => json(providers),
      "PUT /api/setup/access/vendor/anthropic": (_r, body) => {
        const key = (body as { key: string }).key;
        if (!key.startsWith("sk-ant-")) {
          return json({ detail: "that does not look like a Anthropic (Claude) key (it starts with sk-ant-)" }, 422);
        }
        if (key !== "sk-ant-good") return json({ detail: "anthropic: the key was refused", kind: "auth" }, 400);
        providers = [anthropic(true), openai()];
        return json({ models: CLAUDE_MODELS });
      },
      "GET /api/setup/estimate-vendor": () => json(vendorEstimate(["tutor"])),
      "POST /api/setup/vendor-models": () => {
        onboarding = { ...onboarding, models_chosen: true };
        return json({ ...configuredSetup, warnings: [UNTESTED] });
      },
    });
    const u = user();
    renderApp("/setup");

    expect(await screen.findByRole("heading", { level: 2, name: "Recommendation" })).toBeInTheDocument();
    const radios = await screen.findAllByRole("radio");
    const own = screen.getByRole("radio", { name: /Your own API key from a model vendor/ });
    expect(radios.at(-1)).toBe(own);
    expect(own).not.toBeChecked();
    const label = own.closest("label")!;
    expect(label).toHaveTextContent(/Anthropic, OpenAI, Google Gemini, Mistral, DeepSeek, xAI or Qwen; billed by the vendor/);
    expect(label).not.toHaveTextContent("Recommended");
    expect(label).not.toHaveTextContent("$");
    await u.click(own);
    await u.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByRole("heading", { level: 2, name: "AI access" })).toBeInTheDocument();
    expect(screen.getByText("You chose: Your own API key from a model vendor")).toBeInTheDocument();
    await u.click(await screen.findByRole("radio", { name: "Anthropic (Claude)" }));
    const link = screen.getByRole("link", { name: /Create a key on the Anthropic \(Claude\) website/ });
    expect(link).toHaveAttribute("href", "https://console.anthropic.com/settings/keys");
    expect(link).toHaveAttribute("target", "_blank");
    expect(screen.getByText("It starts with sk-ant-.")).toBeInTheDocument();
    const field = screen.getByLabelText(/^Anthropic \(Claude\) key/);
    expect(field).toHaveAttribute("type", "password");
    expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();

    await u.type(field, "not-a-key-at-all");
    await u.click(screen.getByRole("button", { name: "Check key" }));
    expect(
      await screen.findByText("That does not look like a key from Anthropic (Claude). It starts with sk-ant-."),
    ).toBeInTheDocument();
    await u.clear(field);
    await u.type(field, "sk-ant-wrong");
    await u.click(screen.getByRole("button", { name: "Check key" }));
    expect(await screen.findByText(/Anthropic \(Claude\) did not accept this key/)).toBeInTheDocument();
    await u.clear(field);
    await u.type(field, "sk-ant-good");
    await u.click(screen.getByRole("button", { name: "Check key" }));

    expect(await screen.findByText(/Anthropic \(Claude\) accepted the key/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^Anthropic \(Claude\) key/)).not.toBeInTheDocument(); // never shown again
    expect(modelButton(MAIN)).toHaveTextContent("claude-sonnet-5-5");
    expect(modelButton(REVIEWER)).toHaveTextContent("claude-opus-5-5");
    expect(screen.getByText(/A different model for checking catches more mistakes/)).toBeInTheDocument();
    const estimate = await screen.findByTestId("vendor-estimate");
    await waitFor(() =>
      expect(estimate).toHaveTextContent(
        "For a typical 20-lesson path: about $1.20 to $4.80, billed to you by Anthropic (Claude).",
      ),
    );
    expect(estimate).toHaveAttribute("role", "status");
    expect(estimate).toHaveTextContent("Some steps have no known price yet, so it can cost more.");
    const asked = calls.find((c) => c.path.startsWith("/api/setup/estimate-vendor"))!.path;
    expect(new URL(asked, "http://x").searchParams.get("main")).toBe("claude-sonnet-5-5");
    expect(new URL(asked, "http://x").searchParams.get("reviewer")).toBe("claude-opus-5-5");
    expect(new URL(asked, "http://x").searchParams.get("lessons")).toBe("20");

    await u.click(screen.getByRole("button", { name: "Use this and continue" }));
    expect(await screen.findByText("Done. Yuo uses these models from Anthropic (Claude) from now on.")).toBeInTheDocument();
    expect(screen.getByText(UNTESTED)).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/setup/vendor-models")?.body).toEqual({
      provider: "anthropic",
      main: "claude-sonnet-5-5",
      reviewer: "claude-opus-5-5",
    });
    expect(screen.queryByRole("button", { name: "Use this and continue" })).not.toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByRole("heading", { level: 2, name: "About you" })).toBeInTheDocument();
  });

  it("skips to the models for a connected vendor; without suggestions both are required", async () => {
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/setup": () => json({ ...configuredSetup, bindings: {} }),
      "GET /api/paths": () => json([]),
      "GET /api/onboarding": () =>
        json({ probed: true, models_chosen: false, profile_done: false, has_path: false, done: false }),
      "GET /api/setup/recommendation": () => json(recommendation()),
      "GET /api/setup/providers": () => json([anthropic(), openai(true)]),
      "GET /api/setup/access/vendor/openai/models": () => json({ models: ["gpt-b", "gpt-a"] }),
      "GET /api/setup/estimate-vendor": () => json({ ...vendorEstimate(["generator", "reviewer"]), low_usd: 0, high_usd: 0 }),
      "PUT /api/setup/access/vendor/openai": () => json({ detail: "openai: unreachable", kind: "network" }, 502),
      "POST /api/setup/vendor-models": () =>
        json({ ...configuredSetup, warnings: ["The reviewer is the same model as the writer."] }),
    });
    const u = user();
    renderApp("/setup");
    await u.click(await screen.findByRole("radio", { name: /Your own API key from a model vendor/ }));
    await u.click(screen.getByRole("button", { name: "Next" }));

    // the connected vendor is chosen and its key is not asked again
    expect(await screen.findByRole("radio", { name: /OpenAI/ })).toBeChecked();
    expect(screen.getByText("A key for OpenAI is saved on this computer.")).toBeInTheDocument();
    expect(screen.queryByLabelText(/OpenAI key/)).not.toBeInTheDocument();
    expect(await screen.findByText(/Choose both models to see what a typical path costs/)).toBeInTheDocument();
    expect(modelButton(MAIN)).toHaveTextContent("Choose a model");
    const apply = screen.getByRole("button", { name: "Use this and continue" });
    expect(apply).toBeDisabled();

    await u.click(modelButton(MAIN));
    const options = within(await screen.findByRole("listbox")).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["gpt-a", "gpt-b"]);
    await u.click(options[0]!);
    await u.click(modelButton(REVIEWER));
    await u.click(within(await screen.findByRole("listbox")).getByRole("option", { name: "gpt-a" }));
    expect(
      await screen.findByText(/Yuo does not know the prices of these models yet, so it cannot estimate a typical path/),
    ).toBeInTheDocument();
    await waitFor(() => expect(apply).toBeEnabled());
    await u.click(apply);
    expect(await screen.findByText("The reviewer is the same model as the writer.")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/setup/vendor-models")?.body).toEqual({
      provider: "openai",
      main: "gpt-a",
      reviewer: "gpt-a",
    });

    // a different key: the vendor cannot be reached, said in plain words
    await u.click(screen.getByRole("button", { name: "Use a different key" }));
    await u.type(screen.getByLabelText(/^New OpenAI key/), "sk-something");
    await u.click(screen.getByRole("button", { name: "Check key" }));
    expect(await screen.findByText(/Yuo could not reach OpenAI to check the key/)).toBeInTheDocument();
  });
});

describe("own API keys in Settings", () => {
  it("adds a key and uses its models, and removes a key after asking", async () => {
    let providers = [anthropic(true), openai()];
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/settings": () => json([]),
      "GET /api/setup/providers": () => json(providers),
      "PUT /api/setup/access/vendor/openai": () => {
        providers = [providers[0]!, openai(true)];
        return json({ models: ["gpt-a", "gpt-b"] });
      },
      "GET /api/setup/estimate-vendor": () => json(vendorEstimate()),
      "POST /api/setup/vendor-models": () => json({ ...configuredSetup, warnings: [] }),
      "DELETE /api/setup/access/vendor/anthropic": () => {
        providers = [anthropic(), providers[1]!];
        return new Response(null, { status: 204 });
      },
    });
    const u = user();
    renderApp("/settings");

    expect(await screen.findByRole("heading", { level: 3, name: "Your own API keys" })).toBeInTheDocument();
    const list = (await screen.findByText("Anthropic (Claude):")).closest("ul")!;
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(within(list).getByText("Anthropic (Claude):").closest("p")).toHaveTextContent("a key is saved");
    expect(within(list).getByText("OpenAI:").closest("p")).toHaveTextContent("no key");

    await u.click(screen.getByRole("button", { name: "Add a key: OpenAI" }));
    const field = screen.getByLabelText(/^OpenAI key/);
    expect(field).toHaveAttribute("type", "password");
    await u.type(field, "sk-good-key");
    await u.click(screen.getByRole("button", { name: "Check key" }));
    expect(await screen.findByRole("button", { name: MAIN })).toHaveTextContent("Choose a model");
    expect(calls.filter((c) => c.path.endsWith("/vendor/openai/models"))).toHaveLength(0); // from the key check
    await u.click(modelButton(MAIN));
    await u.click(within(await screen.findByRole("listbox")).getByRole("option", { name: "gpt-b" }));
    await u.click(modelButton(REVIEWER));
    await u.click(within(await screen.findByRole("listbox")).getByRole("option", { name: "gpt-a" }));
    expect(await screen.findByText(/about \$1.20 to \$4.80, billed to you by OpenAI/)).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Use these models" }));
    expect(await screen.findByText("Done. Yuo uses these models from OpenAI from now on.")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/setup/vendor-models")?.body).toEqual({
      provider: "openai",
      main: "gpt-b",
      reviewer: "gpt-a",
    });
    await u.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(within(list).getByText("OpenAI:").closest("p")).toHaveTextContent("a key is saved"));

    await u.click(screen.getByRole("button", { name: "Remove the key: Anthropic (Claude)" }));
    expect(screen.getByText(/Remove the Anthropic \(Claude\) key\? Models from Anthropic \(Claude\) stop working/)).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Yes, remove the key" }));
    await waitFor(() =>
      expect(within(list).getByText("Anthropic (Claude):").closest("p")).toHaveTextContent("no key"),
    );
    expect(calls.filter((c) => c.method === "DELETE" && c.path === "/api/setup/access/vendor/anthropic")).toHaveLength(1);
  });

  it("uses a connected vendor's models from the models route", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/settings": () => json([]),
      "GET /api/setup/providers": () => json([anthropic(true)]),
      "GET /api/setup/access/vendor/anthropic/models": () => json({ models: CLAUDE_MODELS }),
      "GET /api/setup/estimate-vendor": () => json(vendorEstimate()),
    });
    const u = user();
    renderApp("/settings");
    await u.click(await screen.findByRole("button", { name: "Use this vendor's models: Anthropic (Claude)" }));
    expect(await screen.findByRole("button", { name: MAIN })).toHaveTextContent("claude-sonnet-5-5");
    expect(modelButton(REVIEWER)).toHaveTextContent("claude-opus-5-5");
    expect(await screen.findByText(/about \$1.20 to \$4.80/)).toBeInTheDocument();
  });
});

// --- the plan meter --------------------------------------------------------------------------------

const reading = (patch: object = {}) => ({
  window_pct: 6,
  week_pct: 47,
  window_resets_at: new Date(Date.now() + 60_000).toISOString(),
  week_resets_at: "2026-11-03T02:00:00Z", // a Tuesday, 03:00 in Berlin (the profile's zone)
  limited: false,
  observed_at: new Date().toISOString(),
  ...patch,
});

describe("the plan meter", () => {
  it("shows the Claude plan right now in Settings, and what Codex shows before its first lesson", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/settings": () => json([]),
      "GET /api/setup/access": () =>
        json({ openrouter: false, local_url: null, local: false, clis: ["claude", "codex"], consent: {}, vendors: [] }),
      "GET /api/setup/plan-meter": () => json({ claude: reading(), codex: null }),
    });
    renderApp("/settings");
    const claude = await screen.findByTestId("plan-meter-claude");
    expect(claude).toHaveTextContent(
      /^Claude plan right now \(all your devices\): 6% of this 5-hour window used, resets (\w+ )?at .+\. 47% of the week used, resets Tuesday at 3:00\sAM\. Checked at .+\.$/,
    );
    expect(screen.getByTestId("plan-meter-codex")).toHaveTextContent(
      "Yuo shows how much of your plan is used after its first lesson with Codex.",
    );
    expect(screen.queryByText(/limit is reached/)).not.toBeInTheDocument();
  });

  it("says when the plan's limit is reached, and what Claude Code shows before its first lesson", async () => {
    let meter: object = { claude: null, codex: null };
    mockApi({
      ...appRoutes,
      "GET /api/settings": () => json([]),
      "GET /api/setup/access": () =>
        json({ openrouter: false, local_url: null, local: false, clis: ["claude"], consent: {}, vendors: [] }),
      "GET /api/setup/plan-meter": () => json(meter),
    });
    const first = renderApp("/settings");
    expect(await screen.findByTestId("plan-meter-claude")).toHaveTextContent(
      "Yuo shows how much of your plan is used after its first lesson with Claude Code.",
    );
    first.unmount();

    meter = { claude: reading({ window_pct: 100, limited: true, week_pct: null, week_resets_at: null }), codex: null };
    renderApp("/settings");
    const claude = await screen.findByTestId("plan-meter-claude");
    expect(claude).toHaveTextContent(/100% of this 5-hour window used/);
    expect(claude).not.toHaveTextContent("of the week");
    expect(screen.getByText(/The plan's limit is reached. Lessons wait until it resets/)).toBeInTheDocument();
  });

  it("adds the plan right now under a subscription's plan usage on the new-path page, never a price", async () => {
    const estimate = {
      low_usd: 0,
      high_usd: 0,
      notional_usd: 5.76,
      missing: [],
      lines: [
        { unit: "lesson", count: 20, adapter: "claude-cli", model: "sonnet", low: 0, high: 0, billed: false, source: "x" },
      ],
      plan_usage: [
        { cli: "claude-cli", plan: "pro", label: "Pro", window_pct: 52.4, week_pct: 3.67, lessons_per_window: 38, lessons_per_week: 545 },
      ],
    };
    mockApi({
      ...appRoutes,
      "GET /api/estimate": () => json(estimate),
      "GET /api/setup/plan-meter": () => json({ claude: reading({ limited: true }), codex: null }),
    });
    renderApp("/paths/new");
    expect(await screen.findByTestId("plan-meter-now-claude")).toHaveTextContent(
      "Right now 6% of this 5-hour window and 47% of the week are used.",
    );
    expect(screen.getByText("Pro: about 38 lessons per 5-hour window; the whole path takes 4% of the week")).toBeInTheDocument();
    expect(screen.getByText(/The plan's limit is reached/)).toBeInTheDocument();
    const notice = screen.getByText(/Estimated cost for 20 lessons/).closest("[role=status]")!;
    expect(notice).not.toHaveTextContent("$");
  });

  it("shows nothing about the plan right now without a reading", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/estimate": () =>
        json({
          low_usd: 0,
          high_usd: 0,
          notional_usd: 5.76,
          missing: [],
          lines: [{ unit: "lesson", count: 20, adapter: "claude-cli", model: "sonnet", low: 0, high: 0, billed: false, source: "x" }],
          plan_usage: [],
        }),
    });
    renderApp("/paths/new");
    expect(await screen.findByText(/Estimated cost for 20 lessons/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText(/Right now/)).not.toBeInTheDocument());
    expect(screen.queryByTestId("plan-meter-now-claude")).not.toBeInTheDocument();
  });
});
