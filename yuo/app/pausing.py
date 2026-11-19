"""Pausing background generation for a while (yuo.generation.pause). A part of the application service.

The pause is the installation setting `generation.pause`; the job worker reads it before it starts a job and
the stage runner before each model call. The view says what waits and what is still finishing: a call already
running always finishes (a video's scene call takes minutes), and its result is kept for the resume.
"""

import sqlite3
import time
from typing import Any

from yuo.app.context import Part
from yuo.core import clock
from yuo.core.errors import InvalidInput
from yuo.generation import pause, progress
from yuo.setup import settings

KEY = "generation.pause"


class Pausing(Part):
    def generation_pause(self) -> dict[str, Any]:
        now = clock.now()
        with self.readers.connection() as c:
            state = settings.effective(c, KEY, {})[0]
            kinds = pause.kinds(state, now)
            if not kinds:
                return {"paused": False, "scope": None, "until": None, "waiting": 0, "finishing": []}
            marks = ", ".join(f"'{k}'" for k in sorted(kinds))  # our own constants
            waiting = c.execute(
                f"SELECT count(*) FROM generation_job WHERE status IN ('queued', 'waiting_resource') AND kind IN ({marks})"
            ).fetchone()[0]
            running = c.execute(
                f"SELECT id, kind FROM generation_job WHERE status = 'running' AND kind IN ({marks}) ORDER BY created_at"
            ).fetchall()
            finishing = [self._finishing(c, r["id"], r["kind"]) for r in running]
        return {
            "paused": True,
            "scope": state["scope"],
            "until": state.get("until"),
            "waiting": int(waiting),
            "finishing": finishing,
        }

    def set_generation_pause(self, scope: str | None, until: str | None) -> dict[str, Any]:
        """Pause (`scope` "all" or "videos", until a time or until resumed) or resume (`scope` None)."""
        if scope is None:
            value = None
        else:
            if scope not in ("all", "videos"):
                raise InvalidInput("scope must be all or videos")
            if until is not None:
                until = clock.to_timestamp(clock.parse_timestamp(until))
                if until <= clock.now():
                    raise InvalidInput("the pause must end in the future")
            value = {"scope": scope, "until": until}
        self.writer.run(lambda c: settings.put(c, KEY, value, "installation"))
        if self.worker:
            self.worker.wake()  # a resume starts the waiting jobs at once
        return self.generation_pause()

    def _finishing(self, c: sqlite3.Connection, job_id: str, kind: str) -> dict[str, Any]:
        """A job of a paused kind still working: the step it is in, for how long, and how long that step usually
        takes (it stops once the step ends)."""
        p = progress.of(job_id)
        step = p.step if p else None
        step_s = round(time.time() - p.step_at) if p and p.step_at else None
        typical = None
        if step:
            row = c.execute(
                "SELECT avg((julianday(finished_at) - julianday(started_at)) * 86400) FROM ("
                "SELECT started_at, finished_at FROM stage_run WHERE stage = ? AND status = 'succeeded' "
                "AND cache_hit_of_stage_run_id IS NULL AND started_at IS NOT NULL AND finished_at IS NOT NULL "
                "ORDER BY finished_at DESC LIMIT 20)",
                (step,),
            ).fetchone()
            typical = round(row[0]) if row and row[0] is not None else None
        return {"job_id": job_id, "kind": kind, "step": step, "step_s": step_s, "typical_s": typical}
