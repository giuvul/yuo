"""The tutor. A part of the application service (yuo.app.context).

A turn: the learner's queued messages in one conversation are answered together. The policy is
resolved on the server from its own records of the attempt and item the client names; an open skill
test or placement attempt applies whatever the client says, so leaving the test screen does not unlock
help (the learner can finish or abandon the attempt instead). Then the layers: the context
without the key, the guess template, the model leak checker (fail closed), the prompt. Replies stream
in unchecked modes only: a checked reply is shown after its check, never before.
"""

import json
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import structlog

from yuo.app.context import AppContext, Part
from yuo.app.ports import Learners, Models, StudyRecords
from yuo.assessment import types as xt
from yuo.content.lesson_body import plain_text
from yuo.core import clock
from yuo.core.enums import CheckVerdict, EventType
from yuo.core.errors import InvalidInput, NotFound
from yuo.core.ids import is_uuid7, new_id
from yuo.core.llm import Binding, Completion, LLMError, Request
from yuo.generation.lanes import Lane, lane
from yuo.generation.runner import BudgetExceeded
from yuo.generation.structured import StructuredFailure, generate_structured
from yuo.learning import events as ev
from yuo.learning import projections as pj
from yuo.setup import settings
from yuo.tutoring import guard, nudges
from yuo.tutoring import prompts as tp
from yuo.tutoring.guard import Actions
from yuo.tutoring.policy import POLICIES, POLICY_VERSION, ItemState, Policy, resolve

if TYPE_CHECKING:
    pass

log = structlog.get_logger(__name__)
MAX_TEXT = 4000
TEST_ATTEMPT_WINDOW = timedelta(hours=3)  # an open test attempt older than this no longer seals the tutor
REPLY_TOKENS = 1500
CHECK_TOKENS = 2000
EXCERPT_CHARS = 6000
TEMPLATE_FOR = {
    "practice.before_attempt": "tutor.guess",
    "review.before_recall": "tutor.review",
    "review.coach": "tutor.review.coach",
}


def _position_numbers(position: str | None) -> tuple[int | None, int | None]:
    m = re.match(r"question (\d+) of (\d+)", position or "")
    return (int(m[1]), int(m[2])) if m else (None, None)


def _rows(c: sqlite3.Connection, sql: str, *args: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in c.execute(sql, args).fetchall()]


@dataclass(slots=True)
class Resolved:
    """What the server makes of a client context: policy, refs it verified, the thread, the chips."""

    policy: Policy
    scope: str
    scope_ref: str | None
    path_id: str | None = None
    skill_id: str | None = None
    lesson_id: str | None = None
    lesson_version_id: str | None = None
    attempt_id: str | None = None
    assessment_id: str | None = None
    item_version_id: str | None = None
    item_state: ItemState = "none"
    position: str | None = None
    sealed_by_open_test: bool = False

    def refs(self) -> dict[str, Any]:
        return {
            k: getattr(self, k)
            for k in (
                "path_id",
                "skill_id",
                "lesson_id",
                "lesson_version_id",
                "attempt_id",
                "assessment_id",
                "item_version_id",
                "item_state",
                "position",
            )
        }


@dataclass
class _Attempt:
    """The attempt behind a tutor context, as far as the server trusts it (Tutor._attempt)."""

    attempt_id: str | None = None
    assessment: str | None = None
    purpose: str | None = None
    open: bool = False
    bank: bool = False  # a review session over the question bank
    snapshot: dict[str, Any] = field(default_factory=dict)
    item_vid: str | None = None  # an item without an attempt is not trusted as context
    position: str | None = None
    item_state: ItemState = "none"


def _thread(r: Resolved, purpose: str | None) -> None:
    """The thread: a test attempt has its own; practice belongs to its lesson."""
    if purpose in ("skill_test", "placement") and r.attempt_id:
        r.scope, r.scope_ref = "attempt", r.attempt_id
    elif purpose == "review" and r.skill_id:
        r.scope, r.scope_ref = "skill", r.skill_id
    elif r.lesson_id:
        r.scope, r.scope_ref = "lesson", r.lesson_id
    elif r.skill_id:
        r.scope, r.scope_ref = "skill", r.skill_id
    elif r.path_id:
        r.scope, r.scope_ref = "path", r.path_id


