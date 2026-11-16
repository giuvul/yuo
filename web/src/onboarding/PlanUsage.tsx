// A subscription's share of the plan's limits for a typical path (yuo/data/plan_limits.json): what a learner
// on Claude Code or Codex sees instead of an API price they do not pay.
import { Trans, useLingui } from "@lingui/react/macro";
import type { PlanUsage as PlanUsageRow } from "../api/client";
import { ui } from "../components/ui";

function Share({ pct }: { pct: number }) {
  const { i18n } = useLingui();
  if (pct < 1) return <Trans id="plan-usage.under-one">under 1%</Trans>;
  const value = i18n.number(Math.round(pct) / 100, { style: "percent" });
  return <>{value}</>;
}

/** Lessons that fit in one 5-hour window: lessons are written a few at a time as you learn, so a whole path
 * is never written inside one window ("over 100% of the window" read as "too much").
 * null: the plan has no 5-hour window (ChatGPT Pro). */
function PerWindow({ lessons }: { lessons: number | null }) {
  if (lessons === null) return <Trans id="plan-usage.window.none">no 5-hour limit</Trans>;
  if (lessons < 1) return <Trans id="plan-usage.window.under-one">under one lesson per 5-hour window</Trans>;
  return (
    <Trans id="plan-usage.window.lessons">
      about {lessons} lessons per 5-hour window
    </Trans>
  );
}

function Week({ pct }: { pct: number | null }) {
  if (pct === null) return <Trans id="plan-usage.week.unpublished">the weekly limit is not published</Trans>;
  return (
    <Trans id="plan-usage.week.share">
      the whole path takes <Share pct={pct} /> of the week
    </Trans>
  );
}

/** One line per plan: lessons per 5-hour window and the path's share of the week. Codex rows are estimates
 * from OpenAI's published message ranges, so they carry a note. */
export function PlanUsageList({ rows, cli }: { rows: PlanUsageRow[]; cli: "claude-cli" | "codex-cli" }) {
  const mine = rows.filter((r) => r.cli === cli);
  if (mine.length === 0) {
    return (
      <span className={ui.muted}>
        <Trans id="plan-usage.unknown">
          It uses your plan. How much of the plan a path takes is not measured yet; your plan's usage page shows what
          is left.
        </Trans>
      </span>
    );
  }
  return (
    <>
      <ul className={ui.compactList} data-testid={`plan-usage-${cli}`}>
        {mine.map((r) => (
          <li key={r.plan}>
            <Trans id="plan-usage.row">
              {r.label}: <PerWindow lessons={r.lessons_per_window ?? null} />; <Week pct={r.week_pct ?? null} />
            </Trans>
          </li>
        ))}
      </ul>
      {cli === "codex-cli" && (
        <span className={ui.muted}>
          <Trans id="plan-usage.codex-estimate">
            Estimated from the message ranges OpenAI publishes; your plan's usage page shows what is left.
          </Trans>
        </span>
      )}
    </>
  );
}
