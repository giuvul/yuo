"""Review: the question bank per lesson, memory per learning objective, review sessions with
answer-until-correct feedback, and the hub. A part of the application service (yuo.app.context).

The bank: when a lesson is ready (buffered ahead) or completed, one writer call drafts its review
questions (`review_bank` stage); each passes deterministic rules, is shuffled and answered blind by the
reviewer model, and is published as an ordinary single-choice item with `extensions.yuo.use = "review"`.
A question the blind solver gets wrong is dropped: a wrong key teaches the wrong thing.
"""

import json
import sqlite3
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import structlog

from yuo.app.context import AppContext, Part
from yuo.app.items import Checked, ItemContext, publish_bank
from yuo.app.ports import ItemWriting, Learners
from yuo.app.stages import render_lesson, review_bank_spec
from yuo.assessment import review_bank as rb
from yuo.assessment import types as xt
from yuo.core import clock
from yuo.core.enums import DataClass, EntityKind
from yuo.core.errors import InvalidInput, NotFound
from yuo.core.ids import new_id
from yuo.generation.jobs import Job, enqueue
from yuo.generation.runner import StageFailed
from yuo.learning import projections as pj
from yuo.setup import settings

if TYPE_CHECKING:
    pass

log = structlog.get_logger(__name__)
BANK_JOB = "items"  # the generation_job kind of a review bank (target: the lesson)
BANK_PRIORITY = -5  # behind lessons and what the learner waits for
PARTNERS = 2  # partner lessons offered for cross-lesson questions
PARTNER_CHARS = 1500  # of each partner lesson's text
LOW_STOCK = 3  # top up a lesson's bank when an objective has fewer unseen questions than this
USE_REVIEW = "review"


def _rows(c: sqlite3.Connection, sql: str, *args: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in c.execute(sql, args).fetchall()]


def split_bank(size: int) -> tuple[int, int]:
    """Single-lesson and cross-lesson questions for a bank of `size` (8 + 3 at the default 11)."""
    cross = round(size * 3 / 11)
    return size - cross, cross


