"""The level check before a path is planned, the urgent job lane, and paths without a subject (0.7.4)."""

import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests import fakes
from tests.integration.test_slice import NoPrices, create, drain, lessons_of
from yuo.api.app import create_app
from yuo.app.forms import PathForm
from yuo.core.llm import Request, Role
from yuo.curriculum import level_check as lc
from yuo.generation.jobs import URGENT_KINDS
from yuo.main import Runtime, start


@pytest.fixture
def llm() -> fakes.FakeLLM:
    return fakes.FakeLLM()


@pytest.fixture
def rt(db_path: Path, llm: fakes.FakeLLM) -> Iterator[Runtime]:
    r = start(db_path, {"openrouter": llm}, NoPrices(), worker=False)
    roles: tuple[tuple[Role, str], ...] = (
        ("generator", "deepseek/deepseek-v4-pro"),
        ("reviewer", "qwen/qwen3.8-27b"),
        ("grader", "deepseek/deepseek-v4-pro"),
        ("utility", "deepseek/deepseek-v4-pro"),
    )
    for role, model in roles:
        r.service.bind(role, "openrouter", model)
    yield r
    r.close()


def _tree_prompt(llm: fakes.FakeLLM) -> str:
    req: Request = next(r for s, r in llm.calls if s == "tree")
    return "\n".join(m.content for m in req.messages)


def test_the_tree_waits_for_the_level_check_and_starts_at_the_learners_level(
    rt: Runtime, llm: fakes.FakeLLM
) -> None:
    path_id = create(rt, level_check=True)
    view = rt.service.level_check(path_id)
    assert view["status"] == "ready" and len(view["questions"]) == 8
    assert "answer" not in view["questions"][0] and "level" not in view["questions"][0]
    assert lessons_of(rt, path_id) == []  # no tree, no lessons before the answers
    assert rt.service.path_view(path_id)["level_check"] == "ready"

    # right on levels 1 to 3 (questions 1-5), wrong or "don't know" above
    out = rt.service.answer_level_check(path_id, [0, 0, 0, 0, 0, 1, None, None])
    assert out["status"] == "done" and out["result"]["level"] == 3
    assert out["result"]["difficulty"] == "intermediate"
    drain(rt)
    assert lessons_of(rt, path_id)
    view = rt.service.path_view(path_id)
    assert view["difficulty"] == "intermediate" and view["status"] == "active"
    prompt = _tree_prompt(llm)
    assert "Level check: 5 of 8 right" in prompt and "Does not know yet: topic 6; topic 7; topic 8" in prompt


def test_a_skipped_level_check_plans_the_tree_from_the_stated_level(rt: Runtime, llm: fakes.FakeLLM) -> None:
    path_id, _ = rt.service.create_path(PathForm(title="SQL", subject="", goal="joins", level_check=True))
    # skipped before the questions were written: the queued job plans the tree straight away
    assert rt.service.answer_level_check(path_id, None)["status"] == "skipped"
    drain(rt)
    assert [s for s, _ in llm.calls].count("level_check") == 0
    assert lessons_of(rt, path_id)
    assert "Level check" not in _tree_prompt(llm)
    with pytest.raises(ValueError):
        rt.service.answer_level_check(path_id, [0])


def test_a_path_without_a_subject_uses_its_title(rt: Runtime) -> None:
    path_id = create(rt, title="Spanish for travel", subject="")
    assert rt.service.path_view(path_id)["subject"] == "Spanish for travel"


def test_level_check_scoring() -> None:
    qs = fakes.level_check()["questions"]
    # a lucky guess at level 5 does not skip the levels below
    assert lc.score(qs, [None, None, None, None, None, None, None, 0])["level"] == 0
    assert lc.score(qs, [0] * 8)["difficulty"] == "expert"
    assert lc.score(qs, [])["right"] == 0  # no answers: all unknown
    assert lc.level_check_rules(lc.LevelCheckDraft(**fakes.level_check())) == []
    bad = fakes.level_check()
    bad["questions"][0]["answer"] = 7
    assert any("answer must be" in p for p in lc.level_check_rules(lc.LevelCheckDraft(**bad)))


