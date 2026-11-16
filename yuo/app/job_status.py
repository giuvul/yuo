"""Generation jobs as the learner sees them: one job, the active ones, the history, a
retry, and the spending ledger. A part of the application service (yuo.app.context)."""

import sqlite3
import statistics
import time
from typing import Any

from yuo.app.context import AppContext, Part
from yuo.app.ports import LessonRequests, VideoRetry
from yuo.core import clock
from yuo.core.errors import InvalidInput, NotFound
from yuo.generation import progress


def _rows(c: sqlite3.Connection, sql: str, *args: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in c.execute(sql, args).fetchall()]


# how long a job of each kind takes when there is no history yet (seconds; claude-cli on a small server)
TYPICAL_JOB_S = {
    "tree": 120,
    "lesson": 240,
    "items": 120,
    "rendition": 900,
    "test_bank": 150,
    "placement": 120,
    "grade": 30,
    "request": 300,
}

# a job's columns for the lists, with the name of what it is for (a lesson before it is written: its skill)
JOB_COLUMNS = (
    "j.id, j.kind, j.status, j.error, j.attempt, j.target_kind, j.target_id, j.next_attempt_at AS retry_at, "
    "CASE j.target_kind "
    "WHEN 'path' THEN (SELECT title FROM path WHERE id = j.target_id) "
    "WHEN 'skill' THEN (SELECT title FROM skill WHERE id = j.target_id) "
    "WHEN 'lesson' THEN (SELECT coalesce(v.title, s.title) FROM lesson l JOIN skill s ON s.id = l.skill_id "
    "LEFT JOIN lesson_version v ON v.id = l.current_version_id WHERE l.id = j.target_id) "
    "WHEN 'rendition' THEN (SELECT coalesce(v.title, s.title) FROM rendition r JOIN lesson l ON l.id = r.lesson_id "
    "JOIN skill s ON s.id = l.skill_id LEFT JOIN lesson_version v ON v.id = l.current_version_id "
    "WHERE r.id = j.target_id) "
    "WHEN 'lesson_request' THEN (SELECT substr(prompt, 1, 80) FROM lesson_request WHERE id = j.target_id) "
    "END AS title, CASE j.target_kind "
    "WHEN 'lesson' THEN j.target_id "
    "WHEN 'rendition' THEN (SELECT lesson_id FROM rendition WHERE id = j.target_id) "
    "END AS lesson_id"
)

# a failed job whose work a later job for the same target did (a video made on a second try): not a problem now
_RESOLVED = (
    "EXISTS (SELECT 1 FROM generation_job o WHERE o.target_id = j.target_id AND o.kind = j.kind "
    "AND o.created_at > j.created_at AND o.status = 'succeeded')"
)


