import { Plural, Trans, useLingui } from "@lingui/react/macro";
import { useQueryClient } from "@tanstack/react-query";
import { createRoute, Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import type { Schemas } from "../api/client";
import { keys, useAcceptLesson, useHome, usePaths } from "../api/hooks";
import { ErrorNotice } from "../components/ErrorNotice";
import { PauseBanner } from "../components/PauseControls";
import { GrowingSprout } from "../components/Grove";
import {
  AlertIcon,
  BookIcon,
  FlameIcon,
  LeafIcon,
  NoteIcon,
  RepeatIcon,
  SparkleIcon,
  SproutIcon,
  TrophyIcon,
} from "../components/icons";
import { Button, ButtonLink, Notice, Waiting } from "../components/ui";
import { AiReadyWarning } from "../onboarding/AiReady";
import { useOnboarding } from "../onboarding/api";
import { useDueTotal } from "../review/api";
import { useTutorRefs } from "../tutor/context";
import { PathsPage } from "./paths";
import { rootRoute } from "./root";
import styles from "./index.module.css";

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: HomePage,
});

type Home = Schemas["HomeOut"];
type Item = Schemas["HomeItem"];

/**
 * Home: in a few seconds, how the learner is doing, what waits for them today and the one best thing to do next,
 * across all their paths. Before the first path it is the paths page, with its "plant your first path".
 */
function HomePage() {
  const paths = usePaths();
  if (paths.isSuccess && paths.data.length === 0) return <PathsPage />;
  return <Dashboard />;
}

function Dashboard() {
  useTutorRefs({ screen: "home" });
  const home = useHome();
  const due = useDueTotal();
  const onboarding = useOnboarding();
  const unfinished = onboarding.data !== undefined && !onboarding.data.done && onboarding.data.has_path;

  return (
    <section className={styles.home}>
      <header className={styles.hello}>
        <h1 className={styles.greeting}>
          <Greeting />
          <SproutIcon className={styles.greetingSprout} size="0.8em" />
        </h1>
        {home.data ? <Summary home={home.data} due={due} /> : null}
      </header>

      <PauseBanner />
      {unfinished ? (
        <Notice>
          <Trans id="home.finish-setup">Yuo is not fully set up yet.</Trans>{" "}
          <Link to="/setup">
            <Trans id="home.finish-setup.link">Finish setting up</Trans>
          </Link>
        </Notice>
      ) : null}

      <AiReadyWarning enabled />

      {home.isPending ? (
        <Waiting>
          <Trans id="common.loading">Loading…</Trans>
        </Waiting>
      ) : home.isError ? (
        <ErrorNotice error={home.error} />
      ) : (
        <div className={styles.grid}>
          <div className={styles.main}>
            <NextStep home={home.data} />
            <Today items={home.data.today} due={due} />
          </div>
          <aside className={styles.side}>
            <YourProgress progress={home.data.progress} />
            {home.data.momentum ? <Momentum momentum={home.data.momentum} /> : null}
            {home.data.insight ? <Insight insight={home.data.insight} /> : null}
          </aside>
        </div>
      )}
    </section>
  );
}

function Greeting() {
  const hour = new Date().getHours();
  if (hour >= 5 && hour < 12) return <Trans id="home.greeting.morning">Good morning</Trans>;
  if (hour >= 12 && hour < 18) return <Trans id="home.greeting.afternoon">Good afternoon</Trans>;
  return <Trans id="home.greeting.evening">Good evening</Trans>;
}

/** "12 reviews due · 2 new lessons ready · exam in 9 days": only what there is. */
function Summary({ home, due }: { home: Home; due: number }) {
  const parts: ReactNode[] = [];
  if (due > 0)
    parts.push(<Plural key="due" id="home.summary.due" value={due} one="# review due" other="# reviews due" />);
  if (home.lessons_ready > 0)
    parts.push(
      <Plural
        key="ready"
        id="home.summary.ready"
        value={home.lessons_ready}
        one="# new lesson ready"
        other="# new lessons ready"
      />,
    );
  if (home.exam)
    parts.push(
      home.exam.days === 0 ? (
        <Trans key="exam" id="home.summary.exam-today">
          exam today
        </Trans>
      ) : (
        <Plural key="exam" id="home.summary.exam" value={home.exam.days} one="exam in # day" other="exam in # days" />
      ),
    );
  if (parts.length === 0) return null;
  return (
    <p className={styles.summary}>
      {parts.map((p, i) => (
        <span key={i}>
          {i > 0 ? <span aria-hidden="true"> · </span> : null}
          {p}
        </span>
      ))}
    </p>
  );
}

