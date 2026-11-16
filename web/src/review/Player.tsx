// One review session (3.2.5): a question at a time, answer until correct (two tries), hints, "Show answer",
// then one reserve question per objective whose question had to be shown, and the results.
//
// Answers and help are events in the outbox, as in every assessment; the ingest reply's `graded[event id]` is
// the staged feedback. The server never sends the key before a question is resolved, so nothing here can leak it.
// Offline, an answer stays in the outbox, counts as one try and the session moves on; its feedback is in the
// results once it has synced.
import { Trans, useLingui } from "@lingui/react/macro";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Button as AriaButton,
  Menu,
  MenuItem,
  MenuTrigger,
  Popover,
  Switch,
} from "react-aria-components";
import type { Graded, HintOut } from "../api/client";
import { fetchHint, keys } from "../api/hooks";
import { ErrorNotice } from "../components/ErrorNotice";
import { grove } from "../components/Grove";
import { ArrowRightIcon, CheckIcon, CloseIcon, MoreIcon, QuestionIcon } from "../components/icons";
import { Badge, Button, Notice, ui } from "../components/ui";
import { useOutbox } from "../outbox/context";
import type { FlushResult } from "../outbox/outbox";
import { uuid7 } from "../outbox/uuid7";
import { useEvent, useTutorActions, useTutorRefs } from "../tutor/context";
import { fetchReviewFeedback, reviewKeys, type ReviewItem, type ReviewSession } from "./api";
import { OptionButton, ProgressVine, type OptionState, type Segment, type SegmentState } from "./primitives";
import { Results } from "./Results";
import styles from "./review.module.css";
import { ReportDialog, Resolved } from "./Resolved";

type Option = { id: string; text: string };
const LETTERS = ["A", "B", "C", "D", "E", "F"];
/** Review has two hint rungs; the third (the worked solution) is "Show answer". */
const MAX_HINTS = 2;

type Phase =
  /** choosing: the first try, or the second after a wrong one */
  | "answering"
  | "checking"
  | "resolved"
  /** sent or queued without feedback (offline, or the server only confirmed it): one try, move on */
  | "saved"
  | "rejected";

type QState = {
  phase: Phase;
  selected: string | null;
  /** the server's latest word on this question */
  feedback: Graded | null;
  hints: HintOut[];
  guessing: boolean;
  offline: boolean;
  reason: string | null;
  reported: boolean;
};

const FRESH: QState = {
  phase: "answering",
  selected: null,
  feedback: null,
  hints: [],
  guessing: false,
  offline: false,
  reason: null,
  reported: false,
};

function restored(state: Graded | null): QState {
  if (!state) return FRESH;
  return { ...FRESH, feedback: state, phase: state.resolved ? "resolved" : "answering" };
}

const touched = (g: Graded | null) => !!g && (g.resolved === true || (g.tries ?? 0) > 0 || (g.hints ?? 0) > 0);
const isDone = (q: QState | undefined) => !!q && (q.phase === "resolved" || q.phase === "saved" || q.phase === "rejected" || q.reported);

/** The reserves to ask now: one per objective whose question was revealed, each reserve once. */
function reservesDue(session: ReviewSession, asked: ReviewItem[], states: Record<string, QState | undefined>): ReviewItem[] {
  const revealed = new Set<string>();
  for (const item of asked) {
    if (states[item.item_version_id]?.feedback?.outcome === "revealed") item.objectives.forEach((o) => revealed.add(o));
  }
  const taken = new Set(asked.map((i) => i.item_version_id));
  return session.reserves.filter((r) => !taken.has(r.item_version_id) && r.objectives.some((o) => revealed.has(o)));
}

type Start = { asked: ReviewItem[]; states: Record<string, QState>; index: number; allDone: boolean };

/** Where a session starts: at the first question, or (resumed) at the first one not yet resolved. */
function startOf(session: ReviewSession): Start {
  const states: Record<string, QState> = {};
  for (const item of [...session.items, ...session.reserves]) states[item.item_version_id] = restored(item.state);
  let asked = [...session.items, ...session.reserves.filter((r) => touched(r.state))];
  let index = asked.findIndex((i) => !isDone(states[i.item_version_id]));
  if (index === -1) {
    const more = reservesDue(session, asked, states);
    index = more.length ? asked.length : -1;
    asked = [...asked, ...more];
  }
  return { asked, states, index: Math.max(index, 0), allDone: index === -1 };
}

function segmentState(q: QState | undefined): SegmentState {
  if (q?.reported) return "skipped";
  const outcome = q?.feedback?.resolved ? q.feedback.outcome : null;
  if (outcome === "first" || outcome === "second" || outcome === "revealed") return outcome;
  if (q?.phase === "saved" || q?.phase === "rejected") return "saved";
  return "todo";
}

