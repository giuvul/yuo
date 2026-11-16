"""A 10-lesson path studied over a simulated week, on a scripted model, plus the
learning-loop rules: unlocks, skill tests and remedial lessons, the review queue and its cap, mastery
with assisted answers, streaks with grace days, the buffer, placement, model grading and contests,
lesson requests, notes, and projections that rebuild to the same state."""

import itertools
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests import fakes
from tests.integration.test_slice import NoPrices, drain, lessons_of
from yuo.app.forms import PathForm
from yuo.core import clock
from yuo.core.ids import new_id
from yuo.core.llm import Role
from yuo.learning import projections as pj
from yuo.learning.events import IncomingEvent
from yuo.main import Runtime, start

START = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)  # a Monday


class Clock:
    def __init__(self) -> None:
        self.at = START

    def __call__(self) -> datetime:
        return self.at

    def advance(self, **kw: float) -> None:
        self.at += timedelta(**kw)


@pytest.fixture
def now() -> Iterator[Clock]:
    c = Clock()
    clock.set_source(c)
    yield c
    clock.set_source(None)


@pytest.fixture
def llm() -> fakes.FakeLLM:
    return fakes.FakeLLM()


@pytest.fixture
def rt(db_path: Path, llm: fakes.FakeLLM, now: Clock) -> Iterator[Runtime]:
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


class Learner:
    """Drives the service like the web client: events through the outbox, answers from the views."""

    def __init__(self, rt: Runtime, llm: fakes.FakeLLM) -> None:
        self.rt, self.llm = rt, llm
        self.device = rt.service.register_device("sim", "pytest")

    def send(self, kind: str, payload: dict[str, Any], eid: str | None = None) -> dict[str, Any]:
        e = IncomingEvent(id=eid or new_id(), type=kind, device_at=clock.now(), tz="UTC", payload=payload)
        out = self.rt.service.ingest(self.device, [e])
        assert out["rejected"] == {}, out["rejected"]
        return out

    def take(self, assessment: dict[str, Any], *, right: bool = True, hint: bool = False) -> dict[str, Any]:
        attempt = new_id()
        self.send(
            "attempt.started",
            {
                "attempt_id": attempt,
                "assessment_id": assessment["assessment_id"],
                "purpose": assessment["purpose"],
            },
        )
        grades = {}
        for item in assessment["items"]:
            if hint and item["type"] != "flashcard":
                self.rt.service.hint(item["item_version_id"], 1)
                self.send(
                    "item.support_shown",
                    {
                        "item_version_id": item["item_version_id"],
                        "attempt_id": attempt,
                        "kind": "hint",
                        "level": 1,
                    },
                )
            answer = (
                fakes.answer_for(item, self.llm)
                if right
                else ("z" if item["type"] == "mcq" else 1 if item["type"] == "flashcard" else [])
            )
            rid = new_id()
            out = self.send(
                "assessment.response_given",
                {
                    "attempt_id": attempt,
                    "item_version_id": item["item_version_id"],
                    "answer": answer,
                    "ms_to_answer": 3000,
                },
                rid,
            )
            grades[rid] = out["graded"][rid]
        out = self.send("attempt.finished", {"attempt_id": attempt, "outcome": "finished"})
        return {"grades": grades, "outcome": out["outcomes"].get(attempt)}

    def study(self, lesson_id: str) -> None:
        lv = self.rt.service.lesson_view(lesson_id)
        self.send("lesson.started", {"lesson_version_id": lv["version_id"], "seconds": 0})
        self.send("lesson.completed", {"lesson_version_id": lv["version_id"], "seconds": 600})
        self.take(self.rt.service.start_practice(lesson_id))


def progress(rt: Runtime, path_id: str) -> dict[str, Any]:
    return rt.service.progress(path_id)


def skill_states(rt: Runtime, path_id: str) -> list[str]:
    view = rt.service.path_view(path_id)
    prog = progress(rt, path_id)["skills"]
    return [prog[s["id"]]["state"] for b in view["branches"] for s in b["skills"]]


