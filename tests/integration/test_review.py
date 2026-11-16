"""The question bank per lesson, memory per objective, sessions with answer-until-correct
feedback, the session builder, and projections that rebuild to the same state."""

import itertools
from pathlib import Path
from typing import Any

import pytest

from tests import fakes
from tests.integration.test_slice import drain, lessons_of
from tests.integration.test_study import Clock, Learner, _projections, llm, now, rt  # noqa: F401
from yuo.app.forms import PathForm
from yuo.app.review import build_session, split_bank
from yuo.assessment import review_bank as rb
from yuo.core import clock
from yuo.core.ids import new_id
from yuo.learning import projections as pj
from yuo.main import Runtime


def _path(rt: Runtime, llm: fakes.FakeLLM) -> tuple[str, list[dict[str, Any]]]:  # noqa: F811
    path_id, _ = rt.service.create_path(PathForm(title="SQL", subject="SQL", goal="joins"))
    drain(rt)
    return path_id, lessons_of(rt, path_id)


def _bank(rt: Runtime, lesson_id: str) -> list[dict[str, Any]]:  # noqa: F811
    with rt.readers.connection() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT i.id, i.code, v.id AS version_id, v.payload, v.support, (SELECT count(*) FROM "
                "item_version_objective o WHERE o.item_version_id = v.id) AS objectives FROM item i JOIN item_version v "
                "ON v.id = i.current_version_id JOIN lesson_version lv ON lv.id = v.origin_lesson_version_id "
                "WHERE lv.lesson_id = ? AND i.extensions ->> '$.yuo.use' = 'review' ORDER BY i.code",
                (lesson_id,),
            )
        ]


class Reviewer(Learner):
    """Plays a review session: starts the attempt, answers right or wrong, asks for hints and the answer."""

    def begin(self, session: dict[str, Any]) -> str:
        self.attempt = session["attempt_id"] or new_id()
        if session["attempt_id"] is None:
            self.send(
                "attempt.started",
                {"attempt_id": self.attempt, "assessment_id": session["assessment_id"], "purpose": "review"},
            )
        return self.attempt

    def answer(self, item: dict[str, Any], *, right: bool, guessing: bool = False) -> dict[str, Any]:
        key = self.llm.solve(item["view"])["answer"]
        choice = key if right else next(o["id"] for o in item["view"]["options"] if o["id"] != key)
        rid = new_id()
        payload = {
            "attempt_id": self.attempt,
            "item_version_id": item["item_version_id"],
            "answer": choice,
            "ms_to_answer": 4000,
        } | ({"confidence": "guessing"} if guessing else {})
        return dict(self.send("assessment.response_given", payload, rid)["graded"][rid])

    def support(self, item: dict[str, Any], kind: str, level: int = 0) -> None:
        self.send(
            "item.support_shown",
            {
                "item_version_id": item["item_version_id"],
                "attempt_id": self.attempt,
                "kind": kind,
                "level": level,
            },
        )

    def finish(self) -> None:
        self.send("attempt.finished", {"attempt_id": self.attempt, "outcome": "finished"})


# --- the bank ------------------------------------------------------------------------------------


def test_a_ready_lesson_gets_its_review_questions(rt: Runtime, llm: fakes.FakeLLM) -> None:  # noqa: F811
    path_id, lessons = _path(rt, llm)
    ready = [x for x in lessons if x["state"] == "ready"]
    assert len(ready) == 3  # the buffer
    first, second = _bank(rt, ready[0]["id"]), _bank(rt, ready[1]["id"])
    assert len(first) == 8  # no partner lesson when the first lesson is written: single questions only
    assert len(second) == 11 and sum(q["objectives"] > 1 for q in second) == 3  # 8 single + 3 cross
    assert split_bank(11) == (8, 3)
    # an ordinary item: versioned, checked, published, never part of the lesson's practice set
    with rt.readers.connection() as c:
        checks = {
            r[0]
            for r in c.execute(
                "SELECT \"check\" FROM quality_check WHERE subject_version_id = ? AND verdict = 'pass'",
                (first[0]["version_id"],),
            )
        }
    assert checks == {"schema", "support_consistency", "leak", "answer_key"}
    practice = rt.service.start_practice(ready[0]["id"])
    assert {i["item_version_id"] for i in practice["items"]}.isdisjoint({q["version_id"] for q in first})
    assert rt.service.lesson_view(ready[0]["id"])["practice_items"] == len(practice["items"])
    # the path page does not list bank jobs as lesson work
    assert all(j["kind"] != "items" for j in rt.service.path_view(path_id)["jobs"])