def test_level_check_over_http(rt: Runtime) -> None:
    http = TestClient(create_app(version="test", health=dict, service=rt.service))
    created = http.post("/api/paths", json={"title": "SQL", "goal": "Write joins", "level_check": True})
    assert created.status_code == 201
    path_id = created.json()["path_id"]
    assert http.get(f"/api/paths/{path_id}/level-check").json()["status"] == "preparing"
    drain(rt)
    view = http.get(f"/api/paths/{path_id}/level-check").json()
    assert view["status"] == "ready" and view["result"] is None
    assert "answer" not in json.dumps(view["questions"])
    done = http.post(f"/api/paths/{path_id}/level-check", json={"answers": [0] * 8})
    assert done.status_code == 200 and done.json()["result"]["right"] == 8
    assert http.post(f"/api/paths/{path_id}/level-check", json={"skip": True}).status_code == 422


def test_urgent_jobs_do_not_wait_behind_a_lesson(rt: Runtime, llm: fakes.FakeLLM) -> None:
    """A skill test bank runs on the urgent thread while a lesson job holds the background one."""
    path_id = create(rt)
    skill_id = rt.service.path_view(path_id)["branches"][0]["skills"][0]["id"]
    lesson = next(lesson for lesson in lessons_of(rt, path_id) if lesson["state"] == "planned")
    rt.service.request_lesson(lesson["id"])  # a queued background job
    blocked, release = threading.Event(), threading.Event()

    def slow_lesson(job: object) -> None:
        blocked.set()
        release.wait(10)

    handlers = rt.worker.handlers
    original = handlers["lesson"]
    handlers["lesson"] = slow_lesson
    try:
        background = threading.Thread(target=lambda: rt.worker.run_once(urgent=False))
        background.start()
        assert blocked.wait(5)
        job = rt.service.start_skill_test(skill_id)["job_id"]
        assert "test_bank" in URGENT_KINDS
        assert rt.worker.run_once(urgent=True)  # done while the lesson still runs
        with rt.readers.connection() as c:
            assert (
                c.execute("SELECT status FROM generation_job WHERE id = ?", (job,)).fetchone()[0]
                == "succeeded"
            )
    finally:
        release.set()
        background.join(10)
        handlers["lesson"] = original
    drain(rt)


def test_a_failed_level_check_can_be_written_again(rt: Runtime, llm: fakes.FakeLLM) -> None:
    """0.7.6: the model was not reachable (e.g. the subscription program was signed out); after fixing
    that the learner asks for the questions again instead of only skipping."""
    from yuo.core.llm import LLMError

    llm.script["level_check"] = [LLMError("claude-cli: Not logged in", kind="auth")]
    path_id = create(rt, level_check=True)
    view = rt.service.level_check(path_id)
    assert view["status"] == "preparing" and view["failed"] is True
    again = rt.service.retry_level_check(path_id)
    assert again["failed"] is False
    drain(rt)
    assert rt.service.level_check(path_id)["status"] == "ready"
    with pytest.raises(ValueError, match="not waiting"):
        rt.service.retry_level_check(path_id)


def test_the_jobs_list_says_what_a_running_job_does_and_how_long_it_usually_takes(
    rt: Runtime, llm: fakes.FakeLLM
) -> None:
    """A video lesson that only says "in progress" looks stuck. The list names the
    lesson, the step it is at and the round, and how long that kind of job usually takes."""
    from yuo.app.job_status import TYPICAL_JOB_S
    from yuo.generation import progress

    path_id = create(rt)
    skill, lesson = next(
        (s["title"], le)
        for b in rt.service.path_view(path_id)["branches"]
        for s in b["skills"]
        for le in s["lessons"]
        if le["state"] == "planned"
    )
    rt.service.request_lesson(lesson["id"])
    inside, release = threading.Event(), threading.Event()

    def slow_lesson(job: object) -> None:
        progress.rounds(2, 4)
        progress.step("narration")
        inside.set()
        release.wait(10)

    handlers = rt.worker.handlers
    original = handlers["lesson"]
    handlers["lesson"] = slow_lesson
    try:
        t = threading.Thread(target=lambda: rt.worker.run_once(urgent=False))
        t.start()
        assert inside.wait(5)
        job = next(j for j in rt.service.active_jobs() if j["kind"] == "lesson" and j["status"] == "running")
        assert job["title"] == skill  # no version yet: the skill's name
        assert (job["step"], job["round"], job["rounds"]) == ("narration", 2, 4)
        assert job["running_s"] is not None and job["running_s"] >= 0
        assert (
            job["typical_s"] == TYPICAL_JOB_S["lesson"]
        )  # the fake model's lessons took no time: no history
    finally:
        release.set()
        t.join(10)
        handlers["lesson"] = original
    done = [j for j in rt.service.active_jobs() if j["kind"] == "lesson" and j["target_id"] == lesson["id"]]
    assert all(j["step"] is None for j in done)  # nothing left over once it ends
    drain(rt)
