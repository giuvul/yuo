// The subscription plan meter (yuo/app/plan_meter.py): the last reading Claude Code or Codex reported after a
// Yuo call, of the 5-hour window and the week. It covers the learner's whole account, other devices included,
// so it says how much of the plan is used right now, not what Yuo used. Times in the profile's time zone.
import { Trans, useLingui } from "@lingui/react/macro";
import type { MeterOut } from "../api/client";
import { Notice, ui } from "../components/ui";
import { useMe, usePlanMeter } from "./api";

type MeterCli = "claude" | "codex";

/** "claude-cli" (an estimate line's adapter) -> "claude" (the meter's key). */
export const meterCli = (adapter: "claude-cli" | "codex-cli"): MeterCli =>
  adapter === "claude-cli" ? "claude" : "codex";

type Clock = {
  time: (iso: string | null) => string | null;
  day: (iso: string | null) => string | null;
  isToday: (iso: string | null) => boolean;
  date: (iso: string | null) => string | null;
};

/** Formats in the learner's locale and the profile's time zone (the browser's while the profile loads). */
function useClock(): Clock {
  const { i18n } = useLingui();
  const me = useMe();
  const tz = me.data?.tz;
  const fmt = (iso: string | null, options: Intl.DateTimeFormatOptions): string | null => {
    if (!iso) return null;
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    try {
      return i18n.date(d, tz ? { ...options, timeZone: tz } : options);
    } catch {
      return i18n.date(d, options); // a time zone this browser does not know
    }
  };
  const ymd: Intl.DateTimeFormatOptions = { year: "numeric", month: "2-digit", day: "2-digit" };
  return {
    time: (iso) => fmt(iso, { timeStyle: "short" }),
    day: (iso) => fmt(iso, { weekday: "long" }),
    isToday: (iso) => iso !== null && fmt(iso, ymd) === fmt(new Date().toISOString(), ymd),
    date: (iso) => fmt(iso, { dateStyle: "medium" }),
  };
}

function usePercent() {
  const { i18n } = useLingui();
  return (pct: number) => i18n.number(Math.min(Math.max(pct, 0), 100) / 100, { style: "percent", maximumFractionDigits: 0 });
}

function Limited() {
  return (
    <Notice tone="warning">
      <Trans id="plan-meter.limited">
        The plan's limit is reached. Lessons wait until it resets, then Yuo continues by itself.
      </Trans>
    </Notice>
  );
}

function WindowLine({ meter, clock }: { meter: MeterOut; clock: Clock }) {
  const percent = usePercent();
  if (meter.window_pct === null) return null;
  const pct = percent(meter.window_pct);
  const time = clock.time(meter.window_resets_at);
  const day = clock.day(meter.window_resets_at);
  if (!time) return <Trans id="plan-meter.window">{pct} of this 5-hour window used.</Trans>;
  if (clock.isToday(meter.window_resets_at)) {
    return <Trans id="plan-meter.window.reset">{pct} of this 5-hour window used, resets at {time}.</Trans>;
  }
  return <Trans id="plan-meter.window.reset-day">{pct} of this 5-hour window used, resets {day} at {time}.</Trans>;
}

function WeekLine({ meter, clock }: { meter: MeterOut; clock: Clock }) {
  const percent = usePercent();
  if (meter.week_pct === null) return null;
  const pct = percent(meter.week_pct);
  const time = clock.time(meter.week_resets_at);
  const day = clock.day(meter.week_resets_at);
  if (!time) return <Trans id="plan-meter.week">{pct} of the week used.</Trans>;
  return <Trans id="plan-meter.week.reset">{pct} of the week used, resets {day} at {time}.</Trans>;
}

function Checked({ meter, clock }: { meter: MeterOut; clock: Clock }) {
  const time = clock.time(meter.observed_at);
  const date = clock.date(meter.observed_at);
  if (!time) return null;
  if (clock.isToday(meter.observed_at)) return <Trans id="plan-meter.checked">Checked at {time}.</Trans>;
  return <Trans id="plan-meter.checked-day">Checked {date} at {time}.</Trans>;
}

/** Settings: one subscription app's plan right now, or what Yuo shows once it has a reading. */
function PlanMeterReading({ cli, meter }: { cli: MeterCli; meter: MeterOut | null }) {
  const clock = useClock();
  if (!meter) {
    return (
      <p className={ui.muted} data-testid={`plan-meter-${cli}`}>
        {cli === "claude" ? (
          <Trans id="plan-meter.none.claude">
            Yuo shows how much of your plan is used after its first lesson with Claude Code.
          </Trans>
        ) : (
          <Trans id="plan-meter.none.codex">Yuo shows how much of your plan is used after its first lesson with Codex.</Trans>
        )}
      </p>
    );
  }
  return (
    <div className={ui.stack}>
      <p data-testid={`plan-meter-${cli}`}>
        {cli === "claude" ? (
          <Trans id="plan-meter.lead.claude">Claude plan right now (all your devices):</Trans>
        ) : (
          <Trans id="plan-meter.lead.codex">Codex plan right now (all your devices):</Trans>
        )}{" "}
        <WindowLine meter={meter} clock={clock} /> <WeekLine meter={meter} clock={clock} />{" "}
        <Checked meter={meter} clock={clock} />
      </p>
      {meter.limited ? <Limited /> : null}
    </div>
  );
}

/** Settings: the readings of the subscription apps found on this computer. */
export function PlanMeters({ clis }: { clis: string[] }) {
  const meter = usePlanMeter();
  const found = clis.filter((c): c is MeterCli => c === "claude" || c === "codex");
  if (found.length === 0 || !meter.data) return null;
  return (
    <>
      {found.map((cli) => (
        <PlanMeterReading key={cli} cli={cli} meter={meter.data[cli]} />
      ))}
    </>
  );
}

/** The new-path page: how much of the plan is used right now, under the plan usage of a typical path. */
export function PlanMeterNow({ cli }: { cli: MeterCli }) {
  const percent = usePercent();
  const meter = usePlanMeter();
  const m = meter.data?.[cli];
  if (!m) return null;
  const windowPct = m.window_pct === null ? null : percent(m.window_pct);
  const weekPct = m.week_pct === null ? null : percent(m.week_pct);
  return (
    <>
      {windowPct !== null || weekPct !== null ? (
        <p data-testid={`plan-meter-now-${cli}`}>
          {windowPct !== null && weekPct !== null ? (
            <Trans id="plan-meter.now">
              Right now {windowPct} of this 5-hour window and {weekPct} of the week are used.
            </Trans>
          ) : windowPct !== null ? (
            <Trans id="plan-meter.now.window">Right now {windowPct} of this 5-hour window is used.</Trans>
          ) : (
            <Trans id="plan-meter.now.week">Right now {weekPct} of the week is used.</Trans>
          )}
        </p>
      ) : null}
      {m.limited ? <Limited /> : null}
    </>
  );
}
