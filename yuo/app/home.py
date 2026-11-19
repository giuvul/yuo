"""Home: what the learner sees first. In a few seconds: how they are doing, what waits for them today, and the
one best thing to do next, across all their paths. A part of the application service (yuo.app.context).

Everything here is read from what Yuo already keeps (the event log and its projections, the paths, their jobs
and files); nothing is generated. Texts are the web client's: this sends what and how much, never sentences.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from yuo.app.context import AppContext, Part
from yuo.app.ports import Learners, ReviewHubs
from yuo.core import clock
from yuo.learning import projections as pj
from yuo.learning.events import learning_day
from yuo.setup import settings

FADING_BELOW = 0.8  # a learned skill's memory below this is worth a look (as on the review page)
FADING_NAMES = 3
EXAM_SOON_DAYS = 21  # an exam this close puts "take a mock exam" on the list
TODAY_MAX = 6
QUIET_DAYS = 3  # no activity for this long: not on track
INSIGHT_MIN_ANSWERS = 12  # answers per part of the day before comparing them
INSIGHT_GAP = 0.1  # how much better one part of the day must be to say so
WEAK_BELOW = 0.6
WEAK_EVIDENCE = 4
OPEN = ("draft", "active")


def _rows(c: sqlite3.Connection, sql: str, *args: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in c.execute(sql, args).fetchall()]


class Home(Part):
    def __init__(self, ctx: AppContext, *, learners: Learners, reviews: ReviewHubs) -> None:
        super().__init__(ctx)
        self.learners = learners
        self.reviews = reviews

    def home(self) -> dict[str, Any]:
        learner = self.learners.ensure_learner()
        now = clock.parse_timestamp(clock.now())
        with self.readers.connection() as c:
            me = c.execute("SELECT tz, day_boundary FROM learner WHERE id = ?", (learner,)).fetchone()
            tz, boundary = me["tz"] or "UTC", me["day_boundary"] or "04:00"
            today = learning_day(now, tz, boundary)
            paths = _rows(
                c,
                "SELECT id, title, status, extensions FROM path WHERE learner_id = ? AND status IN ('draft', 'active') "
                "ORDER BY updated_at DESC",
                learner,
            )
            active = [p["id"] for p in paths if p["status"] == "active"]
            nxt = self._continue(c, learner, paths)
            out: dict[str, Any] = {
                "next_step": nxt,
                "lessons_ready": self._new_lessons(c, learner, active),
                "exam": self._next_exam(c, [p["id"] for p in paths], today),
                "today": self._today(c, paths, today),
                "progress": self._progress(c, learner, active, now),
                "momentum": self._momentum(c, learner, today),
                "insight": self._insight(c, learner, active, nxt, now),
            }
        fading = self._fading(active)
        out["today"] = sorted(fading + out["today"], key=lambda i: PRIORITY[i["kind"]])[:TODAY_MAX]
        return out

    # --- the one next step -------------------------------------------------------------------------

    def _continue(
        self, c: sqlite3.Connection, learner: str, paths: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """The next lesson of the path last studied (then the others): the first, in the path's order, that the
        learner has not finished; ready to read, being written, or still to write."""
        recent = c.execute(
            "SELECT coalesce(l.path_id, s.path_id) FROM learning_event e "
            "LEFT JOIN lesson_version v ON v.id = e.lesson_version_id LEFT JOIN lesson l ON l.id = v.lesson_id "
            "LEFT JOIN skill s ON s.id = e.skill_id WHERE e.learner_id = ? AND coalesce(l.path_id, s.path_id) IS NOT "
            "NULL ORDER BY e.server_seq DESC LIMIT 1",
            (learner,),
        ).fetchone()
        order = sorted(
            (p for p in paths if p["status"] == "active"),
            key=lambda p: recent is None or p["id"] != recent[0],
        )
        for p in order:
            lessons = _rows(
                c,
                "SELECT l.id, l.state, l.skill_id, b.id AS branch_id, b.title AS place, v.est_minutes AS minutes, "
                "coalesce(v.title, l.extensions ->> '$.yuo.planned_title', s.title) AS title FROM lesson l "
                "JOIN skill s ON s.id = l.skill_id JOIN branch b ON b.id = s.branch_id "
                "LEFT JOIN lesson_version v ON v.id = l.current_version_id "
                "WHERE l.path_id = ? AND s.archived_at IS NULL AND b.archived_at IS NULL "
                "ORDER BY b.position, s.position, l.position",
                p["id"],
            )
            done = _lessons_with(c, learner, p["id"], "lesson.completed")
            started = _lessons_with(c, learner, p["id"], "lesson.started")
            for lesson in lessons:
                if lesson["id"] in done or lesson["state"] == "failed":
                    continue
                branch = [x["id"] for x in lessons if x["branch_id"] == lesson["branch_id"]]
                kind = {"ready": "lesson", "planned": "planned"}.get(lesson["state"], "writing")
                return {
                    "kind": kind,
                    "path_id": p["id"],
                    "path_title": p["title"],
                    "lesson_id": lesson["id"],
                    "skill_id": lesson["skill_id"],
                    "title": lesson["title"],
                    "place": lesson["place"],
                    "index": branch.index(lesson["id"]) + 1,
                    "count": len(branch),
                    "minutes": lesson["minutes"],
                    "started": lesson["id"] in started,
                }
        return None

    def _new_lessons(self, c: sqlite3.Connection, learner: str, paths: list[str]) -> int:
        """Lessons ready that the learner has not opened yet."""
        n = 0
        for pid in paths:
            opened = _lessons_with(c, learner, pid, "lesson.started")
            ready = [
                r[0] for r in c.execute("SELECT id FROM lesson WHERE path_id = ? AND state = 'ready'", (pid,))
            ]
            n += sum(1 for lid in ready if lid not in opened)
        return n

    def _next_exam(self, c: sqlite3.Connection, paths: list[str], today: str) -> dict[str, Any] | None:
        if not paths:
            return None
        marks = ",".join("?" * len(paths))
        row = c.execute(
            f"SELECT id, path_id, title, exam_date, branch_id FROM course WHERE path_id IN ({marks}) AND archived_at IS "
            "NULL AND exam_date >= ? ORDER BY exam_date LIMIT 1",
            (*paths, today),
        ).fetchone()
        if row is None:
            return None
        days = (datetime.fromisoformat(row["exam_date"][:10]) - datetime.fromisoformat(today)).days
        return {
            "course_id": row["id"],
            "path_id": row["path_id"],
            "title": row["title"],
            "days": days,
            "built": row["branch_id"] is not None,
        }

    # --- what waits today --------------------------------------------------------------------------

    def _today(self, c: sqlite3.Connection, paths: list[dict[str, Any]], today: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for p in paths:
            pid = p["id"]
            for lesson in _rows(
                c,
                "SELECT l.id, coalesce(l.extensions ->> '$.yuo.planned_title', s.title) AS title, EXISTS (SELECT 1 "
                "FROM lesson_version v WHERE v.lesson_id = l.id AND v.status = 'rejected') AS draft FROM lesson l "
                "JOIN skill s ON s.id = l.skill_id WHERE l.path_id = ? AND l.state = 'failed' ORDER BY l.position",
                pid,
            ):
                items.append(
                    {
                        "kind": "lesson_draft" if lesson["draft"] else "lesson_failed",
                        "path_id": pid,
                        "lesson_id": lesson["id"],
                        "title": lesson["title"],
                    }
                )
            yuo = (json.loads(p["extensions"] or "{}").get("yuo")) or {}
            if yuo.get("origin") != "courses":
                continue
            arrange = yuo.get("arrange") or {}
            if arrange.get("status") == "ready":
                courses = len((arrange.get("proposal") or {}).get("courses", []))
                items.append({"kind": "arrange_ready", "path_id": pid, "title": p["title"], "count": courses})
            preview = (yuo.get("preview") or {}).get("status")
            if preview not in (None, "collecting", "built"):
                plans = [
                    json.loads(r[0] or "{}").get("status")
                    for r in c.execute(
                        "SELECT outline FROM course WHERE path_id = ? AND archived_at IS NULL AND branch_id IS NULL",
                        (pid,),
                    )
                ]
                if plans and all(s == "ready" for s in plans):
                    items.append({"kind": "plan_ready", "path_id": pid, "title": p["title"]})
            for m in _rows(
                c,
                "SELECT title, progress FROM material WHERE path_id = ? AND state = 'transcribing' ORDER BY position",
                pid,
            ):
                items.append(
                    {
                        "kind": "transcribing",
                        "path_id": pid,
                        "title": m["title"],
                        "percent": round(m["progress"] * 100),
                    }
                )
            soon = (datetime.fromisoformat(today) + timedelta(days=EXAM_SOON_DAYS)).date().isoformat()
            for k in _rows(
                c,
                "SELECT id, title, exam_date FROM course WHERE path_id = ? AND archived_at IS NULL AND branch_id IS NOT "
                "NULL AND exam_date BETWEEN ? AND ? ORDER BY exam_date",
                pid,
                today,
                soon,
            ):
                days = (datetime.fromisoformat(k["exam_date"][:10]) - datetime.fromisoformat(today)).days
                items.append(
                    {
                        "kind": "exam_soon",
                        "path_id": pid,
                        "course_id": k["id"],
                        "title": k["title"],
                        "days": days,
                    }
                )
        return items

    def _fading(self, paths: list[str]) -> list[dict[str, Any]]:
        """Skills learned whose memory is fading, per path, from its review hub."""
        items = []
        for pid in paths:
            hub = self.reviews.review_hub(pid)
            low = sorted(
                (s for s in hub.get("skills", []) if s["retrievability"] < FADING_BELOW),
                key=lambda s: s["retrievability"],
            )
            if low:
                items.append(
                    {
                        "kind": "fading",
                        "path_id": pid,
                        "skills": [s["title"] for s in low[:FADING_NAMES]],
                        "count": len(low),
                    }
                )
        return items

    # --- how it goes -------------------------------------------------------------------------------

    def _progress(
        self, c: sqlite3.Connection, learner: str, paths: list[str], now: datetime
    ) -> dict[str, Any] | None:
        """Mastery across the active paths, 0 to 100 (each skill's mastery from the learner's answers, averaged),
        and how it moved in the last seven days (the same measure over the answers given until then)."""
        if not paths:
            return None
        marks = ",".join("?" * len(paths))
        skills = [
            r[0]
            for r in c.execute(
                f"SELECT s.id FROM skill s JOIN branch b ON b.id = s.branch_id WHERE s.path_id IN ({marks}) AND "
                "s.archived_at IS NULL AND b.archived_at IS NULL",
                paths,
            )
        ]
        if not skills:
            return None
        week_ago = clock.to_timestamp(now - timedelta(days=7))
        score = sum(pj.mastery(c, learner, s)[0] for s in skills) / len(skills)
        before = sum(pj.mastery(c, learner, s, until=week_ago)[0] for s in skills) / len(skills)
        mastered = c.execute(
            f"SELECT count(*) FROM skill_progress WHERE learner_id = ? AND state = 'mastered' AND skill_id IN "
            f"({','.join('?' * len(skills))})",
            (learner, *skills),
        ).fetchone()[0]
        last = c.execute(
            "SELECT max(answered_at) FROM response r JOIN learning_event e ON e.id = r.response_event_id "
            "WHERE e.learner_id = ?",
            (learner,),
        ).fetchone()[0]
        delta = round(score * 100) - round(before * 100)
        if last is None:
            status = "starting"
        elif delta < 0 or now - clock.parse_timestamp(last) > timedelta(days=QUIET_DAYS):
            status = "slipping"
        else:
            status = "on_track"
        return {
            "score": round(score * 100),
            "delta": delta,
            "status": status,
            "mastered": mastered,
            "skills": len(skills),
        }

    def _momentum(self, c: sqlite3.Connection, learner: str, today: str) -> dict[str, Any] | None:
        """Streak, this week's XP and the latest achievement: only where the learner wants them (gamification)."""
        if settings.effective(c, "gamification", {"learner": learner})[0] != "full":
            return None
        days = _rows(
            c,
            "SELECT learning_day, xp, streak_len FROM xp_daily WHERE learner_id = ? ORDER BY learning_day DESC LIMIT 8",
            learner,
        )
        start = (datetime.fromisoformat(today) - timedelta(days=6)).date().isoformat()
        yesterday = (datetime.fromisoformat(today) - timedelta(days=1)).date().isoformat()
        streak = days[0]["streak_len"] if days and days[0]["learning_day"] >= yesterday else 0
        latest = c.execute(
            "SELECT key, unlocked_at FROM achievement WHERE learner_id = ? ORDER BY unlocked_at DESC LIMIT 1",
            (learner,),
        ).fetchone()
        return {
            "streak": streak,
            "xp_week": sum(d["xp"] for d in days if d["learning_day"] >= start),
            "achievement": dict(latest) if latest else None,
        }

    def _insight(
        self,
        c: sqlite3.Connection,
        learner: str,
        paths: list[str],
        nxt: dict[str, Any] | None,
        now: datetime,
    ) -> dict[str, Any] | None:
        """One specific observation from the learner's own answers, the most useful that holds."""
        if nxt is not None:  # the next lesson builds on a skill that is not mastered yet
            gap = c.execute(
                "SELECT s.title FROM skill_prerequisite p JOIN skill s ON s.id = p.requires_skill_id "
                "LEFT JOIN skill_progress g ON g.skill_id = s.id AND g.learner_id = ? WHERE p.skill_id = ? AND "
                "coalesce(g.state, '') != 'mastered' ORDER BY s.position LIMIT 1",
                (learner, nxt["skill_id"]),
            ).fetchone()
            if gap is not None:
                skill = c.execute("SELECT title FROM skill WHERE id = ?", (nxt["skill_id"],)).fetchone()[0]
                return {"kind": "builds_on", "skill": skill, "requires": gap[0], "path_id": nxt["path_id"]}
        since = clock.to_timestamp(now - timedelta(days=60))
        parts: dict[str, list[float]] = {}
        for score, at, tz in c.execute(
            "SELECT r.score, r.answered_at, e.tz FROM response r JOIN learning_event e ON e.id = r.response_event_id "
            "WHERE e.learner_id = ? AND r.score IS NOT NULL AND r.answered_at >= ?",
            (learner, since),
        ):
            hour = clock.parse_timestamp(at).astimezone(ZoneInfo(tz or "UTC")).hour
            part = (
                "morning"
                if 5 <= hour < 12
                else "afternoon"
                if hour < 18
                else "evening"
                if hour < 23
                else "night"
            )
            parts.setdefault("night" if hour < 5 else part, []).append(score)
        means = {k: sum(v) / len(v) for k, v in parts.items() if len(v) >= INSIGHT_MIN_ANSWERS}
        if len(means) >= 2:
            best = max(means, key=lambda k: means[k])
            if means[best] - min(means.values()) >= INSIGHT_GAP:
                return {"kind": "time_of_day", "part": best, "percent": round(means[best] * 100)}
        if paths:
            marks = ",".join("?" * len(paths))
            weak = c.execute(
                f"SELECT s.title, g.mastery, s.path_id FROM skill_progress g JOIN skill s ON s.id = g.skill_id "
                f"WHERE g.learner_id = ? AND s.path_id IN ({marks}) AND s.archived_at IS NULL AND "
                "g.evidence_count >= ? AND g.mastery < ? ORDER BY g.mastery LIMIT 1",
                (learner, *paths, WEAK_EVIDENCE, WEAK_BELOW),
            ).fetchone()
            if weak is not None:
                return {
                    "kind": "weakest",
                    "skill": weak[0],
                    "percent": round(weak[1] * 100),
                    "path_id": weak[2],
                }
        return None


# the order of the list: what blocks the learner first, then what fades, then what can wait
PRIORITY = {
    "lesson_draft": 0,
    "lesson_failed": 1,
    "fading": 2,
    "exam_soon": 3,
    "arrange_ready": 4,
    "plan_ready": 5,
    "transcribing": 6,
}


def _lessons_with(c: sqlite3.Connection, learner: str, path_id: str, event: str) -> set[str]:
    return {
        r[0]
        for r in c.execute(
            "SELECT DISTINCT v.lesson_id FROM learning_event e JOIN lesson_version v ON v.id = e.lesson_version_id "
            "JOIN lesson l ON l.id = v.lesson_id WHERE e.learner_id = ? AND e.type = ? AND l.path_id = ?",
            (learner, event, path_id),
        )
    }
