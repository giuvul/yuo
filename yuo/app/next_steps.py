"""The "What next?" checkpoint (yuo/curriculum/next_steps.py): offered on the path page when a branch is
finished or few planned lessons are left, or opened with its button. A part of the application service (yuo.app.context).

States (`path.extensions.yuo.next.status`): preparing (the questions and quiz are being written) -> ready
(the learner answers) -> proposing (directions are being written) -> proposed (the learner picks one, or
asks for others) -> growing (the new branches are being written) -> done. `dismissed` closes it without
changes. Each writing step is the path's `tree` job; nothing is added to the path before the learner
confirms a direction.
"""

import sqlite3
from typing import TYPE_CHECKING, Any

from yuo.app.context import AppContext, Part
from yuo.app.ports import Buffer, Models, PathInputs
from yuo.app.repo import find_path, get_path, path_state, save_path_state
from yuo.app.stages import NEXT_CHECK, next_directions_spec, next_grow_spec
from yuo.core import clock
from yuo.core.enums import DataClass, EntityKind
from yuo.core.errors import InvalidInput
from yuo.curriculum import next_steps as ns
from yuo.curriculum.tree import apply_tree
from yuo.generation.jobs import URGENT_PRIORITY, Job, enqueue

if TYPE_CHECKING:
    pass


def _outline(c: sqlite3.Connection, path_id: str) -> list[dict[str, Any]]:
    out = []
    for bid, title in c.execute(
        "SELECT id, title FROM branch WHERE path_id = ? AND archived_at IS NULL ORDER BY position", (path_id,)
    ).fetchall():
        skills = [
            {"code": code, "title": t}
            for code, t in c.execute(
                "SELECT code, title FROM skill WHERE branch_id = ? AND archived_at IS NULL ORDER BY position",
                (bid,),
            )
        ]
        out.append({"title": title, "skills": skills})
    return out


def _existing(c: sqlite3.Connection, path_id: str) -> dict[str, set[str]]:
    return {
        kind: {r[0] for r in c.execute(f"SELECT code FROM {table} WHERE path_id = ?", (path_id,))}
        for kind, table in (
            ("branch", "branch"),
            ("skill", "skill"),
            ("objective", "learning_objective"),
            ("lesson", "lesson"),
        )
    }