export function ReviewPlayer({
  pathId,
  session,
  onAgain,
}: {
  pathId: string;
  session: ReviewSession & { assessment_id: string };
  /** starts another session (the results offer it when there is more to review) */
  onAgain: () => void;
}) {
  const { t } = useLingui();
  const outbox = useOutbox();
  const tutor = useTutorActions();
  const qc = useQueryClient();
  const start = useMemo(() => startOf(session), [session]);
  const [attemptId] = useState(() => session.attempt_id ?? uuid7());
  const [asked, setAsked] = useState(start.asked);
  const [states, setStates] = useState(start.states);
  const [index, setIndex] = useState(start.index);
  const [finished, setFinished] = useState<"no" | "sending" | "sent" | "offline">("no");
  const [reporting, setReporting] = useState(false);
  const [hintError, setHintError] = useState<unknown>(null);
  const [loadingHint, setLoadingHint] = useState(false);
  const shownAt = useRef(Date.now());
  const promptRef = useRef<HTMLHeadingElement>(null);
  const nextRef = useRef<HTMLDivElement>(null);
  /** response event id -> the question it answers, for grades that arrive in a later flush */
  const responses = useRef(new Map<string, string>());
  const indexRef = useRef(index);
  indexRef.current = index;

  const item = asked[index];
  const iv = item?.item_version_id ?? "";
  const q = states[iv] ?? FRESH;
  const patch = useCallback(
    (id: string, change: Partial<QState> | ((q: QState) => Partial<QState>)) =>
      setStates((s) => {
        const before = s[id] ?? FRESH;
        return { ...s, [id]: { ...before, ...(typeof change === "function" ? change(before) : change) } };
      }),
    [],
  );

  // one attempt.started per attempt; a resumed attempt already has one
  const started = useRef(false);
  useEffect(() => {
    if (started.current || session.attempt_id) return;
    started.current = true;
    void outbox.enqueue("attempt.started", {
      attempt_id: attemptId,
      assessment_id: session.assessment_id,
      purpose: "review",
    });
  }, [outbox, attemptId, session]);

  const finish = useEvent(async () => {
    if (finished !== "no" && finished !== "offline") return;
    if (finished === "no") await outbox.enqueue("attempt.finished", { attempt_id: attemptId, outcome: "finished" });
    setFinished("sending");
    const result = await outbox.flush();
    setFinished(result.offline ? "offline" : "sent");
    void qc.invalidateQueries({ queryKey: reviewKeys.hub(pathId) });
    void qc.invalidateQueries({ queryKey: keys.progress(pathId) });
  });

  // a resumed session with nothing left to ask goes straight to its results
  const resumedDone = useRef(false);
  useEffect(() => {
    if (!start.allDone || resumedDone.current) return;
    resumedDone.current = true;
    void finish();
  }, [start.allDone, finish]);

  /** What the server said about an answer, or that it has not said anything yet. */
  const settle = useCallback(
    (id: string, graded: Graded | undefined, result: FlushResult | null, eventId: string) => {
      if (graded) {
        if (graded.resolved) patch(id, { phase: "resolved", feedback: graded, offline: false });
        else if (asked[indexRef.current]?.item_version_id === id) {
          // wrong, and another try is allowed
          patch(id, { phase: "answering", feedback: graded, selected: null, offline: false });
          shownAt.current = Date.now();
        } else patch(id, { feedback: graded, offline: false }); // they moved on: one try, as when offline
        return;
      }
      const reason = result?.rejected[eventId];
      if (reason !== undefined) patch(id, { phase: "rejected", reason });
      else if (result && (result.accepted.includes(eventId) || result.duplicates.includes(eventId))) {
        patch(id, { phase: "saved", offline: false });
      } else patch(id, { phase: "saved", offline: true });
    },
    [patch, asked],
  );

  useEffect(
    () =>
      outbox.onGraded((eventId, graded) => {
        const id = responses.current.get(eventId);
        if (id) settle(id, graded, null, eventId);
      }),
    [outbox, settle],
  );

  // a resumed question had hints: fetch their text again (reading a hint is not help by itself; the events exist)
  const wantHints = Math.min(q.feedback?.hints ?? 0, MAX_HINTS);
  useEffect(() => {
    if (!iv || q.phase !== "answering" || q.hints.length >= wantHints) return;
    let stale = false;
    void Promise.all(Array.from({ length: wantHints }, (_, i) => fetchHint(iv, i + 1)))
      .then((hints) => {
        if (!stale) patch(iv, (now) => (now.hints.length < hints.length ? { hints } : {}));
      })
      .catch(() => {});
    return () => {
      stale = true;
    };
  }, [iv, q.phase, q.hints.length, wantHints, patch]);

  const options = ((item?.view["options"] as Option[] | undefined) ?? []).slice(0, LETTERS.length);
  const tried = q.feedback?.tried ?? [];
  const canAnswer = finished === "no" && q.phase === "answering" && !q.reported;
  const hintsLeft = canAnswer && q.hints.length < MAX_HINTS;
  const more = reservesDue(session, asked, states);
  const isLast = index >= asked.length - 1 && more.length === 0;

  const select = (id: string) => {
    if (canAnswer && !tried.includes(id)) patch(iv, { selected: id });
  };

  const submit = useEvent(async () => {
    if (!canAnswer || q.selected === null) return;
    patch(iv, { phase: "checking" });
    const event = await outbox.enqueue("assessment.response_given", {
      attempt_id: attemptId,
      item_version_id: iv,
      answer: q.selected,
      ms_to_answer: Math.max(0, Math.round(Date.now() - shownAt.current)),
      ...(q.guessing ? { confidence: "guessing" as const } : {}),
    });
    responses.current.set(event.id, iv);
    const result = await outbox.flush();
    settle(iv, result.graded[event.id], result, event.id);
  });

  const showHint = useEvent(async () => {
    if (!hintsLeft || loadingHint) return;
    setLoadingHint(true);
    setHintError(null);
    try {
      const hint = await fetchHint(iv, q.hints.length + 1);
      patch(iv, (now) => ({ hints: [...now.hints, hint] }));
      void outbox.enqueue("item.support_shown", {
        item_version_id: iv,
        attempt_id: attemptId,
        kind: "hint",
        level: hint.level,
      });
    } catch (err) {
      setHintError(err);
    } finally {
      setLoadingHint(false);
    }
  });

  const showAnswer = useEvent(async () => {
    if (!canAnswer) return;
    patch(iv, { phase: "checking", selected: null });
    await outbox.enqueue("item.support_shown", { item_version_id: iv, attempt_id: attemptId, kind: "solution", level: 0 });
    const result = await outbox.flush();
    if (result.offline) return patch(iv, { phase: "saved", offline: true });
    try {
      const feedback = await fetchReviewFeedback(attemptId, iv);
      patch(iv, { phase: feedback.resolved ? "resolved" : "saved", feedback, offline: false });
    } catch {
      patch(iv, { phase: "saved", offline: true });
    }
  });

  const next = useEvent(() => {
    if (finished !== "no") return;
    setHintError(null);
    if (index < asked.length - 1) setIndex(index + 1);
    else if (more.length > 0) {
      setAsked([...asked, ...more]);
      setIndex(index + 1);
    } else void finish();
  });

  // a new question: the timer starts, and the prompt takes the focus so it is read
  const firstIndex = useRef(index);
  useEffect(() => {
    shownAt.current = Date.now();
    if (firstIndex.current !== index) promptRef.current?.focus();
    firstIndex.current = -1;
  }, [index]);

  const done = isDone(q);
  useEffect(() => {
    if (done) nextRef.current?.querySelector("button")?.focus();
  }, [done, iv]);

  // keys: 1-4 or A-D choose, Enter checks or goes on, H a hint, T the tutor
  const onKey = useEvent((e: KeyboardEvent) => {
    if (finished !== "no" || reporting || e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
    const el = e.target instanceof HTMLElement ? e.target : null;
    if (el?.closest("input, textarea, select, [contenteditable], [role='dialog'], [role='menu'], aside")) return;
    const key = e.key.toLowerCase();
    const n = /^[1-9]$/.test(key) ? Number(key) - 1 : key.length === 1 ? LETTERS.indexOf(key.toUpperCase()) : -1;
    const option = n >= 0 ? options[n] : undefined;
    if (option) {
      e.preventDefault();
      select(option.id);
    } else if (key === "enter") {
      // a focused button or link keeps its own Enter; an answer option submits like the page does
      if (el?.closest("button, a, summary") && !el.closest("[data-option]")) return;
      e.preventDefault();
      if (done) next();
      else void submit();
    } else if (key === "h") {
      e.preventDefault();
      void showHint();
    } else if (key === "t") {
      e.preventDefault();
      tutor.open();
    }
  });
  useEffect(() => {
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onKey]);

  // the tutor resolves its policy from the attempt and the question on screen (no spoilers until it is resolved)
  useTutorRefs({
    screen: "review",
    path_id: pathId,
    skill_id: item?.skill_id ?? null,
    attempt_id: attemptId,
    item_version_id: finished === "no" ? iv || null : null,
  });

  if (finished !== "no") {
    return <Results pathId={pathId} attemptId={attemptId} state={finished} onRetry={() => void finish()} onAgain={onAgain} />;
  }
  if (!item) return null;

  const number = index + 1;
  const total = asked.length;
  const reask = index >= session.items.length || session.reserves.some((r) => r.item_version_id === iv);
  const fb = q.feedback;
  const resolved = q.phase === "resolved" && fb !== null;
  const wrongTry = !resolved && tried.length > 0 && q.phase !== "saved";
  const segments: Segment[] = asked.map((it, i) => {
    const state = segmentState(states[it.item_version_id]);
    const n = i + 1;
    return {
      id: it.item_version_id,
      state,
      current: i === index,
      reask: i >= session.items.length,
      label: {
        todo: i === index ? t({ id: "review.vine.current", message: `Question ${n}: this one` }) : t({ id: "review.vine.todo", message: `Question ${n}: to come` }),
        first: t({ id: "review.vine.first", message: `Question ${n}: right on the first try` }),
        second: t({ id: "review.vine.second", message: `Question ${n}: right on the second try` }),
        revealed: t({ id: "review.vine.revealed", message: `Question ${n}: answer shown` }),
        saved: t({ id: "review.vine.saved", message: `Question ${n}: answer saved` }),
        skipped: t({ id: "review.vine.skipped", message: `Question ${n}: reported` }),
      }[state],
    };
  });

  const optionState = (id: string): OptionState => {
    if (resolved) {
      if (fb.correct === id) return "right";
      return tried.includes(id) ? "wrong" : "other";
    }
    if (tried.includes(id)) return "tried";
    return q.selected === id ? "selected" : "idle";
  };
  const markLabel = (state: OptionState): string | undefined =>
    state === "right"
      ? t({ id: "review.option.right", message: "Right answer" })
      : state === "wrong"
        ? t({ id: "review.option.yours", message: "Your answer" })
        : state === "tried"
          ? t({ id: "review.option.tried", message: "Tried" })
          : undefined;
  const kind = {
    recall: t({ id: "review.kind.recall", message: "Recall" }),
    apply: t({ id: "review.kind.apply", message: "Apply" }),
    scenario: t({ id: "review.kind.scenario", message: "Scenario" }),
    compare: t({ id: "review.kind.compare", message: "Compare" }),
    debug: t({ id: "review.kind.debug", message: "Find the mistake" }),
  }[item.kind];
  const level = item.level;
  const promptId = `review-q-${iv}`;
  const reason = q.reason ?? "";

  return (
    <div className={styles.player}>
      <div className={styles.playerTop}>
        <div className={styles.playerBar}>
          <p className={styles.counter}>
            <Trans id="review.progress">
              Question {number} of {total}
            </Trans>
          </p>
          <MenuTrigger>
            <AriaButton className={styles.quiet} aria-label={t({ id: "review.menu.label", message: "More for this question" })}>
              <MoreIcon />
            </AriaButton>
            <Popover className={styles.menuPopover} placement="bottom end">
              <Menu
                className={styles.menu}
                aria-label={t({ id: "review.menu.label", message: "More for this question" })}
                onAction={(key) => {
                  if (key === "tutor") tutor.open();
                  else if (key === "report") setReporting(true);
                }}
              >
                <MenuItem id="tutor" className={styles.menuItem}>
                  <Trans id="review.menu.tutor">Ask the tutor</Trans>
                </MenuItem>
                <MenuItem id="report" className={styles.menuItem}>
                  <Trans id="review.menu.report">Report question</Trans>
                </MenuItem>
              </Menu>
            </Popover>
          </MenuTrigger>
        </div>
        <ProgressVine segments={segments} label={t({ id: "review.vine.label", message: "Questions of this session" })} />
      </div>

      <section className={`${ui.card} ${styles.question}`} aria-labelledby={promptId}>
        <div className={styles.badges}>
          <span className={styles.skillName}>{item.skill_title}</span>
          <Badge>{kind}</Badge>
          {item.cross ? (
            <Badge tone="success">
              <Trans id="review.badge.cross">Connects lessons</Trans>
            </Badge>
          ) : null}
          <Badge>
            <Trans id="review.badge.level">Level {level}</Trans>
          </Badge>
          {reask ? (
            <Badge tone="highlight">
              <Trans id="review.badge.reask">Asked again</Trans>
            </Badge>
          ) : null}
        </div>
        <h2 id={promptId} ref={promptRef} tabIndex={-1} className={styles.prompt}>
          {String(item.view["prompt"] ?? "")}
        </h2>

        <div className={styles.options} role="group" aria-labelledby={promptId}>
          {options.map((o, i) => {
            const state = optionState(o.id);
            const why = fb?.rationales?.[o.id];
            return (
              <OptionButton
                key={o.id}
                letter={LETTERS[i] ?? ""}
                text={o.text}
                state={state}
                disabled={!canAnswer || state === "tried"}
                onPress={() => select(o.id)}
                markLabel={markLabel(state)}
                note={why && (resolved || state === "tried") ? why : undefined}
              />
            );
          })}
        </div>

        {q.hints.length > 0 && !resolved ? (
          <ol className={styles.hints} aria-label={t({ id: "review.hints.label", message: "Hints" })}>
            {q.hints.map((h) => (
              <li key={h.level}>{h.text}</li>
            ))}
          </ol>
        ) : null}
        {hintError ? <ErrorNotice error={hintError} /> : null}

        {wrongTry && q.phase === "answering" ? (
          <Notice tone="warning" role="status" icon={<CloseIcon />} className={grove.nudge}>
            <strong>
              <Trans id="review.feedback.retry">Not quite. One more try.</Trans>
            </strong>
          </Notice>
        ) : null}
        {q.phase === "checking" ? (
          <p className={`${ui.waiting} ${ui.muted}`} role="status">
            <span className={ui.spinner} aria-hidden="true" />
            <Trans id="review.checking">Checking…</Trans>
          </p>
        ) : null}
        {q.phase === "saved" ? (
          <Notice tone={q.offline ? "warning" : "info"} role="status">
            {q.offline ? (
              <Trans id="review.saved-offline">Saved. You will see the feedback when you are back online.</Trans>
            ) : (
              <Trans id="review.saved">Saved. The feedback is in the results.</Trans>
            )}
          </Notice>
        ) : null}
        {q.phase === "rejected" ? (
          <Notice tone="error">
            <Trans id="review.rejected">This answer could not be recorded: {reason}</Trans>
          </Notice>
        ) : null}
        {resolved ? <Resolved feedback={fb} /> : null}

        {canAnswer ? (
          <>
            <div className={styles.actions}>
              <Button onPress={() => void submit()} isDisabled={q.selected === null}>
                <CheckIcon />
                {wrongTry ? <Trans id="review.try-again">Try again</Trans> : <Trans id="review.check">Check answer</Trans>}
              </Button>
              <Button variant="ghost" onPress={() => void showHint()} isDisabled={!hintsLeft || loadingHint}>
                <QuestionIcon />
                {q.hints.length === 0 ? (
                  <Trans id="review.hint">Hint</Trans>
                ) : hintsLeft ? (
                  <Trans id="review.hint.next">Another hint</Trans>
                ) : (
                  <Trans id="review.hint.none">No more hints</Trans>
                )}
              </Button>
              {wrongTry ? (
                <Button variant="ghost" onPress={() => void showAnswer()}>
                  <Trans id="review.show-answer">Show answer</Trans>
                </Button>
              ) : null}
            </div>
            <Switch
              className={styles.guess}
              isSelected={q.guessing}
              onChange={(guessing) => patch(iv, { guessing })}
            >
              <span className={styles.guessTrack} aria-hidden="true">
                <span className={styles.guessThumb} />
              </span>
              <Trans id="review.guessing">I'm guessing</Trans>
            </Switch>
          </>
        ) : null}

        {done ? (
          <div className={styles.actions} ref={nextRef}>
            <Button onPress={next}>
              {isLast ? <Trans id="review.finish">See results</Trans> : <Trans id="review.next">Next</Trans>}
              <ArrowRightIcon />
            </Button>
          </div>
        ) : null}
      </section>

      <ul className={styles.legend} aria-label={t({ id: "review.keys.label", message: "Keyboard shortcuts" })}>
        <li>
          <kbd>1</kbd>–<kbd>4</kbd> <Trans id="review.keys.choose">or A–D: choose</Trans>
        </li>
        <li>
          <kbd>Enter</kbd> <Trans id="review.keys.enter">check, next</Trans>
        </li>
        <li>
          <kbd>H</kbd> <Trans id="review.keys.hint">hint</Trans>
        </li>
        <li>
          <kbd>T</kbd> <Trans id="review.keys.tutor">tutor</Trans>
        </li>
      </ul>

      <ReportDialog
        open={reporting}
        itemId={item.item_id}
        onClose={() => setReporting(false)}
        onReported={() => {
          setReporting(false);
          patch(iv, { reported: true });
          next();
        }}
      />
    </div>
  );
}