// --- the one next step ---------------------------------------------------------------------------

function NextStep({ home }: { home: Home }) {
  const n = home.next_step;
  if (!n)
    return (
      <Link to="/paths" className={styles.next}>
        <span className={styles.nextMark}>
          <LeafIcon size={38} />
        </span>
        <span className={styles.nextBody}>
          <span className={styles.nextTitle}>
            <Trans id="home.next.none">Everything is learned for now</Trans>
          </span>
          <span className={styles.nextMeta}>
            <Trans id="home.next.none.meta">Open your paths to add lessons or start a new one.</Trans>
          </span>
        </span>
        <Vine />
      </Link>
    );
  const meta = (
    <span className={styles.nextMeta}>
      {n.place} · <Trans id="home.next.index">Lesson {n.index} of {n.count}</Trans>
      {n.kind === "lesson" && n.minutes ? (
        <>
          {" "}
          · <Trans id="home.next.minutes">about {n.minutes} min</Trans>
        </>
      ) : null}
    </span>
  );
  const body = (
    <>
      <span className={styles.nextMark}>{n.kind === "lesson" ? <LeafIcon size={38} /> : <GrowingSprout />}</span>
      <span className={styles.nextBody}>
        <span className={styles.nextTitle}>
          {n.kind === "lesson" ? (
            n.started ? (
              <Trans id="home.next.continue">Continue: {n.title}</Trans>
            ) : (
              <Trans id="home.next.start">Start: {n.title}</Trans>
            )
          ) : n.kind === "writing" ? (
            <Trans id="home.next.writing">Being written: {n.title}</Trans>
          ) : (
            <Trans id="home.next.planned">Up next: {n.title}</Trans>
          )}
        </span>
        {meta}
      </span>
      <Vine />
    </>
  );
  return n.kind === "lesson" ? (
    <Link to="/lessons/$lessonId" params={{ lessonId: n.lesson_id }} className={styles.next}>
      {body}
    </Link>
  ) : (
    <Link to="/paths/$pathId" params={{ pathId: n.path_id }} className={styles.next}>
      {body}
    </Link>
  );
}

const LEAF = "M2 14C4 5 13 1.5 22.5 3.5 21.5 13 12 17.5 2 14z";
/** The leaf above points this many degrees above the x axis, from its base at (2, 14) to its tip. */
const LEAF_AIM = (Math.atan2(10.5, 20.5) * 180) / Math.PI;

type Pt = [number, number];
/** The stem as two cubic segments: the path below spelled out, the second control point reflected. */
const STEM: [[Pt, Pt, Pt, Pt], [Pt, Pt, Pt, Pt]] = [
  [
    [40, 88],
    [70, 82],
    [100, 70],
    [124, 52],
  ],
  [
    [124, 52],
    [148, 34],
    [166, 18],
    [196, 4],
  ],
];

/** A point on the stem (t from 0 to 2, one unit per segment) and the stem's direction there, in degrees. */
function onStem(t: number): [number, number, number] {
  const k = Math.min(1, Math.floor(t));
  const [a, b, c, d] = STEM[k === 0 ? 0 : 1];
  const u = t - k;
  const v = 1 - u;
  const at = (k: 0 | 1) => v * v * v * a[k] + 3 * v * v * u * b[k] + 3 * v * u * u * c[k] + u * u * u * d[k];
  const tan = (k: 0 | 1) => 3 * v * v * (b[k] - a[k]) + 6 * v * u * (c[k] - b[k]) + 3 * u * u * (d[k] - c[k]);
  return [at(0), at(1), (Math.atan2(tan(1), tan(0)) * 180) / Math.PI];
}

