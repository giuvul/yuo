"""The "What next?" checkpoint: offered after progress, AI-written questions and quiz, directions with reasons,
and new branches only after the learner confirms one (0.8.0)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests import fakes
from tests.integration.test_slice import NoPrices, create, drain, lessons_of
from tests.integration.test_study import Learner
from yuo.api.app import create_app
from yuo.core.llm import Role
from yuo.curriculum import next_steps as ns
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


def _prompt(llm: fakes.FakeLLM, stage: str) -> str:
    return "\n".join(m.content for m in [r for s, r in llm.calls if s == stage][-1].messages)


def test_the_checkpoint_grows_the_path_only_after_the_learner_confirms(
    rt: Runtime, llm: fakes.FakeLLM
) -> None:
    path_id = create(rt)
    first = lessons_of(rt, path_id)[0]
    view = rt.service.next_view(path_id)
    assert view["status"] == "none" and view["offer"] is None  # nothing studied yet

    Learner(rt, llm).study(first["id"])
    view = rt.service.next_view(path_id)
    assert view["diagnosis"]["lessons_done"] == 1
    assert view["offer"] in (None, "running_low", "branch_done")

    branches = len(rt.service.path_view(path_id)["branches"])
    rt.service.start_next(path_id)
    assert rt.service.next_view(path_id)["status"] == "preparing"
    with pytest.raises(ValueError, match="already open"):
        rt.service.start_next(path_id)
    drain(rt)
    view = rt.service.next_view(path_id)
    assert view["status"] == "ready" and len(view["questions"]) == 3 and len(view["quiz"]) == 3
    assert "answer" not in view["quiz"][0]
    check = _prompt(llm, "next_check")
    assert "Lessons studied: 1" in check and "<learner_input>" in check

    rt.service.answer_next(
        path_id, [0, 1, None], [{"option": 1, "text": ""}, {"option": None, "text": "jazz"}]
    )
    drain(rt)
    view = rt.service.next_view(path_id)
    assert view["status"] == "proposed" and [d["kind"] for d in view["directions"]] == [
        "deeper",
        "wider",
        "apply",
    ]
    assert view["quiz_result"] == {
        "right": 1,
        "total": 3,
        "ready": ["beyond 1"],
        "not_yet": ["beyond 2", "beyond 3"],
    }
    asked = _prompt(llm, "next_directions")
    assert "Where next 1? -> choice 1b" in asked and "Where next 2? -> jazz" in asked
    assert "1 of 3 right" in asked
    assert len(rt.service.path_view(path_id)["branches"]) == branches  # nothing added yet

    rt.service.other_directions(path_id)  # none fits: different ones, avoiding these
    drain(rt)
    view = rt.service.next_view(path_id)
    assert view["status"] == "proposed" and view["directions"][0]["title"] == "Go deeper again"
    assert "turned these down" in _prompt(llm, "next_directions")

    with pytest.raises(ValueError, match="unknown direction"):
        rt.service.choose_next(path_id, "nope")
    rt.service.choose_next(path_id, "wider-2")
    drain(rt)
    view = rt.service.next_view(path_id)
    assert view["status"] == "done" and view["added"] == ["Grown branch"] and view["offer"] is None
    tree = rt.service.path_view(path_id)
    assert len(tree["branches"]) == branches + 1 and tree["branches"][-1]["title"] == "Grown branch"
    grown = tree["branches"][-1]["skills"]
    first_skill = tree["branches"][0]["skills"][0]["id"]
    assert grown[0]["requires"] == [first_skill] and grown[1]["requires"] == [grown[0]["id"]]
    assert "Go wider again" in _prompt(llm, "next_grow")
    # the progress stays: the studied lesson is still done, and the buffer reaches the new lessons in turn
    assert rt.service.next_view(path_id)["diagnosis"]["lessons_done"] == 1


def test_dismissing_closes_the_checkpoint_until_more_progress(rt: Runtime, llm: fakes.FakeLLM) -> None:
    path_id = create(rt)
    learner = Learner(rt, llm)
    lessons = lessons_of(rt, path_id)
    learner.study(lessons[0]["id"])
    rt.service.start_next(path_id)
    drain(rt)
    view = rt.service.dismiss_next(path_id)
    assert view["status"] == "dismissed" and view["offer"] is None and view["questions"] == []


def test_offer_rules() -> None:
    d = {"lessons_done": 30, "lessons_left": 10, "finished_branch_ids": ["b1"]}  # 75% studied
    assert ns.offer(None, d) == "branch_done"
    assert ns.offer({"status": "dismissed", "seen_done": 30, "seen_branches": ["b1"]}, d) is None
    assert ns.offer({"status": "dismissed", "seen_done": 29, "seen_branches": ["b1"]}, d) is None
    assert (
        ns.offer({"status": "done", "seen_done": 29, "seen_branches": ["b1"]}, d | {"lessons_left": 2})
        == "running_low"
    )
    assert ns.offer({"status": "proposed"}, d) is None
    assert ns.offer(None, d | {"lessons_done": 0}) is None
    # below 75% of the path: no invitation and no button, even with a finished branch
    early = d | {"lessons_done": 4}
    assert ns.offer(None, early) is None and not ns.available(None, early)
    assert ns.available(None, d) and ns.available({"status": "ready"}, early)


def test_direction_and_grow_rules() -> None:
    weak = ns.directions_rules(False, ["Old idea"])
    draft = ns.DirectionsDraft(
        directions=[
            ns.Direction(code="a", kind="fix", title="Old idea", reason="", preview=["x"]),
            ns.Direction(code="a", kind="fix", title="New", reason="ok", preview=["x", "y"]),
        ]
    )
    problems = " | ".join(weak(draft))
    for p in (
        "different kind",
        "codes must be unique",
        "do not propose a fix",
        "2 to 4 skills",
        "give the reason",
        "turned this one down",
    ):
        assert p in problems
    rules = ns.grow_rules({"skill": {"sql.basics"}, "lesson": {"grow.s0.l1"}})
    tree = fakes.next_grow("- Basics: sql.basics (Basics)")
    from yuo.curriculum.tree import TreeDraft

    problems = " | ".join(rules(TreeDraft.model_validate(tree)))
    assert (
        "requires unknown skill" not in problems
        and "lesson code 'grow.s0.l1' is already in the path" in problems
    )


def test_api_round_trip(rt: Runtime, llm: fakes.FakeLLM) -> None:
    path_id = create(rt)
    Learner(rt, llm).study(lessons_of(rt, path_id)[0]["id"])
    with TestClient(create_app(version="test", health=dict, service=rt.service)) as client:
        assert client.get(f"/api/paths/{path_id}/next").json()["status"] == "none"
        assert client.post(f"/api/paths/{path_id}/next").json()["status"] == "preparing"
        drain(rt)
        r = client.post(
            f"/api/paths/{path_id}/next/answers", json={"quiz": [0, 0, 0], "answers": [{"option": 0}]}
        )
        assert r.json()["status"] == "proposing"
        drain(rt)
        assert client.post(f"/api/paths/{path_id}/next/choose", json={"code": "zzz"}).status_code == 422
        assert (
            client.post(f"/api/paths/{path_id}/next/choose", json={"code": "apply"}).json()["status"]
            == "growing"
        )
        drain(rt)
        assert client.get(f"/api/paths/{path_id}/next").json()["status"] == "done"
        assert client.post(f"/api/paths/{path_id}/next/retry").status_code == 422
        assert client.get("/api/paths/0190c5a0-0000-7000-8000-000000000000/next").status_code == 404
