"""On a scripted model: the layered leak control, sealed tests, streaming, queued
messages, proposals, memory, nudges, the priority lane and the event stream."""

import json
import sqlite3
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests import fakes
from tests.integration.test_slice import NoPrices, drain, lessons_of
from tests.integration.test_study import Clock, Learner
from yuo.app.broker import Broker
from yuo.app.forms import PathForm
from yuo.core import clock
from yuo.core.ids import new_id
from yuo.core.llm import LLMError, Role
from yuo.generation.lanes import Lane, Slots
from yuo.learning.events import IncomingEvent
from yuo.main import Runtime, start


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
        ("tutor", "qwen/qwen3.8-27b"),
    )
    for role, model in roles:
        r.service.bind(role, "openrouter", model)
    yield r
    r.close()


@pytest.fixture
def path(rt: Runtime) -> str:
    path_id, _ = rt.service.create_path(PathForm(title="SQL", subject="SQL", goal="joins"))
    drain(rt)
    return path_id


def ask(rt: Runtime, text: str, **ctx: Any) -> dict[str, Any]:
    sent = rt.service.send_message(new_id(), text, ctx)
    assert rt.service.run_tutor_turn()
    return reply_to(rt, sent["id"])


def reply_to(rt: Runtime, learner_message_id: str) -> dict[str, Any]:
    return next(
        m for m in rt.service.messages() if m["role"] == "tutor" and learner_message_id in m["answers"]
    )


def tutor_calls(llm: fakes.FakeLLM, stage: str = "tutor") -> list[Any]:
    return [r for s, r in llm.calls if s == stage]


def practice_attempt(rt: Runtime, me: Learner, lesson_id: str) -> tuple[str, dict[str, Any]]:
    practice = rt.service.start_practice(lesson_id)
    attempt = new_id()
    me.send(
        "attempt.started",
        {"attempt_id": attempt, "assessment_id": practice["assessment_id"], "purpose": "practice"},
    )
    return attempt, practice


def test_a_lesson_question_streams_and_is_ledgered(
    rt: Runtime, llm: fakes.FakeLLM, path: str, db_path: Path
) -> None:
    lesson = lessons_of(rt, path)[0]
    ctx = rt.service.tutor_context({"screen": "lesson", "lesson_id": lesson["id"]})
    assert ctx["policy"] == "lesson" and ctx["scope"] == "lesson" and not ctx["checked"]
    assert {c["kind"] for c in ctx["chips"]} >= {"path", "skill", "lesson", "memory"}
    seen = rt.service.broker.last_id
    reply = ask(rt, "Why does a join need a condition?", screen="lesson", lesson_id=lesson["id"])
    assert reply["status"] == "done" and reply["text"] == fakes.TUTOR_REPLY and reply["guard"] is None
    events = rt.service.broker.wait(seen, 0) or []
    deltas = "".join(e.data["text"] for e in events if e.kind == "tutor.delta")
    assert deltas == fakes.TUTOR_REPLY  # streamed in unchecked modes
    system = tutor_calls(llm)[0].messages[0].content
    assert "LESSON:" in system and "join" in system.lower()
    c = sqlite3.connect(db_path)
    assert (
        c.execute("SELECT count(*) FROM budget_entry WHERE message_id = ?", (reply["id"],)).fetchone()[0] == 1
    )
    assert (
        c.execute("SELECT purpose FROM egress_record WHERE message_id = ?", (reply["id"],)).fetchone()[0]
        == "tutor"
    )
    # the same thread next time, with the earlier turn as history
    ask(rt, "And a left join?", screen="lesson", lesson_id=lesson["id"])
    assert len(rt.service.conversations()) == 1
    history = [m.content for m in tutor_calls(llm)[1].messages[1:]]
    assert history[:2] == ["Why does a join need a condition?", fakes.TUTOR_REPLY]


