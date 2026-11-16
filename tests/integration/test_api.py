"""The slice over HTTP with a scripted model: every response must fit its declared model."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests import fakes
from tests.integration.test_slice import NoPrices
from yuo.api.app import create_app
from yuo.core import clock
from yuo.core.errors import Conflict, InvalidInput, NotFound
from yuo.core.ids import new_id
from yuo.main import Runtime, start


@pytest.fixture
def client(db_path: Path) -> Iterator[tuple[TestClient, Runtime]]:
    rt = start(db_path, {"openrouter": fakes.FakeLLM()}, NoPrices(), worker=False)
    app = create_app(version="test", health=dict, service=rt.service)
    with TestClient(app) as c:
        yield c, rt
    rt.close()


def test_slice_over_http(client: tuple[TestClient, Runtime]) -> None:
    http, rt = client
    assert http.post("/api/setup/preset", json={"preset": "open"}).status_code == 200
    setup = http.get("/api/setup").json()
    assert setup["bindings"]["reviewer"]["model"] == "qwen/qwen3.8-27b"
    assert any("same model" in w for w in setup["warnings"])  # warning with an all-Qwen preset

    est = http.get("/api/estimate", params={"lessons": 20}).json()
    assert est["high_usd"] >= est["low_usd"] > 0

    created = http.post("/api/paths", json={"title": "SQL", "subject": "SQL", "goal": "joins"})
    assert created.status_code == 201
    while rt.worker.run_once():
        pass
    path = http.get(f"/api/paths/{created.json()['path_id']}").json()
    lesson_id = path["branches"][0]["skills"][0]["lessons"][0]["id"]
    lesson = http.get(f"/api/lessons/{lesson_id}").json()
    assert lesson["state"] == "ready" and lesson["body"][0]["bid"] == "b1"

    practice = http.post(f"/api/lessons/{lesson_id}/practice").json()
    item = practice["items"][0]
    assert item["type"] == "mcq"
    key = next(o["id"] for o in item["view"]["options"] if o["text"] == "SELECT list")
    wrong = next(o["id"] for o in item["view"]["options"] if o["id"] != key)
    assert http.get(f"/api/items/{item['item_version_id']}/hints/1").json()["last"] is False
    assert http.get(f"/api/items/{item['item_version_id']}/hints/9").status_code == 404

    device = http.post("/api/devices", json={"label": "browser"}).json()["device_id"]
    attempt, response = new_id(), new_id()
    events = [
        {
            "id": new_id(),
            "type": "attempt.started",
            "device_at": clock.now(),
            "tz": "UTC",
            "payload": {
                "attempt_id": attempt,
                "assessment_id": practice["assessment_id"],
                "purpose": "practice",
            },
        },
        {
            "id": response,
            "type": "assessment.response_given",
            "device_at": clock.now(),
            "tz": "UTC",
            "payload": {
                "attempt_id": attempt,
                "item_version_id": item["item_version_id"],
                "answer": wrong,
                "ms_to_answer": 1000,
            },
        },
    ]
    out = http.post("/api/events", json={"device_id": device, "events": events}).json()
    assert out["graded"][response]["score"] == 0.0 and out["graded"][response]["correct"] == key

    job = http.get(f"/api/jobs/{path['jobs'][1]['id']}").json()
    assert [s["stage"] for s in job["stages"]][:2] == ["lesson_body", "review"]
    assert http.get("/api/ledger").json()["billed_usd"] > 0

    # Endpoints
    progress = http.get(f"/api/paths/{path['id']}/progress").json()
    first_skill = path["branches"][0]["skills"][0]["id"]
    assert progress["skills"][first_skill]["state"] == "in_progress" and progress["gamification"] == "full"
    assert http.get("/api/reviews").json()["due"] == 0
    test = http.post(f"/api/skills/{first_skill}/test").json()
    assert "job_id" in test  # the item bank is written first
    while rt.worker.run_once():
        pass
    test = http.post(f"/api/skills/{first_skill}/test").json()
    assert test["purpose"] == "skill_test" and len(test["items"]) == 5
    note = http.post(
        "/api/notes", json={"text": "why?", "lesson_version_id": lesson["version_id"], "bid": "b2"}
    )
    assert note.status_code == 201
    assert http.get(f"/api/lessons/{lesson_id}/notes").json()[0]["text"] == "why?"
    assert http.delete(f"/api/notes/{note.json()['note_id']}").status_code == 204
    keys = {s["key"]: s for s in http.get("/api/settings").json()}
    assert keys["skill_test.pass_mark"]["value"] == 0.8 and keys["skill_test.pass_mark"]["explanation"]
    assert http.put("/api/settings/generation.buffer", json={"value": 2}).status_code == 204
    assert http.put("/api/settings/generation.buffer", json={"value": 99}).status_code == 422
    req = http.post(f"/api/paths/{path['id']}/requests", json={"prompt": "anti-joins please"})
    assert req.status_code == 202 and http.get("/api/jobs").json()


def test_errors_map_to_status_codes(client: tuple[TestClient, Runtime]) -> None:
    http, _ = client
    assert http.get(f"/api/lessons/{new_id()}").status_code == 404
    assert http.post("/api/paths", json={"title": "", "subject": "x", "goal": "y"}).status_code == 422
    # no model bound yet: creating works, the job fails later; asking for setup tells what is missing
    assert http.get("/api/estimate").status_code == 409


@pytest.mark.parametrize(
    ("raised", "status"),
    [
        (NotFound("no such lesson"), 404),
        (Conflict("not ready yet"), 409),
        (InvalidInput("a title is needed"), 422),
        (KeyError("generator"), 500),  # a bug: it used to come back as a 409
        (ValueError("bad"), 500),  # a bug: it used to come back as a 422
    ],
)
def test_only_errors_raised_on_purpose_get_a_status(
    db_path: Path, monkeypatch: pytest.MonkeyPatch, raised: Exception, status: int
) -> None:
    """The status comes from the error's class in yuo.core.errors, never from a builtin."""
    rt = start(db_path, {"openrouter": fakes.FakeLLM()}, NoPrices(), worker=False)
    try:

        def fail(_lesson_id: str) -> None:
            raise raised

        monkeypatch.setattr(rt.service, "lesson_view", fail)
        app = create_app(version="test", health=dict, service=rt.service)
        with TestClient(app, raise_server_exceptions=False) as http:
            answer = http.get(f"/api/lessons/{new_id()}")
        assert answer.status_code == status
        if status < 500:
            assert answer.json()["detail"] == str(raised)
    finally:
        rt.close()


