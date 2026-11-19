"""Projections over the event log: response, attempt, review_state, skill_progress,
xp_daily, achievement. Each is a deterministic function of the events, `ALGO_VERSION` and a settings
snapshot, so `rebuild_learner` reproduces exactly what incremental updates wrote (tested).

Ordering is (`device_at`, `id`) Late or out-of-order events recompute only the keys they
touch: the item, its skill (and the skills that depend on it), the day, the attempt.

Decay depends on the current time, not only on events, so it is applied when progress is read
(`needs_review` overlay in `progress_view`), never stored.
"""

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from yuo.core import clock
from yuo.core.hashing import content_hash

ALGO_VERSION = 1
HELP_WEIGHT = {
    "none": 1.0,
    "hint": 0.6,
    "tutor": 0.5,
    "solution": 0.2,
}  # assisted successes count less
PURPOSE_WEIGHT = {"practice": 1.0, "review": 1.0, "skill_test": 2.0, "placement": 2.0}
PRIOR = 2.0  # pseudo-evidence at score 0: mastery starts low and needs several good answers
HALF_LIFE_DAYS = 30.0  # older evidence counts less, relative to the learner's latest graded answer
XP_CORRECT, XP_LESSON, XP_TEST = 10, 20, 50
DECAY_BELOW = 0.7  # mean retrievability of a mastered skill's items under which it needs review


class Scheduler(Protocol):
    name: str

    def review(
        self, state: dict[str, Any] | None, rating: int, at: datetime
    ) -> tuple[dict[str, Any], datetime]: ...
    def retrievability(self, state: dict[str, Any], at: datetime) -> float: ...
    def tuned(self, desired_retention: float, max_interval_days: int) -> Scheduler: ...


@dataclass(frozen=True)
class Settings:
    grace_days_per_week: int = 1
    decay: bool = True  # read-time overlay
    retention: float = 0.9  # objective-level review
    max_interval_days: int = 0  # 0 = no cap

    def snapshot_hash(self) -> str:
        return content_hash({"algo": ALGO_VERSION, "grace": self.grace_days_per_week})

    def review_hash(self) -> str:
        return content_hash(
            {"algo": ALGO_VERSION, "retention": self.retention, "max_interval": self.max_interval_days}
        )


@dataclass
class Touched:
    items: set[str] = field(default_factory=set)
    skills: set[str] = field(default_factory=set)
    days: set[str] = field(default_factory=set)
    attempts: set[str] = field(default_factory=set)
    objectives: set[str] = field(default_factory=set)


def _events(c: sqlite3.Connection, where: str, *args: Any) -> list[sqlite3.Row]:
    c.row_factory = sqlite3.Row
    return c.execute(f"SELECT * FROM learning_event WHERE {where} ORDER BY device_at, id", args).fetchall()


def rating_for(score: float, help_kind: str, method: str) -> int:
    """FSRS rating from a graded response: self-graded cards carry the learner's own rating in the score."""
    if method == "self":
        return {0.0: 1, 0.5: 2, 0.8: 3, 1.0: 4}.get(round(score, 1), 3)
    if score < 0.6:
        return 1
    return 3 if help_kind == "none" and score >= 0.99 else 2


# --- responses and review state, per item --------------------------------------------------------


