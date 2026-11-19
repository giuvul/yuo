"""Learning loop: practice for every exercise type, the review queue (FSRS), skill tests with
unlocks and remedial lessons, placement, model grading and contests, the lesson buffer, lesson requests,
notes, progress (mastery, XP, streaks). A part of the application service (yuo.app.context).
"""

import json
import sqlite3
from typing import TYPE_CHECKING, Any

import structlog

from yuo.app.context import AppContext, Part
from yuo.app.erasure import projection_settings
from yuo.app.items import ITEM_MATERIAL_BUDGET, TEST_TYPES, ItemContext, make_items, practice_mix
from yuo.app.ports import Learners, Models, PathInputs, SettingsReader
from yuo.app.repo import get_skill
from yuo.app.stages import grade_spec, place_spec
from yuo.assessment import types as xt
from yuo.core import clock
from yuo.core.enums import DataClass, EntityKind, EventType
from yuo.core.errors import Conflict, InvalidInput, NotFound
from yuo.core.ids import new_id
from yuo.generation.jobs import Job, enqueue
from yuo.generation.lanes import Lane, lane
from yuo.generation.runner import StageFailed
from yuo.learning import events as ev
from yuo.learning import projections as pj
from yuo.setup import models, settings

if TYPE_CHECKING:
    pass

log = structlog.get_logger(__name__)
TEST_SIZE = 5  # items per skill test
PLACEMENT_PER_SKILL = 2
MOCK_MAX = 20  # questions in a course's mock exam: two per skill, one when the course has more than ten


def _rows(c: sqlite3.Connection, sql: str, *args: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in c.execute(sql, args).fetchall()]