def test_a_ten_lesson_path_over_a_simulated_week(
    rt: Runtime, llm: fakes.FakeLLM, now: Clock, db_path: Path
) -> None:
    llm.script["tree"] = [fakes.tree(skills_per_branch=5)]  # 10 skills in a chain, one lesson each
    path_id, _ = rt.service.create_path(PathForm(title="SQL", subject="SQL", goal="joins"))
    drain(rt)
    me = Learner(rt, llm)
    view = rt.service.path_view(path_id)
    skills = [s for b in view["branches"] for s in b["skills"]]
    assert len(skills) == 10 and len(lessons_of(rt, path_id)) == 10
    assert skill_states(rt, path_id)[:2] == ["available", "locked"]
    rt.service.put_setting("reviews.max_per_day", 2, "learner", rt.service.ensure_learner())

    seen_states: list[list[str]] = []
    reviews_done = 0
    for day in range(7):
        if day == 4:  # Friday off: one grace day keeps the streak
            now.advance(days=1)
            continue
        drain(rt)
        due = rt.service.due_reviews(path_id)
        assert len(due["item_version_ids"]) <= 2  # the daily cap
        if due["item_version_ids"]:
            me.take(rt.service.start_reviews(path_id))
            reviews_done += 1
            assert rt.service.due_reviews(path_id)["allowed_today"] <= 2 - min(
                2, len(due["item_version_ids"])
            )
        for _ in range(2 if day != 2 else 1):  # two skills a day
            states = skill_states(rt, path_id)
            if "available" not in states and "in_progress" not in states:
                break
            idx = next(i for i, st in enumerate(states) if st in ("available", "in_progress"))
            lesson = next(
                x for x in lessons_of(rt, path_id) if x["code"].startswith(skills[idx]["code"] + ".l")
            )
            assert lesson["state"] == "ready", f"day {day}: the buffer did not have the lesson ready"
            me.study(lesson["id"])
            test = rt.service.start_skill_test(skills[idx]["id"])
            if "job_id" in test:
                drain(rt)
                test = rt.service.start_skill_test(skills[idx]["id"])
            fail_once = day == 2
            result = me.take(test, right=not fail_once)["outcome"]
            assert result["passed"] is (not fail_once)
            if fail_once:  # A remedial lesson is queued, written, studied, and the test retaken
                drain(rt)
                remedial = [x for x in lessons_of(rt, path_id) if ".remedial" in x["code"]]
                assert remedial and remedial[0]["state"] == "ready"
                me.study(remedial[0]["id"])
                assert me.take(rt.service.start_skill_test(skills[idx]["id"]))["outcome"]["passed"]
            drain(rt)
        seen_states.append(skill_states(rt, path_id))
        now.advance(days=1)

    # unlocks are monotonic: a skill never goes back to locked
    for before, after in itertools.pairwise(seen_states):
        for a, b in zip(before, after, strict=True):
            assert not (a != "locked" and b == "locked")
    final = skill_states(rt, path_id)
    assert final.count("mastered") >= 9
    assert reviews_done >= 3  # FSRS brought earlier items back on later days

    p = progress(rt, path_id)
    assert p["streak"] == 6 and p["xp_total"] > 0  # six study days in a row with Friday covered by grace
    assert {a["key"] for a in p["achievements"]} >= {"first_lesson", "first_mastery", "perfect_test"}
    assert all(b["level"] >= 1 for b in p["branches"])

    # projections are a pure function of the events: a full rebuild reproduces them exactly
    snapshot = _projections(db_path)
    learner = rt.service.ensure_learner()
    rt.service.writer.run(lambda c: pj.rebuild_learner(c, learner, rt.service.scheduler, pj.Settings()))
    assert _projections(db_path) == snapshot


def _projections(db: Path) -> dict[str, list[tuple[Any, ...]]]:
    c = sqlite3.connect(db)
    out = {}
    for table, cols in (
        ("response", "response_event_id, help_kind, hint_depth, score, grading_method"),
        ("review_state", "item_id, state, due_at, last_review_at"),
        ("skill_progress", "skill_id, state, mastery, evidence_count"),
        ("xp_daily", "learning_day, xp, sessions, streak_len, grace_used"),
        ("attempt", "id, finished_at, outcome, score"),
        ("achievement", "key, unlocked_at"),
    ):
        out[table] = sorted(c.execute(f"SELECT {cols} FROM {table}").fetchall(), key=repr)
    return out


