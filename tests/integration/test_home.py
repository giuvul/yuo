"""Home: the next step, what waits today and how it goes, across the learner's paths."""

from datetime import date, timedelta
from pathlib import Path

from tests import fakes
from tests.integration.test_slice import _due_now, create, drain, event, lessons_of, llm, rt  # noqa: F401
from yuo.core import clock
from yuo.core.ids import new_id
from yuo.learning.events import IncomingEvent
from yuo.main import Runtime


def test_an_empty_home(rt: Runtime) -> None:  # noqa: F811
    home = rt.service.home()
    assert home["next_step"] is None and home["today"] == [] and home["progress"] is None
    assert home["lessons_ready"] == 0 and home["exam"] is None


def test_the_next_lesson_progress_and_new_lessons(rt: Runtime, llm: fakes.FakeLLM) -> None:  # noqa: F811
    path_id = create(rt)
    lessons = lessons_of(rt, path_id)
    home = rt.service.home()
    nxt = home["next_step"]
    assert nxt["kind"] == "lesson" and nxt["lesson_id"] == lessons[0]["id"] and nxt["path_id"] == path_id
    assert nxt["index"] == 1 and nxt["count"] >= 2 and not nxt["started"]
    assert home["lessons_ready"] == 3
    assert home["progress"]["score"] == 0 and home["progress"]["status"] == "starting"

    device = rt.service.register_device("test", "pytest")
    version = rt.service.lesson_view(lessons[0]["id"])["version_id"]
    rt.service.ingest(
        device,
        [
            event("lesson.started", {"lesson_version_id": version, "seconds": 0}),
            event("lesson.completed", {"lesson_version_id": version, "seconds": 300}),
        ],
    )
    practice = rt.service.start_practice(lessons[0]["id"])
    mcq = practice["items"][0]
    attempt = new_id()
    rt.service.ingest(
        device,
        [
            event(
                "attempt.started",
                {"attempt_id": attempt, "assessment_id": practice["assessment_id"], "purpose": "practice"},
            ),
            IncomingEvent(
                id=new_id(),
                type="assessment.response_given",
                device_at=clock.now(),
                tz="Europe/Rome",
                payload={
                    "attempt_id": attempt,
                    "item_version_id": mcq["item_version_id"],
                    "answer": fakes.answer_for(mcq, llm),
                    "ms_to_answer": 3000,
                },
            ),
        ],
    )
    home = rt.service.home()
    assert home["next_step"]["lesson_id"] == lessons[1]["id"] and home["next_step"]["index"] == 2
    assert home["lessons_ready"] == 2  # the first one was opened
    progress = home["progress"]
    assert progress["score"] > 0 and progress["delta"] == progress["score"]  # nothing answered a week ago
    assert progress["status"] == "on_track"


def test_a_lesson_that_failed_its_review_is_on_the_list(
    rt: Runtime,  # noqa: F811
    llm: fakes.FakeLLM,  # noqa: F811
    db_path: Path,
) -> None:
    llm.script["review"] = [fakes.review("fail")] * 500
    path_id = create(rt)
    for _ in range(4):
        _due_now(db_path)
        drain(rt)
    items = rt.service.home()["today"]
    assert items[0]["kind"] == "lesson_draft" and items[0]["path_id"] == path_id and items[0]["lesson_id"]


def test_the_nearest_exam(rt: Runtime) -> None:  # noqa: F811
    soon = (date.today() + timedelta(days=9)).isoformat()
    later = (date.today() + timedelta(days=40)).isoformat()
    rt.service.create_studies(
        "Engineering",
        [{"title": "Physics 1", "exam_date": later}, {"title": "Analysis 1", "exam_date": soon}],
    )
    exam = rt.service.home()["exam"]
    assert exam["title"] == "Analysis 1" and exam["days"] in (8, 9, 10) and not exam["built"]


def test_a_path_is_renamed_archived_and_deleted(rt: Runtime, llm: fakes.FakeLLM) -> None:  # noqa: F811
    path_id = create(rt)
    other = create(rt)
    lessons = lessons_of(rt, path_id)
    device = rt.service.register_device("test", "pytest")
    version = rt.service.lesson_view(lessons[0]["id"])["version_id"]
    rt.service.ingest(device, [event("lesson.started", {"lesson_version_id": version, "seconds": 0})])

    row = rt.service.update_path(
        path_id, {"title": "  Renamed  ", "goal": "Pass the exam", "target_date": "2027-01-10"}
    )
    assert row["title"] == "Renamed" and row["goal"] == "Pass the exam" and row["target_date"] == "2027-01-10"
    assert rt.service.update_path(path_id, {"status": "archived"})["status"] == "archived"
    assert rt.service.home()["next_step"]["path_id"] == other  # an archived path leaves Home
    assert rt.service.update_path(path_id, {"status": "active"})["status"] == "active"

    counts = rt.service.delete_path(path_id)
    assert counts["path"] == 1 and counts["lesson"] >= 1 and counts.get("learning_event", 0) >= 1
    assert [p["id"] for p in rt.service.paths()] == [other]
    with rt.readers.connection() as c:
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        assert (
            c.execute("SELECT count(*) FROM generation_job WHERE target_id = ?", (path_id,)).fetchone()[0]
            == 0
        )
    assert len(lessons_of(rt, other)) >= 1


def test_a_path_from_courses_is_deleted_with_its_courses(rt: Runtime) -> None:  # noqa: F811
    soon = (date.today() + timedelta(days=9)).isoformat()
    rt.service.create_studies("Engineering", [{"title": "Analysis 1", "exam_date": soon}])
    path_id = rt.service.paths()[0]["id"]
    counts = rt.service.delete_path(path_id)
    assert counts["path"] == 1 and counts["course"] == 1
    assert rt.service.paths() == [] and rt.service.home()["exam"] is None


def test_my_own_material_opens_the_same_empty_path_again(rt: Runtime) -> None:  # noqa: F811
    first = rt.service.create_studies("", [])
    assert rt.service.create_studies("", []) == first  # back and forth in the wizard: no second empty path
    assert len(rt.service.paths()) == 1