class Study(Part):
    """A part of the application service (yuo.app.context), built with what it calls on the others."""

    def __init__(
        self,
        ctx: AppContext,
        *,
        learners: Learners,
        models: Models,
        paths: PathInputs,
        config: SettingsReader,
    ) -> None:
        super().__init__(ctx)
        self.learners = learners
        self.models = models
        self.paths = paths
        self.config = config

    # --- settings snapshot for projections -------------------------------------------------------

    def _proj_settings(self, c: sqlite3.Connection, learner: str) -> pj.Settings:
        return projection_settings(c, learner)

    def skill_context(
        self,
        c: sqlite3.Connection,
        skill_id: str,
        use: str,
        body: list[dict[str, Any]] | None = None,
        origin: str | None = None,
    ) -> ItemContext:
        s = get_skill(c, skill_id)
        inputs, dclass = self.paths.path_inputs(c, s["path_id"])
        objectives = _rows(
            c,
            "SELECT id, code, statement FROM learning_objective WHERE skill_id = ? AND "
            "archived_at IS NULL ORDER BY position",
            skill_id,
        )
        # questions on a skill built on the learner's material are written from it (the lesson's share of it
        # for a lesson's practice), and under "only my material" must be answerable from it alone
        lesson = (
            c.execute("SELECT lesson_id FROM lesson_version WHERE id = ?", (origin,)).fetchone()
            if origin
            else None
        )
        material = self.paths.skill_material(c, skill_id, lesson[0] if lesson else "", ITEM_MATERIAL_BUDGET)
        if material:
            dclass = DataClass.FREE_TEXT
        return ItemContext(
            s["path_id"],
            skill_id,
            inputs["lang"],
            inputs["difficulty"],
            objectives,
            s["title"],
            s["summary"],
            dclass,
            use,
            body,
            origin,
            material,
        )

    def generator_and_reviewer(self) -> tuple[Any, Any, bool]:
        gen, rev = self.models.binding("generator"), self.models.binding("reviewer")
        return gen, rev, models.independence_warning(gen, rev) is None

    # --- practice set after a lesson ------------------------------------------------------

    def make_practice(
        self, job: Job, lesson: dict[str, Any], version_id: str, body: list[dict[str, Any]]
    ) -> None:
        gen, rev, independent = self.generator_and_reviewer()
        with self.readers.connection() as c:
            ctx = self.skill_context(c, lesson["skill_id"], "practice", body, version_id)
            enabled = settings.effective(c, "practice.types", {"path": lesson["path_id"]})[0]
            # the mix rotates along the whole path: most skills have one or two lessons, so a position
            # inside the skill would give every lesson the same types (found by the browser tests)
            ordinal = c.execute(
                "SELECT count(*) FROM lesson l JOIN skill s ON s.id = l.skill_id JOIN branch b ON b.id = s.branch_id "
                "JOIN skill me ON me.id = ? JOIN branch mb ON mb.id = me.branch_id "
                "WHERE l.path_id = ? AND l.kind = 'core' AND (b.position, s.position, l.position) < (mb.position, me.position, ?)",
                (lesson["skill_id"], lesson["path_id"], lesson["position"]),
            ).fetchone()[0]
        # one batch per lesson: the items are written one by one and blind-solved together. An item that
        # cannot be made does not undo the published lesson; budget stops still stop
        wanted = [
            (t, f"{lesson['code']}.q{n}") for n, t in enumerate(practice_mix(ordinal, enabled), start=1)
        ]
        made = make_items(self.runner, self.writer, job.id, ctx, wanted, gen, rev, independent=independent)
        for (type_key, _), ok in zip(wanted, made, strict=True):
            if ok is None:
                log.warning("practice.item_failed", lesson=lesson["id"], type=type_key)

    def start_practice(self, lesson_id: str) -> dict[str, Any]:
        with self.readers.connection() as c:
            lesson = c.execute(
                "SELECT skill_id, current_version_id FROM lesson WHERE id = ?", (lesson_id,)
            ).fetchone()
            if lesson is None or lesson["current_version_id"] is None:
                raise Conflict(f"lesson {lesson_id} is not ready")
            ids = [
                r[0]
                for r in c.execute(
                    "SELECT v.id FROM item i JOIN item_version v ON v.id = i.current_version_id "
                    "WHERE v.origin_lesson_version_id = ? AND i.extensions ->> '$.yuo.use' IS NOT 'review' "
                    "ORDER BY i.code",
                    (lesson["current_version_id"],),
                )
            ]
        return self._assessment("practice", lesson["skill_id"], ids)

    def _assessment(
        self,
        purpose: str,
        skill_id: str | None,
        version_ids: list[str],
        pass_mark: float | None = None,
        mock_course: str | None = None,
    ) -> dict[str, Any]:
        learner = self.learners.ensure_learner()
        aid = new_id()

        def unit(c: sqlite3.Connection) -> dict[str, Any]:
            if version_ids:  # an item of a type this install does not have is kept, never shown (spec §6)
                playable = {
                    r[0]
                    for r in c.execute(
                        "SELECT v.id FROM item_version v JOIN item i ON i.id = v.item_id JOIN exercise_type t "
                        "ON t.key = i.type_key WHERE t.status = 'installed' AND v.id IN (SELECT value FROM json_each(?))",
                        (json.dumps(version_ids),),
                    )
                }
                version_ids[:] = [v for v in version_ids if v in playable]
            snapshot = {
                k: settings.effective(c, k, {"learner": learner})[0]
                for k in ("practice.solution_after", "skill_test.pass_mark", "tutor.test_policy")
            }
            if (
                mock_course
            ):  # a course's mock exam: a skill test with no skill, scored per skill, nothing mastered
                snapshot["mock_course"] = mock_course
            c.execute(
                "INSERT INTO assessment (id, learner_id, purpose, skill_id, item_version_ids, policy, pass_mark, "
                "settings_snapshot, created_at) VALUES (?, ?, ?, ?, json(?), ?, ?, json(?), ?)",
                (
                    aid,
                    learner,
                    purpose,
                    skill_id,
                    json.dumps(version_ids),
                    "test_locked"
                    if purpose in ("skill_test", "placement")
                    else purpose
                    if purpose != "practice"
                    else "practice",
                    pass_mark,
                    json.dumps(snapshot),
                    clock.now(),
                ),
            )
            items = []
            for vid in version_ids:
                row = c.execute(
                    "SELECT v.payload, i.type_key FROM item_version v JOIN item i ON i.id = v.item_id "
                    "WHERE v.id = ?",
                    (vid,),
                ).fetchone()
                t = xt.get(row[1])
                items.append(
                    {"item_version_id": vid, "type": t.key, "view": t.view(json.loads(row[0]), seed=vid)}
                )
            return {"assessment_id": aid, "purpose": purpose, "items": items}

        return self.writer.run(unit)

    # --- grading on ingest -----------------------------------------------------------------------

    def _purpose_of(self, c: sqlite3.Connection, attempt_id: str) -> str:
        row = c.execute(
            "SELECT a.purpose FROM learning_event e JOIN assessment a ON a.id = e.payload ->> "
            "'$.assessment_id' WHERE e.type = 'attempt.started' AND e.attempt_id = ?",
            (attempt_id,),
        ).fetchone()
        return str(row[0]) if row else "practice"

    def _grade_now(
        self,
        c: sqlite3.Connection,
        response_id: str,
        payload: dict[str, Any],
        learner: str,
        tz: str,
        boundary: str,
    ) -> dict[str, Any] | None:
        """Exact, rule and self types are graded at once; model types get a grading job."""
        row = c.execute(
            "SELECT v.payload, v.support, i.type_key FROM item_version v JOIN item i ON i.id = v.item_id "
            "WHERE v.id = ?",
            (payload["item_version_id"],),
        ).fetchone()
        if row is None:
            raise InvalidInput("unknown item version")
        item, support, t = json.loads(row[0]), json.loads(row[1]), xt.get(row[2])
        score = t.grade(item, payload["answer"])
        if score is None:
            enqueue(c, "grade", EntityKind.RESPONSE, response_id, priority=10)
            return {"pending": True}
        self._write_grade(c, response_id, payload, t.method.value, score, learner, tz, boundary)
        return _grade_view(t, item, support, payload["answer"], score)

    def _write_grade(
        self,
        c: sqlite3.Connection,
        response_id: str,
        payload: dict[str, Any],
        method: str,
        score: float,
        learner: str,
        tz: str,
        boundary: str,
        **extra: Any,
    ) -> str:
        gid = new_id()
        grade = {
            "response_event_id": response_id,
            "attempt_id": payload["attempt_id"],
            "item_version_id": payload["item_version_id"],
            "grading_method": method,
            "score": round(score, 6),
            "reason": extra.pop("reason", "initial"),
            **{k: v for k, v in extra.items() if v is not None},
        }
        ev.insert_event(
            c,
            event_id=gid,
            etype=EventType.RESPONSE_GRADED,
            payload=grade,
            learner_id=learner,
            device_id=ev.server_device(c),
            device_at=clock.now(),
            tz=tz,
            boundary=boundary,
        )
        return gid

    def existing_grade(self, c: sqlite3.Connection, response_id: str) -> dict[str, Any] | None:
        row = c.execute(
            "SELECT e.payload, v.payload, v.support, i.type_key, r.payload ->> '$.answer' FROM learning_event e "
            "JOIN item_version v ON v.id = e.item_version_id JOIN item i ON i.id = v.item_id "
            "JOIN learning_event r ON r.id = e.payload ->> '$.response_event_id' "
            "WHERE e.type = 'assessment.response_graded' AND e.payload ->> '$.response_event_id' = ? "
            "ORDER BY e.server_seq DESC LIMIT 1",
            (response_id,),
        ).fetchone()
        if row is None:
            return {"pending": True}
        g = json.loads(row[0])
        answer = json.loads(
            c.execute("SELECT payload FROM learning_event WHERE id = ?", (response_id,)).fetchone()[0]
        )
        view = _grade_view(
            xt.get(row[3]), json.loads(row[1]), json.loads(row[2]), answer["answer"], g["score"]
        )
        if g.get("rationale"):
            view["rationale"] = g["rationale"]
        return view

    def handle_grade(self, job: Job) -> None:
        """Model grading of one response: the grader sees the learner's answer as data (class F)."""
        with self.readers.connection() as c:
            resp = c.execute("SELECT * FROM learning_event WHERE id = ?", (job.target_id,)).fetchone()
            p = json.loads(resp["payload"])
            item = json.loads(
                c.execute(
                    "SELECT payload FROM item_version WHERE id = ?", (p["item_version_id"],)
                ).fetchone()[0]
            )
            contest = c.execute(
                "SELECT payload ->> '$.reason_text', payload ->> '$.grade_event_id' FROM learning_event WHERE "
                "type = 'assessment.grade_contested' AND payload ->> '$.response_event_id' = ? ORDER BY server_seq "
                "DESC LIMIT 1",
                (job.target_id,),
            ).fetchone()
            graded_before = c.execute(
                "SELECT id, payload ->> '$.score' FROM learning_event WHERE type = 'assessment.response_graded' AND "
                "payload ->> '$.response_event_id' = ? ORDER BY server_seq DESC LIMIT 1",
                (job.target_id,),
            ).fetchone()
            boundary = c.execute(
                "SELECT day_boundary FROM learner WHERE id = ?", (resp["learner_id"],)
            ).fetchone()[0]
        inputs = {"payload": item, "answer": str(p["answer"])[:4000]}
        if contest and graded_before:
            inputs["contest"] = contest[0]
        with lane(Lane.NEAR):  # the learner is waiting for this grade
            out = self.runner.run(
                job.id,
                grade_spec(item),
                self.models.binding("grader"),
                inputs,
                data_class=DataClass.FREE_TEXT,
                role="grader",
            )
        score = xt.rubric_score(item, out.value)
        reason = "initial"
        if contest and graded_before:
            reason = "contest_upheld" if abs(score - float(graded_before[1])) > 1e-6 else "contest_rejected"

        def unit(c: sqlite3.Connection) -> None:
            self._write_grade(
                c,
                job.target_id,
                p,
                "model",
                score,
                resp["learner_id"],
                resp["tz"],
                boundary,
                reason=reason,
                rationale=out.value.rationale,
                grader_stage_run_id=out.stage_run_id,
                supersedes_grade_event_id=graded_before[0] if graded_before else None,
            )
            self.project_events(c, resp["learner_id"], [job.target_id])

        self.writer.run(unit)

    def project_events(self, c: sqlite3.Connection, learner: str, event_ids: list[str]) -> None:
        pj.apply(c, learner, pj.touched_by(c, event_ids), self.scheduler, self._proj_settings(c, learner))

    # --- attempts finishing: skill tests and placement -------------------------------------------

    def _finish_attempt(
        self, c: sqlite3.Connection, learner: str, payload: dict[str, Any], tz: str, boundary: str
    ) -> tuple[dict[str, Any] | None, list[str]]:
        """Server-side outcome events for tests (never trusted from the device); returns a result for the client
        and the ids of the events written."""
        started = c.execute(
            "SELECT payload FROM learning_event WHERE type = 'attempt.started' AND attempt_id = ?",
            (payload["attempt_id"],),
        ).fetchone()
        if started is None:
            return None, []
        a = c.execute(
            "SELECT * FROM assessment WHERE id = ?", (json.loads(started[0])["assessment_id"],)
        ).fetchone()
        if a["purpose"] not in ("skill_test", "placement"):
            return None, []
        pj.rebuild_attempt(c, learner, payload["attempt_id"], self._proj_settings(c, learner))
        pinned = json.loads(a["item_version_ids"])
        scores = {
            r[0]: r[1]
            for r in c.execute(
                "SELECT e.payload ->> '$.item_version_id', max(e.payload ->> '$.score') FROM learning_event e WHERE "
                "e.type = 'assessment.response_graded' AND e.attempt_id = ? GROUP BY 1",
                (payload["attempt_id"],),
            )
        }
        # hints with cost: an answer the tutor helped with counts half
        for vid, kind in c.execute(
            "SELECT item_version_id, help_kind FROM response WHERE attempt_id = ?", (payload["attempt_id"],)
        ).fetchall():
            if kind == "tutor" and vid in scores:
                scores[vid] = float(scores[vid]) * pj.HELP_WEIGHT["tutor"]
        written: list[str] = []
        server = ev.server_device(c)
        mark = float(a["pass_mark"] or 0.8)
        mock = json.loads(a["settings_snapshot"] or "{}").get("mock_course")
        if mock:  # a mock exam: the score and each skill's share, no test result or placement written
            per_skill: dict[str, list[float]] = {}
            for v in pinned:
                sid = c.execute(
                    "SELECT i.skill_id FROM item_version v JOIN item i ON i.id = v.item_id WHERE v.id = ?",
                    (v,),
                ).fetchone()[0]
                per_skill.setdefault(sid, []).append(float(scores.get(v, 0.0)))
            score = sum(float(scores.get(v, 0.0)) for v in pinned) / len(pinned)
            return {
                "mock": {
                    "course_id": mock,
                    "score": round(score, 6),
                    "pass_mark": mark,
                    "passed": score >= mark - 1e-9,
                    "skills": {k: round(sum(x) / len(x), 6) for k, x in per_skill.items()},
                }
            }, written
        if a["purpose"] == "skill_test":
            score = sum(float(scores.get(v, 0.0)) for v in pinned) / len(pinned)
            passed = score >= mark - 1e-9
            eid = new_id()
            ev.insert_event(
                c,
                event_id=eid,
                etype=EventType.SKILL_TEST_RESULT,
                learner_id=learner,
                device_id=server,
                device_at=clock.now(),
                tz=tz,
                boundary=boundary,
                payload={
                    "skill_id": a["skill_id"],
                    "attempt_id": payload["attempt_id"],
                    "passed": passed,
                    "score": round(score, 6),
                    "pass_mark": mark,
                },
            )
            written.append(eid)
            if not passed:
                self._queue_remedial(
                    c, a["skill_id"], [v for v in pinned if float(scores.get(v, 0.0)) < 0.999]
                )
            return {"skill_id": a["skill_id"], "passed": passed, "score": score, "pass_mark": mark}, written
        by_skill: dict[str, list[float]] = {}
        for v in pinned:
            sid = c.execute(
                "SELECT i.skill_id FROM item_version v JOIN item i ON i.id = v.item_id WHERE v.id = ?", (v,)
            ).fetchone()[0]
            by_skill.setdefault(sid, []).append(float(scores.get(v, 0.0)))
        placed = {}
        for sid, xs in by_skill.items():
            result = "mastered" if sum(xs) / len(xs) >= mark - 1e-9 else "not_mastered"
            eid = new_id()
            ev.insert_event(
                c,
                event_id=eid,
                etype=EventType.SKILL_PLACED,
                learner_id=learner,
                device_id=server,
                device_at=clock.now(),
                tz=tz,
                boundary=boundary,
                payload={"skill_id": sid, "attempt_id": payload["attempt_id"], "result": result},
            )
            written.append(eid)
            placed[sid] = result
        return {"placed": placed}, written

    def stored_outcome(self, c: sqlite3.Connection, attempt_id: str) -> dict[str, Any] | None:
        rows = c.execute(
            "SELECT type, payload FROM learning_event WHERE attempt_id = ? AND type IN "
            "('skill.test_result', 'skill.placed') ORDER BY server_seq",
            (attempt_id,),
        ).fetchall()
        if not rows:
            return None
        if rows[0][0] == "skill.test_result":
            p = json.loads(rows[0][1])
            return {k: p[k] for k in ("skill_id", "passed", "score", "pass_mark")}
        return {"placed": {json.loads(p)["skill_id"]: json.loads(p)["result"] for _, p in rows}}

    def reveal(self, item_version_id: str) -> dict[str, Any]:
        """Flashcards: the back, shown after the learner tried to recall it and before they rate themselves.
        Flipping is the normal flashcard flow, not help: no `item.support_shown` event, the rating is the evidence."""
        with self.readers.connection() as c:
            row = c.execute(
                "SELECT v.payload, i.type_key FROM item_version v JOIN item i ON i.id = v.item_id "
                "WHERE v.id = ? AND v.status = 'passed'",
                (item_version_id,),
            ).fetchone()
        if row is None or row[1] != "flashcard":
            raise Conflict("only flashcards can be revealed before answering")
        return {"back": json.loads(row[0])["back"]}

    def _queue_remedial(self, c: sqlite3.Connection, skill_id: str, missed: list[str]) -> None:
        """A short lesson on what the failed test showed, placed after the skill's lessons."""
        s = c.execute("SELECT path_id, code FROM skill WHERE id = ?", (skill_id,)).fetchone()
        n = c.execute(
            "SELECT count(*) FROM lesson WHERE skill_id = ? AND kind = 'remedial'", (skill_id,)
        ).fetchone()[0]
        pos = c.execute(
            "SELECT coalesce(max(position), -1) + 1 FROM lesson WHERE skill_id = ?", (skill_id,)
        ).fetchone()[0]
        prompts = []
        for v in missed:
            p = json.loads(c.execute("SELECT payload FROM item_version WHERE id = ?", (v,)).fetchone()[0])
            prompts.append(str(p.get("prompt") or p.get("text") or p.get("front") or "")[:300])
        lid = new_id()
        c.execute(
            "INSERT INTO lesson (id, skill_id, path_id, code, kind, position, state, current_version_id, "
            "extensions) VALUES (?, ?, ?, ?, 'remedial', ?, 'queued', NULL, json(?))",
            (
                lid,
                skill_id,
                s["path_id"],
                f"{s['code']}.remedial{n + 1}",
                pos,
                json.dumps({"yuo": {"planned_title": None, "remedial": prompts}}),
            ),
        )
        enqueue(c, "lesson", EntityKind.LESSON, lid, requested_by="system", priority=5)

    # --- skill tests and placement -------------------------------------------------

    def test_items(self, c: sqlite3.Connection, skill_id: str, use: str = "test") -> list[str]:
        return [
            r[0]
            for r in c.execute(
                "SELECT v.id FROM item i JOIN item_version v ON v.id = i.current_version_id WHERE i.skill_id = ? "
                "AND i.extensions ->> '$.yuo.use' = ? ORDER BY i.code",
                (skill_id, use),
            )
        ]

    def start_skill_test(self, skill_id: str) -> dict[str, Any]:
        learner = self.learners.ensure_learner()
        with self.readers.connection() as c:
            if c.execute("SELECT 1 FROM skill WHERE id = ?", (skill_id,)).fetchone() is None:
                raise NotFound(f"skill {skill_id}")
            bank = self.test_items(c, skill_id)
            mark = float(settings.effective(c, "skill_test.pass_mark", {"learner": learner})[0])
        if len(bank) < TEST_SIZE:
            return {"job_id": self._queue_once("test_bank", EntityKind.SKILL, skill_id)}
        return self._assessment("skill_test", skill_id, bank[:TEST_SIZE], pass_mark=mark)

    def handle_test_bank(self, job: Job) -> None:
        gen, rev, independent = self.generator_and_reviewer()
        with self.readers.connection() as c:
            ctx = self.skill_context(c, job.target_id, "test")
            have = len(self.test_items(c, job.target_id))
            code = c.execute("SELECT code FROM skill WHERE id = ?", (job.target_id,)).fetchone()[0]
            avoid = [
                str(json.loads(r[0]).get("prompt") or json.loads(r[0]).get("text") or "")[:200]
                for r in c.execute(
                    "SELECT v.payload FROM item i JOIN item_version v ON v.id = i.current_version_id WHERE i.skill_id = ?",
                    (job.target_id,),
                )
            ]
        # a retry writes the missing questions as other kinds, so one kind that keeps failing its checks for
        # this skill does not hold the whole test back
        wanted = [
            (TEST_TYPES[(n - 2 + job.attempt) % len(TEST_TYPES)], f"{code}.t{n}")
            for n in range(have + 1, TEST_SIZE + 1)
        ]
        make_items(
            self.runner, self.writer, job.id, ctx, wanted, gen, rev, independent=independent, avoid=avoid
        )
        with self.readers.connection() as c:
            if len(self.test_items(c, job.target_id)) < TEST_SIZE:
                raise StageFailed(
                    "could not build a full skill test: some items were rejected", retryable=True
                )

    def start_mock_exam(self, course_id: str) -> dict[str, Any]:
        """A course's mock exam: questions from every skill's test bank, scored like a skill test at the end, with
        no mastery written. Skills whose bank is not written yet are queued first (the client asks again)."""
        with self.readers.connection() as c:
            row = c.execute("SELECT branch_id FROM course WHERE id = ?", (course_id,)).fetchone()
            if row is None:
                raise NotFound(f"course {course_id}")
            if row[0] is None:
                raise Conflict("the course is not built yet")
            skills = [
                r[0]
                for r in c.execute(
                    "SELECT id FROM skill WHERE branch_id = ? AND archived_at IS NULL ORDER BY position",
                    (row[0],),
                )
            ][:MOCK_MAX]
            if not skills:
                raise Conflict("the course has no skills")
            banks = {s: self.test_items(c, s) for s in skills}
            mark = float(self.config.setting("skill_test.pass_mark"))
            # a skill whose questions could not all be written (its last bank job failed) goes in with what it has
            gave_up = {
                s
                for s in skills
                if c.execute(
                    "SELECT status FROM generation_job WHERE kind = 'test_bank' AND target_id = ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (s,),
                ).fetchone()
                == ("failed",)
            }
        per = 2 if len(skills) * 2 <= MOCK_MAX else 1
        missing = [s for s in skills if len(banks[s]) < per and s not in gave_up]
        if missing:
            jobs = [self._queue_once("test_bank", EntityKind.SKILL, s) for s in missing]
            return {"job_id": jobs[0]}
        items = [v for s in skills for v in banks[s][:per]]
        if not items:
            raise Conflict("no questions could be written for this course")
        return self._assessment("skill_test", None, items, pass_mark=mark, mock_course=course_id)

    def start_placement(self, path_id: str) -> dict[str, Any]:
        mark = float(self.config.setting("skill_test.pass_mark"))
        with self.readers.connection() as c:
            skills = [
                r[0]
                for r in c.execute("SELECT id FROM skill WHERE path_id = ? ORDER BY position", (path_id,))
            ]
            if not skills:
                raise Conflict(f"path {path_id} has no skills yet")
            items = [v for s in skills for v in self.test_items(c, s, "placement")]
        if len(items) < len(skills) * PLACEMENT_PER_SKILL:
            return {"job_id": self._queue_once("placement", EntityKind.PATH, path_id)}
        return self._assessment("placement", None, items, pass_mark=mark)

    def handle_placement(self, job: Job) -> None:
        gen, rev, independent = self.generator_and_reviewer()
        with self.readers.connection() as c:
            skills = _rows(
                c,
                "SELECT s.id, s.code FROM skill s JOIN branch b ON b.id = s.branch_id WHERE s.path_id = ? "
                "ORDER BY b.position, s.position",
                job.target_id,
            )
        for s in skills:
            with self.readers.connection() as c:
                ctx = self.skill_context(c, s["id"], "placement")
                have = len(self.test_items(c, s["id"], "placement"))
            wanted = [
                (TEST_TYPES[n % 2], f"{s['code']}.p{n}") for n in range(have + 1, PLACEMENT_PER_SKILL + 1)
            ]
            make_items(self.runner, self.writer, job.id, ctx, wanted, gen, rev, independent=independent)

    def _queue_once(self, kind: str, target_kind: EntityKind, target_id: str) -> str:
        def unit(c: sqlite3.Connection) -> str:
            row = c.execute(
                "SELECT id FROM generation_job WHERE kind = ? AND target_id = ? AND status IN "
                "('queued','running','waiting_resource')",
                (kind, target_id),
            ).fetchone()
            return str(row[0]) if row else enqueue(c, kind, target_kind, target_id)

        job = self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return job

    # --- review queue ---------------------------------------------------------------------

    def due_reviews(self, path_id: str | None = None) -> dict[str, Any]:
        learner = self.learners.ensure_learner()
        now = clock.now()
        with self.readers.connection() as c:
            cap = int(settings.effective(c, "reviews.max_per_day", {"learner": learner})[0])
            today = c.execute(
                "SELECT learning_day FROM learning_event WHERE learner_id = ? ORDER BY server_seq DESC "
                "LIMIT 1",
                (learner,),
            ).fetchone()
            done = 0
            if today:
                done = c.execute(
                    "SELECT count(*) FROM learning_event e JOIN assessment a ON a.id = (SELECT payload ->> "
                    "'$.assessment_id' FROM learning_event s WHERE s.type = 'attempt.started' AND s.attempt_id = "
                    "e.attempt_id) WHERE e.learner_id = ? AND e.type = 'assessment.response_given' AND "
                    "e.learning_day = ? AND a.purpose = 'review'",
                    (learner, today[0]),
                ).fetchone()[0]
            rows = c.execute(
                "SELECT rs.item_id, i.current_version_id, rs.due_at FROM review_state rs JOIN item i ON i.id = rs.item_id "
                "JOIN item_version v ON v.id = i.current_version_id WHERE rs.learner_id = ? AND rs.due_at <= ? "
                "AND v.status = 'passed' AND (? IS NULL OR i.path_id = ?) ORDER BY rs.due_at",
                (learner, now, path_id, path_id),
            ).fetchall()
        left = max(0, cap - done)
        return {"due": len(rows), "allowed_today": left, "item_version_ids": [r[1] for r in rows[:left]]}

    def start_reviews(self, path_id: str | None = None, skill_id: str | None = None) -> dict[str, Any]:
        if skill_id is not None:  # an extra review the learner accepted: that skill's cards, due or not
            learner = self.learners.ensure_learner()
            with self.readers.connection() as c:
                ids = [
                    r[0]
                    for r in c.execute(
                        "SELECT i.current_version_id FROM review_state rs JOIN item i ON i.id = rs.item_id JOIN "
                        "item_version v ON v.id = i.current_version_id WHERE rs.learner_id = ? AND i.skill_id = ? "
                        "AND v.status = 'passed' ORDER BY rs.due_at LIMIT 10",
                        (learner, skill_id),
                    )
                ]
            if not ids:
                return {"assessment_id": None, "purpose": "review", "items": [], "due": 0}
            return self._assessment("review", skill_id, ids)
        due = self.due_reviews(path_id)
        if not due["item_version_ids"]:
            return {"assessment_id": None, "purpose": "review", "items": [], "due": due["due"]}
        return self._assessment("review", None, due["item_version_ids"])

    # --- buffer of lessons ahead -------------------------------------------

    def top_up_buffer(self, c: sqlite3.Connection, path_id: str) -> list[str]:
        """Keep `generation.buffer` lessons ready or on their way ahead of the learner (inside a unit)."""
        size = int(settings.effective(c, "generation.buffer", {"path": path_id})[0])
        lessons = c.execute(
            "SELECT l.id, l.state, l.current_version_id FROM lesson l JOIN skill s ON s.id = l.skill_id JOIN branch b "
            "ON b.id = s.branch_id WHERE l.path_id = ? AND s.archived_at IS NULL ORDER BY b.position, s.position, "
            "l.position",
            (path_id,),
        ).fetchall()
        done = {
            r[0]
            for r in c.execute(
                "SELECT v.lesson_id FROM learning_event e JOIN lesson_version v ON v.id = e.lesson_version_id "
                "WHERE e.type = 'lesson.completed'"
            )
        }
        ahead = sum(
            1
            for lid, state, _ in lessons
            if lid not in done and state in ("ready", "queued", "generating", "in_review")
        )
        queued = []
        for lid, state, _ in lessons:
            if ahead >= size:
                break
            if state == "planned":
                c.execute("UPDATE lesson SET state = 'queued' WHERE id = ?", (lid,))
                enqueue(c, "lesson", EntityKind.LESSON, lid, requested_by="buffer")
                queued.append(lid)
                ahead += 1
        return queued

    # --- lesson requests ------------------------------------------------------------------

    def request(
        self, path_id: str, prompt: str, links: list[str], skill_id: str | None = None
    ) -> dict[str, str]:
        self.models.require_ai_ready()
        learner = self.learners.ensure_learner()

        def unit(c: sqlite3.Connection) -> tuple[str, str]:
            return self.insert_request(c, learner, path_id, prompt, skill_id, links)

        rid, job = self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return {"request_id": rid, "job_id": job}

    def insert_request(
        self,
        c: sqlite3.Connection,
        learner: str,
        path_id: str,
        prompt: str,
        skill_id: str | None,
        links: list[str] | None = None,
    ) -> tuple[str, str]:
        """Inside a unit: the request row and its job (also used for an accepted tutor proposal)."""
        if c.execute("SELECT 1 FROM path WHERE id = ?", (path_id,)).fetchone() is None:
            raise NotFound(path_id)
        rid, now = new_id(), clock.now()
        c.execute(
            "INSERT INTO lesson_request (id, learner_id, path_id, skill_id, prompt, links, status, lesson_id, "
            "error, created_at, updated_at) VALUES (?, ?, ?, ?, ?, json(?), 'pending', NULL, NULL, ?, ?)",
            (rid, learner, path_id, skill_id, prompt, json.dumps(links or []), now, now),
        )
        return rid, enqueue(c, "request", EntityKind.LESSON_REQUEST, rid)

    def handle_request(self, job: Job) -> None:
        with self.readers.connection() as c:
            r = c.execute("SELECT * FROM lesson_request WHERE id = ?", (job.target_id,)).fetchone()
            inputs, _ = self.paths.path_inputs(c, r["path_id"])
            skills = _rows(
                c, "SELECT id, code, title FROM skill WHERE path_id = ? AND archived_at IS NULL", r["path_id"]
            )
        self.writer.run(
            lambda c: c.execute(
                "UPDATE lesson_request SET status = 'running', updated_at = ? WHERE id = ?",
                (clock.now(), job.target_id),
            )
        )
        try:
            skill_id, title = r["skill_id"], None
            if skill_id is None:
                codes = {s["code"] for s in skills}
                out = self.runner.run(
                    job.id,
                    place_spec(codes),
                    self.models.binding("utility"),
                    {
                        "lang": inputs["lang"],
                        "prompt": r["prompt"],
                        "skills": [{"code": s["code"], "title": s["title"]} for s in skills],
                    },
                    data_class=DataClass.FREE_TEXT,
                    role="utility",
                )
                skill_id = next(s["id"] for s in skills if s["code"] == out.value.skill_code)
                title = out.value.title

            def unit(c: sqlite3.Connection) -> None:
                s = c.execute("SELECT code FROM skill WHERE id = ?", (skill_id,)).fetchone()
                n = c.execute(
                    "SELECT count(*) FROM lesson WHERE skill_id = ? AND kind = 'requested'", (skill_id,)
                ).fetchone()[0]
                pos = c.execute(
                    "SELECT coalesce(max(position), -1) + 1 FROM lesson WHERE skill_id = ?", (skill_id,)
                ).fetchone()[0]
                lid = new_id()
                c.execute(
                    "INSERT INTO lesson (id, skill_id, path_id, code, kind, position, state, current_version_id, "
                    "extensions) VALUES (?, ?, ?, ?, 'requested', ?, 'queued', NULL, json(?))",
                    (
                        lid,
                        skill_id,
                        r["path_id"],
                        f"{s['code']}.req{n + 1}",
                        pos,
                        json.dumps(
                            {"yuo": {"planned_title": title or r["prompt"][:80], "request_id": r["id"]}}
                        ),
                    ),
                )
                c.execute(
                    "UPDATE lesson_request SET status = 'done', lesson_id = ?, updated_at = ? WHERE id = ?",
                    (lid, clock.now(), r["id"]),
                )
                enqueue(c, "lesson", EntityKind.LESSON, lid, priority=5)

            self.writer.run(unit)
        except Exception as e:
            msg = str(e)[:500]
            self.writer.run(
                lambda c: c.execute(
                    "UPDATE lesson_request SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
                    (msg, clock.now(), job.target_id),
                )
            )
            raise

    # --- notes -----------------------------------------------------------------------------------

    def add_note(
        self,
        text: str,
        *,
        lesson_version_id: str | None = None,
        bid: str | None = None,
        rendition_version_id: str | None = None,
        t_s: float | None = None,
    ) -> str:
        learner = self.learners.ensure_learner()
        nid, now = new_id(), clock.now()
        anchor = {"lesson_version_id": lesson_version_id, "bid": bid} if lesson_version_id else None
        self.writer.run(
            lambda c: c.execute(
                "INSERT INTO note (id, learner_id, rendition_version_id, t_s, anchor, text, sent_message_id, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, json(?), ?, NULL, ?, ?)",
                (
                    nid,
                    learner,
                    rendition_version_id,
                    t_s,
                    json.dumps(anchor) if anchor else None,
                    text,
                    now,
                    now,
                ),
            )
        )
        return nid

    def notes(self, lesson_id: str) -> list[dict[str, Any]]:
        with self.readers.connection() as c:
            return _rows(
                c,
                "SELECT n.id, n.text, n.anchor ->> '$.bid' AS bid, n.anchor ->> '$.lesson_version_id' AS "
                "lesson_version_id, n.sent_message_id, n.created_at, n.updated_at, n.rendition_version_id, n.t_s "
                "FROM note n LEFT JOIN lesson_version v ON v.id = n.anchor ->> '$.lesson_version_id' "
                "WHERE v.lesson_id = ? OR n.rendition_version_id IN (SELECT rv.id FROM rendition_version rv JOIN "
                "rendition r ON r.id = rv.rendition_id WHERE r.lesson_id = ?) ORDER BY n.created_at",
                lesson_id,
                lesson_id,
            )

    def edit_note(self, note_id: str, text: str) -> None:
        def unit(c: sqlite3.Connection) -> None:
            if (
                c.execute(
                    "UPDATE note SET text = ?, updated_at = ? WHERE id = ?", (text, clock.now(), note_id)
                ).rowcount
                == 0
            ):
                raise NotFound(note_id)

        self.writer.run(unit)

    def delete_note(self, note_id: str) -> None:
        """Notes are plain rows; secure_delete zeroes the freed bytes."""
        self.writer.run(lambda c: c.execute("DELETE FROM note WHERE id = ?", (note_id,)))

    # --- progress view ---------------------------------------------------------------------------

    def progress(self, path_id: str) -> dict[str, Any]:
        learner = self.learners.ensure_learner()
        with self.readers.connection() as c:
            s = self._proj_settings(c, learner)
            skills = pj.progress_view(c, learner, path_id, self.scheduler, s)
            days = _rows(
                c,
                "SELECT learning_day, xp, sessions, streak_len, grace_used FROM xp_daily WHERE learner_id = ? "
                "ORDER BY learning_day",
                learner,
            )
            ach = _rows(c, "SELECT key, unlocked_at FROM achievement WHERE learner_id = ?", learner)
            level_setting = settings.effective(c, "gamification", {"learner": learner})[0]
            branches = _rows(
                c, "SELECT b.id, b.title FROM branch b WHERE b.path_id = ? ORDER BY b.position", path_id
            )
            for b in branches:
                xp = c.execute(
                    "SELECT coalesce(sum(CASE WHEN r.score >= 0.8 THEN 10 ELSE 0 END), 0) FROM response r JOIN "
                    "item_version v ON v.id = r.item_version_id JOIN item i ON i.id = v.item_id JOIN skill s ON s.id = "
                    "i.skill_id WHERE s.branch_id = ?",
                    (b["id"],),
                ).fetchone()[0]
                b["xp"] = xp
                b["level"] = int((xp / 100) ** 0.5) + 1
        total = sum(d["xp"] for d in days)
        last = days[-1] if days else None
        out: dict[str, Any] = {"skills": skills, "gamification": level_setting}
        if level_setting != "off":
            out["branches"] = branches
        if level_setting == "full":
            out |= {
                "xp_total": total,
                "streak": last["streak_len"] if last else 0,
                "days": days[-30:],
                "achievements": ach,
            }
        return out


def _grade_view(
    t: xt.ExerciseType, item: dict[str, Any], support: dict[str, Any], answer: Any, score: float
) -> dict[str, Any]:
    why = {e["id"]: e["why"] for e in support.get("explanations", [])}
    explanation = why.get(answer) if isinstance(answer, str) else None
    return {
        "score": score,
        "correct": t.correct(item),
        "explanation": explanation,
        "solution": support.get("solution", ""),
        "pending": False,
    }