def rebuild_item(c: sqlite3.Connection, learner: str, item_id: str, sched: Scheduler, s: Settings) -> None:
    versions = [r[0] for r in c.execute("SELECT id FROM item_version WHERE item_id = ?", (item_id,))]
    if not versions:
        return
    marks = ",".join("?" * len(versions))
    given = _events(
        c,
        f"learner_id = ? AND type = 'assessment.response_given' AND item_version_id IN ({marks})",
        learner,
        *versions,
    )
    c.execute(
        f"DELETE FROM response WHERE item_version_id IN ({marks}) AND response_event_id IN "
        "(SELECT id FROM learning_event WHERE learner_id = ?)",
        (*versions, learner),
    )
    now = clock.now()
    state: dict[str, Any] | None = None
    due, last = None, None
    # a review-bank question has no card of its own: its objectives are scheduled (rebuild_objective), so
    # the next review brings a fresh question on the same idea, not the same question again
    banked = (
        c.execute("SELECT extensions ->> '$.yuo.use' FROM item WHERE id = ?", (item_id,)).fetchone()[0]
        == "review"
    )
    for ev in given:
        p = json.loads(ev["payload"])
        grade = c.execute(
            "SELECT id, payload FROM learning_event WHERE type = 'assessment.response_graded' "
            "AND payload ->> '$.response_event_id' = ? ORDER BY server_seq DESC LIMIT 1",
            (ev["id"],),
        ).fetchone()
        help_kind, depth = _help(c, learner, ev)
        score = method = None
        if grade is not None:
            g = json.loads(grade[1])
            score, method = g["score"], g["grading_method"]
        c.execute(
            "INSERT INTO response (response_event_id, attempt_id, item_version_id, answered_at, help_kind, hint_depth, "
            "ms_to_answer, latest_grade_event_id, score, grading_method, algo_version, inputs_hash, rebuilt_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ev["id"],
                p["attempt_id"],
                ev["item_version_id"],
                ev["device_at"],
                help_kind,
                depth,
                p.get("ms_to_answer"),
                grade[0] if grade else None,
                score,
                method,
                ALGO_VERSION,
                s.snapshot_hash(),
                now,
            ),
        )
        if score is not None and method is not None and not banked:
            at = clock.parse_timestamp(ev["device_at"])
            state, due_dt = sched.review(state, rating_for(score, help_kind, method), at)
            due, last = clock.to_timestamp(due_dt), ev["device_at"]
    c.execute(
        "DELETE FROM review_state WHERE learner_id = ? AND item_id = ? AND facet = ''", (learner, item_id)
    )
    if state is not None and due is not None:
        c.execute(
            "INSERT INTO review_state (learner_id, item_id, facet, scheduler, state, due_at, last_review_at, "
            "algo_version, inputs_hash, rebuilt_at) VALUES (?, ?, '', ?, json(?), ?, ?, ?, ?, ?)",
            (
                learner,
                item_id,
                sched.name,
                json.dumps(state),
                due,
                last,
                ALGO_VERSION,
                s.snapshot_hash(),
                now,
            ),
        )


def _help(c: sqlite3.Connection, learner: str, response: sqlite3.Row) -> tuple[str, int]:
    """The help shown for this item in this attempt before the answer: derived on the server."""
    rows = c.execute(
        "SELECT type, payload FROM learning_event WHERE learner_id = ? AND type IN ('item.support_shown', "
        "'tutor.help_given') AND item_version_id = ? AND attempt_id IS ? AND (device_at, id) < (?, ?)",
        (learner, response["item_version_id"], response["attempt_id"], response["device_at"], response["id"]),
    ).fetchall()
    kind, depth = "none", 0
    for etype, payload in rows:
        p = json.loads(payload)
        if etype == "tutor.help_given":
            kind = "tutor" if kind in ("none", "hint") else kind
        elif p["kind"] == "solution":
            kind = "solution"
        elif p["kind"] == "hint":
            depth = max(depth, int(p["level"]))
            kind = "hint" if kind == "none" else kind
    return kind, depth


# --- review sessions: outcome per question, memory per objective ----------------------------

XP_FIRST_TRY, XP_SECOND_TRY = 10, 5
XP_SESSION_MIN = 3  # answers a review session needs before it earns XP
XP_SESSIONS_PER_DAY = 3  # review sessions a day that earn XP
RATING_AGAIN, RATING_HARD, RATING_GOOD, RATING_EASY = 1, 2, 3, 4
MAX_TRIES = 2


def is_bank(c: sqlite3.Connection, attempt_id: str) -> bool:
    """True for an attempt of a review session over the question bank (not the flashcard queue)."""
    row = c.execute(
        "SELECT a.settings_snapshot ->> '$.review.kind' FROM learning_event e JOIN assessment a ON a.id = "
        "e.payload ->> '$.assessment_id' WHERE e.type = 'attempt.started' AND e.attempt_id = ?",
        (attempt_id,),
    ).fetchone()
    return bool(row) and row[0] == "bank"


