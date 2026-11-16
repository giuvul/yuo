// Settings > AI access (0.8.1): the "sign in" links land on the program's card, the own keys are grouped in a
// closed section, "Models in use" names the exact versions, and an OpenRouter key's models are searched in
// OpenRouter's list.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { activateLocale } from "../i18n";
import { json, mockApi } from "../test/mockApi";
import { appRoutes, cliSignedOut, configuredSetup, renderApp } from "../test/renderApp";

beforeAll(async () => {
  await activateLocale("en");
});
afterEach(() => {
  vi.unstubAllGlobals();
});

const withKey = () =>
  json({ openrouter: true, local_url: null, local: false, clis: ["claude"], consent: {}, vendors: [] });

describe("AI access in Settings", () => {
  it("opens the program's card from a 'sign in' link, not the top of the section", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/settings": () => json([]),
      "GET /api/setup/access": withKey,
      "GET /api/setup/ai-ready": () => json({ ready: false, clis: [cliSignedOut()] }),
      "GET /api/setup/cli/claude": () => json(cliSignedOut()),
    });
    const scrolled: string[] = [];
    // jsdom has no scrolling
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this.id);
    };
    renderApp("/settings#cli-claude");

    const card = await screen.findByTestId("cli-claude");
    await waitFor(() => expect(scrolled).toContain("cli-claude"));
    const target = card.closest("#cli-claude") as HTMLElement;
    expect(target.closest("details")).toHaveAttribute("open");
    expect(document.activeElement).toBe(target);
    expect(within(card).getByRole("heading", { level: 3 })).toHaveTextContent("Claude Code is installed, but not signed in");
    delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
  });

  it("groups the own keys in a closed section and names the versions in use", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/settings": () => json([]),
      "GET /api/setup": () =>
        json({
          ...configuredSetup,
          bindings: {
            generator: { adapter: "claude-cli", model: "sonnet", resolved: "claude-sonnet-5-5" },
            reviewer: { adapter: "claude-cli", model: "opus" },
          },
        }),
      "GET /api/setup/access": withKey,
    });
    renderApp("/settings");

    const keys = (await screen.findByRole("heading", { level: 3, name: "Your own API keys" })).closest("details")!;
    expect(keys).not.toHaveAttribute("open");
    expect(within(keys).getByRole("heading", { level: 4, name: "OpenRouter" })).toBeInTheDocument();
    const used = screen.getByRole("heading", { level: 3, name: "Models in use" }).parentElement!;
    expect(within(used).getByText("Writes lessons:").closest("li")).toHaveTextContent(
      "Writes lessons: claude-sonnet-5-5 (sonnet, through Claude Code)",
    );
    expect(within(used).getByText("Checks lessons:").closest("li")).toHaveTextContent(
      "opus (the newest version, through Claude Code; the exact one shows here after Yuo first uses it)",
    );
  });

  it("searches OpenRouter's list and uses the chosen models", async () => {
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/settings": () => json([]),
      "GET /api/setup/access": withKey,
      "GET /api/setup/access/openrouter/models": () =>
        json({
          models: [
            { id: "deepseek/deepseek-v4-pro", name: "DeepSeek: V4 Pro", in_usd_per_m: 0.5, out_usd_per_m: 2, context: 128000 },
            { id: "qwen/qwen3.8-27b", name: "Qwen: Qwen3.8 27B", in_usd_per_m: 0.3, out_usd_per_m: 1.2, context: null },
            { id: "anthropic/claude-sonnet-5.5", name: "Anthropic: Claude Sonnet 5.5", in_usd_per_m: 2, out_usd_per_m: 10, context: 1000000 },
          ],
        }),
      "GET /api/setup/estimate-vendor": () =>
        json({ low_usd: 0.4, high_usd: 1.1, lessons: 20, lines: [], missing: [], plan_usage: [], prices_as_of: null }),
      "POST /api/setup/vendor-models": () =>
        json({
          ...configuredSetup,
          bindings: { generator: { adapter: "openrouter", model: "qwen/qwen3.8-27b" } },
        }),
    });
    const u = userEvent.setup();
    renderApp("/settings");

    await u.click(await screen.findByRole("button", { name: "Choose the models" }));
    const main = await screen.findByRole("combobox", { name: /Model that writes lessons and answers/ });
    await u.type(main, "qwen");
    const options = within(await screen.findByRole("listbox")).getAllByRole("option");
    expect(options).toHaveLength(1);
    expect(options[0]).toHaveTextContent("qwen/qwen3.8-27b · $0.30 in, $1.20 out per million tokens");
    await u.click(options[0]!);
    const reviewer = screen.getByRole("combobox", { name: /Model that checks lessons/ });
    await u.type(reviewer, "deepseek");
    await u.click(within(await screen.findByRole("listbox")).getByRole("option", { name: /DeepSeek: V4 Pro/ }));
    expect(await screen.findByText(/about \$0.40 to \$1.10, billed to you by OpenRouter/)).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Use these models" }));
    expect(await screen.findByText("Done. Yuo uses these models from OpenRouter from now on.")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/setup/vendor-models")?.body).toEqual({
      provider: "openrouter",
      main: "qwen/qwen3.8-27b",
      reviewer: "deepseek/deepseek-v4-pro",
    });
  });
});
