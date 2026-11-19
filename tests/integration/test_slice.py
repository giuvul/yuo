"""The slice end to end on a scripted model: path -> tree -> lessons through the gate -> practice -> events."""

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests import fakes
from yuo.app.forms import PathForm
from yuo.core import clock
from yuo.core.errors import Conflict
from yuo.core.ids import new_id
from yuo.core.llm import Role
from yuo.learning.events import IncomingEvent
from yuo.main import Runtime, start


class NoPrices:
    def per_token(self, adapter: str, model: str) -> tuple[float, float] | None:
        return (1e-6, 2e-6) if adapter == "openrouter" else None


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


def drain(rt: Runtime) -> None:
    while rt.worker.run_once():
        pass


def create(rt: Runtime, **form: Any) -> str:
    fields = {"title": "SQL", "subject": "SQL for analysts", "goal": "Write joins"} | form
    path_id, _ = rt.service.create_path(PathForm(**fields))
    drain(rt)
    return path_id


def lessons_of(rt: Runtime, path_id: str) -> list[dict[str, Any]]:
    view = rt.service.path_view(path_id)
    return [lesson for b in view["branches"] for s in b["skills"] for lesson in s["lessons"]]


def event(kind: str, payload: dict[str, Any], at: str | None = None) -> IncomingEvent:
    return IncomingEvent(
        id=new_id(), type=kind, device_at=at or clock.now(), tz="Europe/Rome", payload=payload
    )


def test_slice_end_to_end(rt: Runtime, llm: fakes.FakeLLM, db_path: Path) -> None:
    path_id = create(rt)
    assert llm.stages()[:3] == ["tree", "lesson", "review"]
    lessons = lessons_of(rt, path_id)
    assert [x["state"] for x in lessons] == ["ready", "ready", "ready", "planned"]  # buffer of 3

    reader = rt.service.lesson_view(lessons[0]["id"])
    assert reader["body"][0]["type"] == "heading" and reader["practice_items"] == 3

    practice = rt.service.start_practice(lessons[0]["id"])
    assert [i["type"] for i in practice["items"]] == ["mcq", "cloze", "flashcard"]
    for i in practice["items"]:
        assert "answer" not in i["view"] and "blanks" not in i["view"] and "back" not in i["view"]
    mcq = practice["items"][0]

    device = rt.service.register_device("test", "pytest")
    attempt, response = new_id(), new_id()
    batch = [
        event(
            "attempt.started",
            {"attempt_id": attempt, "assessment_id": practice["assessment_id"], "purpose": "practice"},
        ),
        IncomingEvent(
            id=response,
            type="assessment.response_given",
            device_at=clock.now(),
            tz="Europe/Rome",
            payload={
                "attempt_id": attempt,
                "item_version_id": mcq["item_version_id"],
                "answer": fakes.answer_for(mcq, llm),
                "ms_to_answer": 4200,
            },
        ),
    ]
    out = rt.service.ingest(device, batch)
    assert sorted(out["accepted"]) == sorted(e.id for e in batch) and out["rejected"] == {}
    assert out["graded"][response]["score"] == 1.0

    again = rt.service.ingest(
        device, batch
    )  # the outbox retries: duplicates, the same grade, no second grade
    assert sorted(again["duplicates"]) == sorted(e.id for e in batch)
    assert again["graded"][response]["score"] == 1.0

    c = sqlite3.connect(db_path)
    types = [r[0] for r in c.execute("SELECT type FROM learning_event ORDER BY server_seq")]
    assert types == ["attempt.started", "assessment.response_given", "assessment.response_graded"]
    assert (
        c.execute(
            "SELECT count(*) FROM quality_check WHERE \"check\" = 'answer_key' AND verdict = 'pass'"
        ).fetchone()[0]
        >= 2
    )
    assert c.execute("SELECT count(*) FROM lesson_fts WHERE lesson_fts MATCH 'join'").fetchone()[0] == 3
    assert c.execute("SELECT score FROM response").fetchone()[0] == 1.0  # projection written on ingest
    assert c.execute("SELECT count(*) FROM review_state").fetchone()[0] == 1