@dataclass
class Outcome:
    """What happened to one question in one review session, from the events alone."""

    tries: list[tuple[str, Any, float]] = field(default_factory=list)  # (response event id, answer, score)
    right_on: int | None = None  # the try that was right, if any
    revealed: bool = False  # "Show answer", or two wrong tries
    hints: int = 0
    tutor: bool = False
    guessing: bool = False

    @property
    def resolved(self) -> bool:
        return self.right_on is not None or self.revealed

    @property
    def kind(self) -> str:
        """first | second | revealed | open (a wrong try, more allowed) | new (not answered)."""
        if self.right_on == 1 and not self.revealed:
            return "first"
        if self.right_on is not None and not self.revealed:
            return "second"
        if self.revealed:
            return "revealed"
        return "open" if self.tries else "new"

    @property
    def helped(self) -> bool:
        return self.hints > 0 or self.tutor


def item_outcome(c: sqlite3.Connection, learner: str, attempt_id: str, item_version_id: str) -> Outcome:
    out = Outcome()
    rows = c.execute(
        "SELECT id, type, payload FROM learning_event WHERE learner_id = ? AND attempt_id = ? AND "
        "item_version_id = ? AND type IN ('assessment.response_given', 'item.support_shown', 'tutor.help_given') "
        "ORDER BY device_at, id",
        (learner, attempt_id, item_version_id),
    ).fetchall()
    for eid, etype, payload in rows:
        p = json.loads(payload)
        if etype == "tutor.help_given":
            out.tutor = out.tutor or not out.resolved
        elif etype == "item.support_shown":
            if out.resolved:
                continue  # looking at the solution of a resolved question is not help
            if p["kind"] == "solution":
                out.revealed = True
            elif p["kind"] == "hint":
                out.hints = max(out.hints, int(p["level"]))
        elif not out.resolved and len(out.tries) < MAX_TRIES:
            grade = c.execute(
                "SELECT payload ->> '$.score' FROM learning_event WHERE type = 'assessment.response_graded' "
                "AND payload ->> '$.response_event_id' = ? ORDER BY server_seq DESC LIMIT 1",
                (eid,),
            ).fetchone()
            score = float(grade[0]) if grade and grade[0] is not None else 0.0
            out.tries.append((eid, p["answer"], score))
            out.guessing = out.guessing or p.get("confidence") == "guessing"
            if score >= 0.999:
                out.right_on = len(out.tries)
            elif len(out.tries) == MAX_TRIES:
                out.revealed = True
    return out


def session_rating(outcomes: list[Outcome]) -> int | None:
    """One FSRS rating per objective per session, from all its answered questions (never one per try)."""
    answered = [o for o in outcomes if o.tries or o.revealed]
    if not answered:
        return None
    # a question left on a wrong try (an offline session, or one given up) was not recalled
    if any(o.kind in ("revealed", "open") for o in answered):
        return RATING_AGAIN
    if any(o.kind == "second" or o.helped or o.guessing for o in answered):
        return RATING_HARD
    return RATING_EASY if len(answered) >= 2 else RATING_GOOD


def _session_items(c: sqlite3.Connection, attempt_id: str) -> list[str]:
    row = c.execute(
        "SELECT a.item_version_ids FROM learning_event e JOIN assessment a ON a.id = e.payload ->> "
        "'$.assessment_id' WHERE e.type = 'attempt.started' AND e.attempt_id = ?",
        (attempt_id,),
    ).fetchone()
    return list(json.loads(row[0])) if row else []