class TutorWorker:
    """One tutor turn at a time, on its own thread,, beside the generation worker."""

    def __init__(self, run_once: Any) -> None:
        self.run_once = run_once
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="yuo-tutor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=30)

    def wake(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                worked = self.run_once()
            except Exception:  # a bug in one turn must not stop the tutor
                log.exception("tutor.turn_crashed")
                worked = False
            if not worked:
                self._wake.wait(2.0)
                self._wake.clear()


class Tutor(Part):
    """A part of the application service (yuo.app.context), built with what it calls on the others."""

    def __init__(self, ctx: AppContext, *, learners: Learners, models: Models, study: StudyRecords) -> None:
        super().__init__(ctx)
        self.learners = learners
        self.models = models
        self.study = study

    # --- context: what the tutor may see, decided on the server ----------------------------------

    def _open_test(self, c: sqlite3.Connection, learner: str) -> sqlite3.Row | None:
        since = clock.to_timestamp(clock.parse_timestamp(clock.now()) - TEST_ATTEMPT_WINDOW)
        return c.execute(  # type: ignore[no-any-return]
            "SELECT s.attempt_id, s.payload ->> '$.assessment_id' AS assessment_id FROM learning_event s "
            "WHERE s.learner_id = ? AND s.type = 'attempt.started' AND s.payload ->> '$.purpose' IN "
            "('skill_test', 'placement') AND s.server_at >= ? AND NOT EXISTS (SELECT 1 FROM learning_event f "
            "WHERE f.type = 'attempt.finished' AND f.attempt_id = s.attempt_id) ORDER BY s.server_seq DESC LIMIT 1",
            (learner, since),
        ).fetchone()

    def _resolve(self, c: sqlite3.Connection, learner: str, ctx: dict[str, Any]) -> Resolved:
        def ref(key: str) -> str | None:
            v = ctx.get(key)
            return v if isinstance(v, str) and is_uuid7(v) else None

        screen = str(ctx.get("screen") or "other")
        attempt_id, item_vid = ref("attempt_id"), ref("item_version_id")
        sealed = False
        open_test = self._open_test(c, learner)
        if open_test is not None and open_test["attempt_id"] != attempt_id:
            attempt_id, item_vid, sealed = open_test["attempt_id"], None, True  # the test seals the tutor
        a = self._attempt(c, learner, attempt_id, item_vid) if attempt_id else _Attempt()
        test_policy = (
            a.snapshot.get("tutor.test_policy")
            or settings.effective(c, "tutor.test_policy", {"learner": learner})[0]
        )
        policy = resolve(
            screen=screen,
            purpose=a.purpose,
            attempt_open=a.open,
            item_state=a.item_state,
            test_policy=test_policy,
            bank=a.bank,
        )
        r = Resolved(policy, "general", None, attempt_id=a.attempt_id, assessment_id=a.assessment)
        r.item_version_id, r.item_state, r.position, r.sealed_by_open_test = (
            a.item_vid,
            a.item_state,
            a.position,
            sealed,
        )
        self._content(c, learner, r, a, ref("lesson_id"), ref("skill_id"), ref("path_id"))
        _thread(r, a.purpose)
        return r

    def _attempt(
        self, c: sqlite3.Connection, learner: str, attempt_id: str, item_vid: str | None
    ) -> _Attempt:
        """The learner's attempt behind the screen, if it is theirs, and the question on screen in it."""
        started = c.execute(
            "SELECT payload FROM learning_event WHERE type = 'attempt.started' AND attempt_id = ? AND learner_id = ?",
            (attempt_id, learner),
        ).fetchone()
        if started is None:
            return _Attempt()
        assessment = json.loads(started[0])["assessment_id"]
        row = c.execute(
            "SELECT purpose, skill_id, item_version_ids, settings_snapshot FROM assessment WHERE id = ?",
            (assessment,),
        ).fetchone()
        snapshot = json.loads(row["settings_snapshot"])
        a = _Attempt(attempt_id, assessment, row["purpose"], snapshot=snapshot)
        a.bank = (snapshot.get("review") or {}).get("kind") == "bank"
        a.open = (
            c.execute(
                "SELECT 1 FROM learning_event WHERE type = 'attempt.finished' AND attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            is None
        )
        ids = json.loads(row["item_version_ids"])
        if item_vid not in ids:
            item_vid = None
        if item_vid is None and a.open and a.purpose in ("skill_test", "placement"):
            # the question on screen in a test is the first one not answered yet (the runner goes in
            # order), so the leak check always has the key to check against
            done = {
                x[0]
                for x in c.execute(
                    "SELECT item_version_id FROM learning_event WHERE type = 'assessment.response_given' "
                    "AND attempt_id = ?",
                    (attempt_id,),
                )
            }
            item_vid = next((i for i in ids if i not in done), None)
        if item_vid:
            a.item_vid = item_vid
            a.position = f"question {ids.index(item_vid) + 1} of {len(ids)}"
            answered = c.execute(
                "SELECT 1 FROM learning_event WHERE type = 'assessment.response_given' AND attempt_id = ? "
                "AND item_version_id = ?",
                (attempt_id, item_vid),
            ).fetchone()
            a.item_state = "answered" if answered else "unanswered"
            if a.bank:  # two tries, hints and "Show answer": the outcome decides, not the first answer
                o = pj.item_outcome(c, learner, attempt_id, item_vid)
                a.item_state = "answered" if o.resolved else "trying" if o.tries else "unanswered"
        return a

    def _content(
        self, c: sqlite3.Connection, learner: str, r: Resolved, a: _Attempt, lesson_id: str | None,
        skill_id: str | None, path_id: str | None,
    ) -> None:  # fmt: skip
        """The content refs: from the item first, then what the client named; only the learner's own path."""
        if a.item_vid:
            row = c.execute(
                "SELECT i.skill_id, i.path_id, l.id AS lesson_id FROM item_version v JOIN item i ON i.id = v.item_id "
                "LEFT JOIN lesson_version lv ON lv.id = v.origin_lesson_version_id LEFT JOIN lesson l ON l.id = lv.lesson_id "
                "WHERE v.id = ?",
                (a.item_vid,),
            ).fetchone()
            skill_id, path_id = row["skill_id"], row["path_id"]
            # a review question brings its lesson along: the coach points back to it
            lesson_id = row["lesson_id"] if a.purpose == "practice" or a.bank else None
        if r.policy.sealed or (a.purpose in ("skill_test", "placement")):
            lesson_id = None
            if a.assessment and not skill_id:
                skill_id = c.execute(
                    "SELECT skill_id FROM assessment WHERE id = ?", (a.assessment,)
                ).fetchone()[0]
        if lesson_id:
            row = c.execute(
                "SELECT skill_id, path_id, current_version_id FROM lesson WHERE id = ?", (lesson_id,)
            ).fetchone()
            if row is None:
                lesson_id = None
            else:
                skill_id, path_id, r.lesson_version_id = (
                    row["skill_id"],
                    row["path_id"],
                    row["current_version_id"],
                )
        if skill_id:
            row = c.execute("SELECT path_id FROM skill WHERE id = ?", (skill_id,)).fetchone()
            skill_id, path_id = (skill_id, row[0]) if row else (None, path_id)
        if (
            path_id
            and c.execute("SELECT 1 FROM path WHERE id = ? AND learner_id = ?", (path_id, learner)).fetchone()
            is None
        ):
            path_id = skill_id = lesson_id = None
        r.path_id, r.skill_id, r.lesson_id = path_id, skill_id, lesson_id

    def _chips(
        self, c: sqlite3.Connection, r: Resolved, ctx: dict[str, Any], learner: str
    ) -> list[dict[str, Any]]:
        """What the tutor will see, shown to the learner as removable chips."""
        excluded = set(ctx.get("excluded") or [])
        chips: list[dict[str, Any]] = []
        if r.path_id and not r.policy.sealed:
            chips.append(
                {
                    "kind": "path",
                    "label": c.execute("SELECT title FROM path WHERE id = ?", (r.path_id,)).fetchone()[0],
                }
            )
        if r.skill_id:
            chips.append(
                {
                    "kind": "skill",
                    "label": c.execute("SELECT title FROM skill WHERE id = ?", (r.skill_id,)).fetchone()[0],
                }
            )
        if r.lesson_version_id and not r.policy.sealed:
            chips.append(
                {
                    "kind": "lesson",
                    "label": c.execute(
                        "SELECT title FROM lesson_version WHERE id = ?", (r.lesson_version_id,)
                    ).fetchone()[0],
                }
            )
        if r.item_version_id and r.policy.item:
            n, of = _position_numbers(r.position)
            chips.append({"kind": "item", "label": r.position or "this question", "n": n, "of": of})
        sel = ctx.get("selection") or {}
        if (
            isinstance(sel, dict)
            and isinstance(sel.get("text"), str)
            and sel["text"].strip()
            and not r.policy.sealed
        ):
            chips.append({"kind": "selection", "label": sel["text"].strip()[:80]})
        notes = [n for n in ctx.get("note_ids") or [] if isinstance(n, str)]
        if notes and not r.policy.sealed:
            chips.append({"kind": "notes", "label": str(len(notes)), "n": len(notes)})
        if not r.policy.sealed and settings.effective(c, "tutor.memory", {"learner": learner})[0]:
            chips.append({"kind": "memory", "label": "on"})
        return [ch for ch in chips if ch["kind"] not in excluded or ch["kind"] in ("item",)]

    def tutor_context(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """The mode, the reason and the chips for a screen, before anything is sent (the dock shows them)."""
        learner = self.learners.ensure_learner()
        with self.readers.connection() as c:
            r = self._resolve(c, learner, ctx)
            return self._resolved_view(c, r, ctx, learner)

    def _resolved_view(
        self, c: sqlite3.Connection, r: Resolved, ctx: dict[str, Any], learner: str
    ) -> dict[str, Any]:
        conv = c.execute(
            "SELECT id FROM conversation WHERE learner_id = ? AND scope = ? AND scope_ref IS ? AND archived_at IS NULL",
            (learner, r.scope, r.scope_ref),
        ).fetchone()
        return {
            "policy": r.policy.id,
            "mode": r.policy.mode.value,
            "checked": r.policy.checked,
            "sealed": r.policy.sealed,
            "sealed_by_open_test": r.sealed_by_open_test,
            "scope": r.scope,
            "scope_ref": r.scope_ref,
            "conversation_id": conv[0] if conv else None,
            "chips": self._chips(c, r, ctx, learner),
            "refs": r.refs(),
        }

    def _conversation(self, c: sqlite3.Connection, learner: str, r: Resolved) -> str:
        row = c.execute(
            "SELECT id FROM conversation WHERE learner_id = ? AND scope = ? AND scope_ref IS ? AND archived_at IS NULL",
            (learner, r.scope, r.scope_ref),
        ).fetchone()
        if row:
            return str(row[0])
        cid = new_id()
        title = None
        if r.scope == "lesson" and r.lesson_version_id:
            title = c.execute(
                "SELECT title FROM lesson_version WHERE id = ?", (r.lesson_version_id,)
            ).fetchone()[0]
        elif r.scope in ("skill", "attempt") and r.skill_id:
            title = c.execute("SELECT title FROM skill WHERE id = ?", (r.skill_id,)).fetchone()[0]
        elif r.scope == "path" and r.path_id:
            title = c.execute("SELECT title FROM path WHERE id = ?", (r.path_id,)).fetchone()[0]
        c.execute(
            "INSERT INTO conversation (id, learner_id, scope, scope_ref, title, created_at, archived_at) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (cid, learner, r.scope, r.scope_ref, title, clock.now()),
        )
        return cid

    # --- messages ----------------------------------------------------------------------------------

    def send_message(self, message_id: str, text: str, ctx: dict[str, Any]) -> dict[str, Any]:
        """Queue a learner message (client uuid7, idempotent) and wake the tutor."""
        if not is_uuid7(message_id):
            raise InvalidInput("message id must be a lowercase uuid7")
        text = text.strip()
        if not 1 <= len(text) <= MAX_TEXT:
            raise InvalidInput(f"a message is 1 to {MAX_TEXT} characters")
        learner = self.learners.ensure_learner()

        def unit(c: sqlite3.Connection) -> dict[str, Any]:
            prior = c.execute("SELECT conversation_id FROM message WHERE id = ?", (message_id,)).fetchone()
            if prior is not None:  # an outbox retry
                return self._message(c, message_id) | {"duplicate": True}
            r = self._resolve(c, learner, ctx)
            cid = self._conversation(c, learner, r)
            snapshot = {
                "client": {
                    k: ctx.get(k)
                    for k in ("screen", "selection", "note_ids", "excluded", "locale", "video_s")
                }
                | {
                    k: ctx.get(k)
                    for k in ("path_id", "skill_id", "lesson_id", "attempt_id", "item_version_id")
                },
                "resolved": r.refs() | {"policy": r.policy.id, "policy_version": POLICY_VERSION},
                "chips": self._chips(c, r, ctx, learner),
            }
            c.execute(
                "INSERT INTO message (id, conversation_id, role, status, content, context, policy, stage_run_id, "
                "leak_check, guard, created_at, completed_at) VALUES (?, ?, 'learner', 'queued', json(?), json(?), ?, "
                "NULL, NULL, NULL, ?, NULL)",
                (
                    message_id,
                    cid,
                    json.dumps({"text": text}),
                    json.dumps(snapshot),
                    r.policy.mode.value,
                    clock.now(),
                ),
            )
            notes = [n for n in ctx.get("note_ids") or [] if isinstance(n, str)]
            if notes and not r.policy.sealed:
                c.executemany(
                    "UPDATE note SET sent_message_id = ? WHERE id = ? AND learner_id = ?",
                    [(message_id, n, learner) for n in notes],
                )
            return self._message(c, message_id)

        out = self.writer.run(unit)
        self.broker.publish("tutor.message", out)
        if self.tutor_worker:
            self.tutor_worker.wake()
        return out

    def _message(self, c: sqlite3.Connection, message_id: str) -> dict[str, Any]:
        row = c.execute("SELECT * FROM message WHERE id = ?", (message_id,)).fetchone()
        if row is None:
            raise NotFound(message_id)
        return self._message_view(row)

    @staticmethod
    def _message_view(row: sqlite3.Row) -> dict[str, Any]:
        content = json.loads(row["content"])
        context = json.loads(row["context"])
        content.pop("withheld", None)  # a blocked reply is kept for the audit, never shown
        return {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "role": row["role"],
            "status": row["status"],
            "text": content.get("text", ""),
            "template": content.get("template"),
            "retried": bool(content.get("retried")),
            "error": content.get("error"),
            "proposal_id": content.get("proposal_id"),
            "path_id": context.get("resolved", {}).get("path_id") or context.get("path_id"),
            "memory_ids": content.get("memory_ids", []),
            "policy": row["policy"],
            "guard": row["guard"],
            "chips": context.get("chips", []),
            "answers": context.get("answers", []),
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
        }

    def edit_message(self, message_id: str, text: str) -> dict[str, Any]:
        text = text.strip()
        if not 1 <= len(text) <= MAX_TEXT:
            raise InvalidInput(f"a message is 1 to {MAX_TEXT} characters")

        def unit(c: sqlite3.Connection) -> dict[str, Any]:
            n = c.execute(
                "UPDATE message SET content = json_set(content, '$.text', ?) WHERE id = ? AND role = 'learner' "
                "AND status = 'queued'",
                (text, message_id),
            ).rowcount
            if n == 0:
                raise InvalidInput("only a queued message can be edited")
            return self._message(c, message_id)

        out = self.writer.run(unit)
        self.broker.publish("tutor.message", out)
        return out

    def withdraw_message(self, message_id: str) -> dict[str, Any]:
        """Take back a queued learner message, or cancel a reply still being written."""

        def unit(c: sqlite3.Connection) -> dict[str, Any]:
            n = c.execute(
                "UPDATE message SET status = 'withdrawn', completed_at = ? WHERE id = ? AND ((role = 'learner' AND "
                "status = 'queued') OR (role = 'tutor' AND status IN ('queued', 'streaming')))",
                (clock.now(), message_id),
            ).rowcount
            if n == 0:
                raise InvalidInput("only a queued message or a reply in progress can be withdrawn")
            return self._message(c, message_id)

        out = self.writer.run(unit)
        self.broker.publish("tutor.message", out)
        return out

    def retry_reply(self, message_id: str) -> dict[str, Any]:
        """Ask again after a failed reply: its questions go back in the queue."""

        def unit(c: sqlite3.Connection) -> list[str]:
            row = c.execute(
                "SELECT context FROM message WHERE id = ? AND role = 'tutor' AND status = 'failed'",
                (message_id,),
            ).fetchone()
            if row is None:
                raise InvalidInput("only a failed reply can be retried")
            answers = json.loads(row[0]).get("answers", [])
            c.executemany(
                "UPDATE message SET status = 'queued', completed_at = NULL WHERE id = ? AND role = 'learner'",
                [(a,) for a in answers],
            )
            c.execute(
                "UPDATE message SET status = 'withdrawn', content = json_set(content, '$.retried', json('true')) "
                "WHERE id = ?",
                (message_id,),
            )
            return list(answers)

        answers = self.writer.run(unit)
        with self.readers.connection() as c:
            requeued = [self._message(c, a) for a in answers]
            retried = self._message(c, message_id)
        for m in [*requeued, retried]:  # other tabs follow over the stream
            self.broker.publish("tutor.message", m)
        if self.tutor_worker:
            self.tutor_worker.wake()
        return {"requeued": requeued, "retried": retried}

    def conversations(self, path_id: str | None = None) -> list[dict[str, Any]]:
        learner = self.learners.ensure_learner()
        with self.readers.connection() as c:
            return _rows(
                c,
                "SELECT c.id, c.scope, c.scope_ref, c.title, c.created_at, max(m.created_at) AS last_at, count(m.id) AS "
                "messages FROM conversation c LEFT JOIN message m ON m.conversation_id = c.id AND m.status != 'withdrawn' "
                "WHERE c.learner_id = ? AND c.archived_at IS NULL AND (? IS NULL OR c.scope_ref = ? OR c.scope_ref IN "
                "(SELECT id FROM skill WHERE path_id = ?) OR c.scope_ref IN (SELECT id FROM lesson WHERE path_id = ?)) "
                "GROUP BY c.id ORDER BY last_at DESC",
                learner,
                path_id,
                path_id,
                path_id,
                path_id,
            )

    def messages(self, conversation_id: str | None = None, *, limit: int = 200) -> list[dict[str, Any]]:
        """One thread, or the 'All' timeline across threads when no conversation is named."""
        learner = self.learners.ensure_learner()
        with self.readers.connection() as c:
            rows = c.execute(
                "SELECT m.* FROM message m JOIN conversation c ON c.id = m.conversation_id WHERE c.learner_id = ? "
                "AND (? IS NULL OR m.conversation_id = ?) AND NOT (m.role = 'learner' AND m.status = 'withdrawn') "
                "AND m.content ->> '$.retried' IS NOT 1 "
                "ORDER BY m.created_at DESC, m.id DESC LIMIT ?",
                (learner, conversation_id, conversation_id, limit),
            ).fetchall()
        return [self._message_view(r) for r in reversed(rows)]

    # --- a turn --------------------------------------------------------------------------------------

    def run_tutor_turn(self) -> bool:
        """Answer the oldest conversation with queued learner messages. Returns whether there was one."""
        learner = self.learners.ensure_learner()

        def claim(c: sqlite3.Connection) -> tuple[str, list[sqlite3.Row], str] | None:
            first = c.execute(
                "SELECT conversation_id FROM message WHERE role = 'learner' AND status = 'queued' "
                "ORDER BY created_at, id LIMIT 1"
            ).fetchone()
            if first is None:
                return None
            cid = first[0]
            queued = c.execute(
                "SELECT * FROM message WHERE conversation_id = ? AND role = 'learner' AND status = 'queued' "
                "ORDER BY created_at, id",
                (cid,),
            ).fetchall()
            now = clock.now()
            c.executemany(
                "UPDATE message SET status = 'done', completed_at = ? WHERE id = ?",
                [(now, q["id"]) for q in queued],
            )
            tid = new_id()
            last_ctx = json.loads(queued[-1]["context"])
            c.execute(
                "INSERT INTO message (id, conversation_id, role, status, content, context, policy, stage_run_id, "
                "leak_check, guard, created_at, completed_at) VALUES (?, ?, 'tutor', 'streaming', json(?), json(?), ?, "
                "NULL, NULL, NULL, ?, NULL)",
                (
                    tid,
                    cid,
                    json.dumps({"text": ""}),
                    json.dumps({"answers": [q["id"] for q in queued], "chips": last_ctx.get("chips", [])}),
                    queued[-1]["policy"],
                    now,
                ),
            )
            return cid, queued, tid

        got = self.writer.run(claim)
        if got is None:
            return False
        cid, queued, tid = got
        with self.readers.connection() as c:
            for q in queued:  # now answered: no longer editable
                self.broker.publish("tutor.message", self._message(c, q["id"]))
            self.broker.publish("tutor.message", self._message(c, tid))
            client = json.loads(queued[-1]["context"]).get("client", {})
            r = self._resolve(c, learner, client)  # again: the item may have been answered since it was sent
            ctx = self._turn_context(c, learner, r, client, cid, [q["id"] for q in queued])
        texts = [json.loads(q["content"])["text"] for q in queued]
        try:
            outcome = self._answer(tid, r, ctx, texts)
        except Exception as e:
            log.exception("tutor.turn_failed", message=tid)
            outcome = _Outcome(text="", error="error", detail=f"{type(e).__name__}")
        self._finish_turn(learner, tid, r, outcome)
        return True

    def _turn_context(
        self,
        c: sqlite3.Connection,
        learner: str,
        r: Resolved,
        client: dict[str, Any],
        cid: str,
        skip: list[str],
    ) -> tp.TurnContext:
        p = r.policy
        ctx = tp.TurnContext(
            policy=p,
            persona_name=str(settings.effective(c, "tutor.name", {"learner": learner})[0]),
            tone=str(settings.effective(c, "tutor.tone", {"learner": learner})[0]),
        )
        excluded = set(client.get("excluded") or [])
        if r.path_id and "path" not in excluded:
            row = c.execute("SELECT title, subject, goal FROM path WHERE id = ?", (r.path_id,)).fetchone()
            ctx.path = dict(row)
            extra = settings.effective(c, "custom_instructions", {"path": r.path_id, "learner": learner})[0]
            ctx.instructions = extra or None
        if r.skill_id and "skill" not in excluded:
            ctx.skill = {
                "title": c.execute("SELECT title FROM skill WHERE id = ?", (r.skill_id,)).fetchone()[0],
                "objectives": [
                    x[0]
                    for x in c.execute(
                        "SELECT statement FROM learning_objective WHERE skill_id = ? AND archived_at IS NULL "
                        "ORDER BY position",
                        (r.skill_id,),
                    )
                ],
            }
        sel = client.get("selection") or {}
        if r.lesson_version_id and "lesson" not in excluded:
            title, body = c.execute(
                "SELECT title, body FROM lesson_version WHERE id = ?", (r.lesson_version_id,)
            ).fetchone()
            blocks = json.loads(body)
            bid = sel.get("bid") if isinstance(sel, dict) else None
            idx = next((i for i, b in enumerate(blocks) if isinstance(b, dict) and b.get("bid") == bid), None)
            part = blocks[max(0, idx - 2) : idx + 3] if idx is not None else blocks
            ctx.lesson = {"title": title, "excerpt": plain_text(part)[:EXCERPT_CHARS]}
        if isinstance(sel, dict) and isinstance(sel.get("text"), str) and "selection" not in excluded:
            ctx.selection = sel["text"][:1000] or None
        if "notes" not in excluded:
            ids = [n for n in client.get("note_ids") or [] if isinstance(n, str)]
            if ids:
                marks = ",".join("?" * len(ids))
                ctx.notes = [
                    # a note from the video says where in it the question came up (the notes bubble)
                    x[0]
                    if x[1] is None
                    else f"(at {int(x[1]) // 60}:{int(x[1]) % 60:02d} in the video) {x[0]}"
                    for x in c.execute(
                        f"SELECT text, t_s FROM note WHERE learner_id = ? AND id IN ({marks}) ORDER BY t_s, created_at",
                        (learner, *ids),
                    )
                ][:10]
        if r.item_version_id and p.item:
            ctx.item = self._item_context(c, r)
        if r.path_id and not p.sealed:
            for row in c.execute(
                "SELECT v.payload, i.type_key, v.id FROM response x JOIN item_version v ON v.id = x.item_version_id "
                "JOIN item i ON i.id = v.item_id WHERE i.path_id = ? AND x.score < 0.5 AND x.attempt_id IN "
                "(SELECT a.id FROM attempt a JOIN assessment s ON s.id = a.assessment_id WHERE s.purpose IN "
                "('practice', 'review')) ORDER BY x.answered_at DESC LIMIT 5",
                (r.path_id,),
            ):
                view = xt.get(row[1]).view(json.loads(row[0]), seed=row[2])
                ctx.mistakes.append(
                    f"missed: {view.get('prompt') or view.get('front') or view.get('text', '')}"[:200]
                )
        if (
            not p.sealed
            and "memory" not in excluded
            and settings.effective(c, "tutor.memory", {"learner": learner})[0]
        ):
            ctx.memory = _rows(
                c,
                "SELECT kind, text FROM learner_memory_item WHERE learner_id = ? AND archived_at IS NULL "
                "ORDER BY updated_at DESC LIMIT 20",
                learner,
            )
        marks = ",".join("?" * len(skip)) or "''"
        # in checked modes only this attempt's turns on this question: an earlier talk about the same item
        # after an answer (key in context) must not come back before a new attempt (found by the eval)
        same = (
            "AND coalesce(context ->> '$.resolved.attempt_id', context ->> '$.attempt_id') IS ? AND "
            "coalesce(context ->> '$.resolved.item_version_id', context ->> '$.item_version_id') IS ? "
            if p.checked
            else ""
        )
        hist = c.execute(
            "SELECT role, content FROM message WHERE conversation_id = ? AND status = 'done' AND role IN "
            f"('learner', 'tutor') AND id NOT IN ({marks}) {same}ORDER BY created_at DESC, id DESC LIMIT 8",
            (cid, *skip, *((r.attempt_id, r.item_version_id) if p.checked else ())),
        ).fetchall()
        ctx.history = [(h[0], json.loads(h[1]).get("text", "")) for h in reversed(hist)]
        return ctx

    def _item_context(self, c: sqlite3.Connection, r: Resolved) -> tp.ItemContext:
        row = c.execute(
            "SELECT v.payload, v.support, i.type_key FROM item_version v JOIN item i ON i.id = v.item_id WHERE v.id = ?",
            (r.item_version_id,),
        ).fetchone()
        t = xt.get(row["type_key"])
        payload, support = json.loads(row["payload"]), json.loads(row["support"] or "{}")
        item = tp.ItemContext(
            type=t.key,
            view=t.view(payload, seed=str(r.item_version_id)),
            hints=list(support.get("hints") or [])[:-1],  # all rungs but the bottom-out
            key=t.correct(payload),
            solution=support.get("solution"),
            explanations=list(support.get("explanations") or []),
            position=r.position,
        )
        if r.item_state == "trying" and r.attempt_id:
            why = {e.get("id"): e.get("why") for e in item.explanations}
            learner = c.execute(
                "SELECT learner_id FROM learning_event WHERE type = 'attempt.started' AND attempt_id = ?",
                (r.attempt_id,),
            ).fetchone()[0]
            o = pj.item_outcome(c, learner, r.attempt_id, str(r.item_version_id))
            item.tried = [{"id": a, "why": why.get(a, "")} for _, a, _ in o.tries if a != item.key]
        if r.item_state == "answered" and r.attempt_id:
            ans = c.execute(
                "SELECT e.payload ->> '$.answer', x.score FROM learning_event e LEFT JOIN response x ON "
                "x.response_event_id = e.id WHERE e.type = 'assessment.response_given' AND e.attempt_id = ? AND "
                "e.item_version_id = ? ORDER BY e.server_seq DESC LIMIT 1",
                (r.attempt_id, r.item_version_id),
            ).fetchone()
            if ans:
                item.learner_answer = json.loads(ans[0]) if ans[0] and ans[0][:1] in '[{"' else ans[0]
                item.score = ans[1]
        return item

    def _answer(self, tid: str, r: Resolved, ctx: tp.TurnContext, texts: list[str]) -> _Outcome:
        p = r.policy
        item = ctx.item
        if p.guess_guard and item is not None:
            options = item.view.get("options") if item.type in ("mcq", "multi") else None
            open_answer = item.type in ("cloze", "short_answer", "flashcard")
            if any(guard.detect_guess(t, options, open_answer=open_answer) for t in texts):
                template = TEMPLATE_FOR.get(p.id, "tutor.guess.test")
                return _Outcome(text=guard.TEMPLATES[template], template=template, guard="template")
        try:
            self.runner.budget.check()
        except BudgetExceeded:
            return _Outcome(text="", error="budget", detail="the monthly budget cap is reached")
        binding = self.models.binding("tutor")
        port = self.runner.port(binding)
        req = Request(
            messages=tp.tutor_messages(ctx, texts),
            model=binding.model,
            max_tokens=min(binding.max_tokens, REPLY_TOKENS),
            temperature=binding.temperature,
            effort=binding.effort,
            providers=binding.providers,
            avoid=binding.avoid,
            timeout_s=180,
        )
        calls: list[tuple[str, Completion, int]] = []
        bytes_out = sum(len(m.content.encode()) for m in req.messages)
        streaming = not p.checked and bool(getattr(port, "can_stream", lambda: False)())
        self.broker.publish(
            "tutor.progress", {"message_id": tid, "stage": "writing" if streaming else "thinking"}
        )
        flt = guard.StreamFilter()
        try:
            with lane(Lane.INTERACTIVE):
                if streaming:
                    comp = port.stream(  # type: ignore[attr-defined]
                        req, lambda chunk: self._delta(tid, flt.feed(chunk))
                    )
                else:
                    comp = port.generate(req)
        except LLMError as e:
            return _Outcome(text="", error=e.kind, detail=str(e)[:200])
        calls.append(("tutor", comp, bytes_out))
        raw = re.sub(r"<think>.*?</think>", "", comp.text, flags=re.DOTALL).strip()
        text, acts = guard.split_actions(raw)
        if not p.actions:
            acts = guard.Actions()
        out = _Outcome(text=text, calls=calls, actions=acts, model=binding.model, adapter=port.name)
        if not text:
            out.error, out.detail = "empty", "the model returned no text"
            return out
        if p.checked and item is not None:
            self.broker.publish("tutor.progress", {"message_id": tid, "stage": "checking"})
            verdict = self._leak_check(binding, port, item, "\n".join(texts), text, calls)
            out.leak_check = verdict
            if verdict is not CheckVerdict.PASS:
                out.withheld, out.text = text, guard.TEMPLATES["tutor.blocked"]
                out.template, out.guard = "tutor.blocked", "blocked"
                return out
            out.guard = "checked"
        return out

    def _leak_check(
        self,
        binding: Binding,
        port: Any,
        item: tp.ItemContext,
        learner: str,
        reply: str,
        calls: list[tuple[str, Completion, int]],
    ) -> CheckVerdict:
        """Checker, run by the tutor model in checker role; anything but a clear 'no leak' blocks."""
        checker = Binding(
            adapter=binding.adapter,
            model=binding.model,
            mode=binding.mode,
            providers=binding.providers,
            avoid=binding.avoid,
            effort="low" if binding.effort not in (None, "none") else binding.effort,
            max_tokens=min(binding.max_tokens, CHECK_TOKENS),
            temperature=0.0,
            role="reviewer",
        )
        msgs = list(tp.checker_messages(item, learner, reply))
        try:
            with lane(Lane.INTERACTIVE):
                res = generate_structured(port, checker, tp.LeakVerdict, msgs, schema_name="leak_check")
        except StructuredFailure as f:
            calls += [("leak_check", comp, 0) for comp in f.completions]
            return CheckVerdict.FAIL
        except LLMError:
            return CheckVerdict.FAIL
        size = sum(len(m.content.encode()) for m in msgs)
        calls += [("leak_check", comp, size) for comp in res.completions]
        return CheckVerdict.FAIL if res.value.leak else CheckVerdict.PASS

    def _delta(self, tid: str, text: str) -> None:
        if text:
            self.broker.publish("tutor.delta", {"message_id": tid, "text": text})

    def _finish_turn(self, learner: str, tid: str, r: Resolved, o: _Outcome) -> None:
        def unit(c: sqlite3.Connection) -> None:
            now = clock.now()
            for purpose, comp, size in o.calls:
                u = comp.usage
                c.execute(
                    "INSERT INTO budget_entry (id, stage_run_id, message_id, adapter, provider, in_tokens, out_tokens, "
                    "reasoning_tokens, cost_micros, cost_currency, price_ref, estimated, at) "
                    "VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, 'USD', ?, ?, ?)",
                    (
                        new_id(),
                        tid,
                        o.adapter,
                        comp.provider,
                        u.in_tokens,
                        u.out_tokens,
                        u.reasoning_tokens,
                        u.cost_micros,
                        "notional" if u.notional else "provider-reported",
                        int(u.notional),
                        now,
                    ),
                )
                if (
                    self.runner.ports.get(o.adapter or "") is not None
                    and self.runner.ports[o.adapter or ""].remote
                ):
                    c.execute(
                        "INSERT INTO egress_record (id, adapter, data_classes, bytes_out, purpose, stage_run_id, "
                        "message_id, at) VALUES (?, ?, json(?), ?, ?, NULL, ?, ?)",
                        (new_id(), o.adapter, json.dumps(["P", "F", "C"]), size, purpose, tid, now),
                    )
            status = c.execute("SELECT status FROM message WHERE id = ?", (tid,)).fetchone()[0]
            if status == "withdrawn":  # cancelled while it was written: cost recorded, nothing shown
                return
            content: dict[str, Any] = {"text": o.text}
            if o.template:
                content["template"] = o.template
            if o.withheld:
                content["withheld"] = o.withheld
            if o.error:
                content |= {"error": o.error, "detail": o.detail}
            if not o.error and o.actions is not None and r.path_id:
                pid = self._store_actions(c, learner, tid, r, o.actions)
                if pid:
                    content["proposal_id"] = pid
                if o.actions.memory and settings.effective(c, "tutor.memory", {"learner": learner})[0]:
                    content["memory_ids"] = self._remember(c, learner, tid, o.actions.memory)
            ctx = json.loads(c.execute("SELECT context FROM message WHERE id = ?", (tid,)).fetchone()[0])
            ctx |= {
                "policy": r.policy.id,
                "policy_version": POLICY_VERSION,
                "adapter": o.adapter,
                "model": o.model,
                "item_version_id": r.item_version_id,
                "attempt_id": r.attempt_id,
                "path_id": r.path_id,
            }
            c.execute(
                "UPDATE message SET status = ?, content = json(?), context = json(?), policy = ?, leak_check = ?, "
                "guard = ?, completed_at = ? WHERE id = ?",
                (
                    "failed" if o.error else "done",
                    json.dumps(content, ensure_ascii=False),
                    json.dumps(ctx, ensure_ascii=False),
                    r.policy.mode.value,
                    o.leak_check.value if o.leak_check else None,
                    o.guard,
                    now,
                    tid,
                ),
            )
            # Help on an item the learner has not answered yet makes the answer an assisted one
            if (
                not o.error
                and r.policy.records_help
                and r.item_version_id
                and r.attempt_id
                and o.guard == "checked"
            ):
                eid = new_id()
                boundary = c.execute(
                    "SELECT day_boundary, tz FROM learner WHERE id = ?", (learner,)
                ).fetchone()
                ev.insert_event(
                    c,
                    event_id=eid,
                    etype=EventType.TUTOR_HELP_GIVEN,
                    payload={
                        "message_id": tid,
                        "attempt_id": r.attempt_id,
                        "item_version_id": r.item_version_id,
                    },
                    learner_id=learner,
                    device_id=ev.server_device(c),
                    device_at=now,
                    tz=boundary["tz"],
                    boundary=boundary["day_boundary"],
                )
                self.study.project_events(c, learner, [eid])

        self.writer.run(unit)
        with self.readers.connection() as c:
            self.broker.publish("tutor.message", self._message(c, tid))
        log.info("tutor.turn", message=tid, policy=r.policy.id, guard=o.guard, error=o.error)

    # --- proposals and memory ---------------------------------------------------------

    def _store_actions(
        self, c: sqlite3.Connection, learner: str, tid: str, r: Resolved, acts: guard.Actions
    ) -> str | None:
        if acts.proposal is None or r.path_id is None:
            return None
        change = dict(acts.proposal["change"])
        kind = acts.proposal["kind"]
        if kind == "add_lesson" and not isinstance(change.get("prompt"), str):
            return None
        if kind == "change_difficulty" and change.get("difficulty") not in (
            "foundational",
            "intermediate",
            "advanced",
        ):
            return None
        if kind == "extra_review":
            title = change.get("skill")
            row = c.execute(
                "SELECT id FROM skill WHERE path_id = ? AND (id = ? OR lower(title) = lower(?)) LIMIT 1",
                (r.path_id, title, title),
            ).fetchone() or ((r.skill_id,) if r.skill_id else None)
            if row is None:
                return None
            change["skill_id"] = row[0]
        pid = new_id()
        now = clock.parse_timestamp(clock.now())
        c.execute(
            "INSERT INTO proposal (id, learner_id, path_id, kind, rationale, change, origin, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, json(?), 'tutor', ?, ?)",
            (
                pid,
                learner,
                r.path_id,
                kind,
                acts.proposal["rationale"],
                json.dumps(change | {"message_id": tid}, ensure_ascii=False),
                clock.to_timestamp(now),
                clock.to_timestamp(now + timedelta(days=14)),
            ),
        )
        return pid

    def _remember(
        self, c: sqlite3.Connection, learner: str, tid: str, items: list[dict[str, str]]
    ) -> list[str]:
        ids = []
        now = clock.now()
        for m in items:
            if c.execute(
                "SELECT 1 FROM learner_memory_item WHERE learner_id = ? AND lower(text) = lower(?) AND archived_at IS NULL",
                (learner, m["text"]),
            ).fetchone():
                continue
            mid = new_id()
            c.execute(
                "INSERT INTO learner_memory_item (id, learner_id, kind, text, source, evidence_ref, archived_at, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, 'tutor', json(?), NULL, ?, ?)",
                (mid, learner, m["kind"], m["text"], json.dumps({"kind": "message", "id": tid}), now, now),
            )
            ids.append(mid)
        return ids

    def memory(self) -> list[dict[str, Any]]:
        learner = self.learners.ensure_learner()
        with self.readers.connection() as c:
            out = _rows(
                c,
                "SELECT id, kind, text, source, evidence_ref, created_at, updated_at FROM learner_memory_item "
                "WHERE learner_id = ? AND archived_at IS NULL ORDER BY updated_at DESC",
                learner,
            )
        for m in out:
            m["evidence_ref"] = json.loads(m["evidence_ref"]) if m["evidence_ref"] else None
        return out

    def add_memory(self, kind: str, text: str) -> str:
        if kind not in guard.MEMORY_KINDS or not 1 <= len(text.strip()) <= 300:
            raise InvalidInput("a memory entry has a kind and 1 to 300 characters")
        learner, mid, now = self.learners.ensure_learner(), new_id(), clock.now()
        self.writer.run(
            lambda c: c.execute(
                "INSERT INTO learner_memory_item (id, learner_id, kind, text, source, evidence_ref, archived_at, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, 'learner', NULL, NULL, ?, ?)",
                (mid, learner, kind, text.strip(), now, now),
            )
        )
        return mid

    def edit_memory(self, memory_id: str, text: str) -> None:
        if not 1 <= len(text.strip()) <= 300:
            raise InvalidInput("a memory entry is 1 to 300 characters")
        n = self.writer.run(
            lambda c: (
                c.execute(
                    "UPDATE learner_memory_item SET text = ?, source = 'learner', updated_at = ? WHERE id = ? AND "
                    "archived_at IS NULL",
                    (text.strip(), clock.now(), memory_id),
                ).rowcount
            )
        )
        if n == 0:
            raise NotFound(memory_id)

    def delete_memory(self, memory_id: str) -> None:
        """Deleted for real, not archived: the learner asked the tutor to forget it."""
        n = self.writer.run(
            lambda c: c.execute("DELETE FROM learner_memory_item WHERE id = ?", (memory_id,)).rowcount
        )
        if n == 0:
            raise NotFound(memory_id)

    def proposals(self, path_id: str) -> list[dict[str, Any]]:
        with self.readers.connection() as c:
            rows = _rows(
                c,
                "SELECT p.*, (SELECT e.payload ->> '$.decision' FROM learning_event e WHERE e.type = "
                "'tutor.proposal_decided' AND e.payload ->> '$.proposal_id' = p.id ORDER BY e.server_seq LIMIT 1) "
                "AS decision FROM proposal p WHERE p.path_id = ? ORDER BY p.created_at DESC",
                path_id,
            )
        now = clock.now()
        for p in rows:
            p["change"] = json.loads(p["change"])
            p["status"] = p.pop("decision") or (
                "expired" if p["expires_at"] and p["expires_at"] < now else "pending"
            )
        return rows

    def proposal(self, proposal_id: str) -> dict[str, Any]:
        with self.readers.connection() as c:
            row = c.execute("SELECT path_id FROM proposal WHERE id = ?", (proposal_id,)).fetchone()
        if row is None:
            raise NotFound(proposal_id)
        return next(p for p in self.proposals(row[0]) if p["id"] == proposal_id)

    def _decide_proposal(self, c: sqlite3.Connection, learner: str, payload: dict[str, Any]) -> None:
        """Inside the ingest unit, for a fresh `tutor.proposal_decided` event: apply an accepted one."""
        p = c.execute(
            "SELECT * FROM proposal WHERE id = ? AND learner_id = ?", (payload["proposal_id"], learner)
        ).fetchone()
        if p is None:
            raise InvalidInput("unknown proposal")
        earlier = c.execute(
            "SELECT count(*) FROM learning_event WHERE type = 'tutor.proposal_decided' AND payload ->> '$.proposal_id' = ?",
            (p["id"],),
        ).fetchone()[0]
        if earlier > 1:  # this event is already inserted: one earlier decision means it was decided before
            raise InvalidInput("the proposal was already decided")
        if p["expires_at"] and p["expires_at"] < clock.now():
            raise InvalidInput("the proposal has expired")
        if payload["decision"] != "accepted":
            return
        change = json.loads(p["change"])
        if p["kind"] == "add_lesson":
            self.study.insert_request(c, learner, p["path_id"], change["prompt"], change.get("skill_id"))
        elif p["kind"] == "change_difficulty":
            row = c.execute(
                "SELECT difficulty, structure_version FROM path WHERE id = ?", (p["path_id"],)
            ).fetchone()
            c.execute(
                "INSERT INTO path_change (id, path_id, base_structure_version, structure_version, ops, origin, "
                "proposal_id, device_id, at) VALUES (?, ?, ?, ?, json(?), 'proposal', ?, NULL, ?)",
                (
                    new_id(),
                    p["path_id"],
                    row[1],
                    row[1] + 1,
                    json.dumps([{"op": "change_difficulty", "from": row[0], "to": change["difficulty"]}]),
                    p["id"],
                    clock.now(),
                ),
            )
            c.execute(
                "UPDATE path SET difficulty = ?, structure_version = ? WHERE id = ?",
                (change["difficulty"], row[1] + 1, p["path_id"]),
            )
        # extra_review: nothing to change; the client starts a review of that skill (start_reviews)

    # --- nudges -----------------------------------------------------------------------------

    def _nudge_at_breakpoint(
        self, c: sqlite3.Connection, learner: str, written: list[str]
    ) -> list[dict[str, Any]]:
        """Inside the ingest unit, after projections: at most one nudge for what this batch shows."""
        level = settings.effective(c, "tutor.proactivity", {"learner": learner})[0]
        if level == "off" or not written:
            return []
        marks = ",".join("?" * len(written))
        evs = c.execute(
            f"SELECT type, payload, attempt_id FROM learning_event WHERE id IN ({marks}) ORDER BY server_seq",
            written,
        ).fetchall()
        if self._open_test(c, learner) is not None:
            return []  # never during a test
        candidates: list[tuple[str, str | None, dict[str, Any]]] = []
        for etype, payload, attempt in evs:
            p = json.loads(payload)
            if etype == "skill.test_result" and not p["passed"]:
                skill = c.execute(
                    "SELECT title, path_id FROM skill WHERE id = ?", (p["skill_id"],)
                ).fetchone()
                candidates.append(("failed_test", skill[1], {"skill_id": p["skill_id"], "skill": skill[0]}))
            elif etype == "lesson.completed":
                row = c.execute(
                    "SELECT l.id, l.path_id, (SELECT count(*) FROM note n WHERE n.learner_id = ? AND n.sent_message_id "
                    "IS NULL AND n.anchor ->> '$.lesson_version_id' = v.id) FROM lesson_version v JOIN lesson l ON "
                    "l.id = v.lesson_id WHERE v.id = ?",
                    (learner, p["lesson_version_id"]),
                ).fetchone()
                if row and row[2] > 0:
                    candidates.append(("unsent_notes", row[1], {"lesson_id": row[0], "notes": row[2]}))
            elif etype == "assessment.response_given" and attempt:
                purpose = c.execute(
                    "SELECT a.purpose FROM attempt t JOIN assessment a ON a.id = t.assessment_id WHERE t.id = ?",
                    (attempt,),
                ).fetchone()
                if purpose is None or purpose[0] != "practice":
                    continue
                wrong = c.execute(
                    "SELECT o.statement, o.id, count(*), i.path_id FROM response x JOIN item_version_objective io ON "
                    "io.item_version_id = x.item_version_id JOIN learning_objective o ON o.id = io.objective_id "
                    "JOIN item_version v ON v.id = x.item_version_id JOIN item i ON i.id = v.item_id "
                    "WHERE x.score < 0.5 AND x.answered_at >= ? AND x.attempt_id IN (SELECT t.id FROM attempt t "
                    "WHERE t.learner_id = ?) GROUP BY o.id HAVING count(*) >= 2 ORDER BY max(x.answered_at) DESC LIMIT 1",
                    (self._session_start(c, learner), learner),
                ).fetchone()
                if wrong:
                    candidates.append(
                        (
                            "repeated_error",
                            wrong[3],
                            {"objective": wrong[0], "objective_id": wrong[1], "misses": wrong[2]},
                        )
                    )
                fast = c.execute(
                    "SELECT x.ms_to_answer, x.score, i.path_id FROM response x JOIN item_version v ON v.id = "
                    "x.item_version_id JOIN item i ON i.id = v.item_id WHERE x.attempt_id = ? AND i.type_key != "
                    "'flashcard' AND x.score IS NOT NULL ORDER BY x.answered_at DESC LIMIT 3",
                    (attempt,),
                ).fetchall()
                if len(fast) == 3 and all(f[0] < 2500 for f in fast) and sum(f[1] < 0.5 for f in fast) >= 2:
                    candidates.append(("fast_guessing", fast[0][2], {"answers": 3}))
        if not candidates:
            return []
        now = clock.parse_timestamp(clock.now())
        start = clock.parse_timestamp(self._session_start(c, learner))
        past = [
            nudges.Past(r[0], r[1], clock.parse_timestamp(r[2]))
            for r in c.execute(
                "SELECT trigger, status, created_at FROM nudge WHERE learner_id = ? AND created_at >= ?",
                (learner, clock.to_timestamp(now - timedelta(days=1))),
            )
        ]
        muted = list(settings.effective(c, "tutor.muted_triggers", {"learner": learner})[0] or [])
        for trigger, path_id, params in candidates:
            if nudges.may_nudge(level, trigger, now=now, session_start=start, past=past, muted=muted):
                nid = new_id()
                c.execute(
                    "INSERT INTO nudge (id, learner_id, path_id, trigger, params, status, created_at, decided_at) "
                    "VALUES (?, ?, ?, ?, json(?), 'shown', ?, NULL)",
                    (
                        nid,
                        learner,
                        path_id,
                        trigger,
                        json.dumps(params, ensure_ascii=False),
                        clock.to_timestamp(now),
                    ),
                )
                return [{"id": nid, "trigger": trigger, "path_id": path_id, "params": params, "level": level}]
        return []

    def _session_start(self, c: sqlite3.Connection, learner: str) -> str:
        now = clock.parse_timestamp(clock.now())
        recent = [
            clock.parse_timestamp(r[0])
            for r in c.execute(
                "SELECT device_at FROM learning_event WHERE learner_id = ? AND device_at >= ? ORDER BY device_at DESC LIMIT 500",
                (learner, clock.to_timestamp(now - timedelta(hours=12))),
            )
        ]
        return clock.to_timestamp(nudges.session_start(recent, now))

    def nudges(self) -> list[dict[str, Any]]:
        learner = self.learners.ensure_learner()
        with self.readers.connection() as c:
            level = settings.effective(c, "tutor.proactivity", {"learner": learner})[0]
            rows = _rows(
                c,
                "SELECT id, path_id, trigger, params, status, created_at FROM nudge WHERE learner_id = ? AND "
                "status = 'shown' ORDER BY created_at DESC LIMIT 5",
                learner,
            )
        for r in rows:
            r["params"] = json.loads(r["params"])
            r["level"] = level
        return rows

    def decide_nudge(self, nudge_id: str, action: str) -> None:
        """dismiss, accept, or mute ('Don't suggest this': mutes the trigger for good, reversible in settings)."""
        if action not in ("dismiss", "accept", "mute"):
            raise InvalidInput("action is dismiss, accept or mute")
        learner = self.learners.ensure_learner()

        def unit(c: sqlite3.Connection) -> None:
            row = c.execute(
                "SELECT trigger FROM nudge WHERE id = ? AND learner_id = ?", (nudge_id, learner)
            ).fetchone()
            if row is None:
                raise NotFound(nudge_id)
            status = {"dismiss": "dismissed", "accept": "accepted", "mute": "dismissed"}[action]
            c.execute(
                "UPDATE nudge SET status = ?, decided_at = ? WHERE id = ?", (status, clock.now(), nudge_id)
            )
            if action == "mute":
                muted = list(settings.effective(c, "tutor.muted_triggers", {"learner": learner})[0] or [])
                if row[0] not in muted:
                    settings.put(c, "tutor.muted_triggers", [*muted, row[0]], "learner", learner)

        self.writer.run(unit)


@dataclass(slots=True)
class _Outcome:
    text: str
    template: str | None = None
    guard: str | None = None
    leak_check: CheckVerdict | None = None
    withheld: str | None = None
    error: str | None = None
    detail: str | None = None
    calls: list[tuple[str, Completion, int]] = field(default_factory=list)
    actions: Actions | None = None
    model: str | None = None
    adapter: str | None = None


__all__ = ["POLICIES", "Tutor", "TutorWorker"]
