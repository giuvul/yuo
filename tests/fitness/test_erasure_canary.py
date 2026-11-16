"""Erasure canary: after erasure a planted string is gone from the database file, the WAL,
the FTS index and the asset store, while shared content survives."""

import json
import sqlite3
from pathlib import Path

import pytest

from tests import factory
from yuo.core import clock
from yuo.core.enums import EventType, Stage
from yuo.core.hashing import content_hash
from yuo.core.ids import new_id
from yuo.db import erasure
from yuo.db import rows as r
from yuo.db.blobs import BlobStore
from yuo.db.connection import Writer
from yuo.db.dal import insert

pytestmark = pytest.mark.fitness
CANARY = "zqcanary7f3a9"
SHARED = "sharedjoinsprose"


def _files_containing(root: Path, needle: bytes) -> list[str]:
    return [str(f) for f in root.rglob("*") if f.is_file() and needle in f.read_bytes()]


def _plant(conn: sqlite3.Connection, blobs: BlobStore) -> dict[str, str]:
    w = factory.world(conn)
    now = clock.now()
    ids: dict[str, str] = {"path": w.path, "learner": w.learner}
    # shared content: a generated, published lesson that must survive
    shared = factory.lesson_version(conn, w.lesson, body=[{"type": "paragraph", "bid": "b1", "text": SHARED}])
    conn.execute("UPDATE lesson_version SET status = 'passed' WHERE id = ?", (shared,))
    conn.execute("UPDATE lesson SET current_version_id = ? WHERE id = ?", (shared, w.lesson))
    insert(conn, r.LessonSearchDoc(docid=1, lesson_version_id=shared, title="Joins", body=SHARED))
    shared_asset = blobs.put(b"diagram " + SHARED.encode())
    insert(
        conn,
        r.Asset(
            hash=shared_asset,
            media_type="image/png",
            kind="image",
            bytes=10,
            stored_at="local",
            retention_class="keep",
            evicted_at=None,
            data_class="C",
            created_at=now,
        ),
    )
    insert(
        conn, r.AssetRef(asset_hash=shared_asset, owner_kind="lesson_version", owner_id=shared, role="image")
    )
    ids["shared_version"], ids["shared_asset"] = shared, shared_asset

    # a learner-written lesson, current and searchable
    own = new_id()
    insert(
        conn,
        r.Lesson(
            id=own,
            skill_id=w.skill,
            path_id=w.path,
            code="sql.joins.mine",
            kind="requested",
            position=1,
            state="ready",
            current_version_id=None,
            extensions={},
        ),
    )
    mine = factory.lesson_version(
        conn,
        own,
        body=[{"type": "paragraph", "bid": "b1", "text": CANARY}],
        author_kind="learner",
        authorship="human",
    )
    conn.execute("UPDATE lesson_version SET status = 'passed' WHERE id = ?", (mine,))
    conn.execute("UPDATE lesson SET current_version_id = ? WHERE id = ?", (mine, own))
    insert(conn, r.LessonSearchDoc(docid=2, lesson_version_id=mine, title="Mine", body=f"notes {CANARY}"))
    ids["own_lesson"] = own

    # a learner flashcard and an answer event that quotes the canary
    card = factory.item_version(conn, w.item, payload={"prompt": CANARY}, author_kind="learner")
    payload = {"attempt_id": None, "item_version_id": card, "answer": CANARY, "ms_to_answer": 900}
    insert(
        conn,
        r.LearningEvent(
            id=new_id(),
            payload_hash=content_hash(payload),
            learner_id=w.learner,
            type=EventType.RESPONSE_GIVEN,
            type_version=1,
            device_id=w.device,
            device_at=now,
            server_at=now,
            tz="Europe/Rome",
            learning_day=now[:10],
            payload=payload,
            item_version_id=card,
            lesson_version_id=None,
            rendition_version_id=None,
            attempt_id=None,
            skill_id=None,
        ),
    )

    # tutor conversation on the path, its model call and the call's raw output
    conv, msg, job, run = new_id(), new_id(), new_id(), new_id()
    insert(
        conn,
        r.Conversation(
            id=conv,
            learner_id=w.learner,
            scope="path",
            scope_ref=w.path,
            title=None,
            created_at=now,
            archived_at=None,
        ),
    )
    insert(
        conn,
        r.GenerationJob(
            id=job,
            kind="lesson",
            target_kind="path",
            target_id=w.path,
            priority=0,
            status="succeeded",
            attempt=1,
            next_attempt_at=None,
            requested_by="learner",
            created_at=now,
            finished_at=now,
            error=None,
        ),
    )
    out_hash = content_hash({"raw": CANARY})
    insert(
        conn,
        r.StageRun(
            id=run,
            job_id=job,
            stage=Stage.LESSON_BODY,
            input_manifest={"q": CANARY},
            input_hash=content_hash({"q": CANARY}),
            output_hash=out_hash,
            status="succeeded",
            resource=None,
            adapter="openrouter",
            adapter_version="1",
            model_requested="m",
            model_resolved="m",
            provider=None,
            reasoning_effort=None,
            role="tutor",
            cache_hit_of_stage_run_id=None,
            data_class="F",
            started_at=now,
            finished_at=now,
            error=None,
        ),
    )
    insert(
        conn,
        r.StageOutput(
            hash=out_hash,
            schema_id="tutor_reply",
            schema_version=1,
            raw={"raw": CANARY},
            parsed=None,
            data_class="F",
            created_at=now,
        ),
    )
    insert(
        conn,
        r.Message(
            id=msg,
            conversation_id=conv,
            role="learner",
            status="done",
            content={"text": CANARY},
            context={},
            policy="free",
            stage_run_id=run,
            leak_check=None,
            guard=None,
            created_at=now,
            completed_at=now,
        ),
    )
    insert(
        conn,
        r.BudgetEntry(
            id=new_id(),
            stage_run_id=run,
            message_id=msg,
            adapter="openrouter",
            provider=None,
            in_tokens=10,
            out_tokens=20,
            reasoning_tokens=0,
            cost_micros=40,
            cost_currency="USD",
            price_ref=None,
            estimated=False,
            at=now,
        ),
    )

    # a note, a lesson request with an uploaded file
    insert(
        conn,
        r.Note(
            id=new_id(),
            learner_id=w.learner,
            rendition_version_id=None,
            t_s=None,
            anchor={"lesson_version_id": shared, "bid": "b1"},
            text=CANARY,
            sent_message_id=msg,
            created_at=now,
            updated_at=now,
        ),
    )
    req = new_id()
    insert(
        conn,
        r.LessonRequest(
            id=req,
            learner_id=w.learner,
            path_id=w.path,
            skill_id=w.skill,
            prompt=CANARY,
            links=[],
            status="done",
            lesson_id=own,
            error=None,
            created_at=now,
            updated_at=now,
        ),
    )
    upload = blobs.put(f"my upload {CANARY}".encode())
    insert(
        conn,
        r.Asset(
            hash=upload,
            media_type="text/plain",
            kind="document",
            bytes=20,
            stored_at="local",
            retention_class="keep",
            evicted_at=None,
            data_class="F",
            created_at=now,
        ),
    )
    insert(conn, r.AssetRef(asset_hash=upload, owner_kind="lesson_request", owner_id=req, role="attachment"))
    return ids


