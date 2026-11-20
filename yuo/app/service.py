"""Application service: create path -> skill tree -> one reading lesson through the gate
-> read it -> one practice item -> events through the outbox.

The gate: the version is written unpublished, deterministic checks run first (they already ran
before the repair round, and are recorded), then the independent reviewer; a failed review gets one fix
round with the findings, then the lesson fails. Items: deterministic checks, then blind solve.
"""

import dataclasses
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from yuo.adapters.scheduler import FsrsScheduler
from yuo.app.context import AppContext, Part
from yuo.app.erasure import Erasure
from yuo.app.forms import PathForm
from yuo.app.home import Home
from yuo.app.job_status import JOB_COLUMNS, JobStatus
from yuo.app.material import Materials
from yuo.app.next_steps import NextSteps
from yuo.app.onboarding import Onboarding
from yuo.app.pausing import Pausing
from yuo.app.plan_preview import PlanPreview
from yuo.app.repo import find_path, get_path, get_skill, path_state, save_path_state
from yuo.app.review import Review
from yuo.app.sharing import Sharing
from yuo.app.stages import LEVEL_CHECK, REVIEW, TREE_MAX_TOKENS, lesson_spec, tree_spec
from yuo.app.study import Study
from yuo.app.tutor import Tutor
from yuo.app.video import Video
from yuo.app.video_links import VideoLinks
from yuo.assessment import types as xt
from yuo.content.lesson_body import LessonDraft, plain_text, to_body
from yuo.content.review import gate_verdict
from yuo.core import clock
from yuo.core.enums import CheckVerdict, DataClass, EntityKind, EventType
from yuo.core.errors import AiNotReady, Conflict, InvalidInput, NotFound
from yuo.core.hashing import content_hash
from yuo.core.ids import new_id
from yuo.core.llm import Binding, Role
from yuo.core.media import RendererPort, TTSPort
from yuo.curriculum import level_check as lc
from yuo.curriculum.depth import depth_of
from yuo.curriculum.tree import apply_tree
from yuo.db.blobs import BlobStore
from yuo.db.connection import ReadPool, Writer
from yuo.generation import estimate as est
from yuo.generation.jobs import MAX_ATTEMPTS, URGENT_PRIORITY, Job, enqueue
from yuo.generation.runner import BudgetExceeded, StageFailed, StageRunner
from yuo.learning import events as ev
from yuo.learning import projections as pj
from yuo.setup import models, settings

log = structlog.get_logger(__name__)


def _rows(c: sqlite3.Connection, sql: str, *args: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in c.execute(sql, args).fetchall()]


# a lesson the learner asked for goes ahead of the lessons written ahead of them (and of videos)
ASKED_PRIORITY = 5


@dataclass
class _Batch:
    """What one outbox batch has produced so far (Service.ingest)."""

    learner: str
    device_id: str
    boundary: str
    graded: dict[str, Any] = field(default_factory=dict)
    outcomes: dict[str, Any] = field(default_factory=dict)
    written: list[str] = field(default_factory=list)  # event ids stored now, to project
    paths: set[str] = field(default_factory=set)  # paths with a lesson completed: top up their buffer