def test_before_an_attempt_the_key_stays_out_and_guesses_get_the_template(
    rt: Runtime, llm: fakes.FakeLLM, path: str, db_path: Path
) -> None:
    me = Learner(rt, llm)
    lesson = lessons_of(rt, path)[0]
    attempt, practice = practice_attempt(rt, me, lesson["id"])
    mcq = practice["items"][0]
    ctx = {"screen": "practice", "attempt_id": attempt, "item_version_id": mcq["item_version_id"]}
    assert rt.service.tutor_context(ctx)["policy"] == "practice.before_attempt"

    guess = ask(rt, "Is it b?", **ctx)
    assert guess["template"] == "tutor.guess" and guess["guard"] == "template"
    assert tutor_calls(llm) == []  # the model never saw the guess

    help_ = ask(rt, "Where should I start?", **ctx)
    assert help_["guard"] == "checked" and help_["text"] == fakes.TUTOR_REPLY
    system = tutor_calls(llm)[0].messages[0].content
    assert "Answer key" not in system and "Worked solution" not in system
    assert "Hint ladder" in system and "CURRENT QUESTION" in system
    check = tutor_calls(llm, "leak_check")[0].messages[-1].content
    assert "Correct answer:" in check  # the checker sees the key, the tutor never does

    # The answer that follows counts as tutor-assisted
    rid = new_id()
    me.send(
        "assessment.response_given",
        {
            "attempt_id": attempt,
            "item_version_id": mcq["item_version_id"],
            "answer": fakes.answer_for(mcq, llm),
            "ms_to_answer": 9000,
        },
        rid,
    )
    c = sqlite3.connect(db_path)
    assert (
        c.execute("SELECT help_kind FROM response WHERE response_event_id = ?", (rid,)).fetchone()[0]
        == "tutor"
    )
    # after the attempt: the key and the learner's answer are in, nothing is checked
    after = ask(rt, "Why was that right?", **ctx)
    assert after["guard"] is None
    system = tutor_calls(llm)[-1].messages[0].content
    assert "Answer key" in system and "The learner answered" in system


def test_a_leaking_reply_is_withheld_and_an_unclear_check_fails_closed(
    rt: Runtime, llm: fakes.FakeLLM, path: str, db_path: Path
) -> None:
    me = Learner(rt, llm)
    attempt, practice = practice_attempt(rt, me, lessons_of(rt, path)[0]["id"])
    ctx = {
        "screen": "practice",
        "attempt_id": attempt,
        "item_version_id": practice["items"][0]["item_version_id"],
    }
    llm.script["tutor"] = ["The right one is the SELECT list.", "Try the WHERE clause first."]
    llm.script["leak_check"] = [{"leak": True}, "not json", "still not json"]
    blocked = ask(rt, "Just tell me which one", **ctx)
    assert blocked["guard"] == "blocked" and blocked["template"] == "tutor.blocked"
    assert "SELECT list" not in json.dumps(rt.service.messages())  # never shown, not even in the API
    c = sqlite3.connect(db_path)
    withheld = c.execute(
        "SELECT content ->> '$.withheld', leak_check FROM message WHERE id = ?", (blocked["id"],)
    )
    assert withheld.fetchone() == ("The right one is the SELECT list.", "fail")  # kept for the audit
    unclear = ask(rt, "What does the question mean?", **ctx)
    assert unclear["guard"] == "blocked"  # unparseable verdict after repair = leak


def test_an_open_skill_test_seals_the_tutor_on_every_screen(
    rt: Runtime, llm: fakes.FakeLLM, path: str
) -> None:
    me = Learner(rt, llm)
    lesson = lessons_of(rt, path)[0]
    skill = rt.service.path_view(path)["branches"][0]["skills"][0]["id"]
    test = rt.service.start_skill_test(skill)
    if "job_id" in test:
        drain(rt)
        test = rt.service.start_skill_test(skill)
    attempt = new_id()
    me.send(
        "attempt.started",
        {"attempt_id": attempt, "assessment_id": test["assessment_id"], "purpose": "skill_test"},
    )
    # the learner leaves the test screen and asks from the lesson: still the test policy, its own thread
    ctx = rt.service.tutor_context({"screen": "lesson", "lesson_id": lesson["id"]})
    assert ctx["policy"] == "test.locked" and ctx["sealed_by_open_test"] and ctx["scope"] == "attempt"
    assert {c["kind"] for c in ctx["chips"]} <= {"skill", "item"}  # no lesson, notes or memory
    reply = ask(rt, "Explain joins to me", screen="lesson", lesson_id=lesson["id"])
    assert reply["guard"] == "checked"
    system = tutor_calls(llm)[0].messages[0].content
    assert "LOCKED" in system and "LESSON:" not in system and "Answer key" not in system
    assert "remember about the learner" not in system
    # hints with cost is fixed when the test is assembled, not when the learner asks
    rt.service.put_setting("tutor.test_policy", "hints", "installation")
    assert rt.service.tutor_context({"screen": "test", "attempt_id": attempt})["policy"] == "test.locked"
    for item in test["items"]:
        me.send(
            "assessment.response_given",
            {
                "attempt_id": attempt,
                "item_version_id": item["item_version_id"],
                "answer": fakes.answer_for(item, llm),
                "ms_to_answer": 4000,
            },
        )
    me.send("attempt.finished", {"attempt_id": attempt, "outcome": "finished"})
    after = rt.service.tutor_context({"screen": "test", "attempt_id": attempt})
    assert after["policy"] == "test.debrief" and not after["sealed_by_open_test"]