def test_a_failed_review_gets_one_fix_round_with_the_findings(
    rt: Runtime, llm: fakes.FakeLLM, db_path: Path
) -> None:
    llm.script["review"] = [fakes.review("fail")]
    create(rt)
    assert llm.stages()[:5] == ["tree", "lesson", "review", "lesson", "review"]
    fix_prompt = [r for s, r in llm.calls if s == "lesson"][1].messages[-1].content
    assert "inner joins drop unmatched rows" in fix_prompt
    c = sqlite3.connect(db_path)
    first = c.execute("SELECT id FROM lesson ORDER BY rowid LIMIT 1").fetchone()[0]
    statuses = [
        r[0]
        for r in c.execute(
            "SELECT status FROM lesson_version WHERE lesson_id = ? ORDER BY version_no", (first,)
        )
    ]
    assert statuses == ["rejected", "passed"]


def _due_now(db_path: Path) -> None:
    """Skip the retry backoff."""
    c = sqlite3.connect(db_path)
    c.execute("UPDATE generation_job SET next_attempt_at = NULL WHERE status = 'queued'")
    c.commit()
    c.close()


def test_two_failed_reviews_retry_the_lesson_with_a_fresh_draft(
    rt: Runtime, llm: fakes.FakeLLM, db_path: Path
) -> None:
    llm.script["review"] = [fakes.review("fail"), fakes.review("fail")]
    path_id = create(rt)
    assert lessons_of(rt, path_id)[0]["state"] == "queued"  # retried by itself, not left for the learner
    waiting = [j for j in rt.service.path_view(path_id)["jobs"] if j["kind"] == "lesson" and j["error"]]
    assert waiting and "attempt 1 of 3" in waiting[0]["error"]
    _due_now(db_path)
    drain(rt)
    assert lessons_of(rt, path_id)[0]["state"] == "ready"
    c = sqlite3.connect(db_path)
    first = c.execute("SELECT id FROM lesson ORDER BY rowid LIMIT 1").fetchone()[0]
    statuses = [
        r[0]
        for r in c.execute(
            "SELECT status FROM lesson_version WHERE lesson_id = ? ORDER BY version_no", (first,)
        )
    ]
    assert statuses == ["rejected", "rejected", "passed"]  # the retry wrote a new draft, not the stored one


def test_a_lesson_failing_every_attempt_fails_without_holding_back_the_next(
    rt: Runtime, llm: fakes.FakeLLM, db_path: Path
) -> None:
    llm.script["review"] = [fakes.review("fail")] * 500  # no lesson ever passes
    path_id = create(rt)
    for _ in range(12):
        _due_now(db_path)
        drain(rt)
    lessons = lessons_of(rt, path_id)
    assert len(lessons) > 3  # more than the buffer holds
    # each failed lesson made room for the next: none is left planned behind a failure
    assert [x["state"] for x in lessons] == ["failed"] * len(lessons)
    failed = [j for j in rt.service.path_view(path_id)["jobs"] if j["status"] == "failed"]
    assert failed and all("attempt 3 of 3" in j["error"] for j in failed)


def test_a_wrong_key_is_caught_by_blind_solve(rt: Runtime, llm: fakes.FakeLLM, db_path: Path) -> None:
    """The first lesson's practice items are blind-solved in one call; its first answer disagrees with the key,
    so that item alone is rejected and written again, and the retry is checked in a call of its own."""

    def first_wrong(request: Any) -> dict[str, Any]:
        reply: dict[str, Any] = llm.default("blind_batch", request)
        return reply | {"item_1": fakes.blind("z")}

    llm.script["blind_batch"] = [first_wrong]
    create(rt)
    c = sqlite3.connect(db_path)
    histories: dict[str, list[str]] = {}
    for code, status in c.execute(
        "SELECT i.code, v.status FROM item_version v JOIN item i ON i.id = v.item_id ORDER BY i.code, v.version_no"
    ):
        histories.setdefault(code, []).append(status)
    redone = [h for h in histories.values() if h != ["passed"]]
    assert redone == [["rejected", "passed"]]
    batches = [r for s, r in llm.calls if s == "blind_batch"]
    first = batches[0].messages[0].content
    assert first.count('"n":') >= 2  # several items in the one call
    assert batches[1].messages[0].content.count('"n":') == 1  # only the rejected one again