/** Where the leaves grow: how far along the stem, which side (1 above, -1 below) and their size. */
const VINE_LEAVES = (
  [
    [0.55, -1, 0.75],
    [0.85, 1, 0.9],
    [1.15, -1, 0.8],
    [1.45, 1, 0.8],
    [1.7, -1, 0.7],
    [1.88, -1, 0.55],
  ] as const
).map(([t, side, scale]) => {
  const [x, y, dir] = onStem(t);
  // Leaves lean 45 degrees off the stem, towards its tip; the leaf's base sits on the stem.
  const angle = dir - side * 45 + LEAF_AIM;
  return `translate(${x.toFixed(1)} ${y.toFixed(1)}) rotate(${angle.toFixed(1)}) scale(${scale}) translate(-2 -14)`;
});

/** A vine climbing into the card's corner. */
function Vine() {
  return (
    <svg className={styles.vine} viewBox="0 0 200 90" aria-hidden="true" focusable="false">
      <path className={styles.vineStem} d="M40 88C70 82 100 70 124 52S166 18 196 4" />
      {VINE_LEAVES.map((transform, i) => (
        <path key={i} className={styles.vineLeaf} d={LEAF} transform={transform} />
      ))}
    </svg>
  );
}

// --- what waits today ----------------------------------------------------------------------------

function Today({ items, due }: { items: Item[]; due: number }) {
  const empty = due === 0 && items.length === 0;
  return (
    <section className={styles.today} aria-labelledby="home-today">
      <h2 id="home-today" className={styles.todayTitle}>
        <Trans id="home.today">Today</Trans>
      </h2>
      {empty ? (
        <p className={`${styles.todayList} ${styles.quiet}`}>
          <Trans id="home.today.none">Nothing waiting. A good day for a new lesson.</Trans>
        </p>
      ) : (
        <ul className={styles.todayList}>
          {due > 0 ? (
            <Row
              icon={<RepeatIcon />}
              title={
                <Plural id="home.today.due" value={due} one="# review question due" other="# review questions due" />
              }
              action={
                <ButtonLink to="/review" small>
                  <Trans id="home.today.due.action">Start review</Trans>
                </ButtonLink>
              }
            />
          ) : null}
          {items.map((item, i) => (
            <TodayRow key={`${item.kind}-${item.lesson_id ?? item.course_id ?? item.path_id}-${i}`} item={item} />
          ))}
        </ul>
      )}
    </section>
  );
}

function Row({
  icon,
  title,
  detail,
  action,
  tone,
}: {
  icon: ReactNode;
  title: ReactNode;
  detail?: ReactNode;
  action?: ReactNode;
  tone?: "warning";
}) {
  return (
    <li className={styles.row}>
      <span className={styles.rowIcon} data-tone={tone} aria-hidden="true">
        {icon}
      </span>
      <span className={styles.rowBody}>
        <span className={styles.rowTitle}>{title}</span>
        {detail ? <span className={styles.rowDetail}>{detail}</span> : null}
      </span>
      {action ? <span className={styles.rowAction}>{action}</span> : null}
    </li>
  );
}