def objective_history(
    c: sqlite3.Connection,
    learner: str,
    objective_id: str,
    sched: Scheduler,
    *,
    before_attempt: str | None = None,
) -> tuple[dict[str, Any] | None, datetime | None, str | None, int, int]:
    """Replay an objective's reviews: (state, due, last review, reviews, lapses). The first card is virtual:
    Good on the day the first lesson that teaches the objective was completed. `before_attempt` stops
    before that session (the memory a session started from)."""
    first = c.execute(
        "SELECT e.device_at, e.id FROM learning_event e JOIN lesson_version cv ON cv.id = e.lesson_version_id "
        "WHERE e.learner_id = ? AND e.type = 'lesson.completed' AND EXISTS (SELECT 1 FROM "
        "lesson_version_objective o JOIN lesson_version x ON x.id = o.lesson_version_id WHERE x.lesson_id = "
        "cv.lesson_id AND o.objective_id = ?) ORDER BY e.device_at, e.id LIMIT 1",
        (learner, objective_id),
    ).fetchone()
    steps: list[tuple[str, str, int, bool]] = []  # (at, event id, rating, a real review)
    if first:
        steps.append((first[0], first[1], RATING_GOOD, False))
    sessions = c.execute(
        "SELECT DISTINCT f.attempt_id, f.device_at, f.id FROM learning_event f JOIN learning_event r ON "
        "r.attempt_id = f.attempt_id AND r.type = 'assessment.response_given' JOIN item_version_objective o ON "
        "o.item_version_id = r.item_version_id WHERE f.learner_id = ? AND f.type = 'attempt.finished' AND "
        "o.objective_id = ? ORDER BY f.device_at, f.id",
        (learner, objective_id),
    ).fetchall()
    for attempt_id, at, eid in sessions:
        if attempt_id == before_attempt:
            break
        if not is_bank(c, attempt_id):
            continue
        linked = [
            v
            for v in _session_items(c, attempt_id)
            if c.execute(
                "SELECT 1 FROM item_version_objective WHERE item_version_id = ? AND objective_id = ?",
                (v, objective_id),
            ).fetchone()
        ]
        rating = session_rating([item_outcome(c, learner, attempt_id, v) for v in linked])
        if rating is not None:
            steps.append((at, eid, rating, True))
    state: dict[str, Any] | None = None
    due: datetime | None = None
    last: str | None = None
    reviews = lapses = 0
    for at, _, rating, real in sorted(steps):
        state, due = sched.review(state, rating, clock.parse_timestamp(at))
        if real:
            last = at
            reviews += 1
            lapses += rating == RATING_AGAIN
    return state, due, last, reviews, lapses


def rebuild_objective(
    c: sqlite3.Connection, learner: str, objective_id: str, sched: Scheduler, s: Settings
) -> None:
    tuned = sched.tuned(s.retention, s.max_interval_days)
    state, due, last, reviews, lapses = objective_history(c, learner, objective_id, tuned)
    c.execute(
        "DELETE FROM objective_review_state WHERE learner_id = ? AND objective_id = ?",
        (learner, objective_id),
    )
    if state is None or due is None:
        return
    c.execute(
        "INSERT INTO objective_review_state (learner_id, objective_id, scheduler, state, due_at, last_review_at, "
        "reviews, lapses, algo_version, inputs_hash, rebuilt_at) VALUES (?, ?, ?, json(?), ?, ?, ?, ?, ?, ?, ?)",
        (
            learner,
            objective_id,
            tuned.name,
            json.dumps(state),
            clock.to_timestamp(due),
            last,
            reviews,
            lapses,
            ALGO_VERSION,
            s.review_hash(),
            clock.now(),
        ),
    )


# --- attempts ------------------------------------------------------------------------------------


def rebuild_attempt(c: sqlite3.Connection, learner: str, attempt_id: str, s: Settings) -> None:
    c.execute("DELETE FROM attempt WHERE id = ?", (attempt_id,))
    events = _events(
        c,
        "learner_id = ? AND attempt_id = ? AND type IN ('attempt.started', 'attempt.finished')",
        learner,
        attempt_id,
    )
    started = next((e for e in events if e["type"] == "attempt.started"), None)
    if started is None:
        return
    finished = next((e for e in events if e["type"] == "attempt.finished"), None)
    p = json.loads(started["payload"])
    score = attempt_score(c, attempt_id, p["assessment_id"]) if finished else None
    c.execute(
        "INSERT INTO attempt (id, assessment_id, learner_id, started_at, finished_at, outcome, score, algo_version, "
        "inputs_hash, rebuilt_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            attempt_id,
            p["assessment_id"],
            learner,
            started["device_at"],
            finished["device_at"] if finished else None,
            json.loads(finished["payload"])["outcome"] if finished else None,
            score,
            ALGO_VERSION,
            s.snapshot_hash(),
            clock.now(),
        ),
    )