def test_assisted_success_counts_less_towards_mastery(rt: Runtime, llm: fakes.FakeLLM, db_path: Path) -> None:
    """Every response carries its help level; hints lower the weight of a success."""
    path_id, _ = rt.service.create_path(PathForm(title="SQL", subject="SQL", goal="joins"))
    drain(rt)
    me = Learner(rt, llm)
    first = lessons_of(rt, path_id)[0]
    me.take(rt.service.start_practice(first["id"]), hint=True)
    c = sqlite3.connect(db_path)
    helped = c.execute("SELECT mastery FROM skill_progress").fetchone()[0]
    assert {r[0] for r in c.execute("SELECT help_kind FROM response")} == {
        "hint",
        "none",
    }  # flashcards: no hints
    me.take(rt.service.start_practice(first["id"]))
    unhelped_gain = c.execute("SELECT mastery FROM skill_progress").fetchone()[0] - helped
    assert unhelped_gain > 0 and helped < 0.5


def test_placement_marks_known_skills_and_unlocks_the_next(rt: Runtime, llm: fakes.FakeLLM) -> None:
    path_id, _ = rt.service.create_path(PathForm(title="SQL", subject="SQL", goal="joins"))
    drain(rt)
    started = rt.service.start_placement(path_id)
    assert "job_id" in started
    drain(rt)
    placement = rt.service.start_placement(path_id)
    me = Learner(rt, llm)
    skills = [s["id"] for b in rt.service.path_view(path_id)["branches"] for s in b["skills"]]
    assert len(placement["items"]) == 2 * len(skills)
    out = me.take(placement)["outcome"]
    assert set(out["placed"].values()) == {"mastered"}
    assert set(skill_states(rt, path_id)) == {"mastered"}


def test_the_practice_mix_rotates_along_the_path_not_inside_a_skill(rt: Runtime, llm: fakes.FakeLLM) -> None:
    path_id, _ = rt.service.create_path(
        PathForm(title="SQL", subject="SQL", goal="joins")
    )  # 1 lesson per skill
    drain(rt)
    ready = [x for x in lessons_of(rt, path_id) if x["state"] == "ready"]
    mixes = [[i["type"] for i in rt.service.start_practice(x["id"])["items"]] for x in ready[:3]]
    assert mixes == [
        ["mcq", "cloze", "flashcard"],
        ["mcq", "multi", "flashcard"],
        ["mcq", "ordering", "flashcard", "short_answer"],
    ]


def test_short_answers_are_graded_by_the_grader_and_can_be_contested(
    rt: Runtime, llm: fakes.FakeLLM, db_path: Path
) -> None:
    llm.script["tree"] = [fakes.tree(skills_per_branch=2, lessons_per_skill=3)]
    path_id, _ = rt.service.create_path(PathForm(title="SQL", subject="SQL", goal="joins"))
    drain(rt)
    # the practice mix adds a short answer to every third lesson of the path: find one that is ready
    lesson = next(
        x
        for x in lessons_of(rt, path_id)
        if x["state"] == "ready"
        and any(i["type"] == "short_answer" for i in rt.service.start_practice(x["id"])["items"])
    )
    practice = rt.service.start_practice(lesson["id"])
    item = next(i for i in practice["items"] if i["type"] == "short_answer")
    me = Learner(rt, llm)
    attempt, rid = new_id(), new_id()
    me.send(
        "attempt.started",
        {"attempt_id": attempt, "assessment_id": practice["assessment_id"], "purpose": "practice"},
    )
    out = me.send(
        "assessment.response_given",
        {
            "attempt_id": attempt,
            "item_version_id": item["item_version_id"],
            "answer": "It keeps all left rows.",
            "ms_to_answer": 9000,
        },
        rid,
    )
    assert out["graded"][rid] == {"pending": True}
    drain(rt)  # the grade job runs the grader (role `grader`)
    with rt.service.readers.connection() as rc:
        grade = rt.service.existing_grade(rc, rid)
    assert grade is not None and grade["score"] == pytest.approx(2 / 3) and "rationale" in grade
    c = sqlite3.connect(db_path)
    grade_event = c.execute(
        "SELECT id FROM learning_event WHERE type = 'assessment.response_graded'"
    ).fetchone()[0]
    llm.grade_met = [True, True]
    me.send(
        "assessment.grade_contested",
        {
            "response_event_id": rid,
            "grade_event_id": grade_event,
            "reason_text": "I also said unmatched rows get nulls",
        },
    )
    drain(rt)
    reasons = [
        r[0]
        for r in c.execute(
            "SELECT payload ->> '$.reason' FROM learning_event WHERE type = "
            "'assessment.response_graded' ORDER BY server_seq"
        )
    ]
    assert reasons == ["initial", "contest_upheld"]
    assert c.execute("SELECT score FROM response WHERE response_event_id = ?", (rid,)).fetchone()[0] == 1.0
    contest_prompt = [r for s, r in llm.calls if s == "grade"][-1].messages[-1].content
    assert "<learner_input>I also said" in contest_prompt and "<learner_answer>" in contest_prompt


