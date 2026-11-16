"""Row-local invariants enforced by triggers and constraints."""

import sqlite3

import pytest

from tests import factory
from yuo.core import clock
from yuo.core.enums import EventType, GateStatus
from yuo.core.hashing import content_hash
from yuo.core.ids import new_id
from yuo.db import rows as r
from yuo.db.dal import insert, load


def test_version_content_is_immutable(conn: sqlite3.Connection) -> None:
    w = factory.world(conn)
    v = factory.lesson_version(conn, w.lesson)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE lesson_version SET title = 'changed' WHERE id = ?", (v,))


def test_gate_status_is_set_once(conn: sqlite3.Connection) -> None:
    w = factory.world(conn)
    v = factory.lesson_version(conn, w.lesson)
    conn.execute(
        "UPDATE lesson_version SET status = 'passed', published_at = ? WHERE id = ?", (clock.now(), v)
    )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE lesson_version SET status = 'rejected' WHERE id = ?", (v,))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE lesson_version SET published_at = '2030-01-01T00:00:00.000Z' WHERE id = ?", (v,))


def test_current_version_must_be_passed_and_of_the_same_head(conn: sqlite3.Connection) -> None:
    w = factory.world(conn)
    v = factory.lesson_version(conn, w.lesson)
    with pytest.raises(sqlite3.IntegrityError, match="passed version"):
        conn.execute("UPDATE lesson SET current_version_id = ? WHERE id = ?", (v, w.lesson))
    conn.execute("UPDATE lesson_version SET status = 'passed' WHERE id = ?", (v,))
    conn.execute("UPDATE lesson SET current_version_id = ? WHERE id = ?", (v, w.lesson))

    other = new_id()
    insert(
        conn,
        r.Lesson(
            id=other,
            skill_id=w.skill,
            path_id=w.path,
            code="sql.joins.l2",
            kind="core",
            position=1,
            state="planned",
            current_version_id=None,
            extensions={},
        ),
    )
    conn.execute("BEGIN")
    conn.execute("UPDATE lesson SET current_version_id = ? WHERE id = ?", (v, other))
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.execute("COMMIT")
    conn.execute("ROLLBACK")


def test_version_lang_must_match_the_path(conn: sqlite3.Connection) -> None:
    w = factory.world(conn)
    with pytest.raises(sqlite3.IntegrityError, match="content_lang"):
        factory.lesson_version(conn, w.lesson, lang="de")


def test_version_rows_are_not_deleted_outside_erasure(conn: sqlite3.Connection) -> None:
    w = factory.world(conn)
    v = factory.lesson_version(conn, w.lesson)
    with pytest.raises(sqlite3.IntegrityError, match="only by erasure"):
        conn.execute("DELETE FROM lesson_version WHERE id = ?", (v,))


def _event(w: factory.World, **refs: str) -> r.LearningEvent:
    payload = {"seconds": 30, **refs}
    now = clock.now()
    return r.LearningEvent(
        id=new_id(),
        payload_hash=content_hash(payload),
        learner_id=w.learner,
        type=EventType.LESSON_STARTED,
        type_version=1,
        device_id=w.device,
        device_at=now,
        server_at=now,
        tz="Europe/Rome",
        learning_day=now[:10],
        payload=payload,
        item_version_id=None,
        lesson_version_id=refs.get("lesson_version_id"),
        rendition_version_id=None,
        attempt_id=None,
        skill_id=None,
    )


def test_event_log_is_append_only(conn: sqlite3.Connection) -> None:
    w = factory.world(conn)
    insert(conn, _event(w))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE learning_event SET tz = 'UTC'")
    with pytest.raises(sqlite3.IntegrityError, match="only by erasure"):
        conn.execute("DELETE FROM learning_event")


def test_event_refs_must_agree_with_the_payload(conn: sqlite3.Connection) -> None:
    w = factory.world(conn)
    v = factory.lesson_version(conn, w.lesson)
    good = _event(w, lesson_version_id=v)
    insert(conn, good)
    bad = good.model_copy(update={"id": new_id(), "lesson_version_id": None})
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        insert(conn, bad)
    row = conn.execute("SELECT * FROM learning_event WHERE id = ?", (good.id,)).fetchone()
    assert load(r.LearningEvent, row).payload == good.payload
    assert row["server_seq"] == 1


def test_timestamps_and_ids_are_checked(conn: sqlite3.Connection) -> None:
    w = factory.world(conn)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("UPDATE learner SET created_at = '2026-10-27 10:00:00' WHERE id = ?", (w.learner,))
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(
            "INSERT INTO device VALUES ('not-a-uuid', 'x', 'x', ?, ?, NULL)", (clock.now(), clock.now())
        )


def test_status_enum_is_closed(conn: sqlite3.Connection) -> None:
    w = factory.world(conn)
    v = factory.lesson_version(conn, w.lesson, status=GateStatus.IN_REVIEW)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("UPDATE lesson_version SET status = 'superseded' WHERE id = ?", (v,))