class Service(Part):
    """The application service: a facade over the feature parts (yuo.app.context). A method not defined here is
    looked up on the parts, so callers (the API, the composition root, tests) keep one object to talk to."""

    def __init__(
        self,
        writer: Writer,
        readers: ReadPool,
        runner: StageRunner,
        prices: est.PriceSource,
        scheduler: pj.Scheduler | None = None,
        *,
        renderer: RendererPort | None = None,
        voices: dict[str, TTSPort] | None = None,
        ffmpeg: Any = None,
        blobs: BlobStore | None = None,
        media_dir: Path | None = None,
    ) -> None:
        super().__init__(
            AppContext(
                writer, readers, runner, prices, scheduler or FsrsScheduler(), renderer=renderer,
                voices=voices or {}, ffmpeg=ffmpeg, blobs=blobs, media_dir=media_dir or Path(".dev") / "media",
            )
        )  # fmt: skip
        # the parts, each built with what it calls on the others (yuo.app.ports); the service is the core
        # they share: the learner, the model bindings, settings, and what generation needs about a path
        self.study = Study(self.ctx, learners=self, models=self, paths=self, config=self)
        self.reviews = Review(self.ctx, learners=self, study=self.study)
        self.tutor = Tutor(self.ctx, learners=self, models=self, study=self.study)
        self.videos = Video(self.ctx, models=self, paths=self)
        self.sharing = Sharing(self.ctx, learners=self, buffer=self.study)
        self.next_steps = NextSteps(self.ctx, models=self, paths=self, buffer=self.study)
        self.wizard = Onboarding(self.ctx, learners=self)
        self.preview = PlanPreview(self.ctx, models=self, paths=self, buffer=self.study)
        self.materials = Materials(self.ctx, learners=self, models=self, paths=self, buffer=self.study)
        self.jobs = JobStatus(self.ctx, lessons=self, videos=self.videos)
        self.dashboard = Home(self.ctx, learners=self, reviews=self.reviews)
        self.pausing = Pausing(self.ctx)
        self.video_links = VideoLinks(self.ctx, models=self)
        self._parts: tuple[Part, ...] = (
            self.study, self.reviews, self.tutor, self.videos, self.sharing, self.next_steps, self.wizard, self.jobs,
            self.preview, self.materials, self.dashboard, self.pausing, self.video_links,
        )  # fmt: skip
        self.erasure = Erasure(writer, readers, blobs, self.scheduler, self.ensure_learner)

    def __getattr__(self, name: str) -> Any:
        # only reached when normal lookup fails: a public method of a part
        for part in self.__dict__.get("_parts", ()):
            if hasattr(type(part), name):
                return getattr(part, name)
        raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}")

    def handlers(self) -> dict[str, Any]:
        return {
            "tree": self.handle_tree,
            "lesson": self.handle_lesson,
            "test_bank": self.study.handle_test_bank,
            "placement": self.study.handle_placement,
            "items": self.reviews.handle_review_bank,
            "grade": self.study.handle_grade,
            "request": self.study.handle_request,
            "rendition": self.videos.handle_rendition,
            "material": self.materials.handle_material,
            "course": self.materials.handle_course,
            "course_links": self.materials.handle_links,
        }

    # --- subscription CLIs: checked before any generation ----------------------------------------

    def cli_needed(self) -> list[str]:
        """The subscription CLIs the bound models run through ("claude", "codex")."""
        adapters = {b.adapter for b in self.bindings().values()}
        return sorted(a.removesuffix("-cli") for a in adapters if a.endswith("-cli"))

    def ai_readiness(self, *, fresh: bool = False) -> dict[str, Any]:
        if self.cli is None:
            return {"ready": True, "clis": []}
        views = [self.cli.view(name, fresh=fresh) | {"needed": True} for name in self.cli_needed()]
        return {"ready": all(v["ready"] for v in views), "clis": views}

    def require_ai_ready(self) -> None:
        """Refuse to start generation that cannot work: the chosen subscription program is missing or signed
        out. The app shows the step to fix it (install, sign in) instead of a failed lesson later."""
        if self.cli is None:
            return
        for name in self.cli_needed():
            s = self.cli.status(name)
            if not s.ready:
                raise AiNotReady(name, s.reason or "not_ready")

    # --- setup -----------------------------------------------------------------------------------

    def ensure_learner(self) -> str:
        """Local mode has one learner, created on first use."""

        def unit(c: sqlite3.Connection) -> str:
            row = c.execute("SELECT id FROM learner ORDER BY created_at LIMIT 1").fetchone()
            if row:
                return str(row[0])
            now = clock.now()
            if c.execute("SELECT count(*) FROM installation").fetchone()[0] == 0:
                c.execute(
                    "INSERT INTO installation (id, mode, created_at, env_profile) VALUES (?, 'local', ?, '{}')",
                    (new_id(), now),
                )
            lid = new_id()
            c.execute(
                "INSERT INTO learner (id, display_name, ui_lang, default_content_lang, tz, day_boundary, "
                "created_at) VALUES (?, 'Learner', 'en', 'en', 'UTC', '04:00', ?)",
                (lid, now),
            )
            ev.server_device(c)
            return lid

        return self.writer.run(unit)

    def register_device(self, label: str, user_agent: str) -> str:
        did, now = new_id(), clock.now()
        self.writer.run(
            lambda c: c.execute(
                "INSERT INTO device (id, label, user_agent, first_seen, last_seen, revoked_at) VALUES (?, ?, ?, ?, ?, NULL)",
                (did, label[:80], user_agent[:300], now, now),
            )
        )
        return did

    def apply_preset(self, preset: str) -> None:
        self.writer.run(lambda c: models.apply_preset(c, preset))

    def bind(self, role: Role, adapter: str, model: str, **settings_: Any) -> None:
        self.writer.run(lambda c: models.bind(c, role, adapter, model, **settings_))

    def binding(self, role: Role) -> Binding:
        with self.readers.connection() as c:
            return models.resolve(c, role)

    def bindings(self) -> dict[Role, Binding]:
        with self.readers.connection() as c:
            return {r: models.resolve(c, r) for r in models.ROLES if _bound(c, r)}

    def resolved_models(self) -> dict[tuple[str, str], str]:
        """The exact model behind each (adapter, requested) pair, from the latest call that named one: a CLI
        alias such as `opus` becomes the version it ran (claude-opus-5-5). Empty before the first call."""
        with self.readers.connection() as c:
            rows = c.execute(
                "SELECT adapter, model_requested, model_resolved FROM stage_run s WHERE model_resolved IS NOT NULL "
                "AND model_resolved != model_requested AND status = 'succeeded' AND started_at = (SELECT max(started_at) "
                "FROM stage_run t WHERE t.adapter = s.adapter AND t.model_requested = s.model_requested "
                "AND t.model_resolved != t.model_requested AND t.status = 'succeeded') ORDER BY s.rowid"
            ).fetchall()
        return {(r[0], r[1]): r[2] for r in rows}

    def put_setting(self, key: str, value: Any, level: settings.Level, ref: str | None = None) -> None:
        self.writer.run(lambda c: settings.put(c, key, value, level, ref))

    def setting(self, key: str, scopes: dict[settings.Level, str | None] | None = None) -> Any:
        with self.readers.connection() as c:
            return settings.effective(c, key, scopes or {})[0]

    def warnings(self) -> list[str]:
        b = self.bindings()
        out = [
            w
            for role in ("generator", "reviewer")
            if role in b and (w := models.untested_warning(b[role])) is not None
        ]
        if (
            "generator" in b
            and "reviewer" in b
            and (w := models.independence_warning(b["generator"], b["reviewer"]))
        ):
            out.append(w)
        return out

    # --- estimate --------------------------------------------------------------------------------

    def estimate(
        self, lessons: int = 20, *, include_path: bool = True, videos: str | None = None
    ) -> est.Estimate:  # the bound models
        """`videos`: youtube, generated or reading, as on the New path form; None: the learner's settings."""
        bindings = self.bindings()
        if "generator" not in bindings:
            raise Conflict("no model is chosen yet: choose how Yuo reaches an AI first")
        with self.readers.connection() as c:
            if videos is None:
                videos = (
                    "reading"
                    if settings.effective(c, "video.format", {})[0] == "reading"
                    else str(settings.effective(c, "video.source", {})[0])
                )
            video = None
            if videos == "generated" and self.videos.video_unavailable() is None:
                video = str(settings.effective(c, "video.length", {})[0])
            return est.estimate(
                c,
                bindings,
                self.prices,
                lessons=lessons,
                include_path=include_path,
                video=video,
                youtube=videos == "youtube",
            )

    # --- paths -----------------------------------------------------------------------------------

    def create_path(self, form: PathForm) -> tuple[str, str]:
        self.require_ai_ready()
        learner = self.ensure_learner()
        path_id = new_id()

        reasons = list(dict.fromkeys(form.goal_types)) or [form.goal_type]

        def unit(c: sqlite3.Connection) -> str:
            lang = (
                form.content_lang
                or c.execute("SELECT default_content_lang FROM learner WHERE id = ?", (learner,)).fetchone()[
                    0
                ]
            )
            now = clock.now()
            code = f"path-{path_id[-12:]}"
            c.execute(
                "INSERT INTO path (id, code, learner_id, title, subject, goal, goal_type, target_date, difficulty, "
                "content_lang, status, authorship, acquired_via, package_id, translation_of_path_id, "
                "structure_version, licence, authors, extensions, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, 'draft', 'generated', 'local', NULL, NULL, 0, "
                "'CC-BY-4.0', '[]', '{}', ?, ?)",
                (
                    path_id,
                    code,
                    learner,
                    form.title,
                    form.subject.strip() or form.title,
                    form.goal,
                    reasons[0],
                    form.difficulty,
                    lang,
                    now,
                    now,
                ),
            )
            # how big a plan, and every reason for learning (the column keeps the first, for packages)
            save_path_state(c, path_id, "plan", {"depth": depth_of(form.depth), "goal_types": reasons})
            if form.custom_instructions:
                settings.put(c, "custom_instructions", form.custom_instructions, "path", path_id)
            if form.videos == "reading":  # this path's videos, chosen on the New path form
                settings.put(c, "video.format", "reading", "path", path_id)
            elif form.videos is not None:
                settings.put(c, "video.format", "when_possible", "path", path_id)
                settings.put(c, "video.source", form.videos, "path", path_id)
            if form.preview:  # the plan is shown to the learner before it is built (yuo/app/plan_preview.py)
                save_path_state(c, path_id, "preview", {"status": "drafting", "rounds": []})
            if form.level_check:  # the tree waits for the learner's answers (or a skip)
                save_path_state(c, path_id, "level_check", {"status": "preparing"})
                return enqueue(c, "tree", EntityKind.PATH, path_id, priority=URGENT_PRIORITY)
            return enqueue(c, "tree", EntityKind.PATH, path_id)

        job = self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return path_id, job

    def skill_material(
        self, c: sqlite3.Connection, skill_id: str, lesson_id: str, budget: int
    ) -> dict[str, Any] | None:
        found = self.materials.lesson_material(c, skill_id, lesson_id, budget)
        if found is not None:
            found["exam_style"] = self.materials.exam_examples(c, skill_id)
        return found

    def path_inputs(self, c: sqlite3.Connection, path_id: str) -> tuple[dict[str, Any], DataClass]:
        p = get_path(c, path_id)
        scopes: dict[settings.Level, str | None] = {"path": path_id, "learner": p["learner_id"]}
        extra, _ = settings.effective(c, "custom_instructions", scopes)
        interests = settings.effective(c, "learner.interests", scopes)[0]
        inputs = {
            "subject": p["subject"],
            "goal": p["goal"],
            "difficulty": p["difficulty"],
            "goal_type": p["goal_type"],
            "lang": p["content_lang"],
            "path_title": p["title"],
            "custom_instructions": extra,
        }
        if interests:  # only when set, so inputs (and stage cache keys) without them stay as they were
            inputs["interests"] = interests
        plan = path_state(p, "plan")
        if plan:  # same: paths planned before the choice keep their inputs
            reasons = plan.get("goal_types") or []
            if len(reasons) > 1:
                inputs["goal_type"] = " + ".join(reasons)
            inputs["depth"] = depth_of(plan.get("depth"))
        result = (path_state(p, "level_check") or {}).get("result")
        if result:  # same: only when the learner took the level check
            inputs["level"] = lc.summary(result)
        return inputs, DataClass.FREE_TEXT if extra or interests else DataClass.CONTENT

    def handle_tree(self, job: Job) -> None:
        with self.readers.connection() as c:
            step = self.next_steps.next_pending(c, job.target_id)
        if step is not None:  # a "What next?" step on a planned path (yuo/app/next_steps.py)
            self.next_steps.handle_next(job, step)
            return
        with self.readers.connection() as c:
            inputs, dclass = self.path_inputs(c, job.target_id)
            state = path_state(find_path(c, job.target_id), "level_check")
        if state is not None and state["status"] in ("preparing", "ready"):
            if state["status"] == "preparing":
                self._write_level_check(job)
            return  # the tree waits for the learner's answers
        with self.readers.connection() as c:
            preview = self.preview.wants_preview(c, job.target_id)
        if preview == "revising":
            self.preview.revise(job)
            return
        depth = depth_of(inputs.get("depth"))
        gen = self.binding("generator")
        if gen.max_tokens < TREE_MAX_TOKENS[depth]:  # a long plan is a long reply
            gen = dataclasses.replace(gen, max_tokens=TREE_MAX_TOKENS[depth])
        out = self.runner.run(
            job.id,
            tree_spec(depth),
            gen,
            {
                k: inputs[k]
                for k in (
                    "subject",
                    "goal",
                    "difficulty",
                    "goal_type",
                    "lang",
                    "custom_instructions",
                    "interests",
                    "level",
                    "depth",
                )
                if k in inputs
            },
            data_class=dclass,
        )

        if preview == "drafting":
            self.writer.run(lambda c: self.preview.store_draft(c, job.target_id, out.value))
            return

        def unit(c: sqlite3.Connection) -> None:
            if c.execute("SELECT count(*) FROM branch WHERE path_id = ?", (job.target_id,)).fetchone()[0]:
                return  # a retried job after a crash: the tree is already there
            lessons = apply_tree(c, job.target_id, out.value)
            c.execute(
                "UPDATE path SET status = 'active', updated_at = ? WHERE id = ?", (clock.now(), job.target_id)
            )
            if not lessons:
                raise StageFailed("the tree has no lessons")
            self.study.top_up_buffer(c, job.target_id)  # lessons ahead, from the first one

        self.writer.run(unit)
        if self.worker:
            self.worker.wake()

    # --- level check before the tree ------------------------------------------------------------

    def _write_level_check(self, job: Job) -> None:
        """The tree job's first phase when the path has a level check: write the questions, then stop.
        The learner's answers (or a skip) queue the tree job again."""
        with self.readers.connection() as c:
            inputs, dclass = self.path_inputs(c, job.target_id)
        out = self.runner.run(
            job.id,
            LEVEL_CHECK,
            self.binding("generator"),
            {
                k: inputs[k]
                for k in ("subject", "goal", "goal_type", "lang", "custom_instructions", "interests")
                if k in inputs
            },
            data_class=dclass,
        )
        questions = lc.stored(out.value, f"{job.target_id}:{job.id}")  # options shuffled

        def unit(c: sqlite3.Connection) -> None:
            c.execute(
                "UPDATE path SET extensions = json_set(extensions, '$.yuo.level_check', json(?)) WHERE id = ? "
                "AND extensions ->> '$.yuo.level_check.status' = 'preparing'",
                (json.dumps({"status": "ready", "questions": questions}), job.target_id),
            )

        self.writer.run(unit)

    def level_check(self, path_id: str) -> dict[str, Any]:
        """The learner's view: status, the questions without answer keys, and the job writing them."""
        with self.readers.connection() as c:
            p = get_path(c, path_id)
            state = path_state(p, "level_check")
            job = c.execute(
                "SELECT id, status, error FROM generation_job WHERE kind = 'tree' AND target_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (path_id,),
            ).fetchone()
        if state is None:
            return {"status": "none", "questions": [], "result": None, "job_id": None, "failed": False}
        failed = state["status"] == "preparing" and job is not None and job["status"] == "failed"
        result = state.get("result")
        return {
            "status": state["status"],
            "questions": lc.public(state.get("questions") or []),
            "result": {k: result[k] for k in ("level", "difficulty", "right", "total", "known", "unknown")}
            if result
            else None,
            "job_id": job["id"] if job else None,
            "failed": failed,
        }

    def retry_level_check(self, path_id: str) -> dict[str, Any]:
        """Write the questions again after the job that writes them failed (e.g. the model was not reachable)."""
        self.require_ai_ready()

        def unit(c: sqlite3.Connection) -> None:
            p = get_path(c, path_id)
            state = path_state(p, "level_check")
            job = c.execute(
                "SELECT status FROM generation_job WHERE kind = 'tree' AND target_id = ? ORDER BY created_at DESC, "
                "rowid DESC LIMIT 1",
                (path_id,),
            ).fetchone()
            if state is None or state["status"] != "preparing" or job is None or job[0] != "failed":
                raise InvalidInput("the level check is not waiting to be written again")
            enqueue(c, "tree", EntityKind.PATH, path_id)

        self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return self.level_check(path_id)

    def answer_level_check(self, path_id: str, answers: list[int | None] | None) -> dict[str, Any]:
        """Score the answers (None: skipped), set the path's level and start planning the tree."""

        def unit(c: sqlite3.Connection) -> None:
            p = get_path(c, path_id)
            state = path_state(p, "level_check")
            if state is None or state["status"] in ("done", "skipped"):
                raise InvalidInput("this path has no level check waiting for answers")
            new: dict[str, Any]
            if answers is None:
                new = {"status": "skipped"}
            else:
                if state["status"] != "ready":
                    raise InvalidInput("the level check is not ready yet")
                result = lc.score(state["questions"], answers)
                new = {"status": "done", "questions": state["questions"], "result": result}
                c.execute(
                    "UPDATE path SET difficulty = ?, updated_at = ? WHERE id = ?",
                    (result["difficulty"], clock.now(), path_id),
                )
            save_path_state(c, path_id, "level_check", new)
            queued = c.execute(
                "SELECT 1 FROM generation_job WHERE kind = 'tree' AND target_id = ? AND status IN "
                "('queued', 'waiting_resource')",
                (path_id,),
            ).fetchone()
            if queued:  # skipped before the questions were written: that job plans the tree now
                return
            enqueue(c, "tree", EntityKind.PATH, path_id, priority=URGENT_PRIORITY)

        self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return self.level_check(path_id)

    def request_lesson(self, lesson_id: str) -> str:
        self.require_ai_ready()

        def unit(c: sqlite3.Connection) -> str:
            row = c.execute("SELECT state FROM lesson WHERE id = ?", (lesson_id,)).fetchone()
            if row is None:
                raise NotFound(lesson_id)
            busy = c.execute(
                "SELECT id FROM generation_job WHERE target_id = ? AND status IN "
                "('queued','running','waiting_resource')",
                (lesson_id,),
            ).fetchone()
            if busy:  # already on its way: the learner waits for it now, so it goes to the front
                c.execute(
                    "UPDATE generation_job SET priority = max(priority, ?) WHERE id = ? AND kind = 'lesson'",
                    (ASKED_PRIORITY, busy[0]),
                )
                return str(busy[0])
            c.execute("UPDATE lesson SET state = 'queued' WHERE id = ?", (lesson_id,))
            return enqueue(c, "lesson", EntityKind.LESSON, lesson_id, priority=ASKED_PRIORITY)

        job = self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return job

    def accept_lesson_draft(self, lesson_id: str) -> str:
        """A lesson that failed its review: publish its best rejected draft (the fewest major, then minor issues)
        with the reviewer's notes shown in it, instead of writing it again."""

        def unit(c: sqlite3.Connection) -> str:
            row = c.execute("SELECT state FROM lesson WHERE id = ?", (lesson_id,)).fetchone()
            if row is None:
                raise NotFound(lesson_id)
            if row[0] != "failed":
                raise Conflict("only a lesson that failed its review can be accepted as it is")
            best = _best_draft(c, lesson_id)
            if best is None:
                raise Conflict("this lesson has no draft to accept")
            c.execute(
                "UPDATE lesson SET state = 'queued', extensions = json_set(extensions, '$.yuo.accept', ?) WHERE id = ?",
                (best, lesson_id),
            )
            return enqueue(c, "lesson", EntityKind.LESSON, lesson_id)

        job = self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return job

    # --- lesson job: write, gate, publish, item --------------------------------------------------

    def _lesson_context(self, c: sqlite3.Connection, lesson_id: str) -> dict[str, Any]:
        lesson = c.execute("SELECT * FROM lesson WHERE id = ?", (lesson_id,)).fetchone()
        if lesson is None:
            raise NotFound(lesson_id)
        skill = get_skill(c, lesson["skill_id"])
        objectives = _rows(
            c,
            "SELECT id, code, statement FROM learning_objective WHERE skill_id = ? "
            "AND archived_at IS NULL ORDER BY position",
            lesson["skill_id"],
        )
        prior = [
            r["title"]
            for r in _rows(
                c,
                "SELECT s.title FROM skill_prerequisite p JOIN skill s "
                "ON s.id = p.requires_skill_id WHERE p.skill_id = ?",
                skill["id"],
            )
        ]
        path_inputs, dclass = self.path_inputs(c, lesson["path_id"])
        length, _ = settings.effective(c, "lesson.reading_length", {"path": lesson["path_id"]})
        ext = json.loads(lesson["extensions"]).get("yuo", {})
        title = ext.get("planned_title") or (
            f"{skill['title']}: another look" if ext.get("remedial") else skill["title"]
        )
        if ext.get("remedial"):
            length = "short"
        material = self.materials.lesson_material(c, skill["id"], lesson_id)
        if material:  # the learner's own files: personal, like their own words
            dclass = DataClass.FREE_TEXT
        request = None
        if ext.get("request_id"):  # the learner's own words shape the lesson, so it is personal (F)
            row = c.execute("SELECT prompt FROM lesson_request WHERE id = ?", (ext["request_id"],)).fetchone()
            request = row[0] if row else None
            if request:
                dclass = DataClass.FREE_TEXT
        return {
            "lesson": dict(lesson),
            "skill": dict(skill),
            "objectives": objectives,
            "data_class": dclass,
            "inputs": path_inputs
            | {
                "skill_title": skill["title"],
                "skill_summary": skill["summary"],
                "lesson_title": title,
                "prior_skills": prior,
                "length": length,
                "objectives": [{"code": o["code"], "statement": o["statement"]} for o in objectives],
            }
            | ({"remedial": ext["remedial"]} if ext.get("remedial") else {})
            | ({"request": request} if request else {})
            | ({"material": material} if material else {}),
        }

    def handle_lesson(self, job: Job) -> None:
        try:
            self._lesson(job)
        except Exception as e:
            # the head must not stay `generating`: queued again if the job will retry, else failed
            retry = isinstance(e, StageFailed) and e.retryable and job.attempt < MAX_ATTEMPTS
            state = "queued" if retry or isinstance(e, BudgetExceeded) else "failed"

            def unit(c: sqlite3.Connection) -> None:
                c.execute(
                    "UPDATE lesson SET state = ? WHERE id = ? AND state != 'ready'", (state, job.target_id)
                )
                if (
                    state == "failed"
                ):  # one lesson that cannot be written does not hold back the ones after it
                    row = c.execute("SELECT path_id FROM lesson WHERE id = ?", (job.target_id,)).fetchone()
                    if row is not None:
                        self.study.top_up_buffer(c, row[0])

            self.writer.run(unit)
            raise

    def _lesson(self, job: Job) -> None:
        with self.readers.connection() as c:
            ctx = self._lesson_context(c, job.target_id)
            accept = c.execute(
                "SELECT extensions ->> '$.yuo.accept' FROM lesson WHERE id = ?", (job.target_id,)
            ).fetchone()[0]
        if accept:
            self._accept_draft(job, ctx, accept)
            return
        lesson_id, dclass = job.target_id, ctx["data_class"]
        gen, rev = self.binding("generator"), self.binding("reviewer")
        independent = models.independence_warning(gen, rev) is None
        self.writer.run(
            lambda c: c.execute("UPDATE lesson SET state = 'generating' WHERE id = ?", (lesson_id,))
        )
        if "material" not in ctx["inputs"] and (video := self.video_links.prepare(job, ctx)) is not None:
            ctx["inputs"]["video"] = video  # written from a YouTube video's transcript (yuo.app.video_links)
        spec = lesson_spec(ctx["inputs"]["length"])
        # a later attempt writes a fresh draft rather than the stored one that failed (the job retries it)
        nonce = f"attempt-{job.attempt}" if job.attempt > 1 else None
        findings: list[dict[str, Any]] = []
        published: tuple[str, list[dict[str, Any]]] | None = None
        for fix_round in (0, 1):
            inputs = ctx["inputs"] | ({"findings": findings} if findings else {})
            body_out = self.runner.run(
                job.id, spec, gen, inputs, data_class=dclass, fix_round=fix_round, variant_nonce=nonce
            )
            body = to_body(body_out.value)
            version_id = self.writer.run(
                lambda c: self._write_lesson_version(
                    c, lesson_id, body_out.value, body, body_out.stage_run_id, dclass, fix_round
                )
            )
            review = self.runner.run(
                job.id,
                REVIEW,
                rev,
                {
                    "difficulty": ctx["inputs"]["difficulty"],
                    "body": body,
                    "objectives": ctx["inputs"]["objectives"],
                }
                | ({"material": ctx["inputs"]["material"]} if "material" in ctx["inputs"] else {})
                | ({"video": ctx["inputs"]["video"]} if "video" in ctx["inputs"] else {}),
                data_class=dclass,
                upstream=[body_out.output_hash],
                fix_round=fix_round,
                variant_nonce=nonce,
                role="reviewer",
            )
            verdict = gate_verdict(review.value)
            self.writer.run(
                lambda c: _check(
                    c,
                    EntityKind.LESSON_VERSION,
                    version_id,
                    "reviewer",
                    verdict,
                    fix_round,
                    review.value.model_dump(mode="json"),
                    review.stage_run_id,
                    independent=independent,
                )
            )
            if verdict is CheckVerdict.FAIL:
                findings = [i.model_dump() for i in review.value.issues if i.severity == "major"] or [
                    {"where": "lesson", "claim": "reviewer verdict fail", "correction": "fix the errors"}
                ]
                self.writer.run(
                    lambda c: c.execute(
                        "UPDATE lesson_version SET status = 'rejected' WHERE id = ?", (version_id,)
                    )
                )
                continue
            self.writer.run(
                lambda c: self._publish_lesson(
                    c, lesson_id, version_id, body_out.value.title, body, ctx["objectives"]
                )
            )
            published = (version_id, body)
            break
        if published is None:
            # retried later with a fresh draft, up to MAX_ATTEMPTS: the learner should not have to ask
            raise StageFailed(
                f"the lesson failed review twice (attempt {job.attempt} of {MAX_ATTEMPTS})", retryable=True
            )
        self._after_publish(job, ctx, published[0], published[1], notes=None)

    def _accept_draft(self, job: Job, ctx: dict[str, Any], version_id: str) -> None:
        """Publish a rejected draft the learner accepted, with what its reviewer found wrong."""
        with self.readers.connection() as c:
            v = c.execute(
                "SELECT title, body FROM lesson_version WHERE id = ? AND lesson_id = ?",
                (version_id, job.target_id),
            ).fetchone()
            issues = _review_issues(c, version_id)
        if v is None:
            raise StageFailed("the accepted draft is gone", retryable=False)
        body = json.loads(v["body"])

        def unit(c: sqlite3.Connection) -> str:
            # a rejected version stays rejected (versions are immutable): the accepted one is its copy
            vid = new_id()
            no = c.execute(
                "SELECT coalesce(max(version_no), 0) + 1 FROM lesson_version WHERE lesson_id = ?",
                (job.target_id,),
            ).fetchone()[0]
            c.execute(
                "INSERT INTO lesson_version (id, lesson_id, version_no, version_hash, lang, translation_of_version_hash, "
                "derived_from_version_id, title, body, est_minutes, status, published_at, created_at, authorship, "
                "acquired_via, author_kind, author_ref, produced_by_stage_run_id, upstream, licence, personal_inputs) "
                "SELECT ?, lesson_id, ?, version_hash, lang, NULL, id, title, body, est_minutes, 'in_review', NULL, ?, "
                "authorship, acquired_via, author_kind, author_ref, produced_by_stage_run_id, upstream, licence, "
                "personal_inputs FROM lesson_version WHERE id = ?",
                (vid, no, clock.now(), version_id),
            )
            self._publish_lesson(c, job.target_id, vid, v["title"], body, ctx["objectives"])
            return vid

        published = self.writer.run(unit)
        self._after_publish(job, ctx, published, body, notes={"version_id": published, "issues": issues})

    def _after_publish(
        self,
        job: Job,
        ctx: dict[str, Any],
        version_id: str,
        body: list[dict[str, Any]],
        *,
        notes: dict[str, Any] | None,
    ) -> None:
        lesson_id = job.target_id
        sources = json.dumps(ctx["inputs"]["material"]["sources"]) if "material" in ctx["inputs"] else None

        def unit(c: sqlite3.Connection) -> None:
            c.execute(
                "UPDATE lesson SET extensions = json_remove(json_set(extensions, '$.yuo.review_notes', json(?)), "
                "'$.yuo.accept') WHERE id = ?",
                (json.dumps(notes), lesson_id),
            )
            if notes is None:  # passed its review: no notes
                c.execute(
                    "UPDATE lesson SET extensions = json_remove(extensions, '$.yuo.review_notes') WHERE id = ?",
                    (lesson_id,),
                )
            if sources is not None:  # where in the learner's files this lesson comes from
                c.execute(
                    "UPDATE lesson SET extensions = json_set(extensions, '$.yuo.sources', json(?)) WHERE id = ?",
                    (sources, lesson_id),
                )
            if "video" in ctx["inputs"]:  # the YouTube video it was written from
                self.video_links.attach(c, version_id, ctx["inputs"]["video"])

        self.writer.run(unit)
        self.study.make_practice(job, ctx["lesson"], version_id, body)
        # the lesson's review questions, written ahead so the first review does not wait
        self.writer.run(lambda c: self.reviews.queue_review_bank(c, lesson_id))
        self.writer.run(lambda c: self.study.top_up_buffer(c, ctx["lesson"]["path_id"]))
        self.writer.run(lambda c: self.videos.queue_video(c, lesson_id))  # video by default, after the gate

    def _write_lesson_version(
        self,
        c: sqlite3.Connection,
        lesson_id: str,
        draft: LessonDraft,
        body: list[dict[str, Any]],
        run_id: str,
        dclass: DataClass,
        fix_round: int,
    ) -> str:
        lang = c.execute(
            "SELECT p.content_lang FROM lesson l JOIN path p ON p.id = l.path_id WHERE l.id = ?", (lesson_id,)
        ).fetchone()[0]
        no = c.execute(
            "SELECT coalesce(max(version_no), 0) + 1 FROM lesson_version WHERE lesson_id = ?", (lesson_id,)
        ).fetchone()[0]
        vid = new_id()
        content = {"title": draft.title, "body": body, "lang": lang, "est_minutes": draft.est_minutes}
        c.execute(
            "INSERT INTO lesson_version (id, lesson_id, version_no, version_hash, lang, translation_of_version_hash, "
            "derived_from_version_id, title, body, est_minutes, status, published_at, created_at, authorship, "
            "acquired_via, author_kind, author_ref, produced_by_stage_run_id, upstream, licence, personal_inputs) "
            "VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, json(?), ?, 'in_review', NULL, ?, 'generated', 'local', 'system', "
            "NULL, ?, NULL, NULL, ?)",
            (
                vid,
                lesson_id,
                no,
                content_hash(content),
                lang,
                draft.title,
                json.dumps(body, ensure_ascii=False),
                draft.est_minutes,
                clock.now(),
                run_id,
                int(dclass is DataClass.FREE_TEXT),
            ),
        )
        c.execute("UPDATE lesson SET state = 'in_review' WHERE id = ?", (lesson_id,))
        # the deterministic checks ran before the repair round; they passed or the stage would have failed
        for check in ("schema", "links"):
            _check(c, EntityKind.LESSON_VERSION, vid, check, CheckVerdict.PASS, fix_round, {}, run_id)
        return vid

    def _publish_lesson(
        self,
        c: sqlite3.Connection,
        lesson_id: str,
        version_id: str,
        title: str,
        body: list[dict[str, Any]],
        objectives: list[dict[str, Any]],
    ) -> None:
        now = clock.now()
        for pos, o in enumerate(objectives):
            c.execute(
                "INSERT INTO lesson_version_objective (lesson_version_id, objective_id, role) VALUES (?, ?, ?)",
                (version_id, o["id"], "primary" if pos == 0 else "secondary"),
            )
        c.execute(
            "UPDATE lesson_version SET status = 'passed', published_at = ? WHERE id = ?", (now, version_id)
        )
        old = c.execute("SELECT current_version_id FROM lesson WHERE id = ?", (lesson_id,)).fetchone()[0]
        c.execute(
            "UPDATE lesson SET current_version_id = ?, state = 'ready' WHERE id = ?", (version_id, lesson_id)
        )
        if old:
            c.execute("DELETE FROM lesson_search_doc WHERE lesson_version_id = ?", (old,))
        c.execute(
            "INSERT INTO lesson_search_doc (lesson_version_id, title, body) VALUES (?, ?, ?)",
            (version_id, title, plain_text(body)),
        )
        c.execute(
            "INSERT INTO publication (id, head_kind, head_id, version_id, at, by) VALUES (?, 'lesson', ?, ?, ?, "
            "'gate')",
            (new_id(), lesson_id, version_id, now),
        )

    # --- reading views ---------------------------------------------------------------------------

    def paths(self) -> list[dict[str, Any]]:
        with self.readers.connection() as c:
            return _rows(
                c,
                "SELECT id, title, subject, goal, target_date, status, difficulty, content_lang, created_at "
                "FROM path ORDER BY created_at DESC",
            )

    def update_path(self, path_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        """The learner renames the path, rewrites its goal or exam date, or archives it and brings it back.
        Only a path that is built can be archived (a draft is still being planned: delete it instead)."""

        def unit(c: sqlite3.Connection) -> None:
            p = get_path(c, path_id)
            sets: dict[str, Any] = {}
            for key in ("title", "subject", "goal"):
                if key in changes:
                    text = str(changes[key] or "").strip()
                    if not text:
                        raise InvalidInput(f"{key} cannot be empty")
                    sets[key] = text[:200] if key != "goal" else text[:2000]
            if "target_date" in changes:
                sets["target_date"] = changes["target_date"] or None
            if "status" in changes:
                status = changes["status"]
                if status == "archived" and p["status"] == "draft":
                    raise Conflict("a path still being planned cannot be archived")
                if status == "active" and p["status"] != "archived":
                    raise Conflict("only an archived path can be brought back")
                sets["status"] = status
            if not sets:
                return
            sets["updated_at"] = clock.now()
            c.execute(
                f"UPDATE path SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
                (*sets.values(), path_id),
            )

        self.writer.run(unit)
        return next(p for p in self.paths() if p["id"] == path_id)

    def delete_path(self, path_id: str) -> dict[str, int]:
        return self.erasure.path_whole(path_id)

    def path_view(self, path_id: str) -> dict[str, Any]:
        with self.readers.connection() as c:
            p = c.execute(
                "SELECT id, title, subject, goal, status, difficulty, content_lang, extensions FROM path WHERE id = ?",
                (path_id,),
            ).fetchone()
            if p is None:
                raise NotFound(path_id)
            check = (path_state(p, "level_check") or {}).get("status", "none")
            preview = (path_state(p, "preview") or {}).get("status", "none")
            origin = (json.loads(p["extensions"] or "{}").get("yuo") or {}).get("origin", "goal")
            if origin == "courses":  # the courses' plan has its own states (yuo/app/material.py)
                preview = "none"
            branches = _rows(
                c, "SELECT id, code, title FROM branch WHERE path_id = ? ORDER BY position", path_id
            )
            for b in branches:
                b["skills"] = _rows(
                    c,
                    "SELECT id, code, title, summary FROM skill WHERE branch_id = ? ORDER BY position",
                    b["id"],
                )
                for s in b["skills"]:
                    s["requires"] = [
                        r[0]
                        for r in c.execute(
                            "SELECT requires_skill_id FROM skill_prerequisite WHERE skill_id = ?", (s["id"],)
                        )
                    ]
                    s["objectives"] = _rows(
                        c,
                        "SELECT id, statement FROM learning_objective WHERE skill_id = ? AND archived_at IS NULL "
                        "ORDER BY position",
                        s["id"],
                    )
                    s["lessons"] = [
                        {
                            "id": r["id"],
                            "code": r["code"],
                            "kind": r["kind"],
                            "state": r["state"],
                            "has_draft": bool(r["drafts"]),
                            "title": r["vtitle"]
                            or json.loads(r["extensions"]).get("yuo", {}).get("planned_title"),
                        }
                        for r in c.execute(
                            "SELECT l.id, l.code, l.kind, l.state, l.extensions, v.title AS vtitle, l.state = 'failed' "
                            "AND EXISTS (SELECT 1 FROM lesson_version x WHERE x.lesson_id = l.id AND x.status = "
                            "'rejected') AS drafts FROM lesson l "
                            "LEFT JOIN lesson_version v ON v.id = l.current_version_id WHERE l.skill_id = ? "
                            "ORDER BY l.position",
                            (s["id"],),
                        )
                    ]
            jobs = self._with_progress(
                c,
                _rows(
                    c,
                    f"SELECT {JOB_COLUMNS} FROM generation_job j WHERE (j.target_id = ? OR j.target_id IN "
                    "(SELECT id FROM lesson WHERE path_id = ?) OR j.target_id IN (SELECT r.id FROM rendition r "
                    "JOIN lesson l ON l.id = r.lesson_id WHERE l.path_id = ?)) AND j.kind != 'items' "
                    "ORDER BY j.created_at",
                    path_id,
                    path_id,
                    path_id,
                ),
            )
        out = dict(p)
        del out["extensions"]
        return out | {
            "branches": branches,
            "jobs": jobs,
            "level_check": check,
            "preview": preview,
            "origin": origin,
        }

    def lesson_view(self, lesson_id: str) -> dict[str, Any]:
        with self.readers.connection() as c:
            r = c.execute(
                "SELECT l.id, l.state, l.path_id, l.skill_id, v.id AS version_id, v.title, v.body, v.est_minutes, "
                "v.lang, s.title AS skill_title, p.title AS path_title, l.extensions ->> '$.yuo.sources' AS sources, "
                "l.extensions ->> '$.yuo.review_notes' AS notes "
                "FROM lesson l "
                "JOIN skill s ON s.id = l.skill_id JOIN path p ON p.id = l.path_id "
                "LEFT JOIN lesson_version v ON v.id = l.current_version_id WHERE l.id = ?",
                (lesson_id,),
            ).fetchone()
            if r is None:
                raise NotFound(lesson_id)
            items = c.execute(
                "SELECT count(*) FROM item i JOIN item_version v ON v.id = i.current_version_id "
                "WHERE v.origin_lesson_version_id = ? AND i.extensions ->> '$.yuo.use' IS NOT 'review'",
                (r["version_id"],),
            ).fetchone()[0]
        out = dict(r)
        out["body"] = json.loads(r["body"]) if r["body"] else None
        out["practice_items"] = items
        out["sources"] = _merge_sources(json.loads(r["sources"])) if r["sources"] else []
        notes = json.loads(out.pop("notes") or "null")
        # accepted without passing its review: what the reviewer found, shown with the lesson
        out["review_notes"] = notes["issues"] if notes and notes["version_id"] == r["version_id"] else None
        out["video"] = self.videos.video_of(lesson_id)
        with self.readers.connection() as c:
            out["youtube"] = self.video_links.link_of(c, lesson_id)
            youtube_only = settings.effective(c, "video.source", {"path": r["path_id"]})[0] == "youtube"
        # a lesson with a YouTube video, or a path that only uses them, needs no video renderer
        on_youtube = youtube_only or (out["youtube"] is not None and out["youtube"]["video_id"] is not None)
        out["video_unavailable"] = None if on_youtube else self.videos.video_unavailable()
        return out

    def hint(self, item_version_id: str, level: int) -> dict[str, Any]:
        with self.readers.connection() as c:
            row = c.execute(
                "SELECT v.support, i.extensions ->> '$.yuo.use' FROM item_version v JOIN item i ON i.id = v.item_id "
                "WHERE v.id = ? AND v.status = 'passed'",
                (item_version_id,),
            ).fetchone()
        if row is None:
            raise NotFound(item_version_id)
        hints = json.loads(row[0])["hints"]
        if row[1] == "review":  # the third hint all but gives the answer: review stops at the second
            hints = hints[:2]
        if not 1 <= level <= len(hints):
            raise NotFound(f"hint {level}")
        return {"level": level, "text": hints[level - 1], "last": level == len(hints)}

    # --- outbox ingest ---------------------------------------------------------------------------

    def ingest(self, device_id: str, incoming: list[ev.IncomingEvent]) -> dict[str, Any]:
        """Store a batch from a device's outbox: each event is accepted, a duplicate, or rejected on its own."""
        learner = self.ensure_learner()
        result = ev.IngestResult()
        shown: list[dict[str, Any]] = []
        batch: _Batch | None = None

        def unit(c: sqlite3.Connection) -> None:
            nonlocal batch
            if (
                c.execute("SELECT 1 FROM device WHERE id = ? AND revoked_at IS NULL", (device_id,)).fetchone()
                is None
            ):
                raise NotFound("device")
            boundary = c.execute("SELECT day_boundary FROM learner WHERE id = ?", (learner,)).fetchone()[0]
            batch = _Batch(learner, device_id, boundary)
            for e in incoming:
                self._ingest_one(c, batch, e, result)
            self.study.project_events(c, learner, batch.written)
            shown.extend(self.tutor._nudge_at_breakpoint(c, learner, batch.written))
            for path_id in batch.paths:
                self.study.top_up_buffer(c, path_id)
            c.execute("UPDATE device SET last_seen = ? WHERE id = ?", (clock.now(), device_id))

        self.writer.run(unit)
        assert batch is not None
        if self.worker:
            self.worker.wake()
        for n in shown:
            self.broker.publish("nudge", n)
        return result.model_dump() | {"graded": batch.graded, "outcomes": batch.outcomes, "nudges": shown}

    def _ingest_one(
        self, c: sqlite3.Connection, b: _Batch, e: ev.IncomingEvent, result: ev.IngestResult
    ) -> None:
        try:
            etype, payload = ev.validate(e)
            if etype in ev.SERVER_ONLY:
                raise InvalidInput(f"{etype} events are written by the server")
        except ValueError as err:
            result.rejected[e.id] = str(err)[:300]
            return
        # one savepoint per event: a bad event is rejected without losing the rest of the batch
        c.execute("SAVEPOINT ev")
        try:
            fresh = self._apply(c, b, e, etype, payload)
        except (ValueError, sqlite3.IntegrityError, TypeError, KeyError) as err:
            c.execute("ROLLBACK TO ev")
            c.execute("RELEASE ev")
            result.rejected[e.id] = str(err)[:300]
            return
        c.execute("RELEASE ev")
        (result.accepted if fresh else result.duplicates).append(e.id)
        if fresh:
            b.written.append(e.id)

    def _apply(
        self, c: sqlite3.Connection, b: _Batch, e: ev.IncomingEvent, etype: EventType, payload: dict[str, Any]
    ) -> bool:
        """Store one valid event and what follows from it; False when it was already stored (a retry)."""
        banked = False
        if etype is EventType.RESPONSE_GIVEN:
            known = c.execute("SELECT 1 FROM learning_event WHERE id = ?", (e.id,)).fetchone()
            # a review question takes two tries at most; a retry of a stored answer is not a new try
            banked = (
                pj.is_bank(c, payload["attempt_id"])
                if known
                else self.reviews.check_review_answer(c, b.learner, payload)
            )
        status = ev.insert_event(
            c,
            event_id=e.id,
            etype=etype,
            payload=payload,
            learner_id=b.learner,
            device_id=b.device_id,
            device_at=e.device_at,
            tz=e.tz,
            boundary=b.boundary,
            type_version=e.type_version,
        )
        fresh = status == "accepted"
        if etype is EventType.RESPONSE_GIVEN:
            b.graded[e.id] = self._graded(c, b, e, payload, fresh=fresh, banked=banked)
        elif etype is EventType.ATTEMPT_FINISHED:
            self._attempt_finished(c, b, e, payload, fresh=fresh)
        elif fresh:
            self._after_event(c, b, etype, payload)
        return fresh

    def _graded(
        self, c: sqlite3.Connection, b: _Batch, e: ev.IncomingEvent, payload: dict[str, Any], *, fresh: bool,
        banked: bool,
    ) -> Any:  # fmt: skip
        # a retry after a lost reply gets the grade it already has, never a second one
        g = (
            self.study._grade_now(c, e.id, payload, b.learner, e.tz, b.boundary)
            if fresh
            else self.study.existing_grade(c, e.id)
        )
        if self.study._purpose_of(c, payload["attempt_id"]) in ("skill_test", "placement"):
            g = {"pending": True, "hidden": True}  # tests show results when finished
        if banked:  # staged: no key and no other rationale before the question is resolved
            g = self.reviews._feedback(c, b.learner, payload["attempt_id"], payload["item_version_id"])
        return g

    def _attempt_finished(
        self, c: sqlite3.Connection, b: _Batch, e: ev.IncomingEvent, payload: dict[str, Any], *, fresh: bool
    ) -> None:
        if fresh:
            outcome, extra = self.study._finish_attempt(c, b.learner, payload, e.tz, b.boundary)
            b.written += extra
            self.reviews.after_review_session(c, b.learner, payload["attempt_id"])
        else:  # a retry after a lost reply: the outcome already written, never a second one
            outcome = self.study.stored_outcome(c, payload["attempt_id"])
        if outcome is not None:
            b.outcomes[payload["attempt_id"]] = outcome

    def _after_event(
        self, c: sqlite3.Connection, b: _Batch, etype: EventType, payload: dict[str, Any]
    ) -> None:
        """What a newly stored event of the other types sets off."""
        if etype is EventType.GRADE_CONTESTED:
            self._contest(c, payload)
        elif etype is EventType.PROPOSAL_DECIDED:
            self.tutor._decide_proposal(c, b.learner, payload)
        elif etype is EventType.LESSON_COMPLETED:
            row = c.execute(
                "SELECT l.path_id, l.id FROM lesson_version v JOIN lesson l ON l.id = v.lesson_id WHERE v.id = ?",
                (payload["lesson_version_id"],),
            ).fetchone()
            if row:
                b.paths.add(row[0])
                self.reviews.queue_review_bank(c, row[1])  # if the buffer did not write it already

    def _contest(self, c: sqlite3.Connection, payload: dict[str, Any]) -> None:
        """A contested model grade is graded again with the learner's reason; other types keep theirs."""
        row = c.execute(
            "SELECT i.type_key FROM learning_event e JOIN item_version v ON v.id = e.item_version_id "
            "JOIN item i ON i.id = v.item_id WHERE e.id = ?",
            (payload["response_event_id"],),
        ).fetchone()
        if row and xt.get(row[0]).method.value == "model":
            enqueue(c, "grade", EntityKind.RESPONSE, payload["response_event_id"], priority=10)

    def settings_view(self, path_id: str | None = None) -> list[dict[str, Any]]:
        learner = self.ensure_learner()
        with self.readers.connection() as c:
            out = []
            for key, d in settings.REGISTRY.items():
                value, source = settings.effective(c, key, {"learner": learner, "path": path_id})
                out.append(
                    {
                        "key": key,
                        "cfg": d.cfg,
                        "levels": list(d.levels),
                        "value": value,
                        "source": source,
                        "default": d.default,
                        "explanation": d.explanation,
                        "example": d.example,
                        "suggestion": d.suggestion,
                        "impact": list(d.impact),
                        "weakens_learning": d.weakens_learning,
                    }
                )
        return out

    def put_learner_setting(self, key: str, value: Any, level: settings.Level, ref: str | None) -> None:
        if key not in settings.REGISTRY:
            raise NotFound(key)
        if level == "learner":
            ref = self.ensure_learner()
        self.put_setting(key, value, level, ref)
        if key in ("review.desired_retention", "review.max_interval_days"):
            # the review dates follow the setting at once: replay every objective with the new values
            learner = self.ensure_learner()

            def unit(c: sqlite3.Connection) -> None:
                s = self.study._proj_settings(c, learner)
                for (oid,) in c.execute(
                    "SELECT objective_id FROM objective_review_state WHERE learner_id = ?", (learner,)
                ).fetchall():
                    pj.rebuild_objective(c, learner, oid, self.scheduler, s)

            self.writer.run(unit)

    def requests(self, path_id: str) -> list[dict[str, Any]]:
        with self.readers.connection() as c:
            return _rows(
                c,
                "SELECT id, prompt, status, lesson_id, error, created_at FROM lesson_request "
                "WHERE path_id = ? ORDER BY created_at DESC",
                path_id,
            )


def _bound(c: sqlite3.Connection, role: str) -> bool:
    return (
        c.execute(
            "SELECT 1 FROM adapter_binding WHERE port = 'llm' AND role = ? AND enabled = 1", (role,)
        ).fetchone()
        is not None
    )


def _check(
    c: sqlite3.Connection,
    kind: EntityKind,
    version_id: str,
    check: str,
    verdict: CheckVerdict,
    fix_round: int,
    details: dict[str, Any],
    run_id: str | None,
    *,
    independent: bool | None = None,
) -> None:
    c.execute(
        'INSERT INTO quality_check (id, subject_kind, subject_version_id, "check", verdict, fix_round, '
        "independent, details, stage_run_id, at) VALUES (?, ?, ?, ?, ?, ?, ?, json(?), ?, ?)",
        (
            new_id(),
            kind.value,
            version_id,
            check,
            verdict.value,
            fix_round,
            None if independent is None else int(independent),
            json.dumps(details, ensure_ascii=False),
            run_id,
            clock.now(),
        ),
    )


def _review_issues(c: sqlite3.Connection, version_id: str) -> list[dict[str, Any]]:
    """What the reviewer found in a lesson version (its last review), most serious first."""
    row = c.execute(
        "SELECT details FROM quality_check WHERE subject_version_id = ? AND \"check\" = 'reviewer' ORDER BY at DESC "
        "LIMIT 1",
        (version_id,),
    ).fetchone()
    issues = json.loads(row[0]).get("issues", []) if row else []
    return sorted(
        ({k: i.get(k, "") for k in ("severity", "where", "claim", "correction")} for i in issues),
        key=lambda i: i["severity"] != "major",
    )


def _best_draft(c: sqlite3.Connection, lesson_id: str) -> str | None:
    """The rejected version with the fewest major issues, then minor ones, then the latest."""
    best: tuple[int, int, int] | None = None
    found = None
    for vid, no in c.execute(
        "SELECT id, version_no FROM lesson_version WHERE lesson_id = ? AND status = 'rejected'", (lesson_id,)
    ).fetchall():
        issues = _review_issues(c, vid)
        majors = sum(i["severity"] == "major" for i in issues)
        rank = (majors, len(issues) - majors, -no)
        if best is None or rank < best:
            best, found = rank, vid
    return found


def _merge_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Where a lesson comes from in the learner's files, one entry per file with its range (pages, slides, time)."""
    out: dict[str, dict[str, Any]] = {}
    for x in sources:
        m = out.get(x["material_id"])
        if m is None:
            out[x["material_id"]] = {
                k: x[k] for k in ("material_id", "title", "kind", "loc_kind", "loc_start", "loc_end")
            }
        else:
            m["loc_start"], m["loc_end"] = (
                min(m["loc_start"], x["loc_start"]),
                max(m["loc_end"], x["loc_end"]),
            )
    return list(out.values())
