"""The plan preview: the learner sees the plan, changes it in their own words and builds it."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests import fakes
from tests.integration.test_slice import NoPrices, create, drain, lessons_of
from yuo.api.app import create_app
from yuo.core.llm import LLMError, Role
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


def _skills(view: dict) -> list[str]:  # type: ignore[type-arg]
    return [s["code"] for b in view["tree"]["branches"] for s in b["skills"]]


def test_the_plan_waits_for_the_learner_and_is_revised_with_their_feedback(
    rt: Runtime, llm: fakes.FakeLLM
) -> None:
    path_id = create(rt, preview=True)
    view = rt.service.preview_view(path_id)
    assert view["status"] == "ready" and view["version"] == 1
    assert len(_skills(view)) == 4
    assert lessons_of(rt, path_id) == []  # nothing is built or written before the learner accepts
    assert rt.service.path_view(path_id)["preview"] == "ready"
    assert rt.service.path_view(path_id)["status"] == "draft"

    view = rt.service.preview_feedback(path_id, "Go deeper on joins, please")
    assert view["status"] == "revising" and view["job_id"]
    drain(rt)
    view = rt.service.preview_view(path_id)
    assert view["status"] == "ready" and view["version"] == 2
    assert len(_skills(view)) == 6 and view["changes"] == ["Added a third skill to each branch."]
    assert view["feedback"] == ["Go deeper on joins, please"]
    req = next(r for s, r in llm.calls if s == "tree_revise")
    prompt = "\n".join(m.content for m in req.messages)
    assert "Go deeper on joins, please" in prompt and '"sql.b0.s0"' in prompt
    assert lessons_of(rt, path_id) == []

    # back to the first plan, then build it
    view = rt.service.undo_feedback(path_id)
    assert len(_skills(view)) == 4 and view["feedback"] == []
    with pytest.raises(ValueError):
        rt.service.undo_feedback(path_id)
    view = rt.service.build_preview(path_id)
    assert view["status"] == "built"
    p = rt.service.path_view(path_id)
    assert p["status"] == "active" and p["preview"] == "built"
    assert len(lessons_of(rt, path_id)) == 4
    with pytest.raises(ValueError):
        rt.service.build_preview(path_id)
    with pytest.raises(ValueError):
        rt.service.preview_feedback(path_id, "more")


def test_a_plan_with_a_level_check_is_previewed_after_the_answers(rt: Runtime) -> None:
    path_id = create(rt, preview=True, level_check=True)
    assert rt.service.preview_view(path_id)["status"] == "drafting"
    rt.service.answer_level_check(path_id, [0] * 8)
    drain(rt)
    assert rt.service.preview_view(path_id)["status"] == "ready"
    assert lessons_of(rt, path_id) == []


def test_a_failed_revision_can_be_tried_again(rt: Runtime, llm: fakes.FakeLLM) -> None:
    path_id = create(rt, preview=True)
    llm.script["tree_revise"] = [LLMError("openrouter: the key was refused", kind="auth")]
    rt.service.preview_feedback(path_id, "Add window functions")
    drain(rt)
    view = rt.service.preview_view(path_id)
    assert view["status"] == "revising" and view["failed"]
    rt.service.retry_preview(path_id)
    drain(rt)
    assert rt.service.preview_view(path_id)["status"] == "ready"


def test_paths_without_a_preview_are_built_straight_away(rt: Runtime) -> None:
    path_id = create(rt)
    assert rt.service.preview_view(path_id)["status"] == "none"
    assert lessons_of(rt, path_id)


def test_preview_over_http(rt: Runtime) -> None:
    http = TestClient(create_app(version="test", health=dict, service=rt.service))
    created = http.post("/api/paths", json={"title": "SQL", "goal": "Write joins", "preview": True})
    path_id = created.json()["path_id"]
    assert http.get(f"/api/paths/{path_id}/preview").json()["status"] == "drafting"
    drain(rt)
    assert http.get(f"/api/paths/{path_id}").json()["preview"] == "ready"
    assert http.post(f"/api/paths/{path_id}/preview/feedback", json={"text": ""}).status_code == 422
    assert http.post(f"/api/paths/{path_id}/preview/feedback", json={"text": "more"}).status_code == 200
    drain(rt)
    built = http.post(f"/api/paths/{path_id}/preview/build")
    assert built.status_code == 200 and built.json()["status"] == "built"
