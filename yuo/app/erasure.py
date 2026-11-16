"""Selective erasure for the learner: a conversation, the video watch history, one path's personal data.

The deletion itself is `yuo.db.erasure` (the only routine allowed past the append-only and version guards).
This module adds what the learner's view needs around it: refusing while a model is still writing into the
path, putting the path's heads back to "planned" where their version went, dropping the level check
answers kept in the path row, and rebuilding the learner's projections from what is left.

Notes are not erased here: they are plain rows deleted directly (`secure_delete` zeroes the bytes).
"""

import sqlite3
from collections.abc import Callable

from yuo.app.repo import drop_path_state
from yuo.core.errors import Conflict, NotFound
from yuo.db import erasure as engine
from yuo.db.blobs import BlobStore
from yuo.db.connection import ReadPool, Writer
from yuo.learning import projections as pj
from yuo.setup import settings

# jobs whose output lands in the path: while one runs, erasing would race it
_PATH_TARGETS = (
    "SELECT :p UNION SELECT id FROM skill WHERE path_id = :p UNION SELECT id FROM lesson WHERE path_id = :p "
    "UNION SELECT id FROM item WHERE path_id = :p UNION SELECT r.id FROM rendition r "
    "JOIN lesson l ON l.id = r.lesson_id WHERE l.path_id = :p"
)


class Erasure:
    def __init__(
        self,
        writer: Writer,
        readers: ReadPool,
        blobs: BlobStore | None,
        scheduler: pj.Scheduler,
        learner: Callable[[], str],
    ) -> None:
        self.writer = writer
        self.readers = readers
        self.blobs = blobs
        self.scheduler = scheduler
        self.learner = learner

    def conversation(self, conversation_id: str) -> dict[str, int]:
        with self.readers.connection() as c:
            if c.execute("SELECT 1 FROM conversation WHERE id = ?", (conversation_id,)).fetchone() is None:
                raise NotFound(conversation_id)
            if c.execute(
                "SELECT 1 FROM message WHERE conversation_id = ? AND status IN ('queued','streaming')",
                (conversation_id,),
            ).fetchone():
                raise Conflict("the tutor is still answering in this conversation: stop it first")
        return self._erase(engine.conversation(conversation_id))

    def video_history(self) -> dict[str, int]:
        return self._erase(engine.video_history(self.learner()))

    def path_personal(self, path_id: str) -> dict[str, int]:
        with self.readers.connection() as c:
            if c.execute("SELECT 1 FROM path WHERE id = ?", (path_id,)).fetchone() is None:
                raise NotFound(path_id)
            if c.execute(
                f"SELECT 1 FROM generation_job WHERE status = 'running' AND target_id IN ({_PATH_TARGETS})",
                {"p": path_id},
            ).fetchone():
                raise Conflict(
                    "something is being written for this path right now: try again when it has finished"
                )

        def before(c: sqlite3.Connection) -> None:
            # queued work would only write personal content again
            c.execute(
                f"UPDATE generation_job SET status = 'cancelled' WHERE status IN ('queued','waiting_resource') "
                f"AND target_id IN ({_PATH_TARGETS})",
                {"p": path_id},
            )

        self.writer.run(before)
        counts = self._erase(engine.path_personal(path_id))

        def after(c: sqlite3.Connection) -> None:
            for head in ("lesson", "item"):
                c.execute(
                    f"UPDATE {head} SET state = 'planned' WHERE path_id = ? AND current_version_id IS NULL",
                    (path_id,),
                )
            c.execute(
                "UPDATE rendition SET state = 'planned' WHERE current_version_id IS NULL "
                "AND lesson_id IN (SELECT id FROM lesson WHERE path_id = ?)",
                (path_id,),
            )
            drop_path_state(c, path_id, "level_check")

        self.writer.run(after)
        return counts

    def _erase(self, plan: engine.Plan) -> dict[str, int]:
        counts = engine.erase(self.writer, self.blobs, plan)
        learner = self.learner()

        def rebuild(c: sqlite3.Connection) -> None:
            pj.rebuild_learner(c, learner, self.scheduler, projection_settings(c, learner))

        self.writer.run(rebuild)
        return counts


def projection_settings(c: sqlite3.Connection, learner: str) -> pj.Settings:
    scope: dict[settings.Level, str | None] = {"learner": learner}
    return pj.Settings(
        grace_days_per_week=int(settings.effective(c, "streak.grace_days", scope)[0]),
        decay=bool(settings.effective(c, "mastery.decay", scope)[0]),
        retention=float(settings.effective(c, "review.desired_retention", scope)[0]),
        max_interval_days=int(settings.effective(c, "review.max_interval_days", scope)[0]),
    )
