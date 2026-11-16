import { render, screen } from "@testing-library/react";
import { I18nProvider } from "@lingui/react";
import { i18n } from "@lingui/core";
import { beforeAll, describe, expect, it } from "vitest";
import { activateLocale } from "../i18n";
import { PlanUsageList } from "./PlanUsage";

beforeAll(async () => {
  await activateLocale("en");
});

describe("plan usage", () => {
  it("shows each plan's share, and a note for a subscription with no plans", () => {
    const rows = [
      {
        cli: "claude-cli",
        plan: "pro",
        label: "Pro",
        window_pct: 0.4,
        week_pct: 0.05,
        lessons_per_window: 9,
        lessons_per_week: 99,
      },
    ];
    render(
      <I18nProvider i18n={i18n}>
        <PlanUsageList rows={rows} cli="claude-cli" />
        <PlanUsageList rows={rows} cli="codex-cli" />
      </I18nProvider>,
    );
    expect(screen.getByText("Pro: about 9 lessons per 5-hour window; the whole path takes under 1% of the week")).toBeInTheDocument();
    expect(screen.getByText(/How much of the plan a path takes is not measured yet/)).toBeInTheDocument();
  });

  it("shows Codex plans with no 5-hour window or no published week as such, with the estimate note", () => {
    const rows = [
      { cli: "codex-cli", plan: "plus", label: "Plus", window_pct: 84.7, week_pct: null, lessons_per_window: 23, lessons_per_week: null },
      { cli: "codex-cli", plan: "pro", label: "Pro", window_pct: null, week_pct: null, lessons_per_window: null, lessons_per_week: null },
    ];
    render(
      <I18nProvider i18n={i18n}>
        <PlanUsageList rows={rows} cli="codex-cli" />
      </I18nProvider>,
    );
    expect(screen.getByText("Plus: about 23 lessons per 5-hour window; the weekly limit is not published")).toBeInTheDocument();
    expect(screen.getByText("Pro: no 5-hour limit; the weekly limit is not published")).toBeInTheDocument();
    expect(screen.getByText(/Estimated from the message ranges OpenAI publishes/)).toBeInTheDocument();
  });
});