class Review(Part):
    """A part of the application service (yuo.app.context), built with what it calls on the others."""

    def __init__(self, ctx: AppContext, *, learners: Learners, study: ItemWriting) -> None:
        super().__init__(ctx)
        self.learners = learners
        self.study = study

    # --- the bank: one job per lesson ------------------------------------------------------------

    def queue_review_bank(self, c: sqlite3.Connection, lesson_id: str, *, top_up: bool = False) -> str | None:
        """Queue the bank job of a ready lesson once (inside a unit). A lesson that has questions is left
        alone unless `top_up` asks for more."""
        lesson = c.execute("SELECT current_version_id FROM lesson WHERE id = ?", (lesson_id,)).fetchone()
        if lesson is None or lesson[0] is None:
            return None
        busy = c.execute(
            "SELECT id FROM generation_job WHERE kind = ? AND target_id = ? AND status IN "
            "('queued','running','waiting_resource')",
            (BANK_JOB, lesson_id),
        ).fetchone()
        if busy:
            return str(busy[0])
        if not top_up and self._bank_count(c, lesson_id):
            return None
        return enqueue(
            c, BANK_JOB, EntityKind.LESSON, lesson_id, priority=BANK_PRIORITY, requested_by="system"
        )

    def _bank_count(self, c: sqlite3.Connection, lesson_id: str) -> int:
        return int(
            c.execute(
                "SELECT count(*) FROM item i JOIN item_version v ON v.id = i.current_version_id "
                "JOIN lesson_version lv ON lv.id = v.origin_lesson_version_id "
                "WHERE lv.lesson_id = ? AND i.extensions ->> '$.yuo.use' = ? AND v.status = 'passed'",
                (lesson_id, USE_REVIEW),
            ).fetchone()[0]
        )

    def _bank_inputs(self, c: sqlite3.Connection, lesson_id: str) -> dict[str, Any] | None:
        lesson = c.execute(
            "SELECT l.id, l.code, l.skill_id, l.path_id, l.position, v.id AS version_id, v.body, v.title "
            "FROM lesson l JOIN lesson_version v ON v.id = l.current_version_id WHERE l.id = ?",
            (lesson_id,),
        ).fetchone()
        if lesson is None:
            return None
        body = json.loads(lesson["body"])
        ctx = self.study.skill_context(c, lesson["skill_id"], USE_REVIEW, body, lesson["version_id"])
        # partners for cross-lesson questions: other ready lessons of the same skill or of a direct
        # prerequisite (the objective links the invariant allows), completed ones first, nearest first
        partners = _rows(
            c,
            "SELECT l.id, l.skill_id, v.title, v.body, EXISTS (SELECT 1 FROM learning_event e JOIN lesson_version x "
            "ON x.id = e.lesson_version_id WHERE e.type = 'lesson.completed' AND x.lesson_id = l.id) AS done "
            "FROM lesson l JOIN lesson_version v ON v.id = l.current_version_id JOIN skill s ON s.id = l.skill_id "
            "JOIN branch b ON b.id = s.branch_id WHERE l.id != ? AND (l.skill_id = ? OR l.skill_id IN "
            "(SELECT requires_skill_id FROM skill_prerequisite WHERE skill_id = ?)) "
            "ORDER BY done DESC, (l.skill_id = ?) DESC, b.position DESC, s.position DESC, l.position DESC LIMIT ?",
            lesson_id,
            lesson["skill_id"],
            lesson["skill_id"],
            lesson["skill_id"],
            PARTNERS,
        )
        partner_objectives: list[dict[str, Any]] = []
        shown = []
        for p in partners:
            objectives = _rows(
                c,
                "SELECT id, code, statement FROM learning_objective WHERE skill_id = ? AND archived_at IS NULL "
                "ORDER BY position",
                p["skill_id"],
            )
            partner_objectives += [
                o for o in objectives if o["code"] not in {x["code"] for x in partner_objectives}
            ]
            shown.append(
                {
                    "title": p["title"],
                    "objectives": [{"code": o["code"], "statement": o["statement"]} for o in objectives],
                    "summary": render_lesson(json.loads(p["body"]))[:PARTNER_CHARS],
                }
            )
        # never repeat what the learner has seen for this skill: practice items and earlier review questions
        avoid = [
            r[0]
            for r in c.execute(
                "SELECT coalesce(v.payload ->> '$.prompt', v.payload ->> '$.front', v.payload ->> '$.text') FROM item i "
                "JOIN item_version v ON v.id = i.current_version_id WHERE i.skill_id = ? AND v.status = 'passed'",
                (lesson["skill_id"],),
            )
            if r[0]
        ]
        size = int(settings.effective(c, "review.bank_size", {"path": lesson["path_id"]})[0])
        taken = c.execute(
            "SELECT count(*) FROM item WHERE path_id = ? AND code LIKE ? ESCAPE '\\'",
            (lesson["path_id"], lesson["code"].replace("%", "\\%").replace("_", "\\_") + ".r%"),
        ).fetchone()[0]
        return {
            "lesson": dict(lesson),
            "ctx": ctx,
            "partners": shown,
            "partner_objectives": partner_objectives,
            "avoid": avoid,
            "size": size,
            "taken": int(taken),
        }

    def handle_review_bank(self, job: Job) -> None:
        """Write, check and publish the review questions of one lesson."""
        with self.readers.connection() as c:
            inputs = self._bank_inputs(c, job.target_id)
        if inputs is None:  # the lesson went away or was never published: nothing to write
            return
        ctx: ItemContext = inputs["ctx"]
        gen, rev, independent = self.study.generator_and_reviewer()
        own = {o["code"] for o in ctx.objectives}
        own_ids = {o["id"] for o in ctx.objectives}
        partner_objectives = [o for o in inputs["partner_objectives"] if o["id"] not in own_ids]
        partner_codes = {o["code"] for o in partner_objectives}
        single, cross = split_bank(inputs["size"])
        if not partner_codes:
            cross = 0
        out = self.runner.run(
            job.id,
            review_bank_spec(own, partner_codes, inputs["avoid"], single, cross),
            gen,
            {
                "lang": ctx.lang,
                "single": single,
                "cross": cross,
                "objectives": [{"code": o["code"], "statement": o["statement"]} for o in ctx.objectives],
                "partners": inputs["partners"] if cross else [],
                "avoid": inputs["avoid"],
                "body": ctx.body,
            },
            data_class=ctx.data_class,
        )
        questions = rb.keep(out.value, own, partner_codes, inputs["avoid"])
        # the item links objectives of its own skill and of direct prerequisites (05 section 4)
        wide = ItemContext(
            ctx.path_id,
            ctx.skill_id,
            ctx.lang,
            ctx.difficulty,
            ctx.objectives + partner_objectives,
            ctx.skill_title,
            ctx.skill_summary,
            ctx.data_class,
            USE_REVIEW,
            ctx.body,
            ctx.origin_lesson_version_id,
        )
        t = xt.get("mcq")
        drafts = [
            Checked(f"{inputs['lesson']['code']}.r{n}", q.payload(), q.support(), f"{out.output_hash}:{n}",
                    q.objective_codes)
            for n, q in enumerate(questions, start=inputs["taken"] + 1)
        ]  # fmt: skip
        published = publish_bank(
            self.runner,
            self.writer,
            job.id,
            wide,
            t,
            drafts,
            rev,
            run_id=out.stage_run_id,
            upstream=out.output_hash,
            independent=independent,
        )
        kept = sum(v is not None for v in published)
        log.info(
            "review_bank.written",
            lesson=job.target_id,
            drafted=len(out.value.questions),
            passed_rules=len(questions),
            published=kept,
        )
        if kept == 0:
            raise StageFailed("no review question passed the checks")

    # --- memory per objective --------------------------------------------------------------------

    def _memory(
        self,
        c: sqlite3.Connection,
        learner: str,
        path_id: str,
        *,
        skill_id: str | None = None,
        branch_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """The learned objectives of a path (a lesson that teaches them was completed) with their memory."""
        now = clock.parse_timestamp(clock.now())
        sched = self.scheduler.tuned(*self._review_params(c, learner))
        rows = _rows(
            c,
            "SELECT o.id, o.code, o.statement, o.skill_id, s.title AS skill_title, s.branch_id, rs.state, rs.due_at, "
            "rs.lapses, rs.reviews, rs.last_review_at FROM learning_objective o JOIN skill s ON s.id = o.skill_id "
            "JOIN branch b ON b.id = s.branch_id JOIN objective_review_state rs ON rs.objective_id = o.id AND "
            "rs.learner_id = ? WHERE o.path_id = ? AND o.archived_at IS NULL AND (? IS NULL OR o.skill_id = ?) "
            "AND (? IS NULL OR s.branch_id = ?) ORDER BY b.position, s.position, o.position",
            learner,
            path_id,
            skill_id,
            skill_id,
            branch_id,
            branch_id,
        )
        for r in rows:
            state = json.loads(r.pop("state"))
            r["retrievability"] = round(sched.retrievability(state, now), 4)
            r["due"] = r["due_at"] <= clock.to_timestamp(now)
        return rows

    def _review_params(self, c: sqlite3.Connection, learner: str) -> tuple[float, int]:
        retention = settings.effective(c, "review.desired_retention", {"learner": learner})[0]
        cap = settings.effective(c, "review.max_interval_days", {"learner": learner})[0]
        return float(retention), int(cap)

    def _allowance(self, c: sqlite3.Connection, learner: str) -> int:
        """Review answers still allowed today, cards and questions together."""
        cap = int(settings.effective(c, "reviews.max_per_day", {"learner": learner})[0])
        today = c.execute(
            "SELECT learning_day FROM learning_event WHERE learner_id = ? ORDER BY server_seq DESC LIMIT 1",
            (learner,),
        ).fetchone()
        if not today:
            return cap
        done = c.execute(
            "SELECT count(DISTINCT e.attempt_id || e.item_version_id) FROM learning_event e JOIN assessment a ON "
            "a.id = (SELECT payload ->> '$.assessment_id' FROM learning_event s WHERE s.type = 'attempt.started' "
            "AND s.attempt_id = e.attempt_id) WHERE e.learner_id = ? AND e.type = 'assessment.response_given' "
            "AND e.learning_day = ? AND a.purpose = 'review'",
            (learner, today[0]),
        ).fetchone()[0]
        return max(0, cap - int(done))

    def _bank_items(self, c: sqlite3.Connection, learner: str, path_id: str) -> list[dict[str, Any]]:
        """Every live review question of the path: its objectives and when the learner last saw it."""
        rows = _rows(
            c,
            "SELECT i.id AS item_id, i.skill_id, i.code, v.id AS version_id, (SELECT json_group_array(objective_id) "
            "FROM item_version_objective WHERE item_version_id = v.id) AS objectives, (SELECT max(e.device_at) FROM "
            "learning_event e JOIN item_version x ON x.id = e.item_version_id WHERE x.item_id = i.id AND "
            "e.learner_id = ? AND e.type IN ('assessment.response_given', 'item.support_shown')) AS seen_at FROM item i JOIN item_version v "
            "ON v.id = i.current_version_id JOIN exercise_type t ON t.key = i.type_key WHERE i.path_id = ? AND "
            "i.extensions ->> '$.yuo.use' = ? AND i.extensions ->> '$.yuo.retired_at' IS NULL AND "
            "v.status = 'passed' AND t.status = 'installed' ORDER BY i.code",
            learner,
            path_id,
            USE_REVIEW,
        )
        for r in rows:
            r["objectives"] = sorted(json.loads(r["objectives"]))
        return rows

    # --- the hub ---------------------------------------------------------------------------------

    def review_hub(self, path_id: str) -> dict[str, Any]:
        learner = self.learners.ensure_learner()
        with self.readers.connection() as c:
            if c.execute("SELECT 1 FROM path WHERE id = ?", (path_id,)).fetchone() is None:
                raise NotFound(path_id)
            memory = self._memory(c, learner, path_id)
            items = self._bank_items(c, learner, path_id)
            learned = {m["id"] for m in memory}
            ready = [i for i in items if set(i["objectives"]) <= learned]
            writing = c.execute(
                "SELECT count(*) FROM generation_job WHERE kind = ? AND status IN ('queued','running',"
                "'waiting_resource') AND target_id IN (SELECT id FROM lesson WHERE path_id = ?)",
                (BANK_JOB, path_id),
            ).fetchone()[0]
            open_session = self._open_session(c, learner, path_id)
            recent = _rows(
                c,
                "SELECT t.id AS attempt_id, t.finished_at, t.score, json_array_length(a.item_version_ids) AS pinned, "
                "a.settings_snapshot ->> '$.review.size' AS size FROM attempt t JOIN assessment a ON a.id = "
                "t.assessment_id WHERE t.learner_id = ? AND t.finished_at IS NOT NULL AND a.settings_snapshot ->> "
                "'$.review.kind' = 'bank' AND a.settings_snapshot ->> '$.review.path_id' = ? "
                "ORDER BY t.finished_at DESC LIMIT 5",
                learner,
                path_id,
            )
            for r in recent:
                outcomes = [
                    pj.item_outcome(c, learner, r["attempt_id"], v)
                    for v in pj._session_items(c, r["attempt_id"])
                ]
                answered = [o for o in outcomes if o.tries or o.revealed]
                r["answered"] = len(answered)
                r["first_try"] = sum(o.kind == "first" for o in answered)
                del r["pinned"], r["score"], r["size"]
            allowance = self._allowance(c, learner)
            cards = c.execute(
                "SELECT count(*) FROM review_state rs JOIN item i ON i.id = rs.item_id JOIN item_version v ON "
                "v.id = i.current_version_id WHERE rs.learner_id = ? AND rs.due_at <= ? AND v.status = 'passed' "
                "AND i.path_id = ?",
                (learner, clock.now(), path_id),
            ).fetchone()[0]
            branches = _rows(c, "SELECT id, title FROM branch WHERE path_id = ? ORDER BY position", path_id)
        skills: dict[str, dict[str, Any]] = {}
        for m in memory:
            sk = skills.setdefault(
                m["skill_id"],
                {
                    "id": m["skill_id"],
                    "title": m["skill_title"],
                    "branch_id": m["branch_id"],
                    "objectives": [],
                },
            )
            sk["objectives"].append(
                {
                    "id": m["id"],
                    "statement": m["statement"],
                    "retrievability": m["retrievability"],
                    "due": m["due"],
                    "due_at": m["due_at"],
                    "reviews": m["reviews"],
                }
            )
        for sk in skills.values():
            rs = [o["retrievability"] for o in sk["objectives"]]
            sk["retrievability"] = round(sum(rs) / len(rs), 4)
            sk["due"] = sum(o["due"] for o in sk["objectives"])
            sk["questions"] = sum(1 for i in ready if i["skill_id"] == sk["id"])
        rs = [m["retrievability"] for m in memory]
        return {
            "path_id": path_id,
            "memory": round(sum(rs) / len(rs), 4) if rs else None,
            "objectives": len(memory),
            "due": sum(m["due"] for m in memory),
            "fading": sum(1 for m in memory if not m["due"] and m["retrievability"] < FADING_BELOW),
            "strong": sum(1 for m in memory if m["retrievability"] >= STRONG_FROM),
            "questions": len(ready),
            "writing": int(writing),
            "allowed_today": allowance,
            "sizes": [n for n in SIZES if n <= max(len(ready), SIZES[0]) and len(ready) > 0],
            "open_session": open_session,
            "skills": sorted(skills.values(), key=lambda s: (s["retrievability"], s["title"])),
            "branches": [b for b in branches if any(s["branch_id"] == b["id"] for s in skills.values())],
            "recent": recent,
            "cards_due": int(cards),
        }

    def _open_session(self, c: sqlite3.Connection, learner: str, path_id: str) -> dict[str, Any] | None:
        """The newest unfinished review session of the path, with how far it got."""
        row = c.execute(
            "SELECT a.id, a.item_version_ids, a.settings_snapshot FROM assessment a WHERE a.learner_id = ? AND "
            "a.purpose = 'review' AND a.settings_snapshot ->> '$.review.kind' = 'bank' AND a.settings_snapshot ->> "
            "'$.review.path_id' = ? AND a.created_at >= ? AND NOT EXISTS (SELECT 1 FROM learning_event s JOIN "
            "learning_event f ON f.attempt_id = s.attempt_id AND f.type = 'attempt.finished' WHERE s.type = "
            "'attempt.started' AND s.payload ->> '$.assessment_id' = a.id) ORDER BY a.created_at DESC LIMIT 1",
            (learner, path_id, clock.to_timestamp(clock.parse_timestamp(clock.now()) - OPEN_FOR)),
        ).fetchone()
        if row is None:
            return None
        attempt = c.execute(
            "SELECT attempt_id FROM learning_event WHERE type = 'attempt.started' AND payload ->> "
            "'$.assessment_id' = ? ORDER BY device_at DESC, id DESC LIMIT 1",
            (row[0],),
        ).fetchone()
        review = json.loads(row[2])["review"]
        answered = 0
        if attempt:
            answered = sum(
                1 for v in json.loads(row[1]) if pj.item_outcome(c, learner, attempt[0], v).resolved
            )
        return {
            "assessment_id": row[0],
            "attempt_id": attempt[0] if attempt else None,
            "size": review["size"],
            "answered": answered,
        }

    # --- sessions --------------------------------------------------------------------------------

    def start_review_session(
        self, path_id: str, size: int = 10, *, skill_id: str | None = None, branch_id: str | None = None
    ) -> dict[str, Any]:
        """Resume the open session of the path, or build a new one."""
        learner = self.learners.ensure_learner()

        def unit(c: sqlite3.Connection) -> dict[str, Any]:
            existing = self._open_session(c, learner, path_id)
            if existing is not None:
                return self._session_view(c, learner, existing["assessment_id"], existing["attempt_id"])
            memory = self._memory(c, learner, path_id, skill_id=skill_id, branch_id=branch_id)
            items = self._bank_items(c, learner, path_id)
            learned = (
                {m["id"] for m in self._memory(c, learner, path_id)} if (skill_id or branch_id) else None
            )
            wanted = min(size, self._allowance(c, learner))
            primaries, reserves = build_session(memory, items, wanted, now=clock.now(), learned=learned)
            if not primaries:
                return {"assessment_id": None, "attempt_id": None, "items": [], "reserves": [], "size": 0}
            aid = new_id()
            snapshot = {
                k: settings.effective(c, k, {"learner": learner})[0]
                for k in ("practice.solution_after", "skill_test.pass_mark", "tutor.test_policy")
            } | {
                "review": {
                    "kind": "bank",
                    "size": len(primaries),
                    "reserve_from": len(primaries),
                    "path_id": path_id,
                    "focus": {"skill_id": skill_id, "branch_id": branch_id},
                }
            }
            c.execute(
                "INSERT INTO assessment (id, learner_id, purpose, skill_id, item_version_ids, policy, pass_mark, "
                "settings_snapshot, created_at) VALUES (?, ?, 'review', ?, json(?), 'review', NULL, json(?), ?)",
                (
                    aid,
                    learner,
                    skill_id,
                    json.dumps([i["version_id"] for i in primaries + reserves]),
                    json.dumps(snapshot),
                    clock.now(),
                ),
            )
            return self._session_view(c, learner, aid, None)

        return self.writer.run(unit)

    def _session_view(
        self, c: sqlite3.Connection, learner: str, assessment_id: str, attempt_id: str | None
    ) -> dict[str, Any]:
        a = c.execute(
            "SELECT item_version_ids, settings_snapshot FROM assessment WHERE id = ?", (assessment_id,)
        ).fetchone()
        review = json.loads(a[1])["review"]
        out: list[dict[str, Any]] = []
        for vid in json.loads(a[0]):
            row = c.execute(
                "SELECT v.payload, i.id AS item_id, i.skill_id, s.title AS skill_title FROM item_version v JOIN item i "
                "ON i.id = v.item_id JOIN skill s ON s.id = i.skill_id WHERE v.id = ?",
                (vid,),
            ).fetchone()
            payload = json.loads(row["payload"])
            objectives = [
                r[0]
                for r in c.execute(
                    "SELECT objective_id FROM item_version_objective WHERE item_version_id = ? ORDER BY objective_id",
                    (vid,),
                )
            ]
            item: dict[str, Any] = {
                "item_version_id": vid,
                "item_id": row["item_id"],
                "type": "mcq",
                "view": xt.get("mcq").view(payload, seed=vid),
                "skill_id": row["skill_id"],
                "skill_title": row["skill_title"],
                "objectives": objectives,
                "cross": len(objectives) > 1,
                "kind": payload.get("kind", "recall"),
                "level": int(payload.get("level", 1)),
                "state": None,
            }
            if attempt_id:
                item["state"] = self._feedback(c, learner, attempt_id, vid)
            out.append(item)
        cut = int(review["reserve_from"])
        return {
            "assessment_id": assessment_id,
            "attempt_id": attempt_id,
            "purpose": "review",
            "path_id": review["path_id"],
            "size": int(review["size"]),
            "items": out[:cut],
            "reserves": out[cut:],
        }

    # --- staged feedback: nothing that gives the answer away before the question is resolved ------

    def _feedback(
        self, c: sqlite3.Connection, learner: str, attempt_id: str, item_version_id: str
    ) -> dict[str, Any]:
        """What the learner may see about a review question now. Before it is resolved: the rationale of
        each option they tried, never the key, the other rationales or the explanation."""
        o = pj.item_outcome(c, learner, attempt_id, item_version_id)
        row = c.execute(
            "SELECT v.payload, v.support, l.id AS lesson_id, lv.title AS lesson_title FROM item_version v "
            "LEFT JOIN lesson_version lv ON lv.id = v.origin_lesson_version_id LEFT JOIN lesson l ON "
            "l.id = lv.lesson_id WHERE v.id = ?",
            (item_version_id,),
        ).fetchone()
        payload, support = json.loads(row["payload"]), json.loads(row["support"])
        why = {e["id"]: e["why"] for e in support.get("explanations", [])}
        tried = [str(answer) for _, answer, _ in o.tries]
        view: dict[str, Any] = {
            "outcome": o.kind,
            "resolved": o.resolved,
            "tries": len(o.tries),
            "tried": tried,
            "hints": o.hints,
            "guessing": o.guessing,
            "score": 1.0 if o.kind == "first" else 0.5 if o.kind == "second" else 0.0,
            "pending": False,
            "rationales": {k: why[k] for k in tried if k in why},
        }
        if not o.resolved:
            return view
        return view | {
            "correct": payload["answer"],
            "rationales": why,
            "solution": support.get("solution", ""),
            "concept": payload.get("concept"),
            "revisit": payload.get("revisit"),
            "lesson_id": row["lesson_id"],
            "lesson_title": row["lesson_title"],
        }

    def review_feedback(self, attempt_id: str, item_version_id: str) -> dict[str, Any]:
        learner = self.learners.ensure_learner()
        with self.readers.connection() as c:
            if item_version_id not in pj._session_items(c, attempt_id) or not pj.is_bank(c, attempt_id):
                raise NotFound("not a question of this review session")
            return self._feedback(c, learner, attempt_id, item_version_id)

    def check_review_answer(self, c: sqlite3.Connection, learner: str, payload: dict[str, Any]) -> bool:
        """Before an answer is stored: True when it belongs to a review session over the bank. A resolved
        question takes no further answer (the third try, or one after "Show answer")."""
        if not pj.is_bank(c, payload["attempt_id"]):
            return False
        if payload["item_version_id"] not in pj._session_items(c, payload["attempt_id"]):
            raise InvalidInput("this question is not part of the review session")
        if pj.item_outcome(c, learner, payload["attempt_id"], payload["item_version_id"]).resolved:
            raise InvalidInput("this question is already resolved")
        return True

    def review_result(self, attempt_id: str) -> dict[str, Any]:
        """The results of a review session: outcomes, XP, memory before and after per skill."""
        learner = self.learners.ensure_learner()
        with self.readers.connection() as c:
            if not pj.is_bank(c, attempt_id):
                raise NotFound(attempt_id)
            finished = c.execute(
                "SELECT device_at FROM learning_event WHERE type = 'attempt.finished' AND attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            now = clock.parse_timestamp(clock.now())
            sched = self.scheduler.tuned(*self._review_params(c, learner))
            items = []
            by_objective: dict[str, list[pj.Outcome]] = {}
            for vid in pj._session_items(c, attempt_id):
                o = pj.item_outcome(c, learner, attempt_id, vid)
                if not (o.tries or o.revealed):
                    continue
                fb = self._feedback(c, learner, attempt_id, vid)
                prompt = c.execute(
                    "SELECT payload ->> '$.prompt' FROM item_version WHERE id = ?", (vid,)
                ).fetchone()
                items.append({"item_version_id": vid, "prompt": prompt[0]} | fb)
                for (oid,) in c.execute(
                    "SELECT objective_id FROM item_version_objective WHERE item_version_id = ?", (vid,)
                ):
                    by_objective.setdefault(oid, []).append(o)
            skills: dict[str, dict[str, Any]] = {}
            for oid in by_objective:
                meta = c.execute(
                    "SELECT o.skill_id, s.title FROM learning_objective o JOIN skill s ON s.id = o.skill_id "
                    "WHERE o.id = ?",
                    (oid,),
                ).fetchone()
                before_state, *_ = pj.objective_history(c, learner, oid, sched, before_attempt=attempt_id)
                after = c.execute(
                    "SELECT state, due_at FROM objective_review_state WHERE learner_id = ? AND objective_id = ?",
                    (learner, oid),
                ).fetchone()
                at = clock.parse_timestamp(finished[0]) if finished else now
                sk = skills.setdefault(
                    meta[0], {"id": meta[0], "title": meta[1], "before": [], "after": [], "next_due": None}
                )
                sk["before"].append(sched.retrievability(before_state, at) if before_state else 0.0)
                if after:
                    sk["after"].append(sched.retrievability(json.loads(after[0]), now))
                    sk["next_due"] = min(filter(None, [sk["next_due"], after[1]]))
            for sk in skills.values():
                sk["before"] = round(sum(sk["before"]) / len(sk["before"]), 4)
                sk["after"] = round(sum(sk["after"]) / len(sk["after"]), 4) if sk["after"] else None
            gamification = settings.effective(c, "gamification", {"learner": learner})[0]
            xp = pj.review_session_xp(c, learner, attempt_id) if gamification == "full" else None
        first = sum(i["outcome"] == "first" for i in items)
        return {
            "attempt_id": attempt_id,
            "finished": finished is not None,
            "answered": len(items),
            "first_try": first,
            "second_try": sum(i["outcome"] == "second" for i in items),
            "revealed": sum(i["outcome"] in ("revealed", "open") for i in items),
            "score": round(first / len(items), 4) if items else 0.0,
            "xp": xp,
            "skills": sorted(skills.values(), key=lambda s: s["title"]),
            "items": items,
        }

    def after_review_session(self, c: sqlite3.Connection, learner: str, attempt_id: str) -> None:
        """When a session finishes: top up the bank of lessons whose objectives are running out of unseen
        questions (inside the ingest unit)."""
        if not pj.is_bank(c, attempt_id):
            return
        for (oid,) in c.execute(
            "SELECT DISTINCT objective_id FROM item_version_objective WHERE item_version_id IN "
            "(SELECT value FROM json_each(?))",
            (json.dumps(pj._session_items(c, attempt_id)),),
        ).fetchall():
            unseen = c.execute(
                "SELECT count(*) FROM item i JOIN item_version v ON v.id = i.current_version_id JOIN "
                "item_version_objective o ON o.item_version_id = v.id WHERE o.objective_id = ? AND "
                "i.extensions ->> '$.yuo.use' = ? AND i.extensions ->> '$.yuo.retired_at' IS NULL AND "
                "v.status = 'passed' AND NOT EXISTS (SELECT 1 FROM learning_event e JOIN item_version x ON "
                "x.id = e.item_version_id WHERE x.item_id = i.id AND e.learner_id = ? AND e.type IN "
                "('assessment.response_given', 'item.support_shown'))",
                (oid, USE_REVIEW, learner),
            ).fetchone()[0]
            if unseen >= LOW_STOCK:
                continue
            lesson = c.execute(
                "SELECT l.id, l.path_id, l.code FROM lesson l JOIN lesson_version_objective o ON "
                "o.lesson_version_id = l.current_version_id WHERE o.objective_id = ? ORDER BY l.position LIMIT 1",
                (oid,),
            ).fetchone()
            if lesson is None:
                continue
            size = int(settings.effective(c, "review.bank_size", {"path": lesson[1]})[0])
            written = c.execute(
                "SELECT count(*) FROM item WHERE path_id = ? AND code LIKE ?", (lesson[1], lesson[2] + ".r%")
            ).fetchone()[0]
            if written < MAX_BANKS * size:  # bounded: a lesson's bank is written at most a few times
                self.queue_review_bank(c, lesson[0], top_up=True)

    def report_item(self, item_id: str, reason: str = "") -> None:
        """A learner reports a review question as wrong or unclear: it leaves the bank at once."""

        def unit(c: sqlite3.Connection) -> None:
            row = c.execute("SELECT extensions FROM item WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise NotFound(item_id)
            ext = json.loads(row[0])
            if ext.get("yuo", {}).get("use") != USE_REVIEW:
                raise InvalidInput("only review questions can be reported")
            ext["yuo"] |= {"retired_at": clock.now(), "retired_reason": reason[:300]}
            c.execute("UPDATE item SET extensions = json(?) WHERE id = ?", (json.dumps(ext), item_id))

        self.writer.run(unit)


# --- the session builder: a pure function of memory, bank and time ------------------------------------

SIZES = (5, 10, 20)
FADING_BELOW = 0.8  # not due yet, but worth a look
STRONG_FROM = 0.9
CROSS_SHARE = 0.25
RECENT = timedelta(days=2)  # a question seen this recently is not asked again if another fits
OPEN_FOR = timedelta(days=2)  # an unfinished session older than this is not resumed
MAX_BANKS = 3


def build_session(
    memory: list[dict[str, Any]],
    items: list[dict[str, Any]],
    size: int,
    *,
    now: str,
    learned: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pick the questions of a session and one reserve per objective.

    `memory`: the objectives in focus (id, skill_id, retrievability, due, lapses). `items`: the bank
    (version_id, skill_id, objectives, seen_at). `learned`: every learned objective when the focus is
    narrower than the path (a cross question needs all its objectives learned).

    Priority of an objective: 2(1 - R) + 1 if due + 0.3 x lapses. Unseen questions first; none seen in the
    last two days if another fits; at most a third of the session per skill; about a quarter cross-lesson
    questions; no skill twice in a row. Deterministic: ties break on the question's code order.
    """
    if size <= 0 or not memory:
        return [], []
    prio = {
        m["id"]: 2 * (1 - m["retrievability"]) + (1 if m["due"] else 0) + 0.3 * m["lapses"] for m in memory
    }
    focus = set(prio)
    known = learned if learned is not None else focus
    cutoff = clock.to_timestamp(clock.parse_timestamp(now) - RECENT)
    usable = [i for i in items if set(i["objectives"]) <= known and set(i["objectives"]) & focus]
    order = {i["version_id"]: n for n, i in enumerate(usable)}

    def freshness(i: dict[str, Any]) -> tuple[int, str, int]:
        # unseen first, then the one seen longest ago
        return (0 if i["seen_at"] is None else 1, i["seen_at"] or "", order[i["version_id"]])

    def recent(i: dict[str, Any]) -> bool:
        return i["seen_at"] is not None and i["seen_at"] > cutoff

    singles = [i for i in usable if len(i["objectives"]) == 1]
    crosses = [i for i in usable if len(i["objectives"]) > 1]
    skills = {m["skill_id"] for m in memory}
    cap = max(1, -(-size // 3)) if len(skills) >= 3 else size
    chosen: list[dict[str, Any]] = []
    per_skill: dict[str, int] = {}
    taken: set[str] = set()

    def take(i: dict[str, Any]) -> None:
        chosen.append(i)
        taken.add(i["version_id"])
        per_skill[i["skill_id"]] = per_skill.get(i["skill_id"], 0) + 1

    cross_target = min(round(size * CROSS_SHARE), len(crosses)) if size >= 4 else 0
    for strict in (True, False):  # second pass: relax the per-skill cap and the two-day rule
        # cross questions by the summed priority of their objectives
        for i in sorted(crosses, key=lambda i: (-sum(prio.get(o, 0) for o in i["objectives"]), freshness(i))):
            if sum(1 for x in chosen if len(x["objectives"]) > 1) >= cross_target:
                break
            if i["version_id"] in taken or (strict and (recent(i) or per_skill.get(i["skill_id"], 0) >= cap)):
                continue
            take(i)
        # single questions: objectives by priority, one question each per round
        by_objective: dict[str, list[dict[str, Any]]] = {}
        for i in sorted(singles, key=freshness):
            by_objective.setdefault(i["objectives"][0], []).append(i)
        ranked = sorted(by_objective, key=lambda o: (-prio[o], o))
        progress = True
        while len(chosen) < size and progress:
            progress = False
            for o in ranked:
                if len(chosen) >= size:
                    break
                pick = next(
                    (
                        i
                        for i in by_objective[o]
                        if i["version_id"] not in taken
                        and not (strict and (recent(i) or per_skill.get(i["skill_id"], 0) >= cap))
                    ),
                    None,
                )
                if pick is not None:
                    take(pick)
                    progress = True
        if len(chosen) >= size:
            break
    # no skill twice in a row where the mix allows it
    ordered: list[dict[str, Any]] = []
    pool = list(chosen)
    while pool:
        last = ordered[-1]["skill_id"] if ordered else None
        pick = next((i for i in pool if i["skill_id"] != last), pool[0])
        pool.remove(pick)
        ordered.append(pick)
    # one reserve per objective of the session: asked only when a question on it was revealed
    reserves: list[dict[str, Any]] = []
    for o in dict.fromkeys(o for i in ordered for o in i["objectives"] if o in focus):
        spare = next(
            (
                i
                for i in sorted(singles, key=freshness)
                if i["objectives"] == [o] and i["version_id"] not in taken
            ),
            None,
        )
        if spare is not None:
            reserves.append(spare)
            taken.add(spare["version_id"])
    return ordered, reserves


__all__ = ["BANK_JOB", "USE_REVIEW", "DataClass", "Review", "build_session", "split_bank"]