def test_queued_messages_are_answered_together_and_can_be_edited_or_taken_back(
    rt: Runtime, llm: fakes.FakeLLM, path: str
) -> None:
    ctx = {"screen": "path", "path_id": path}
    a = rt.service.send_message(new_id(), "What is a join?", ctx)
    b = rt.service.send_message(new_id(), "And a key?", ctx)
    c = rt.service.send_message(new_id(), "Never mind", ctx)
    assert rt.service.edit_message(b["id"], "And a primary key?")["status"] == "queued"
    assert rt.service.withdraw_message(c["id"])["status"] == "withdrawn"
    assert rt.service.send_message(a["id"], "What is a join?", ctx)["duplicate"]  # outbox retry
    assert rt.service.run_tutor_turn() and not rt.service.run_tutor_turn()
    reply = reply_to(rt, a["id"])
    assert reply["answers"] == [a["id"], b["id"]]
    last = tutor_calls(llm)[0].messages[-1].content
    assert "several messages" in last and "1. What is a join?" in last and "2. And a primary key?" in last
    with pytest.raises(ValueError, match="queued"):
        rt.service.edit_message(a["id"], "too late")


def test_proposals_and_memory_come_from_the_actions_block(
    rt: Runtime, llm: fakes.FakeLLM, path: str, db_path: Path
) -> None:
    actions = {
        "proposal": {
            "kind": "add_lesson",
            "rationale": "You asked twice about NULLs.",
            "prompt": "NULL in joins",
        },
        "memory": [{"kind": "goal", "text": "Preparing for a data analyst interview"}],
    }
    llm.script["tutor"] = [f"Sure, NULLs are tricky.\n<actions>{json.dumps(actions)}</actions>"]
    seen = rt.service.broker.last_id
    reply = ask(rt, "I keep getting NULLs wrong, I have an interview soon", screen="path", path_id=path)
    assert (
        reply["text"] == "Sure, NULLs are tricky." and reply["proposal_id"] and len(reply["memory_ids"]) == 1
    )
    streamed = "".join(
        e.data["text"] for e in rt.service.broker.wait(seen, 0) or [] if e.kind == "tutor.delta"
    )
    assert "<actions>" not in streamed and "{" not in streamed  # the block never reaches the screen
    [prop] = rt.service.proposals(path)
    assert prop["status"] == "pending" and prop["kind"] == "add_lesson"
    me = Learner(rt, llm)
    me.send("tutor.proposal_decided", {"proposal_id": prop["id"], "decision": "accepted"})
    assert rt.service.proposals(path)[0]["status"] == "accepted"
    assert [r["prompt"] for r in rt.service.requests(path)] == ["NULL in joins"]
    again = me.rt.service.ingest(me.device, [fakes_event("tutor.proposal_decided", prop["id"])])
    assert "already decided" in next(iter(again["rejected"].values()))
    # memory is visible, editable, deletable, and goes into the next prompt
    [entry] = rt.service.memory()
    assert entry["source"] == "tutor" and entry["evidence_ref"] == {"kind": "message", "id": reply["id"]}
    rt.service.edit_memory(entry["id"], "Data analyst interview in December")
    ask(rt, "Quiz me", screen="path", path_id=path)
    assert "Data analyst interview in December" in tutor_calls(llm)[-1].messages[0].content
    rt.service.delete_memory(entry["id"])
    rt.service.put_setting("tutor.memory", False, "installation")
    llm.script["tutor"] = [f"Ok.<actions>{json.dumps(actions)}</actions>"]
    assert ask(rt, "Remember this", screen="path", path_id=path)["memory_ids"] == []
    assert rt.service.memory() == []


def fakes_event(kind: str, proposal_id: str) -> Any:
    return IncomingEvent(
        id=new_id(),
        type=kind,
        device_at=clock.now(),
        tz="UTC",
        payload={"proposal_id": proposal_id, "decision": "rejected"},
    )