def test_invalid_output_is_repaired_once(rt: Runtime, llm: fakes.FakeLLM) -> None:
    llm.script["lesson"] = [fakes.lesson(words=100)]
    create(rt)
    lesson_calls = [r for s, r in llm.calls if s == "lesson"]
    assert "words; write between" in lesson_calls[1].messages[-1].content


def test_a_repeated_stage_is_served_from_cache(rt: Runtime, llm: fakes.FakeLLM, db_path: Path) -> None:
    path_id = create(rt)
    first = lessons_of(rt, path_id)[0]
    c = sqlite3.connect(db_path)
    c.execute("UPDATE lesson SET state = 'planned' WHERE id = ?", (first["id"],))
    c.commit()
    before = len(llm.calls)
    rt.service.request_lesson(first["id"])
    drain(rt)
    assert len(llm.calls) == before  # same inputs, same prompts: every stage hits the cache
    assert (
        c.execute("SELECT count(*) FROM stage_run WHERE cache_hit_of_stage_run_id IS NOT NULL").fetchone()[0]
        >= 2
    )


def test_the_budget_cap_pauses_generation(rt: Runtime, llm: fakes.FakeLLM) -> None:
    rt.service.put_setting("budget.cap_usd_month", 0.0005, "installation")
    _, job = rt.service.create_path(PathForm(title="SQL", subject="SQL", goal="joins"))
    rt.service.writer.run(
        lambda c: c.execute(
            "INSERT INTO budget_entry VALUES (?, NULL, NULL, 'openrouter', NULL, 1, 1, 0, 600, 'USD', NULL, 0, ?)",
            (new_id(), clock.now()),
        )
    )
    rt.worker.run_once()
    assert rt.service.job(job)["status"] == "waiting_resource" and llm.calls == []


def test_custom_instructions_make_the_lessons_personal(
    rt: Runtime, llm: fakes.FakeLLM, db_path: Path
) -> None:
    create(rt, custom_instructions="Use football examples")
    tree_prompt = llm.calls[0][1].messages[-1].content
    assert "<learner_input>" in tree_prompt and "Use football examples" in tree_prompt
    c = sqlite3.connect(db_path)
    assert {r[0] for r in c.execute("SELECT personal_inputs FROM lesson_version")} == {1}
    assert {r[0] for r in c.execute("SELECT data_class FROM stage_run WHERE stage != 'blind_solve'")} == {"F"}


def test_estimate_uses_profiles_and_prices(rt: Runtime) -> None:
    e = rt.service.estimate(20)
    assert e.low_usd > 0 and e.high_usd > e.low_usd and not e.missing


def test_events_are_validated(rt: Runtime) -> None:
    device = rt.service.register_device("t", "t")
    bad = [
        IncomingEvent(id="not-uuid", type="lesson.started", device_at=clock.now(), tz="UTC", payload={}),
        event("assessment.response_graded", {}),
        event("skill.test_result", {}),
        IncomingEvent(id=new_id(), type="lesson.started", device_at=clock.now(), tz="Mars/Base", payload={}),
        event("lesson.started", {"lesson_version_id": new_id(), "seconds": 3}),
    ]
    out = rt.service.ingest(device, bad)
    assert len(out["rejected"]) == 5 and out["accepted"] == []
    assert "FOREIGN KEY" in json.dumps(out["rejected"])


class Crash(BaseException):
    """The process dies mid-stage (an OOM kill, a reboot): nothing below the worker catches it."""


