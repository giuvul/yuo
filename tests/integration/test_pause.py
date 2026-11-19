"""Pausing background generation: nothing is started while paused, a running job stops before its next model
call, and on resume it goes on from its stored stages without repeating a call or using up an attempt."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from tests import fakes
from tests.integration.test_slice import create, drain, lessons_of, llm, rt  # noqa: F401
from yuo.core import clock
from yuo.core.enums import EntityKind
from yuo.core.errors import InvalidInput
from yuo.generation import pause
from yuo.main import Runtime


def _jobs(rt: Runtime, kind: str) -> list[dict[str, Any]]:  # noqa: F811
    with rt.readers.connection() as c:
        return [dict(r) for r in c.execute("SELECT * FROM generation_job WHERE kind = ?", (kind,))]


def test_a_pause_until_a_time_ends_by_itself() -> None:
    assert pause.kinds(None, clock.now()) == pause.NOTHING
    assert pause.kinds({"scope": "all", "until": None}, clock.now()) == pause.PAUSABLE
    assert pause.kinds({"scope": "videos", "until": None}, clock.now()) == {"rendition"}
    past = clock.to_timestamp(datetime.now(UTC) - timedelta(minutes=1))
    assert pause.kinds({"scope": "all", "until": past}, clock.now()) == pause.NOTHING


def test_nothing_is_written_ahead_while_paused_and_the_plan_still_comes(
    rt: Runtime,  # noqa: F811
    llm: fakes.FakeLLM,  # noqa: F811
) -> None:
    view = rt.service.set_generation_pause("all", None)
    assert view["paused"] and view["scope"] == "all" and view["until"] is None
    path_id = create(rt)  # the plan is what the learner waits for on screen: never paused
    assert "tree" in llm.stages() and "lesson" not in llm.stages()
    assert rt.service.generation_pause()["waiting"] >= 1
    assert all(j["status"] == "queued" and j["attempt"] == 0 for j in _jobs(rt, "lesson"))

    assert rt.service.set_generation_pause(None, None)["paused"] is False
    drain(rt)
    assert any(lesson["state"] == "ready" for lesson in lessons_of(rt, path_id))


def test_a_lesson_paused_mid_way_goes_on_from_its_stored_stages(rt: Runtime, llm: fakes.FakeLLM) -> None:  # noqa: F811
    paused: list[bool] = []

    def review_then_pause(request: Any) -> Any:
        if not paused:  # the learner pauses while the first review call runs: that call still finishes
            rt.service.set_generation_pause("all", None)
            paused.append(True)
        return llm.default("review", request)

    llm.script["review"] = [review_then_pause]
    path_id = create(rt)
    first = [j for j in _jobs(rt, "lesson") if j["error"] == "paused"]
    assert len(first) == 1 and first[0]["status"] == "queued" and first[0]["attempt"] == 0
    before = llm.stages().count("lesson"), llm.stages().count("review")

    rt.service.set_generation_pause(None, None)
    drain(rt)
    lessons = lessons_of(rt, path_id)
    ready = [lesson for lesson in lessons if lesson["state"] == "ready"]
    assert ready
    # the paused lesson's body and review came back from the store: each lesson was written and checked once
    assert llm.stages().count("lesson") == len(ready) and before[0] >= 1
    assert all(j["attempt"] == 1 for j in _jobs(rt, "lesson") if j["status"] == "succeeded")


def test_a_pause_must_end_in_the_future(rt: Runtime) -> None:  # noqa: F811
    with pytest.raises(InvalidInput):
        rt.service.set_generation_pause("all", "2020-01-01T00:00:00.000Z")
    with pytest.raises(InvalidInput):
        rt.service.set_generation_pause("everything", None)
    later = clock.to_timestamp(datetime.now(UTC) + timedelta(hours=1))
    assert rt.service.set_generation_pause("videos", later)["until"] == later


def test_the_jobs_list_shows_the_line_in_the_order_the_worker_takes_it(rt: Runtime) -> None:  # noqa: F811
    from yuo.core.ids import new_id
    from yuo.generation.jobs import enqueue

    ids = [new_id() for _ in range(4)]

    def unit(c: Any) -> list[str]:
        return [
            enqueue(c, "items", EntityKind.LESSON, ids[0], priority=-5),  # review questions: last
            enqueue(c, "lesson", EntityKind.LESSON, ids[1]),  # a lesson ahead
            enqueue(c, "rendition", EntityKind.RENDITION, ids[2], priority=-1),  # a video made by itself
            enqueue(c, "lesson", EntityKind.LESSON, ids[3], priority=5),  # a lesson the learner asked for
        ]

    items, ahead, video, asked = rt.writer.run(unit)
    line = {j["id"]: j["turn"] for j in rt.service.active_jobs()}
    assert [j["id"] for j in rt.service.active_jobs()] == [asked, ahead, video, items]
    assert line == {asked: 1, ahead: 2, video: 3, items: 4}
    rt.service.set_generation_pause("videos", None)
    line = {j["id"]: j["turn"] for j in rt.service.active_jobs()}
    assert line == {asked: 1, ahead: 2, video: None, items: 3}  # a paused video waits outside the line