def test_a_lesson_request_is_placed_in_the_tree_and_generated(
    rt: Runtime, llm: fakes.FakeLLM, db_path: Path
) -> None:
    path_id, _ = rt.service.create_path(PathForm(title="SQL", subject="SQL", goal="joins"))
    drain(rt)
    req = rt.service.request(path_id, "Explain anti-joins with NOT EXISTS", [])
    drain(rt)
    c = sqlite3.connect(db_path)
    status, lesson_id = c.execute(
        "SELECT status, lesson_id FROM lesson_request WHERE id = ?", (req["request_id"],)
    ).fetchone()
    assert status == "done"
    kind, state, personal = c.execute(
        "SELECT l.kind, l.state, v.personal_inputs FROM lesson l LEFT JOIN lesson_version v ON v.id = "
        "l.current_version_id WHERE l.id = ?",
        (lesson_id,),
    ).fetchone()
    assert (kind, state, personal) == ("requested", "ready", 1)
    lesson_prompt = [r for s, r in llm.calls if s == "lesson"][-1].messages[-1].content
    assert "asked for this lesson" in lesson_prompt and "anti-joins" in lesson_prompt
    place_prompt = next(r for s, r in llm.calls if s == "place").messages[-1].content
    assert "<learner_input>\nExplain anti-joins" in place_prompt


def test_notes_on_a_lesson(rt: Runtime, llm: fakes.FakeLLM) -> None:
    path_id, _ = rt.service.create_path(PathForm(title="SQL", subject="SQL", goal="joins"))
    drain(rt)
    lesson = lessons_of(rt, path_id)[0]
    lv = rt.service.lesson_view(lesson["id"])
    nid = rt.service.add_note("Ask about NULLs", lesson_version_id=lv["version_id"], bid="b2")
    rt.service.edit_note(nid, "Ask about NULL handling")
    assert [(n["text"], n["bid"]) for n in rt.service.notes(lesson["id"])] == [
        ("Ask about NULL handling", "b2")
    ]
    rt.service.delete_note(nid)
    assert rt.service.notes(lesson["id"]) == []


def test_completing_lessons_keeps_the_buffer_full(rt: Runtime, llm: fakes.FakeLLM) -> None:
    llm.script["tree"] = [fakes.tree(skills_per_branch=3)]
    path_id, _ = rt.service.create_path(PathForm(title="SQL", subject="SQL", goal="joins"))
    drain(rt)
    me = Learner(rt, llm)
    done: set[str] = set()
    for _ in range(3):
        nxt = next(x for x in lessons_of(rt, path_id) if x["state"] == "ready" and x["id"] not in done)
        done.add(nxt["id"])
        lv = rt.service.lesson_view(nxt["id"])
        me.send("lesson.completed", {"lesson_version_id": lv["version_id"], "seconds": 300})
        drain(rt)
    states = [x["state"] for x in lessons_of(rt, path_id)]
    assert states.count("ready") == 6  # three done, three ahead


def test_mastery_decays_when_reviews_are_overdue(rt: Runtime, llm: fakes.FakeLLM, now: Clock) -> None:
    """A mastered skill shows needs_review once its items are likely forgotten; off keeps mastered."""
    path_id, _ = rt.service.create_path(PathForm(title="SQL", subject="SQL", goal="joins"))
    drain(rt)
    me = Learner(rt, llm)
    first = lessons_of(rt, path_id)[0]
    skill = rt.service.path_view(path_id)["branches"][0]["skills"][0]["id"]
    me.study(first["id"])
    test = rt.service.start_skill_test(skill)
    drain(rt)
    assert me.take(rt.service.start_skill_test(skill))["outcome"]["passed"]
    assert progress(rt, path_id)["skills"][skill]["state"] == "mastered"
    now.advance(days=120)
    assert progress(rt, path_id)["skills"][skill]["state"] == "needs_review"
    rt.service.put_setting("mastery.decay", False, "learner", rt.service.ensure_learner())
    assert progress(rt, path_id)["skills"][skill]["state"] == "mastered"
    assert "job_id" in test