function TodayRow({ item }: { item: Item }) {
  const { t } = useLingui();
  const title = item.title ?? "";
  switch (item.kind) {
    case "fading": {
      const skills = (item.skills ?? []).join(", ");
      const count = item.count ?? 0;
      return (
        <Row
          tone="warning"
          icon={<AlertIcon />}
          title={
            <Plural
              id="home.today.fading"
              value={count}
              one={`# skill fading: ${skills}`}
              other={`# skills fading: ${skills}`}
            />
          }
          detail={<Trans id="home.today.fading.detail">Needs review to keep them fresh.</Trans>}
          action={
            <ButtonLink to="/paths/$pathId/review" params={{ pathId: item.path_id }} small>
              <Trans id="home.today.fading.action">Refresh</Trans>
            </ButtonLink>
          }
        />
      );
    }
    case "lesson_draft":
      return (
        <Row
          icon={<NoteIcon />}
          title={<Trans id="home.today.draft">1 lesson needs your decision: “{title}”</Trans>}
          detail={<Trans id="home.today.draft.detail">Failed its quality review.</Trans>}
          action={<AcceptDraft pathId={item.path_id} lessonId={item.lesson_id!} />}
        />
      );
    case "lesson_failed":
      return (
        <Row
          tone="warning"
          icon={<AlertIcon />}
          title={<Trans id="home.today.failed">A lesson could not be written: “{title}”</Trans>}
          action={
            <ButtonLink to="/lessons/$lessonId" params={{ lessonId: item.lesson_id! }} small>
              <Trans id="home.today.failed.action">Open</Trans>
            </ButtonLink>
          }
        />
      );
    case "transcribing":
      return (
        <Row
          icon={<GrowingSprout />}
          title={
            <Trans id="home.today.transcribing">
              {title} is being transcribed ({item.percent ?? 0}%)
            </Trans>
          }
        />
      );
    case "arrange_ready":
      return (
        <Row
          icon={<SparkleIcon />}
          title={
            <Plural
              id="home.today.arrange"
              value={item.count ?? 0}
              one="New suggestion: your files could form # course"
              other="New suggestion: your files could form # courses"
            />
          }
          detail={<Trans id="home.today.arrange.detail">We found natural groupings in your material.</Trans>}
          action={
            <ButtonLink to="/paths/$pathId" params={{ pathId: item.path_id }} small>
              <Trans id="home.today.review">Review</Trans>
            </ButtonLink>
          }
        />
      );
    case "plan_ready":
      return (
        <Row
          icon={<SparkleIcon />}
          title={<Trans id="home.today.plan">The plan for “{title}” is ready</Trans>}
          detail={<Trans id="home.today.plan.detail">Check it before the lessons are written.</Trans>}
          action={
            <ButtonLink to="/paths/$pathId" params={{ pathId: item.path_id }} small>
              <Trans id="home.today.review">Review</Trans>
            </ButtonLink>
          }
        />
      );
    case "exam_soon":
      return (
        <Row
          icon={<BookIcon />}
          title={
            <Plural
              id="home.today.exam"
              value={item.days ?? 0}
              _0={`${title}: exam today`}
              one={`${title}: exam in # day`}
              other={`${title}: exam in # days`}
            />
          }
          detail={<Trans id="home.today.exam.detail">A mock exam shows what to go over.</Trans>}
          action={
            <ButtonLink
              to="/paths/$pathId/courses/$courseId/mock-exam"
              params={{ pathId: item.path_id, courseId: item.course_id! }}
              small
              aria-label={t({ id: "home.today.exam.action.label", message: `Take a mock exam: ${title}` })}
            >
              <Trans id="home.today.exam.action">Mock exam</Trans>
            </ButtonLink>
          }
        />
      );
  }
}

function AcceptDraft({ pathId, lessonId }: { pathId: string; lessonId: string }) {
  const accept = useAcceptLesson(pathId);
  const qc = useQueryClient();
  return (
    <Button
      small
      isDisabled={accept.isPending}
      onPress={() => accept.mutate(lessonId, { onSettled: () => qc.invalidateQueries({ queryKey: keys.home }) })}
    >
      <Trans id="path.lesson.accept">Accept with feedback</Trans>
    </Button>
  );
}

// --- how it goes ---------------------------------------------------------------------------------

function YourProgress({ progress }: { progress: Home["progress"] }) {
  const { t } = useLingui();
  if (!progress) return null;
  const r = 26;
  const length = 2 * Math.PI * r;
  return (
    <section className={styles.card} aria-labelledby="home-progress">
      <h2 id="home-progress" className={styles.cardTitle}>
        <Trans id="home.progress">Your progress</Trans>
      </h2>
      <div className={styles.progress}>
        <svg
          className={styles.ring}
          viewBox="0 0 64 64"
          role="img"
          aria-label={t({ id: "home.progress.label", message: `Mastery ${progress.score} of 100` })}
        >
          <circle className={styles.ringTrack} cx="32" cy="32" r={r} />
          <circle
            className={styles.ringValue}
            cx="32"
            cy="32"
            r={r}
            strokeDasharray={`${(length * progress.score) / 100} ${length}`}
            transform="rotate(-90 32 32)"
          />
          <text className={styles.ringText} x="32" y="32" textAnchor="middle" dominantBaseline="central">
            {progress.score}
          </text>
        </svg>
        <span className={styles.progressBody}>
          <span className={styles.progressStatus} data-status={progress.status}>
            {progress.status === "on_track" ? (
              <Trans id="home.progress.on-track">On track</Trans>
            ) : progress.status === "slipping" ? (
              <Trans id="home.progress.slipping">Slipping a little</Trans>
            ) : (
              <Trans id="home.progress.starting">Just starting</Trans>
            )}
          </span>
          <span className={styles.muted}>
            {progress.delta > 0 ? (
              <Plural id="home.progress.up" value={progress.delta} one="+# pt this week" other="+# pts this week" />
            ) : progress.delta < 0 ? (
              <Plural
                id="home.progress.down"
                value={-progress.delta}
                one="−# pt this week"
                other="−# pts this week"
              />
            ) : (
              <Trans id="home.progress.mastered">
                {progress.mastered} of {progress.skills} skills mastered
              </Trans>
            )}
          </span>
        </span>
      </div>
    </section>
  );
}