def test_a_job_cut_short_by_a_crash_resumes_at_startup(db_path: Path, llm: fakes.FakeLLM) -> None:
    rt = start(db_path, {"openrouter": llm}, NoPrices(), worker=False)
    for role in ("generator", "reviewer", "grader", "utility"):
        rt.service.bind(role, "openrouter", "deepseek/deepseek-v4-pro")
    path_id, _ = rt.service.create_path(PathForm(title="SQL", subject="SQL for analysts", goal="Write joins"))

    def crash(_: Any) -> Any:
        raise Crash

    llm.script["review"] = [crash]
    with pytest.raises(Crash):
        drain(rt)
    rt.close()
    c = sqlite3.connect(db_path)
    (job,) = c.execute("SELECT id FROM generation_job WHERE status = 'running'").fetchall()

    rt = start(db_path, {"openrouter": llm}, NoPrices(), worker=False)
    try:
        assert c.execute("SELECT count(*) FROM generation_job WHERE status = 'running'").fetchone()[0] == 0
        drain(rt)
        assert lessons_of(rt, path_id)[0]["state"] == "ready"
        runs = c.execute(
            "SELECT stage, status, cache_hit_of_stage_run_id IS NOT NULL FROM stage_run WHERE job_id = ? ORDER BY rowid",
            job,
        ).fetchall()
        assert ("review", "failed", 0) in runs  # the stage the crash cut short, run again
        assert ("lesson_body", "succeeded", 1) in runs  # the finished draft is a cache hit, not written again
    finally:
        rt.close()


def test_settings_show_the_version_behind_an_alias(rt: Runtime, db_path: Path) -> None:
    """A CLI alias (`opus`) is shown with the version it last ran, from the ledger (0.8.1)."""
    create(rt)
    assert rt.service.resolved_models() == {}  # the scripted model answers with the name it was asked for
    c = sqlite3.connect(db_path)
    c.execute(
        "UPDATE stage_run SET model_resolved = 'deepseek-v4-pro-0612' WHERE rowid = (SELECT max(rowid) FROM stage_run "
        "WHERE model_requested = 'deepseek/deepseek-v4-pro' AND status = 'succeeded')"
    )
    c.commit()
    assert rt.service.resolved_models() == {
        ("openrouter", "deepseek/deepseek-v4-pro"): "deepseek-v4-pro-0612"
    }


def test_a_failed_lesson_is_accepted_with_the_reviewers_notes(
    rt: Runtime, llm: fakes.FakeLLM, db_path: Path
) -> None:
    llm.script["review"] = [fakes.review("fail")] * 500  # no lesson ever passes
    path_id = create(rt)
    for _ in range(4):
        _due_now(db_path)
        drain(rt)
    refs = [x for b in rt.service.path_view(path_id)["branches"] for s in b["skills"] for x in s["lessons"]]
    failed = next(x for x in refs if x["state"] == "failed")
    assert failed["has_draft"]
    assert rt.service.lesson_view(failed["id"])["review_notes"] is None

    rt.service.accept_lesson_draft(failed["id"])
    drain(rt)
    lesson = rt.service.lesson_view(failed["id"])
    assert lesson["state"] == "ready" and lesson["body"]
    assert lesson["review_notes"] == [
        {
            "severity": "major",
            "where": "b2",
            "claim": "joins drop rows",
            "correction": "inner joins drop unmatched rows",
        }
    ]
    assert lesson["practice_items"] > 0  # its practice is written as for any published lesson
    with pytest.raises(Conflict):
        rt.service.accept_lesson_draft(failed["id"])  # only a failed lesson


def test_a_deep_path_for_several_reasons_is_planned_long(rt: Runtime, llm: fakes.FakeLLM) -> None:
    path_id = create(rt, goal_types=["exam", "practical"], depth="deep")
    prompt = next(r for s, r in llm.calls if s == "tree").messages[-1].content
    assert "80 to 120 lessons in total" in prompt and "Goal type: exam + practical" in prompt
    with rt.readers.connection() as c:
        row = c.execute("SELECT goal_type, extensions FROM path WHERE id = ?", (path_id,)).fetchone()
    assert row[0] == "exam"  # the first reason, for packages and older versions
    assert json.loads(row[1])["yuo"]["plan"] == {"depth": "deep", "goal_types": ["exam", "practical"]}


def test_a_standard_path_aims_for_dozens_of_lessons(rt: Runtime, llm: fakes.FakeLLM) -> None:
    create(rt)
    prompt = next(r for s, r in llm.calls if s == "tree").messages[-1].content
    assert "40 to 70 lessons in total" in prompt and "Goal type: understanding." in prompt