def test_flashcards_flip_before_rating_and_test_outcomes_survive_a_lost_reply(
    rt: Runtime, llm: fakes.FakeLLM
) -> None:
    path_id, _ = rt.service.create_path(PathForm(title="SQL", subject="SQL", goal="joins"))
    drain(rt)
    first = lessons_of(rt, path_id)[0]
    practice = rt.service.start_practice(first["id"])
    card = next(i for i in practice["items"] if i["type"] == "flashcard")
    assert rt.service.reveal(card["item_version_id"])["back"] == "Only matching rows."
    with pytest.raises(LookupError):
        rt.service.reveal(practice["items"][0]["item_version_id"])  # not a flashcard: no peeking
    skill = rt.service.path_view(path_id)["branches"][0]["skills"][0]["id"]
    rt.service.start_skill_test(skill)
    drain(rt)
    test = rt.service.start_skill_test(skill)
    me = Learner(rt, llm)
    attempt = new_id()
    me.send(
        "attempt.started",
        {"attempt_id": attempt, "assessment_id": test["assessment_id"], "purpose": "skill_test"},
    )
    for item in test["items"]:
        me.send(
            "assessment.response_given",
            {
                "attempt_id": attempt,
                "item_version_id": item["item_version_id"],
                "answer": fakes.answer_for(item, llm),
                "ms_to_answer": 1000,
            },
        )
    finished = new_id()
    first_reply = me.send("attempt.finished", {"attempt_id": attempt, "outcome": "finished"}, finished)
    retry = me.rt.service.ingest(
        me.device,
        [
            IncomingEvent(
                id=finished,
                type="attempt.finished",
                device_at=clock.now(),
                tz="UTC",
                payload={"attempt_id": attempt, "outcome": "finished"},
            )
        ],
    )
    assert retry["duplicates"] == [finished]
    assert (
        retry["outcomes"][attempt] == first_reply["outcomes"][attempt]
        and retry["outcomes"][attempt]["passed"]
    )


def test_a_paths_personal_data_is_erased_and_the_path_starts_over(
    rt: Runtime, llm: fakes.FakeLLM, db_path: Path
) -> None:
    """Progress, answers, the level check and notes go; the path, its tree and its shared lessons stay,
    and the path is studied again from the start."""
    path_id, _ = rt.service.create_path(PathForm(title="SQL", subject="SQL", goal="joins"))
    drain(rt)
    me = Learner(rt, llm)
    first = lessons_of(rt, path_id)[0]
    fresh = skill_states(rt, path_id)
    me.study(first["id"])
    rt.service.add_note(
        "Ask about NULLs", lesson_version_id=rt.service.lesson_view(first["id"])["version_id"]
    )
    assert skill_states(rt, path_id) != fresh
    # queued work is cancelled: those lessons go back to planned, the written ones stay
    ready = {
        lesson["id"]: "planned" if lesson["state"] == "queued" else lesson["state"]
        for lesson in lessons_of(rt, path_id)
    }
    assert "ready" in ready.values()

    counts = rt.service.erasure.path_personal(path_id)

    assert counts["learning_event"] > 0 and counts["note"] == 1 and counts["assessment"] > 0
    assert "lesson_version" not in counts  # written from the path's description only: shared content
    assert [p["id"] for p in rt.service.paths()] == [path_id]
    assert {lesson["id"]: lesson["state"] for lesson in lessons_of(rt, path_id)} == ready
    assert skill_states(rt, path_id) == fresh
    assert rt.service.level_check(path_id)["status"] == "none"
    c = sqlite3.connect(db_path)
    for table in ("review_state", "response", "attempt", "assessment", "note"):
        assert c.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table
    assert c.execute("SELECT kind FROM erasure_record").fetchall() == [("path_personal",)]
    me.study(first["id"])  # studied again from the start
    assert skill_states(rt, path_id) != fresh


def test_a_path_is_not_erased_while_something_is_written_for_it(rt: Runtime, db_path: Path) -> None:
    path_id, _ = rt.service.create_path(PathForm(title="SQL", subject="SQL", goal="joins"))
    drain(rt)
    rt.writer.run(
        lambda c: c.execute(
            "UPDATE generation_job SET status = 'running' WHERE id = "
            "(SELECT id FROM generation_job ORDER BY created_at DESC LIMIT 1)"
        )
    )
    with pytest.raises(LookupError, match="being written"):
        rt.service.erasure.path_personal(path_id)


def test_the_video_watch_history_is_erased(rt: Runtime, db_path: Path) -> None:
    assert rt.service.erasure.video_history() == {}
    c = sqlite3.connect(db_path)
    assert c.execute("SELECT kind, counts FROM erasure_record").fetchall() == [("video_history", "{}")]