def attempt_score(c: sqlite3.Connection, attempt_id: str, assessment_id: str) -> float:
    """Mean of the latest grades over the assessment's pinned items; unanswered items count 0."""
    pinned = json.loads(
        c.execute("SELECT item_version_ids FROM assessment WHERE id = ?", (assessment_id,)).fetchone()[0]
    )
    if not pinned:
        return 0.0
    scores = {
        r[0]: r[1]
        for r in c.execute(
            "SELECT item_version_id, score FROM response WHERE attempt_id = ? AND score IS NOT NULL "
            "ORDER BY answered_at",
            (attempt_id,),
        )
    }
    return float(sum(scores.get(v, 0.0) for v in pinned) / len(pinned))


# --- skills --------------------------------------------------------------------------------------


def _mastered_events(c: sqlite3.Connection, learner: str, skill_id: str) -> bool:
    for ev in _events(
        c,
        "learner_id = ? AND skill_id = ? AND type IN ('skill.test_result', 'skill.placed', 'skill.override')",
        learner,
        skill_id,
    ):
        p = json.loads(ev["payload"])
        if ev["type"] == "skill.test_result" and p["passed"]:
            return True
        if ev["type"] == "skill.placed" and p["result"] == "mastered":
            return True
        if ev["type"] == "skill.override" and p["new_state"] == "mastered":
            return True
    return False


def _override(c: sqlite3.Connection, learner: str, skill_id: str) -> str | None:
    rows = _events(c, "learner_id = ? AND skill_id = ? AND type = 'skill.override'", learner, skill_id)
    return json.loads(rows[-1]["payload"])["new_state"] if rows else None


def skill_state(c: sqlite3.Connection, learner: str, skill_id: str) -> str:
    if (o := _override(c, learner, skill_id)) is not None:
        return o
    if _mastered_events(c, learner, skill_id):
        return "mastered"
    prereqs = [
        r[0]
        for r in c.execute("SELECT requires_skill_id FROM skill_prerequisite WHERE skill_id = ?", (skill_id,))
    ]
    # unlock is monotonic: it follows mastered events, which are never retracted except by override
    if all(skill_state(c, learner, p) == "mastered" for p in prereqs):
        active = c.execute(
            "SELECT 1 FROM learning_event e WHERE e.learner_id = ? AND (e.skill_id = ? OR e.item_version_id IN "
            "(SELECT v.id FROM item_version v JOIN item i ON i.id = v.item_id WHERE i.skill_id = ?) OR "
            "e.lesson_version_id IN (SELECT v.id FROM lesson_version v JOIN lesson l ON l.id = v.lesson_id "
            "WHERE l.skill_id = ?)) LIMIT 1",
            (learner, skill_id, skill_id, skill_id),
        ).fetchone()
        return "in_progress" if active else "available"
    return "locked"


def mastery(
    c: sqlite3.Connection, learner: str, skill_id: str, until: str | None = None
) -> tuple[float, int, str | None]:
    """A skill's mastery from the learner's graded answers (recent ones weigh more); `until`: as it was then."""
    rows = c.execute(
        "SELECT r.score, r.help_kind, a.purpose, r.answered_at FROM response r "
        "JOIN item_version v ON v.id = r.item_version_id JOIN item i ON i.id = v.item_id "
        "LEFT JOIN attempt t ON t.id = r.attempt_id LEFT JOIN assessment a ON a.id = t.assessment_id "
        "JOIN learning_event e ON e.id = r.response_event_id "
        "WHERE i.skill_id = ? AND e.learner_id = ? AND r.score IS NOT NULL AND (? IS NULL OR r.answered_at <= ?) "
        "ORDER BY r.answered_at",
        (skill_id, learner, until, until),
    ).fetchall()
    if not rows:
        return 0.0, 0, None
    latest = clock.parse_timestamp(rows[-1][3])
    num = den = 0.0
    for score, help_kind, purpose, at in rows:
        age = (latest - clock.parse_timestamp(at)).total_seconds() / 86400
        w = (
            PURPOSE_WEIGHT.get(purpose or "practice", 1.0)
            * HELP_WEIGHT[help_kind]
            * 0.5 ** (age / HALF_LIFE_DAYS)
        )
        num += w * score
        den += w
    return round(num / (den + PRIOR), 6), len(rows), rows[-1][3]