def test_tutor_over_http(client: tuple[TestClient, Runtime]) -> None:
    http, rt = client
    http.post("/api/setup/preset", json={"preset": "open"})
    path_id = http.post("/api/paths", json={"title": "SQL", "subject": "SQL", "goal": "joins"}).json()[
        "path_id"
    ]
    while rt.worker.run_once():
        pass
    lesson_id = http.get(f"/api/paths/{path_id}").json()["branches"][0]["skills"][0]["lessons"][0]["id"]
    ctx = {"screen": "reading", "lesson_id": lesson_id, "selection": {"text": "a join", "bid": "b2"}}
    resolved = http.post("/api/tutor/context", json=ctx).json()
    assert resolved["policy"] == "lesson"
    assert {"kind": "selection", "label": "a join", "n": None, "of": None} in resolved["chips"]
    mid = new_id()
    sent = http.post("/api/tutor/messages", json={"id": mid, "text": "What is this?", "context": ctx})
    assert sent.status_code == 202 and sent.json()["status"] == "queued"
    assert http.post("/api/tutor/messages", json={"id": "nope", "text": "x"}).status_code == 422
    assert rt.service.run_tutor_turn()
    thread = http.get(
        "/api/tutor/messages", params={"conversation_id": sent.json()["conversation_id"]}
    ).json()
    assert [m["role"] for m in thread] == ["learner", "tutor"] and thread[1]["text"] == fakes.TUTOR_REPLY
    assert http.get("/api/tutor/conversations").json()[0]["messages"] == 2
    assert http.delete(f"/api/tutor/messages/{thread[1]['id']}").status_code == 422  # a finished reply stays
    created = http.post("/api/tutor/memory", json={"kind": "preference", "text": "Short answers"})
    memory_id = created.json()["memory_id"]
    assert (
        http.patch(f"/api/tutor/memory/{memory_id}", json={"text": "Very short answers"}).status_code == 204
    )
    assert http.get("/api/tutor/memory").json()[0]["text"] == "Very short answers"
    assert http.delete(f"/api/tutor/memory/{memory_id}").status_code == 204
    assert http.get(f"/api/paths/{path_id}/proposals").json() == []
    assert http.get("/api/nudges").json() == []