def test_actions_are_ignored_where_the_policy_does_not_allow_them(
    rt: Runtime, llm: fakes.FakeLLM, path: str
) -> None:
    me = Learner(rt, llm)
    attempt, practice = practice_attempt(rt, me, lessons_of(rt, path)[0]["id"])
    llm.script["tutor"] = ['Think again.<actions>{"memory": [{"kind": "fact", "text": "x"}]}</actions>']
    reply = ask(
        rt,
        "help",
        screen="practice",
        attempt_id=attempt,
        item_version_id=practice["items"][0]["item_version_id"],
    )
    assert reply["text"] == "Think again." and reply["memory_ids"] == []


def test_nudges_follow_the_proactivity_caps(rt: Runtime, llm: fakes.FakeLLM, path: str, now: Clock) -> None:
    me = Learner(rt, llm)
    lesson = lessons_of(rt, path)[0]
    out = me.take(rt.service.start_practice(lesson["id"]), right=False)
    assert out  # the first wrong answers: one objective missed twice
    nudges = rt.service.nudges()
    assert [n["trigger"] for n in nudges] == ["repeated_error"] and nudges[0]["params"]["misses"] >= 2
    rt.service.decide_nudge(nudges[0]["id"], "dismiss")
    me.take(rt.service.start_practice(lesson["id"]), right=False)
    assert rt.service.nudges() == []  # within 10 minutes and once per trigger per session
    now.advance(hours=2)  # a new session
    me.take(rt.service.start_practice(lesson["id"]), right=False)
    [n] = rt.service.nudges()
    rt.service.decide_nudge(n["id"], "mute")
    learner = rt.service.ensure_learner()
    assert rt.service.setting("tutor.muted_triggers", {"learner": learner}) == ["repeated_error"]
    now.advance(hours=2)
    me.take(rt.service.start_practice(lesson["id"]), right=False)
    assert rt.service.nudges() == []
    rt.service.put_setting("tutor.muted_triggers", [], "learner", learner)
    rt.service.put_setting("tutor.proactivity", "off", "installation")
    now.advance(hours=2)
    me.take(rt.service.start_practice(lesson["id"]), right=False)
    assert rt.service.nudges() == []


def test_a_failed_reply_says_why_and_can_be_retried(rt: Runtime, llm: fakes.FakeLLM, path: str) -> None:
    llm.script["tutor"] = [LLMError("openrouter: rate limited", retryable=True, kind="quota")]
    sent = rt.service.send_message(new_id(), "Hello?", {"screen": "path", "path_id": path})
    rt.service.run_tutor_turn()
    failed = reply_to(rt, sent["id"])
    assert failed["status"] == "failed" and failed["error"] == "quota"
    assert rt.service.retry_reply(failed["id"])["requeued"][0]["status"] == "queued"
    rt.service.run_tutor_turn()
    assert [m["status"] for m in rt.service.messages() if m["role"] == "tutor"] == ["done"]


def test_the_budget_cap_stops_the_tutor_too(rt: Runtime, llm: fakes.FakeLLM, path: str) -> None:
    rt.service.put_setting("budget.cap_usd_month", 0.000001, "installation")
    reply = ask(rt, "Hello?", screen="path", path_id=path)
    assert reply["status"] == "failed" and reply["error"] == "budget" and tutor_calls(llm) == []


def test_tutor_calls_go_ahead_of_queued_background_calls() -> None:
    slots, order = Slots(1), []
    release = threading.Event()

    def call(name: str, priority: Lane, hold: bool = False) -> None:
        with slots.take(priority):
            order.append(name)
            if hold:
                release.wait(5)

    busy = threading.Thread(target=call, args=("lesson-1", Lane.BACKGROUND, True))
    busy.start()
    time.sleep(0.05)
    waiting = [
        threading.Thread(target=call, args=(n, p))
        for n, p in (
            ("lesson-2", Lane.BACKGROUND),
            ("lesson-3", Lane.BACKGROUND),
            ("tutor", Lane.INTERACTIVE),
        )
    ]
    for t in waiting:
        t.start()
        time.sleep(0.05)
    assert slots.waiting == [0, 2, 2]
    release.set()
    for t in [busy, *waiting]:
        t.join(5)
    assert order == ["lesson-1", "tutor", "lesson-2", "lesson-3"]


def test_the_stream_replays_missed_events_and_resets_when_it_cannot() -> None:
    b = Broker(size=3)
    first = b.publish("a", {"n": 1})
    b.publish("b", {"n": 2})
    assert [e.kind for e in b.wait(first, 0) or []] == ["b"]
    assert b.wait(b.last_id, 0.01) == []
    for n in range(5):
        b.publish("c", {"n": n})
    assert b.wait(first, 0) is None  # overrun: reload state
    assert Broker().wait(first, 0) is None  # another boot