def test_path_personal_erasure_leaves_no_canary(db_path: Path, writer: Writer, blobs: BlobStore) -> None:
    ids = writer.run(lambda c: _plant(c, blobs))
    writer.maintenance("PRAGMA wal_checkpoint(PASSIVE)")
    assert _files_containing(db_path.parent, CANARY.encode()), "the canary was not planted"

    counts = erasure.erase(writer, blobs, erasure.path_personal(ids["path"]))

    assert _files_containing(db_path.parent, CANARY.encode()) == []
    assert counts["learning_event"] == 1 and counts["message"] == 1 and counts["asset_bytes"] == 1

    c = sqlite3.connect(db_path)
    try:
        assert (
            c.execute("SELECT count(*) FROM lesson_fts WHERE lesson_fts MATCH ?", (CANARY,)).fetchone()[0]
            == 0
        )
        assert (
            c.execute("SELECT count(*) FROM lesson_fts WHERE lesson_fts MATCH ?", (SHARED,)).fetchone()[0]
            == 1
        )
        # shared content and its asset survive; the head of the erased lesson is left without a version
        assert c.execute(
            "SELECT current_version_id FROM lesson WHERE id = ?", (ids["own_lesson"],)
        ).fetchone() == (None,)
        assert (
            c.execute(
                "SELECT count(*) FROM lesson_version WHERE id = ?", (ids["shared_version"],)
            ).fetchone()[0]
            == 1
        )
        assert blobs.path(ids["shared_asset"]).exists()
        # operational rows keep their numbers, lose the link to personal rows
        assert c.execute("SELECT message_id, stage_run_id, cost_micros FROM budget_entry").fetchone() == (
            None,
            None,
            40,
        )
        kind, recorded = c.execute("SELECT kind, counts FROM erasure_record").fetchone()
        assert kind == "path_personal" and CANARY not in recorded and json.loads(recorded)["note"] == 1
        assert c.execute("SELECT count(*) FROM erasure_guard").fetchone()[0] == 0
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        c.close()


def test_conversation_erasure_keeps_the_rest(db_path: Path, writer: Writer, blobs: BlobStore) -> None:
    writer.run(lambda c: _plant(c, blobs))
    conv = writer.run(lambda c: c.execute("SELECT id FROM conversation").fetchone()[0])
    counts = erasure.erase(writer, blobs, erasure.conversation(conv))
    assert counts["conversation"] == 1 and counts["message"] == 1 and counts["stage_run"] == 1
    left = writer.run(
        lambda c: (
            c.execute("SELECT count(*) FROM note WHERE sent_message_id IS NULL").fetchone()[0],
            c.execute("SELECT count(*) FROM learning_event").fetchone()[0],
        )
    )
    assert left == (1, 1)