def rebuild_skill(
    c: sqlite3.Connection, learner: str, skill_id: str, s: Settings, _seen: set[str] | None = None
) -> None:
    seen = _seen if _seen is not None else set()
    if skill_id in seen:
        return
    seen.add(skill_id)
    m, n, last = mastery(c, learner, skill_id)
    state = skill_state(c, learner, skill_id)
    c.execute("DELETE FROM skill_progress WHERE learner_id = ? AND skill_id = ?", (learner, skill_id))
    c.execute(
        "INSERT INTO skill_progress (learner_id, skill_id, state, mastery, evidence_count, last_activity_at, "
        "algo_version, inputs_hash, rebuilt_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (learner, skill_id, state, m, n, last, ALGO_VERSION, s.snapshot_hash(), clock.now()),
    )
    for (dependent,) in c.execute(
        "SELECT skill_id FROM skill_prerequisite WHERE requires_skill_id = ?", (skill_id,)
    ).fetchall():
        rebuild_skill(c, learner, dependent, s, seen)


# --- XP, streaks, achievements -------------------------------------------------------------------


def review_session_xp(c: sqlite3.Connection, learner: str, attempt_id: str) -> int:
    """First try 10, second try 5, revealed 0 (halved with a hint or the tutor); short sessions earn nothing."""
    outcomes = [item_outcome(c, learner, attempt_id, v) for v in _session_items(c, attempt_id)]
    answered = [o for o in outcomes if o.tries or o.revealed]
    if len(answered) < XP_SESSION_MIN:
        return 0
    total = 0.0
    for o in answered:
        base = {"first": XP_FIRST_TRY, "second": XP_SECOND_TRY}.get(o.kind, 0)
        total += base * (0.5 if o.helped else 1.0)
    return round(total)


def _day_xp(c: sqlite3.Connection, learner: str, day: str) -> tuple[int, int]:
    xp = sessions = bank_sessions = 0
    for ev in _events(c, "learner_id = ? AND learning_day = ?", learner, day):
        p = json.loads(ev["payload"])
        match ev["type"]:
            case "lesson.completed":
                xp += XP_LESSON
                sessions += 1
            case "attempt.finished":
                sessions += 1
                if is_bank(c, p["attempt_id"]):
                    bank_sessions += 1
                    if bank_sessions <= XP_SESSIONS_PER_DAY:
                        xp += review_session_xp(c, learner, p["attempt_id"])
            case "skill.test_result" if p["passed"]:
                xp += XP_TEST
            case "assessment.response_graded" if p["score"] >= 0.8:
                if is_bank(c, p["attempt_id"]):
                    continue  # review sessions earn XP per question outcome when they finish
                row = c.execute(
                    "SELECT help_kind FROM response WHERE response_event_id = ?", (p["response_event_id"],)
                ).fetchone()
                factor = {"none": 1.0, "hint": 0.5, "tutor": 0.5, "solution": 0.0}[row[0] if row else "none"]
                xp += round(XP_CORRECT * factor)
    return xp, sessions


def rebuild_days(c: sqlite3.Connection, learner: str, s: Settings) -> None:
    """All days of the learner: streaks depend on every earlier day, so they are rebuilt together."""
    days = sorted(
        {
            r[0]
            for r in c.execute(
                "SELECT DISTINCT learning_day FROM learning_event WHERE learner_id = ?", (learner,)
            )
        }
    )
    c.execute("DELETE FROM xp_daily WHERE learner_id = ?", (learner,))
    streak, prev = 0, None
    grace_by_week: defaultdict[tuple[int, int], int] = defaultdict(int)
    now = clock.now()
    for d in days:
        xp, sessions = _day_xp(c, learner, d)
        if sessions:
            cur = date.fromisoformat(d)
            if prev is None:
                streak = 1
            else:
                gap = (cur - prev).days - 1
                covered = 0
                for k in range(1, gap + 1):
                    week = (prev + timedelta(days=k)).isocalendar()[:2]
                    if grace_by_week[week] < s.grace_days_per_week:
                        grace_by_week[week] += 1
                        covered += 1
                streak = streak + 1 if covered == gap else 1
            prev = cur
        week = date.fromisoformat(d).isocalendar()[:2]
        c.execute(
            "INSERT INTO xp_daily (learner_id, learning_day, xp, sessions, streak_len, grace_used, algo_version, "
            "inputs_hash, rebuilt_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                learner,
                d,
                xp,
                sessions,
                streak if sessions else 0,
                grace_by_week[week],
                ALGO_VERSION,
                s.snapshot_hash(),
                now,
            ),
        )
    rebuild_achievements(c, learner, s)