def test_hints_with_cost_make_a_helped_test_answer_count_half(
    rt: Runtime, llm: fakes.FakeLLM, path: str
) -> None:
    me = Learner(rt, llm)
    rt.service.put_setting("tutor.test_policy", "hints", "installation")
    skill = rt.service.path_view(path)["branches"][0]["skills"][0]["id"]
    test = rt.service.start_skill_test(skill)
    if "job_id" in test:
        drain(rt)
        test = rt.service.start_skill_test(skill)
    attempt = new_id()
    me.send(
        "attempt.started",
        {"attempt_id": attempt, "assessment_id": test["assessment_id"], "purpose": "skill_test"},
    )
    first = test["items"][0]
    reply = ask(
        rt,
        "What should I think about here?",
        screen="test",
        attempt_id=attempt,
        item_version_id=first["item_version_id"],
    )
    assert reply["guard"] == "checked" and "HINTS WITH COST" in tutor_calls(llm)[0].messages[0].content
    for item in test["items"]:
        me.send(
            "assessment.response_given",
            {
                "attempt_id": attempt,
                "item_version_id": item["item_version_id"],
                "answer": fakes.answer_for(item, llm),
                "ms_to_answer": 4000,
            },
        )
    out = me.send("attempt.finished", {"attempt_id": attempt, "outcome": "finished"})
    assert out["outcomes"][attempt]["score"] == pytest.approx(0.9)  # (4 + 0.5) / 5


def test_fast_answers_with_an_ungraded_short_answer_do_not_break_ingest(
    rt: Runtime, llm: fakes.FakeLLM, path: str
) -> None:
    me = Learner(rt, llm)
    lesson = next(
        x
        for x in lessons_of(rt, path)
        if any(i["type"] == "short_answer" for i in rt.service.start_practice(x["id"])["items"])
    )
    practice = rt.service.start_practice(lesson["id"])
    attempt = new_id()
    me.send(
        "attempt.started",
        {"attempt_id": attempt, "assessment_id": practice["assessment_id"], "purpose": "practice"},
    )
    for item in practice["items"]:  # fast, and the short answer waits for its model grade (score NULL)
        me.send(
            "assessment.response_given",
            {
                "attempt_id": attempt,
                "item_version_id": item["item_version_id"],
                "answer": "z" if item["type"] == "mcq" else fakes.answer_for(item, llm),
                "ms_to_answer": 800,
            },
        )


def test_a_retried_reply_is_replaced_and_the_stream_says_so(
    rt: Runtime, llm: fakes.FakeLLM, path: str
) -> None:
    llm.script["tutor"] = [LLMError("timeout", retryable=True, kind="timeout")]
    sent = rt.service.send_message(new_id(), "Hello?", {"screen": "path", "path_id": path})
    rt.service.run_tutor_turn()
    failed = reply_to(rt, sent["id"])
    mark = rt.service.broker.last_id
    out = rt.service.retry_reply(failed["id"])
    assert out["retried"]["retried"] and out["requeued"][0]["status"] == "queued"
    published = {e.data["id"]: e.data["status"] for e in rt.service.broker.wait(mark, 0) or []}
    assert published == {sent["id"]: "queued", failed["id"]: "withdrawn"}
    assert failed["id"] not in {m["id"] for m in rt.service.messages()}  # replaced, not shown as cancelled


def test_before_an_attempt_the_history_is_this_attempt_and_question_only(
    rt: Runtime, llm: fakes.FakeLLM, path: str
) -> None:
    me = Learner(rt, llm)
    lesson = lessons_of(rt, path)[0]
    ask(rt, "Tell me about joins", screen="lesson", lesson_id=lesson["id"])  # same lesson thread, no item
    attempt, practice = practice_attempt(rt, me, lesson["id"])
    item = practice["items"][0]["item_version_id"]
    ask(rt, "Where do I start?", screen="practice", attempt_id=attempt, item_version_id=item)
    ask(rt, "And then?", screen="practice", attempt_id=attempt, item_version_id=item)
    history = [m.content for m in tutor_calls(llm)[-1].messages[1:-1]]
    assert history == ["Where do I start?", fakes.TUTOR_REPLY]  # not the lesson chat before it


