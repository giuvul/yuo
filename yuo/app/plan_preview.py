"""The plan preview: the learner sees the skill tree before it is built, asks for changes in their own words,
and builds it when it fits. A part of the application service (yuo.app.context).

States (`path.extensions.yuo.preview.status`): drafting (the first plan is being written, by the path's `tree`
job) -> ready (the learner reads it) -> revising (their feedback is being applied, the `tree` job again) ->
ready ... -> built (the plan was written into the path; lessons follow). Nothing is spent on lessons before the
learner builds the plan.
"""

import sqlite3
from typing import Any

from yuo.app.context import AppContext, Part
from yuo.app.ports import Buffer, Models, PathInputs
from yuo.app.repo import get_path, path_state, save_path_state
from yuo.app.stages import tree_revise_spec
from yuo.core import clock
from yuo.core.enums import DataClass, EntityKind
from yuo.core.errors import InvalidInput
from yuo.curriculum.depth import TREE_SIZES, depth_of
from yuo.curriculum.tree import TreeDraft, apply_tree
from yuo.generation.jobs import URGENT_PRIORITY, Job, enqueue
from yuo.generation.runner import StageFailed

FEEDBACK_MAX = 2000
ROUNDS_MAX = 12  # feedback rounds kept and sent to the model; older ones are dropped
WRITING = ("drafting", "revising")