ACHIEVEMENTS = ("first_lesson", "first_mastery", "perfect_test", "streak_7", "first_review", "clear_recall")
CLEAR_RECALL_SIZE = 10  # questions in a session with every answer right at the first try


def rebuild_achievements(c: sqlite3.Connection, learner: str, s: Settings) -> None:
    c.execute("DELETE FROM achievement WHERE learner_id = ?", (learner,))
    found: dict[str, str] = {}
    for ev in _events(c, "learner_id = ? AND type IN ('lesson.completed', 'skill.test_result')", learner):
        p = json.loads(ev["payload"])
        if ev["type"] == "lesson.completed":
            found.setdefault("first_lesson", ev["device_at"])
        elif p["passed"]:
            found.setdefault("first_mastery", ev["device_at"])
            if p["score"] >= 0.999:
                found.setdefault("perfect_test", ev["device_at"])
    for ev in _events(c, "learner_id = ? AND type = 'attempt.finished'", learner):
        attempt_id = json.loads(ev["payload"])["attempt_id"]
        if "clear_recall" in found or not is_bank(c, attempt_id):
            continue
        outcomes = [item_outcome(c, learner, attempt_id, v) for v in _session_items(c, attempt_id)]
        answered = [o for o in outcomes if o.tries or o.revealed]
        if answered:
            found.setdefault("first_review", ev["device_at"])
        if len(answered) >= CLEAR_RECALL_SIZE and all(o.kind == "first" for o in answered):
            found.setdefault("clear_recall", ev["device_at"])
    row = c.execute(
        "SELECT learning_day FROM xp_daily WHERE learner_id = ? AND streak_len >= 7 "
        "ORDER BY learning_day LIMIT 1",
        (learner,),
    ).fetchone()
    if row:
        found["streak_7"] = f"{row[0]}T00:00:00.000Z"
    for key, at in found.items():
        c.execute(
            "INSERT INTO achievement (learner_id, key, unlocked_at, algo_version, inputs_hash, rebuilt_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (learner, key, at, ALGO_VERSION, s.snapshot_hash(), clock.now()),
        )


# --- entry points --------------------------------------------------------------------------------


def touched_by(c: sqlite3.Connection, event_ids: list[str]) -> Touched:
    t = Touched()
    if not event_ids:
        return t
    marks = ",".join("?" * len(event_ids))
    for etype, iv, attempt, skill, day, payload in c.execute(
        f"SELECT type, item_version_id, attempt_id, skill_id, learning_day, payload FROM learning_event "
        f"WHERE id IN ({marks})",
        event_ids,
    ):
        t.days.add(day)
        if attempt:
            t.attempts.add(attempt)
        if iv:
            row = c.execute(
                "SELECT i.id, i.skill_id FROM item_version v JOIN item i ON i.id = v.item_id WHERE v.id = ?",
                (iv,),
            ).fetchone()
            t.items.add(row[0])
            t.skills.add(row[1])
        if skill:
            t.skills.add(skill)
        if etype == "lesson.completed":
            lv = json.loads(payload)["lesson_version_id"]
            t.objectives.update(
                r[0]
                for r in c.execute(
                    "SELECT o.objective_id FROM lesson_version_objective o JOIN lesson_version x ON x.id = "
                    "o.lesson_version_id WHERE x.lesson_id = (SELECT lesson_id FROM lesson_version WHERE id = ?)",
                    (lv,),
                )
            )
        if attempt and etype != "attempt.started" and is_bank(c, attempt):
            # a review session: its objectives are rated when it finishes; a late answer changes the rating
            t.objectives.update(
                r[0]
                for r in c.execute(
                    "SELECT DISTINCT objective_id FROM item_version_objective WHERE item_version_id IN "
                    "(SELECT value FROM json_each(?))",
                    (json.dumps(_session_items(c, attempt)),),
                )
            )
        if etype == "lesson.started":
            lv = json.loads(payload)["lesson_version_id"]
            row = c.execute(
                "SELECT l.skill_id FROM lesson_version v JOIN lesson l ON l.id = v.lesson_id WHERE v.id = ?",
                (lv,),
            ).fetchone()
            if row:
                t.skills.add(row[0])
    return t