def test_review_coach_keeps_the_answer_out_until_the_question_is_resolved(
    rt: Runtime, llm: fakes.FakeLLM, path: str, db_path: Path
) -> None:
    """In a review session the tutor coaches without spoilers, may explain a tried option, and
    explains freely once the question is resolved."""
    from tests.integration.test_review import Reviewer

    me = Reviewer(rt, llm)
    lesson = next(x for x in lessons_of(rt, path) if x["state"] == "ready")
    me.study(lesson["id"])
    session = rt.service.start_review_session(path, 5)
    attempt = me.begin(session)
    item = session["items"][0]
    ctx = {"screen": "review", "attempt_id": attempt, "item_version_id": item["item_version_id"]}
    assert rt.service.tutor_context(ctx)["policy"] == "review.coach"

    guess = ask(rt, "Is it c?", **ctx)
    assert guess["template"] == "tutor.review.coach" and tutor_calls(llm) == []

    wrong = me.answer(item, right=False)
    assert not wrong["resolved"] and rt.service.tutor_context(ctx)["policy"] == "review.coach"
    help_ = ask(rt, "Why is my choice wrong?", **ctx)
    assert help_["guard"] == "checked"
    system = tutor_calls(llm)[-1].messages[0].content
    assert "Answer key" not in system and "Worked solution" not in system
    assert "Options the learner already tried" in system and wrong["tried"][0] + ":" in system
    key = llm.solve(item["view"])["answer"]
    assert f"Option {key}:" not in system  # the right option's rationale is not in the coach's context
    assert "Hint ladder" in system and system.count("\n- ") >= 2
    assert "LESSON:" in system  # the lesson the question came from

    resolved = me.answer(item, right=True)
    assert resolved["outcome"] == "second"
    assert rt.service.tutor_context(ctx)["policy"] == "review.resolved"
    ask(rt, "Explain it fully", **ctx)
    system = tutor_calls(llm)[-1].messages[0].content
    assert "Answer key" in system and "Worked solution" in system
    # help before the answer makes the session's rating Hard, never Good
    me.finish()
    with sqlite3.connect(db_path) as c:
        assert (
            c.execute("SELECT count(*) FROM learning_event WHERE type = 'tutor.help_given'").fetchone()[0]
            == 1
        )


def test_review_policies_resolve_from_the_item_state() -> None:
    from yuo.tutoring.policy import ItemState, resolve

    def policy(state: ItemState, bank: bool) -> str:
        return resolve(
            screen="review",
            purpose="review",
            attempt_open=True,
            item_state=state,
            test_policy="locked",
            bank=bank,
        ).id

    assert policy("unanswered", True) == policy("trying", True) == "review.coach"
    assert policy("answered", True) == "review.resolved"
    assert policy("unanswered", False) == "review.before_recall"  # the flashcard queue is unchanged
    assert policy("answered", False) == "review.after_recall"


def test_the_api_schema_knows_every_policy_and_template() -> None:
    """A policy or template the response models do not list turns a tutor reply into a 500."""
    from typing import get_args

    from yuo.api import schemas as S
    from yuo.tutoring import guard
    from yuo.tutoring.policy import POLICIES

    assert set(POLICIES) <= set(get_args(S.TutorPolicyId))
    template = S.TutorMessageOut.model_fields["template"].annotation
    assert set(guard.TEMPLATES) <= set(get_args(get_args(template)[0]))


def test_a_conversation_is_erased_with_its_messages(rt: Runtime, path: str, db_path: Path) -> None:
    """The learner erases one thread; the money spent stays in the ledger, unlinked."""
    lesson = lessons_of(rt, path)[0]
    reply = ask(rt, "Why does a join need a condition?", screen="lesson", lesson_id=lesson["id"])
    [conv] = rt.service.conversations()
    c = sqlite3.connect(db_path)
    spent = c.execute("SELECT count(*), sum(cost_micros) FROM budget_entry").fetchone()
    counts = rt.service.erasure.conversation(conv["id"])
    assert counts["conversation"] == 1 and counts["message"] == 2
    assert rt.service.conversations() == [] and rt.service.messages() == []
    assert c.execute("SELECT count(*) FROM budget_entry WHERE message_id IS NOT NULL").fetchone() == (0,)
    assert c.execute("SELECT count(*), sum(cost_micros) FROM budget_entry").fetchone() == spent
    assert c.execute("SELECT kind FROM erasure_record").fetchall() == [("conversation",)]
    assert c.execute("SELECT count(*) FROM message WHERE id = ?", (reply["id"],)).fetchone()[0] == 0
    with pytest.raises(LookupError):
        rt.service.erasure.conversation(conv["id"])