def test_a_question_the_blind_solver_gets_wrong_is_dropped(rt: Runtime, llm: fakes.FakeLLM) -> None:  # noqa: F811
    _, lessons = _path(rt, llm)
    ready = [x for x in lessons if x["state"] == "ready"]
    before = len(_bank(rt, ready[0]["id"]))
    llm.wrong_blind = True
    rt.service.writer.run(lambda c: rt.service.queue_review_bank(c, ready[0]["id"], top_up=True))
    drain(rt)
    assert len(_bank(rt, ready[0]["id"])) == before  # nothing new was published
    with rt.readers.connection() as c:
        job = c.execute(
            "SELECT status, error FROM generation_job WHERE kind = 'items' ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    assert job[0] == "failed" and "no review question passed" in job[1]


def test_question_rules() -> None:
    own, partners = {"sql.a.o1"}, {"sql.b.o1"}
    ok = rb.ReviewQuestion.model_validate(fakes.bank_question(["sql.a.o1"]))
    assert rb.question_rules(ok, own, partners, []) == []

    def broken(**change: Any) -> list[str]:
        q = rb.ReviewQuestion.model_validate(fakes.bank_question(["sql.a.o1"]) | change)
        return rb.question_rules(q, own, partners, ["Which clause filters rows before grouping?"])

    long_key = [
        {"id": "a", "text": "An inner join"},
        {"id": "b", "text": "A cross join"},
        {"id": "c", "text": "A left join that starts from customers and keeps each of them"},
        {"id": "d", "text": "A self join"},
    ]
    assert any("longest" in p for p in broken(options=long_key))
    assert any(
        "hint 1 gives the answer away" in p
        for p in broken(hints=["Use a left join from customers.", "x", "y"])
    )
    leaky = [
        {"id": "a", "why": "Wrong: a left join from customers is needed."},
        {"id": "b", "why": "No."},
        {"id": "c", "why": "Yes."},
        {"id": "d", "why": "No."},
    ]
    assert any("rationale of option a names the right answer" in p for p in broken(rationales=leaky))
    assert any("unknown objective codes" in p for p in broken(objective_codes=["sql.zzz.o1"]))
    assert any("at least one objective of this lesson" in p for p in broken(objective_codes=["sql.b.o1"]))
    assert any("repeats" in p for p in broken(prompt="Which clause filters rows before grouping"))
    assert any("exactly three hints" in p for p in broken(hints=["one"]))
    refers = [
        {"id": i, "text": t}
        for i, t in zip("abcd", ["An inner join", "A cross join", "A left join", "Both a and b"], strict=True)
    ]
    assert any("refers to other options" in p for p in broken(options=refers))
    assert any("one rationale per option" in p for p in broken(rationales=leaky[1:]))
    # a few bad questions are dropped, many send the bank back for repair
    good = [fakes.bank_question(["sql.a.o1"]) for _ in range(8)]
    bad = fakes.bank_question(["sql.zzz.o1"])
    draft = rb.ReviewBankDraft.model_validate({"questions": [*good, bad]})
    assert rb.bank_rules(draft, own, partners, [], 8, 0) == []
    assert len(rb.keep(draft, own, partners, [])) == 8
    mostly_bad = rb.ReviewBankDraft.model_validate({"questions": [good[0], bad, bad | {"prompt": "Other?"}]})
    assert rb.bank_rules(mostly_bad, own, partners, [], 3, 0) != []


# --- sessions ------------------------------------------------------------------------------------


def test_a_review_session_end_to_end(rt: Runtime, llm: fakes.FakeLLM, now: Clock, db_path: Path) -> None:  # noqa: F811
    path_id, lessons = _path(rt, llm)
    me = Reviewer(rt, llm)
    ready = [x for x in lessons if x["state"] == "ready"]
    hub = rt.service.review_hub(path_id)
    assert hub["memory"] is None and hub["questions"] == 0 and hub["sizes"] == []  # nothing studied yet
    me.study(ready[0]["id"])
    me.study(ready[1]["id"])
    drain(rt)
    hub = rt.service.review_hub(path_id)
    # a completed lesson's objectives are in memory at once (a virtual first review), and its questions count
    assert hub["objectives"] == 2 and hub["memory"] > 0.99 and hub["questions"] >= 19 and 5 in hub["sizes"]
    now.advance(days=3)
    assert rt.service.review_hub(path_id)["memory"] < 0.99

    session = rt.service.start_review_session(path_id, 5)
    assert len(session["items"]) == 5 and session["attempt_id"] is None and session["reserves"]
    assert {len(i["view"]["options"]) for i in session["items"]} == {4}
    assert "answer" not in str(session["items"][0]["view"])
    # the same session comes back until it is finished
    assert rt.service.start_review_session(path_id, 10)["assessment_id"] == session["assessment_id"]
    attempt = me.begin(session)
    a, b, c_, d, e = session["items"]

    first = me.answer(a, right=True)
    assert (
        first["outcome"] == "first"
        and first["resolved"]
        and first["correct"]
        and len(first["rationales"]) == 4
    )

    wrong = me.answer(b, right=False)
    # staged: the tried option's rationale only; no key, no explanation, no other rationale
    assert wrong["outcome"] == "open" and not wrong["resolved"] and len(wrong["rationales"]) == 1
    assert "correct" not in wrong and "solution" not in wrong and "lesson_id" not in wrong
    assert rt.service.hint(b["item_version_id"], 2)["last"] is True
    with pytest.raises(LookupError):
        rt.service.hint(b["item_version_id"], 3)  # the third hint is not for review
    me.support(b, "hint", 1)
    second = me.answer(b, right=True)
    assert second["outcome"] == "second" and second["resolved"] and second["tries"] == 2

    assert not me.answer(c_, right=False)["resolved"]
    twice = me.answer(c_, right=False)
    assert twice["outcome"] == "revealed" and twice["correct"]  # two wrong tries reveal the answer
    rejected = rt.service.ingest(
        me.device,
        [
            fakes_event(
                {
                    "attempt_id": attempt,
                    "item_version_id": c_["item_version_id"],
                    "answer": "a",
                    "ms_to_answer": 1,
                }
            )
        ],
    )
    assert "already resolved" in next(iter(rejected["rejected"].values()))

    assert rt.service.review_feedback(attempt, d["item_version_id"])["outcome"] == "new"
    me.support(d, "solution")  # "Show answer"
    shown = rt.service.review_feedback(attempt, d["item_version_id"])
    assert shown["outcome"] == "revealed" and shown["correct"] and shown["lesson_id"]

    assert me.answer(e, right=True, guessing=True)["guessing"] is True

    # resuming before the end returns the states
    resumed = rt.service.start_review_session(path_id, 5)
    assert resumed["attempt_id"] == attempt
    assert [i["state"]["outcome"] for i in resumed["items"]] == [
        "first",
        "second",
        "revealed",
        "revealed",
        "first",
    ]

    me.finish()
    result = rt.service.review_result(attempt)
    assert (result["answered"], result["first_try"], result["second_try"], result["revealed"]) == (5, 2, 1, 2)
    assert result["xp"] == 10 + round(5 * 0.5) + 10  # first, second with a hint, guessed but right
    assert result["skills"] and all(s["after"] is not None for s in result["skills"])
    learner = rt.service.ensure_learner()
    with rt.readers.connection() as c:
        states = {
            r[0]: (r[1], r[2])
            for r in c.execute(
                "SELECT objective_id, reviews, lapses FROM objective_review_state WHERE learner_id = ?",
                (learner,),
            )
        }
        cards = c.execute(
            "SELECT count(*) FROM review_state rs JOIN item i ON i.id = rs.item_id WHERE i.extensions ->> '$.yuo.use' = 'review'"
        ).fetchone()[0]
    assert cards == 0  # review questions keep no card of their own
    assert all(reviews == 1 for reviews, _ in states.values())  # one review per objective per session
    assert sum(lapses for _, lapses in states.values()) >= 1  # a revealed answer is a lapse
    hub = rt.service.review_hub(path_id)
    assert (
        hub["open_session"] is None
        and hub["recent"][0]["answered"] == 5
        and hub["recent"][0]["first_try"] == 2
    )
    progress = rt.service.progress(path_id)
    assert "first_review" in {x["key"] for x in progress["achievements"]}

    # a finished session: the next one is new and avoids the questions just seen
    again = rt.service.start_review_session(path_id, 5)
    assert again["assessment_id"] != session["assessment_id"]
    assert {i["item_version_id"] for i in again["items"]}.isdisjoint(
        {i["item_version_id"] for i in session["items"]}
    )

    # projections are a pure function of the events
    snapshot = _projections(db_path)
    rt.service.writer.run(
        lambda c: pj.rebuild_learner(c, learner, rt.service.scheduler, rt.service._proj_settings(c, learner))
    )
    assert _projections(db_path) == snapshot


def fakes_event(payload: dict[str, Any]) -> Any:
    from yuo.learning.events import IncomingEvent

    return IncomingEvent(
        id=new_id(), type="assessment.response_given", device_at=clock.now(), tz="UTC", payload=payload
    )


def test_ratings_follow_the_session(rt: Runtime, llm: fakes.FakeLLM, now: Clock) -> None:  # noqa: F811
    assert pj.session_rating([]) is None
    first, second, revealed = pj.Outcome(right_on=1), pj.Outcome(right_on=2), pj.Outcome(revealed=True)
    for o in (first, second, revealed):
        o.tries.append(("e", "a", 1.0))
    guess = pj.Outcome(right_on=1, guessing=True, tries=[("e", "a", 1.0)])
    helped = pj.Outcome(right_on=1, hints=1, tries=[("e", "a", 1.0)])
    stuck = pj.Outcome(tries=[("e", "a", 0.0)])  # one wrong try, session ended (offline)
    assert pj.session_rating([first]) == 3
    assert pj.session_rating([first, first]) == 4  # sure and right on two questions
    assert pj.session_rating([first, second]) == 2
    assert pj.session_rating([first, guess]) == 2
    assert pj.session_rating([helped]) == 2
    assert pj.session_rating([first, revealed]) == 1
    assert pj.session_rating([stuck]) == 1


def test_reporting_a_question_retires_it(rt: Runtime, llm: fakes.FakeLLM, now: Clock) -> None:  # noqa: F811
    path_id, lessons = _path(rt, llm)
    me = Reviewer(rt, llm)
    lesson = next(x for x in lessons if x["state"] == "ready")
    me.study(lesson["id"])
    before = rt.service.review_hub(path_id)["questions"]
    rt.service.report_item(_bank(rt, lesson["id"])[0]["id"], "two right answers")
    assert rt.service.review_hub(path_id)["questions"] == before - 1


def test_review_settings_move_the_dates(rt: Runtime, llm: fakes.FakeLLM, now: Clock) -> None:  # noqa: F811
    _path_id, lessons = _path(rt, llm)
    me = Reviewer(rt, llm)
    me.study(next(x for x in lessons if x["state"] == "ready")["id"])

    def due() -> str:
        with rt.readers.connection() as c:
            return str(c.execute("SELECT due_at FROM objective_review_state").fetchone()[0])

    default = due()
    rt.service.put_learner_setting("review.desired_retention", 0.95, "learner", None)
    assert due() < default  # a higher retention brings the review forward


# --- the session builder (pure) --------------------------------------------------------------------


def _mem(oid: str, skill: str, r: float = 0.8, due: bool = False, lapses: int = 0) -> dict[str, Any]:
    return {"id": oid, "skill_id": skill, "retrievability": r, "due": due, "lapses": lapses}


def _q(n: int, skill: str, objectives: list[str], seen: str | None = None) -> dict[str, Any]:
    return {
        "version_id": f"v{n:03d}",
        "item_id": f"i{n}",
        "skill_id": skill,
        "objectives": sorted(objectives),
        "seen_at": seen,
    }


NOW = "2026-11-12T09:00:00.000Z"


def test_builder_caps_a_skill_and_interleaves() -> None:
    memory = [_mem("o1", "s1", 0.3, True), _mem("o2", "s2", 0.9), _mem("o3", "s3", 0.9)]
    items = [_q(n, "s1", ["o1"]) for n in range(10)] + [_q(20 + n, "s2", ["o2"]) for n in range(4)]
    items += [_q(40 + n, "s3", ["o3"]) for n in range(4)]
    picked, reserves = build_session(memory, items, 9, now=NOW)
    assert len(picked) == 9
    assert sum(i["skill_id"] == "s1" for i in picked) == 3  # a third of the session at most
    assert all(a["skill_id"] != b["skill_id"] for a, b in itertools.pairwise(picked))
    assert picked[0]["skill_id"] == "s1"  # the weakest objective leads
    # one unseen reserve per objective, none of them in the session
    assert {r["objectives"][0] for r in reserves} == {"o1", "o2", "o3"}
    assert {r["version_id"] for r in reserves}.isdisjoint({i["version_id"] for i in picked})
    assert build_session(memory, items, 9, now=NOW) == (picked, reserves)  # deterministic


def test_builder_prefers_unseen_and_skips_recent() -> None:
    memory = [_mem("o1", "s1", 0.5, True)]
    old, recent = "2026-11-01T09:00:00.000Z", "2026-11-11T20:00:00.000Z"
    items = [_q(1, "s1", ["o1"], recent), _q(2, "s1", ["o1"], old), _q(3, "s1", ["o1"])]
    picked, _ = build_session(memory, items, 2, now=NOW)
    assert [i["version_id"] for i in picked] == ["v003", "v002"]  # unseen, then the oldest; not yesterday's
    picked, _ = build_session(memory, items, 3, now=NOW)
    assert len(picked) == 3  # unless nothing else is left


def test_builder_asks_cross_questions_only_when_everything_is_learned() -> None:
    memory = [_mem("o1", "s1", 0.5, True), _mem("o2", "s2", 0.6)]
    singles = [_q(n, "s1", ["o1"]) for n in range(6)] + [_q(10 + n, "s2", ["o2"]) for n in range(6)]
    cross = [_q(30, "s2", ["o1", "o2"]), _q(31, "s2", ["o2", "o9"])]  # o9 is not learned
    picked, _ = build_session(memory, singles + cross, 8, now=NOW)
    ids = {i["version_id"] for i in picked}
    assert "v030" in ids and "v031" not in ids
    assert sum(len(i["objectives"]) > 1 for i in picked) <= 2  # about a quarter
    # a focus on one skill still needs every objective of a cross question learned somewhere in the path
    focus = [memory[1]]
    picked, _ = build_session(focus, singles + cross, 4, now=NOW, learned={"o1", "o2"})
    assert all("o2" in i["objectives"] for i in picked)
    assert build_session([], singles, 5, now=NOW) == ([], [])
    assert build_session(memory, singles, 0, now=NOW) == ([], [])