def apply(c: sqlite3.Connection, learner: str, t: Touched, sched: Scheduler, s: Settings) -> None:
    """Recompute what a batch of new events touched: items first (responses feed attempts and skills)."""
    for item in sorted(t.items):
        rebuild_item(c, learner, item, sched, s)
    for attempt in sorted(t.attempts):
        rebuild_attempt(c, learner, attempt, s)
    for skill in sorted(t.skills):
        rebuild_skill(c, learner, skill, s)
    for objective in sorted(t.objectives):
        rebuild_objective(c, learner, objective, sched, s)
    if t.days:
        rebuild_days(c, learner, s)


def rebuild_learner(c: sqlite3.Connection, learner: str, sched: Scheduler, s: Settings) -> None:
    """Drop and recompute every projection of a learner (after erasure, an algorithm change, or a test)."""
    for table in (
        "review_state",
        "objective_review_state",
        "skill_progress",
        "xp_daily",
        "achievement",
        "attempt",
    ):
        c.execute(f"DELETE FROM {table} WHERE learner_id = ?", (learner,))
    c.execute(
        "DELETE FROM response WHERE response_event_id IN (SELECT id FROM learning_event WHERE learner_id = ?)",
        (learner,),
    )
    items = [
        r[0]
        for r in c.execute(
            "SELECT DISTINCT i.id FROM learning_event e JOIN item_version v ON v.id = e.item_version_id "
            "JOIN item i ON i.id = v.item_id WHERE e.learner_id = ?",
            (learner,),
        )
    ]
    attempts = [
        r[0]
        for r in c.execute(
            "SELECT DISTINCT attempt_id FROM learning_event WHERE learner_id = ? AND attempt_id IS NOT NULL",
            (learner,),
        )
    ]
    skills = [
        r[0]
        for r in c.execute(
            "SELECT s.id FROM skill s JOIN path p ON p.id = s.path_id WHERE p.learner_id = ?", (learner,)
        )
    ]
    objectives = [
        r[0]
        for r in c.execute(
            "SELECT o.id FROM learning_objective o JOIN path p ON p.id = o.path_id WHERE p.learner_id = ?",
            (learner,),
        )
    ]
    apply(c, learner, Touched(set(items), set(skills), {"*"}, set(attempts), set(objectives)), sched, s)


def progress_view(
    c: sqlite3.Connection,
    learner: str,
    path_id: str,
    sched: Scheduler,
    s: Settings,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Per skill: stored progress plus the decay overlay computed at read time."""
    now = now or clock.parse_timestamp(clock.now())
    out: dict[str, dict[str, Any]] = {}
    for (sid,) in c.execute(
        "SELECT id FROM skill WHERE path_id = ? AND archived_at IS NULL", (path_id,)
    ).fetchall():
        row = c.execute(
            "SELECT state, mastery, evidence_count FROM skill_progress WHERE learner_id = ? AND skill_id = ?",
            (learner, sid),
        ).fetchone()
        state, m, n = (row[0], row[1], row[2]) if row else (skill_state(c, learner, sid), 0.0, 0)
        if s.decay and state == "mastered":
            # memory of the skill's objectives (review sessions); skills without any fall back to item cards
            states = [
                json.loads(r[0])
                for r in c.execute(
                    "SELECT rs.state FROM objective_review_state rs JOIN learning_objective o ON o.id = "
                    "rs.objective_id WHERE rs.learner_id = ? AND o.skill_id = ?",
                    (learner, sid),
                )
            ] or [
                json.loads(r[0])
                for r in c.execute(
                    "SELECT rs.state FROM review_state rs JOIN item i ON i.id = rs.item_id WHERE rs.learner_id = ? "
                    "AND i.skill_id = ?",
                    (learner, sid),
                )
            ]
            if states and sum(sched.retrievability(x, now) for x in states) / len(states) < DECAY_BELOW:
                state = "needs_review"
        out[sid] = {"state": state, "mastery": m, "evidence": n}
    return out