class JobStatus(Part):
    def __init__(self, ctx: AppContext, *, lessons: LessonRequests, videos: VideoRetry) -> None:
        super().__init__(ctx)
        self.lessons = lessons
        self.videos = videos
        self._typical_cache: tuple[float, dict[str, int]] | None = None

    def job(self, job_id: str) -> dict[str, Any]:
        with self.readers.connection() as c:
            row = c.execute(
                "SELECT id, kind, status, attempt, error, target_kind, target_id FROM generation_job "
                "WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise NotFound(job_id)
            stages = _rows(
                c,
                "SELECT s.stage, s.status, s.adapter, s.model_requested, s.cache_hit_of_stage_run_id, "
                "coalesce(sum(b.cost_micros), 0) AS cost_micros, max(b.estimated) AS notional "
                "FROM stage_run s LEFT JOIN budget_entry b ON b.stage_run_id = s.id WHERE s.job_id = ? "
                "GROUP BY s.id ORDER BY s.started_at",
                job_id,
            )
        return dict(row) | {"stages": stages}

    def active_jobs(self) -> list[dict[str, Any]]:
        """The jobs list: what runs, waits or failed in the last day, each with a name a learner knows (the
        lesson or skill), what a running job is doing now, and how long that kind of job usually takes."""
        with self.readers.connection() as c:
            rows = _rows(
                c,
                f"SELECT {JOB_COLUMNS} FROM generation_job j "
                "WHERE j.status IN ('queued','running','waiting_resource') OR (j.status = 'failed' AND "
                f"j.finished_at > ? AND NOT {_RESOLVED}) ORDER BY j.created_at",
                _day_ago(),
            )
            return self._with_progress(c, rows)

    def job_history(self, before: str | None = None, limit: int = 50) -> dict[str, Any]:
        """Finished jobs, newest first (keep the executed ones in a history). `before` is
        the `next` cursor of the previous page."""
        limit = max(1, min(limit, 200))
        where, args = "j.status IN ('succeeded','failed','cancelled')", []
        if before:
            at, _, jid = before.partition("|")
            where += " AND (coalesce(j.finished_at, j.created_at), j.id) < (?, ?)"
            args = [at, jid]
        with self.readers.connection() as c:
            rows = _rows(
                c,
                f"SELECT {JOB_COLUMNS}, j.created_at, j.finished_at, "
                "(SELECT min(started_at) FROM stage_run WHERE job_id = j.id) AS started_at, "
                f"(j.status = 'failed' AND {_RESOLVED}) AS resolved "
                f"FROM generation_job j WHERE {where} "
                "ORDER BY coalesce(j.finished_at, j.created_at) DESC, j.id DESC LIMIT ?",
                *args,
                limit + 1,
            )
        more = len(rows) > limit
        rows = rows[:limit]
        for r in rows:
            r["resolved"] = bool(r["resolved"])
        last = rows[-1] if rows else None
        cursor = f"{last['finished_at'] or last['created_at']}|{last['id']}" if more and last else None
        return {"jobs": rows, "next": cursor}

    def retry_job(self, job_id: str) -> str:
        """Start a failed job's work again from the jobs list: a lesson is written again, a video made again.
        Returns the new job (or the one already at work)."""
        with self.readers.connection() as c:
            row = c.execute(
                "SELECT kind, target_id, status FROM generation_job WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise NotFound(job_id)
            lesson = (
                c.execute("SELECT lesson_id FROM rendition WHERE id = ?", (row[1],)).fetchone()
                if row[0] == "rendition"
                else None
            )
        kind, target, status = row
        if status != "failed":
            raise InvalidInput("only a failed job can be started again")
        if kind == "rendition" and lesson is not None:
            return self.videos.retry_video(lesson[0])
        if kind == "lesson":
            return self.lessons.request_lesson(target)
        raise InvalidInput(f"a {kind} job is started again from its own page")

    def _with_progress(self, c: sqlite3.Connection, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        typical = self._typical_job_seconds(c) if rows else {}
        now = clock.parse_timestamp(clock.now())
        for r in rows:
            p = progress.of(r["id"]) if r["status"] == "running" else None
            r["step"] = p.step if p else None
            r["round"], r["rounds"] = (p.n, p.of) if p else (None, None)
            r["running_s"] = round(time.time() - p.started) if p else None
            r["typical_s"] = typical.get(r["kind"], TYPICAL_JOB_S.get(r["kind"]))
            if r["retry_at"] is not None and clock.parse_timestamp(r["retry_at"]) <= now:
                r["retry_at"] = None  # due: it starts when the worker is free
        return rows

    def _typical_job_seconds(self, c: sqlite3.Connection) -> dict[str, int]:
        """The median length of the last first-try successes of each kind, from their model stages' start to
        the job's end (renders and narration included). Cached for a few minutes."""
        cached = getattr(self, "_typical_cache", None)
        if cached is not None and time.monotonic() - cached[0] < 300:
            return dict(cached[1])
        rows = c.execute(
            "SELECT kind, (julianday(finished_at) - julianday((SELECT min(started_at) FROM stage_run "
            "WHERE job_id = j.id))) * 86400 AS s FROM generation_job j WHERE status = 'succeeded' AND attempt = 1 "
            "AND finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 400"
        ).fetchall()
        by: dict[str, list[float]] = {}
        for kind, secs in rows:
            if secs is not None and secs >= 1 and len(by.setdefault(kind, [])) < 20:  # not cache replays
                by[kind].append(secs)
        out = {k: round(statistics.median(v)) for k, v in by.items() if len(v) >= 3}
        self._typical_cache = (time.monotonic(), out)
        return dict(out)

    def ledger(self) -> dict[str, Any]:
        with self.readers.connection() as c:
            rows = _rows(
                c,
                "SELECT adapter, provider, estimated AS notional, count(*) AS calls, sum(in_tokens) AS "
                "in_tokens, sum(out_tokens) AS out_tokens, sum(reasoning_tokens) AS reasoning_tokens, "
                "sum(cost_micros) AS cost_micros FROM budget_entry GROUP BY adapter, provider, estimated",
            )
        return {
            "rows": rows,
            "billed_usd": sum(r["cost_micros"] for r in rows if not r["notional"]) / 1e6,
            "notional_usd": sum(r["cost_micros"] for r in rows if r["notional"]) / 1e6,
        }


def _day_ago() -> str:
    from datetime import timedelta

    return clock.to_timestamp(clock.parse_timestamp(clock.now()) - timedelta(days=1))