class NextSteps(Part):
    """A part of the application service (yuo.app.context), built with what it calls on the others."""

    def __init__(self, ctx: AppContext, *, models: Models, paths: PathInputs, buffer: Buffer) -> None:
        super().__init__(ctx)
        self.models = models
        self.paths = paths
        self.buffer = buffer

    # --- the learner's view ------------------------------------------------------------------------

    def next_view(self, path_id: str) -> dict[str, Any]:
        with self.readers.connection() as c:
            p = get_path(c, path_id)
            state = path_state(p, "next") or {}
            d = ns.diagnose(c, path_id)
            job = c.execute(
                "SELECT id, status FROM generation_job WHERE kind = 'tree' AND target_id = ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (path_id,),
            ).fetchone()
        status = state.get("status", "none")
        writing = status in ("preparing", "proposing", "growing")
        return {
            "status": status,
            "offer": ns.offer(state, d),
            "available": ns.available(state, d),
            "completion": round(ns.completion(d), 3),
            "diagnosis": {
                k: d[k]
                for k in ("lessons_done", "lessons_left", "finished_branches", "strong", "weak", "shaky")
            },
            "questions": state.get("questions", []) if status == "ready" else [],
            "quiz": ns.public_quiz(state.get("quiz", [])) if status == "ready" else [],
            "quiz_result": {k: v for k, v in state["quiz_result"].items() if k != "answers"}
            if state.get("quiz_result")
            else None,
            "directions": state.get("directions", []) if status in ("proposed", "growing") else [],
            "chosen": state.get("chosen"),
            "added": state.get("added", []),
            "job_id": job["id"] if job is not None and writing else None,
            "failed": writing and job is not None and job["status"] == "failed",
        }

    # --- the learner's steps ---------------------------------------------------------------------------

    def _step(self, path_id: str, change: Any, *, ai: bool = True) -> dict[str, Any]:
        if ai:
            self.models.require_ai_ready()

        def unit(c: sqlite3.Connection) -> None:
            p = get_path(c, path_id)
            if p["status"] != "active":
                raise InvalidInput("the path is not planned yet")
            new = change(c, path_state(p, "next") or {})
            save_path_state(c, path_id, "next", touch=True, state=new)
            if new["status"] in ("preparing", "proposing", "growing"):
                enqueue(c, "tree", EntityKind.PATH, path_id, priority=URGENT_PRIORITY)

        self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return self.next_view(path_id)

    def start_next(self, path_id: str) -> dict[str, Any]:
        """Open the checkpoint: write the direction questions and the quiz."""

        def change(c: sqlite3.Connection, state: dict[str, Any]) -> dict[str, Any]:
            if state.get("status") in ns.ACTIVE:
                raise InvalidInput("a checkpoint is already open for this path")
            return {"status": "preparing", "started_at": clock.now(), **_seen(state)}

        return self._step(path_id, change)

    def answer_next(
        self, path_id: str, quiz: list[int | None], answers: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Score the quiz, keep the answers and write the directions."""

        def change(c: sqlite3.Connection, state: dict[str, Any]) -> dict[str, Any]:
            if state.get("status") != "ready":
                raise InvalidInput("the checkpoint is not waiting for answers")
            return state | {
                "status": "proposing",
                "quiz_result": ns.score_quiz(state["quiz"], quiz),
                "answers": answers[: len(state["questions"])],
            }

        return self._step(path_id, change)

    def other_directions(self, path_id: str) -> dict[str, Any]:
        """None of the directions fits: propose different ones."""

        def change(c: sqlite3.Connection, state: dict[str, Any]) -> dict[str, Any]:
            if state.get("status") != "proposed":
                raise InvalidInput("there are no directions to replace")
            avoid = [*state.get("avoid", []), *(d["title"] for d in state.get("directions", []))]
            return state | {"status": "proposing", "avoid": avoid[-9:], "directions": []}

        return self._step(path_id, change)

    def choose_next(self, path_id: str, code: str) -> dict[str, Any]:
        """The learner confirms a direction: only now is the path grown."""

        def change(c: sqlite3.Connection, state: dict[str, Any]) -> dict[str, Any]:
            if state.get("status") != "proposed":
                raise InvalidInput("there are no directions to choose from")
            if code not in {d["code"] for d in state["directions"]}:
                raise InvalidInput(f"unknown direction {code!r}")
            return state | {"status": "growing", "chosen": code}

        return self._step(path_id, change)

    def dismiss_next(self, path_id: str) -> dict[str, Any]:
        """Close the checkpoint without changes ("Not now"); it is offered again after more progress."""

        def change(c: sqlite3.Connection, state: dict[str, Any]) -> dict[str, Any]:
            if state.get("status") in ("growing",):
                raise InvalidInput("the new branches are being written")
            return {"status": "dismissed", **_seen(state, ns.diagnose(c, path_id))}

        return self._step(path_id, change, ai=False)

    def retry_next(self, path_id: str) -> dict[str, Any]:
        """Run the failed writing step again."""

        def change(c: sqlite3.Connection, state: dict[str, Any]) -> dict[str, Any]:
            job = c.execute(
                "SELECT status FROM generation_job WHERE kind = 'tree' AND target_id = ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (path_id,),
            ).fetchone()
            if (
                state.get("status") not in ("preparing", "proposing", "growing")
                or job is None
                or job[0] != "failed"
            ):
                raise InvalidInput("nothing to retry")
            return state

        return self._step(path_id, change)

    # --- the writing steps (the path's tree job) ---------------------------------------------------------

    def next_pending(self, c: sqlite3.Connection, path_id: str) -> str | None:
        """The checkpoint step a `tree` job on this path should run, if any."""
        p = find_path(c, path_id)
        status = (path_state(p, "next") or {}).get("status")
        return status if status in ("preparing", "proposing", "growing") else None

    def handle_next(self, job: Job, step: str) -> None:
        with self.readers.connection() as c:
            p = find_path(c, job.target_id)
            state = path_state(p, "next") or {}
            inputs, dclass = self.paths.path_inputs(c, job.target_id)
            d = ns.diagnose(c, job.target_id)
            outline = _outline(c, job.target_id)
            existing = _existing(c, job.target_id)
        private = d["misconceptions"] or d["requests"] or state.get("answers")
        dclass = DataClass.FREE_TEXT if private else dclass
        base = {
            k: inputs[k]
            for k in (
                "subject",
                "goal",
                "goal_type",
                "difficulty",
                "lang",
                "custom_instructions",
                "interests",
            )
            if k in inputs
        } | {"outline": outline, "diagnosis": ns.summary(d)}
        gen = self.models.binding("generator")
        new: dict[str, Any]
        if step == "preparing":
            check = self.runner.run(job.id, NEXT_CHECK, gen, base, data_class=dclass).value
            new = state | {
                "status": "ready",
                "questions": [q.model_dump() for q in check.questions],
                "quiz": [q.model_dump() for q in check.quiz],
            }
        elif step == "proposing":
            qr = state.get("quiz_result") or {"right": 0, "total": 0, "ready": [], "not_yet": []}
            quiz = (
                f"{qr['right']} of {qr['total']} right. Ready for: {'; '.join(qr['ready']) or '(none)'}. "
                f"Not yet: {'; '.join(qr['not_yet']) or '(none)'}."
            )
            avoid = list(state.get("avoid", []))
            inputs_ = base | {
                "quiz": quiz,
                "answers": ns.answered(state.get("questions", []), state.get("answers", [])),
                "avoid": avoid,
            }
            proposed = self.runner.run(
                job.id,
                next_directions_spec(ns.has_weak_spots(d), avoid),
                gen,
                inputs_,
                data_class=dclass,
            )
            new = state | {
                "status": "proposed",
                "directions": [x.model_dump() for x in proposed.value.directions],
            }
        else:  # growing
            chosen = next(x for x in state["directions"] if x["code"] == state["chosen"])
            grown = self.runner.run(
                job.id,
                next_grow_spec(existing),
                gen,
                base | {k: chosen[k] for k in ("kind", "title", "reason", "preview")},
                data_class=dclass,
            )
            tree = grown.value

            def unit(c: sqlite3.Connection) -> None:
                now = path_state(find_path(c, job.target_id), "next") or {}
                if now.get("status") != "growing":
                    return  # a retried job after the branches were added
                apply_tree(c, job.target_id, tree, grow={k: chosen[k] for k in ("code", "kind", "title")})
                after = ns.diagnose(c, job.target_id)
                save_path_state(
                    c,
                    job.target_id,
                    "next",
                    now
                    | {
                        "status": "done",
                        "added": [b.title for b in tree.branches],
                        "finished_at": clock.now(),
                    }
                    | _seen(now, after),
                    touch=True,
                )
                self.buffer.top_up_buffer(c, job.target_id)

            self.writer.run(unit)
            if self.worker:
                self.worker.wake()
            return

        def save(c: sqlite3.Connection) -> None:
            now = path_state(find_path(c, job.target_id), "next") or {}
            if now.get("status") != step:
                return  # dismissed while the step ran
            save_path_state(c, job.target_id, "next", touch=True, state=new)

        self.writer.run(save)


def _seen(state: dict[str, Any], d: dict[str, Any] | None = None) -> dict[str, Any]:
    """What the checkpoint has already covered, so it is offered again only after more progress."""
    if d is None:
        return {k: state[k] for k in ("seen_done", "seen_branches") if k in state}
    return {"seen_done": d["lessons_done"], "seen_branches": d["finished_branch_ids"]}