class PlanPreview(Part):
    def __init__(self, ctx: AppContext, *, models: Models, paths: PathInputs, buffer: Buffer) -> None:
        super().__init__(ctx)
        self.models = models
        self.paths = paths
        self.buffer = buffer

    # --- the learner's view ----------------------------------------------------------------------------

    def preview_view(self, path_id: str) -> dict[str, Any]:
        with self.readers.connection() as c:
            state = path_state(get_path(c, path_id), "preview") or {}
            job = c.execute(
                "SELECT id, status FROM generation_job WHERE kind = 'tree' AND target_id = ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (path_id,),
            ).fetchone()
        status = state.get("status", "none")
        writing = status in WRITING
        return {
            "status": status,
            "version": state.get("version", 0),
            "tree": state.get("tree"),
            "changes": state.get("changes", []),
            "feedback": [r["text"] for r in state.get("rounds", [])],
            "job_id": job["id"] if job is not None and writing else None,
            "failed": writing and job is not None and job["status"] == "failed",
        }

    def preview_feedback(self, path_id: str, text: str) -> dict[str, Any]:
        """The learner's change request: the plan is revised with it."""
        text = text.strip()
        if not text:
            raise InvalidInput("say what to change")
        if len(text) > FEEDBACK_MAX:
            raise InvalidInput(f"at most {FEEDBACK_MAX} characters")
        self.models.require_ai_ready()

        def unit(c: sqlite3.Connection) -> None:
            state = path_state(get_path(c, path_id), "preview") or {}
            if state.get("status") != "ready":
                raise InvalidInput("the plan is not waiting for feedback")
            rounds = [*state.get("rounds", []), {"text": text, "at": clock.now()}][-ROUNDS_MAX:]
            save_path_state(
                c, path_id, "preview", state | {"status": "revising", "rounds": rounds}, touch=True
            )
            enqueue(c, "tree", EntityKind.PATH, path_id, priority=URGENT_PRIORITY)

        self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return self.preview_view(path_id)

    def retry_preview(self, path_id: str) -> dict[str, Any]:
        """Write the plan again after the job that writes it failed."""
        self.models.require_ai_ready()

        def unit(c: sqlite3.Connection) -> None:
            state = path_state(get_path(c, path_id), "preview") or {}
            job = c.execute(
                "SELECT status FROM generation_job WHERE kind = 'tree' AND target_id = ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (path_id,),
            ).fetchone()
            if state.get("status") not in WRITING or job is None or job[0] != "failed":
                raise InvalidInput("the plan is not waiting to be written again")
            enqueue(c, "tree", EntityKind.PATH, path_id, priority=URGENT_PRIORITY)

        self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return self.preview_view(path_id)

    def undo_feedback(self, path_id: str) -> dict[str, Any]:
        """Back to the plan before the last change (the revision did not help)."""

        def unit(c: sqlite3.Connection) -> None:
            state = path_state(get_path(c, path_id), "preview") or {}
            history = state.get("history", [])
            if state.get("status") != "ready" or not history:
                raise InvalidInput("there is no earlier plan")
            prev = history[-1]
            save_path_state(
                c,
                path_id,
                "preview",
                state
                | {
                    "tree": prev["tree"],
                    "changes": [],
                    "version": state.get("version", 1) + 1,
                    "history": history[:-1],
                    "rounds": state.get("rounds", [])[:-1],
                },
                touch=True,
            )

        self.writer.run(unit)
        return self.preview_view(path_id)

    def build_preview(self, path_id: str) -> dict[str, Any]:
        """The learner accepts the plan: it is written into the path and the first lessons are queued."""

        def unit(c: sqlite3.Connection) -> None:
            state = path_state(get_path(c, path_id), "preview") or {}
            if state.get("status") != "ready" or not state.get("tree"):
                raise InvalidInput("there is no plan ready to build")
            if c.execute("SELECT count(*) FROM branch WHERE path_id = ?", (path_id,)).fetchone()[0]:
                raise InvalidInput("this path is already built")
            tree = TreeDraft.model_validate(state["tree"])
            lessons = apply_tree(c, path_id, tree)
            if not lessons:
                raise InvalidInput("the plan has no lessons")
            c.execute(
                "UPDATE path SET status = 'active', updated_at = ? WHERE id = ?", (clock.now(), path_id)
            )
            save_path_state(
                c,
                path_id,
                "preview",
                {"status": "built", "version": state.get("version", 1), "at": clock.now()},
            )
            self.buffer.top_up_buffer(c, path_id)

        self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return self.preview_view(path_id)

    # --- the tree job's preview steps --------------------------------------------------------------------

    def wants_preview(self, c: sqlite3.Connection, path_id: str) -> str | None:
        """The preview step the path's tree job has to do: 'drafting', 'revising', or None."""
        status = (path_state(get_path(c, path_id), "preview") or {}).get("status")
        return status if status in WRITING else None

    def store_draft(self, c: sqlite3.Connection, path_id: str, tree: TreeDraft) -> None:
        """The first plan, from the `tree_outline` stage: kept for the learner instead of being built."""
        state = path_state(get_path(c, path_id), "preview") or {}
        if state.get("status") != "drafting":
            return  # a retried job after a crash: the plan is already there
        save_path_state(
            c,
            path_id,
            "preview",
            state | {"status": "ready", "tree": tree.model_dump(mode="json"), "version": 1, "changes": []},
            touch=True,
        )

    def revise(self, job: Job) -> None:
        with self.readers.connection() as c:
            inputs, _ = self.paths.path_inputs(c, job.target_id)
            state = path_state(get_path(c, job.target_id), "preview") or {}
        if state.get("status") != "revising" or not state.get("tree"):
            return
        feedback = [r["text"] for r in state.get("rounds", [])]
        out = self.ctx.runner.run(
            job.id,
            tree_revise_spec(TREE_SIZES[depth_of(inputs.get("depth"))].max_lessons),
            self.models.binding("generator"),
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
                )
                if k in inputs
            }
            | {"tree": state["tree"], "feedback": feedback},
            data_class=DataClass.FREE_TEXT,  # the feedback is the learner's own words
        )
        if not out.value.tree.branches:
            raise StageFailed("the revised plan has no branches")

        def unit(c: sqlite3.Connection) -> None:
            now = path_state(get_path(c, job.target_id), "preview") or {}
            if now.get("status") != "revising":
                return
            history = [*now.get("history", []), {"tree": now["tree"], "version": now.get("version", 1)}][
                -ROUNDS_MAX:
            ]
            save_path_state(
                c,
                job.target_id,
                "preview",
                now
                | {
                    "status": "ready",
                    "tree": out.value.tree.model_dump(mode="json"),
                    "changes": out.value.changes,
                    "version": now.get("version", 1) + 1,
                    "history": history,
                },
                touch=True,
            )

        self.writer.run(unit)