function Momentum({ momentum }: { momentum: NonNullable<Home["momentum"]> }) {
  const a = momentum.achievement;
  return (
    <section className={styles.card} aria-labelledby="home-momentum">
      <h2 id="home-momentum" className={styles.cardTitle}>
        <Trans id="home.momentum">Momentum</Trans>
      </h2>
      <ul className={styles.stats}>
        <li className={styles.stat}>
          <span className={styles.statIcon} data-tone="flame" aria-hidden="true">
            <FlameIcon />
          </span>
          <span>
            <span className={styles.statValue}>
              <Plural id="home.momentum.streak" value={momentum.streak} one="# day" other="# days" />
            </span>
            <span className={styles.statLabel}>
              <Trans id="home.momentum.streak.label">streak</Trans>
            </span>
          </span>
        </li>
        <li className={styles.stat}>
          <span className={styles.statIcon} aria-hidden="true">
            <SproutIcon />
          </span>
          <span>
            <span className={styles.statValue}>
              <Trans id="home.momentum.xp">{momentum.xp_week} XP</Trans>
            </span>
            <span className={styles.statLabel}>
              <Trans id="home.momentum.xp.label">this week</Trans>
            </span>
          </span>
        </li>
        {a ? (
          <li className={styles.stat}>
            <span className={styles.statIcon} aria-hidden="true">
              <TrophyIcon />
            </span>
            <span>
              <span className={styles.statLabel}>
                <Trans id="home.momentum.achievement">Latest achievement</Trans>
              </span>
              <span className={styles.statValue}>{achievementName(a.key)}</span>
            </span>
          </li>
        ) : null}
      </ul>
    </section>
  );
}

/** Achievement keys are codes; show them as words until the backend sends titles (as on the progress page). */
function achievementName(key: string): string {
  const s = key.replace(/[._-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function Insight({ insight }: { insight: NonNullable<Home["insight"]> }) {
  const skill = insight.skill ?? "";
  const requires = insight.requires ?? "";
  const percent = insight.percent ?? 0;
  let text: ReactNode;
  switch (insight.kind) {
    case "builds_on":
      text = (
        <Trans id="home.insight.builds-on">
          {skill} builds on {requires}, which is not mastered yet. A short review first will make it easier.
        </Trans>
      );
      break;
    case "weakest":
      text = (
        <Trans id="home.insight.weakest">
          {skill} is your weakest skill so far ({percent}% right). A little practice there goes a long way.
        </Trans>
      );
      break;
    case "time_of_day":
      text =
        insight.part === "morning" ? (
          <Trans id="home.insight.morning">You answer best in the morning ({percent}% right).</Trans>
        ) : insight.part === "afternoon" ? (
          <Trans id="home.insight.afternoon">You answer best in the afternoon ({percent}% right).</Trans>
        ) : insight.part === "evening" ? (
          <Trans id="home.insight.evening">You answer best in the evening ({percent}% right).</Trans>
        ) : (
          <Trans id="home.insight.night">You answer best late at night ({percent}% right).</Trans>
        );
      break;
  }
  return (
    <section className={styles.card} aria-labelledby="home-insight">
      <h2 id="home-insight" className={styles.cardTitle}>
        <Trans id="home.insight">Insight</Trans>
      </h2>
      <p className={styles.insight}>
        <span className={styles.statIcon} aria-hidden="true">
          <LeafIcon />
        </span>
        <span>{text}</span>
      </p>
    </section>
  );
}

