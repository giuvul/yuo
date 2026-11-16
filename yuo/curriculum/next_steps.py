"""The "What next?" checkpoint: how a path keeps going once a branch is done or the planned lessons run low.

Three steps, each one generation stage run by the path's `tree` job (the same job that planned the path):

1. `next_check`: from what Yuo already knows about the learner (mastery, objectives that keep slipping,
   wrong answers, the tutor's notes, lesson requests; see `diagnose`), the model writes 3 or 4 questions
   about where the learner wants to go, specific to the subject, and a short quiz on what lies just
   beyond what was learned. The quiz is a diagnostic like the level check: no learning events, the answer
   keys stay on the server.
2. `next_directions`: from the diagnosis, the quiz result and the answers, 2 or 3 named directions
   (deeper, wider, apply, fix weak spots), each with the reason it fits this learner.
3. `next_grow`: only after the learner confirms one direction, the new branches for it, added to the
   same path (progress stays; new skills may build on the skills already there).

The state lives in `path.extensions.yuo.next` (like the level check), so no table changes.
"""

import sqlite3
from typing import Any, Literal

from pydantic import BaseModel, Field

from yuo.curriculum.tree import TreeDraft, tree_rules

Kind = Literal["deeper", "wider", "apply", "fix"]
KINDS: tuple[Kind, ...] = ("deeper", "wider", "apply", "fix")
QUESTIONS = range(3, 5)  # direction questions
QUIZ = range(3, 6)  # quiz questions
DIRECTIONS = range(2, 4)
GROW_MAX_LESSONS = 12
LOW_LESSONS = 3  # "running low": this many lessons or fewer still to study
ACTIVE = ("preparing", "ready", "proposing", "proposed", "growing")


class DirectionQuestion(BaseModel):
    prompt: str = Field(
        description="one question about where the learner wants to go next, specific to the subject"
    )
    options: list[str] = Field(description="2 to 5 short answers to choose from")


class QuizQuestion(BaseModel):
    topic: str = Field(
        description="the topic just beyond what was learned, a few words (shown to the learner)"
    )
    prompt: str
    options: list[str] = Field(description="3 or 4 options, exactly one correct")
    answer: int = Field(description="index of the correct option, from 0")


class NextCheckDraft(BaseModel):
    questions: list[DirectionQuestion]
    quiz: list[QuizQuestion]


class Direction(BaseModel):
    code: str = Field(description="short lowercase id, unique among the directions, e.g. deeper-voicings")
    kind: Kind
    title: str = Field(description="a few words, names what the learner would learn")
    reason: str = Field(
        description="one or two sentences: why this fits this learner, from their answers and results"
    )
    preview: list[str] = Field(description="2 to 4 skill titles this direction would add")


class DirectionsDraft(BaseModel):
    directions: list[Direction]


def check_rules(draft: NextCheckDraft) -> list[str]:
    problems: list[str] = []
    if len(draft.questions) not in QUESTIONS:
        problems.append(f"write 3 or 4 direction questions, not {len(draft.questions)}")
    for n, q in enumerate(draft.questions, 1):
        if not q.prompt.strip():
            problems.append(f"direction question {n}: the prompt is empty")
        if not 2 <= len(q.options) <= 5:
            problems.append(f"direction question {n}: give 2 to 5 options")
        if len({o.strip().lower() for o in q.options}) != len(q.options):
            problems.append(f"direction question {n}: options must differ")
    if len(draft.quiz) not in QUIZ:
        problems.append(f"write 3 to 5 quiz questions, not {len(draft.quiz)}")
    for n, item in enumerate(draft.quiz, 1):
        if not 3 <= len(item.options) <= 4:
            problems.append(f"quiz question {n}: give 3 or 4 options")
        elif not 0 <= item.answer < len(item.options):
            problems.append(f"quiz question {n}: answer must be the index of one of its options")
        if len({o.strip().lower() for o in item.options}) != len(item.options):
            problems.append(f"quiz question {n}: options must differ")
        if not item.prompt.strip():
            problems.append(f"quiz question {n}: the prompt is empty")
    return problems


def directions_rules(weak: bool, avoid: list[str]) -> Any:
    """`weak`: the diagnosis found weak spots (only then is a "fix" direction allowed). `avoid`: titles the
    learner already turned down."""
    taken = {a.strip().lower() for a in avoid}

    def rules(draft: DirectionsDraft) -> list[str]:
        problems: list[str] = []
        ds = draft.directions
        if len(ds) not in DIRECTIONS:
            problems.append(f"propose 2 or 3 directions, not {len(ds)}")
        if len({d.kind for d in ds}) != len(ds):
            problems.append("each direction must be a different kind")
        if len({d.code for d in ds}) != len(ds):
            problems.append("direction codes must be unique")
        for d in ds:
            if d.kind == "fix" and not weak:
                problems.append("no weak spots were found: do not propose a fix direction")
            if not 2 <= len(d.preview) <= 4:
                problems.append(f"direction {d.code}: list 2 to 4 skills in preview")
            if not d.reason.strip():
                problems.append(f"direction {d.code}: give the reason it fits the learner")
            if d.title.strip().lower() in taken:
                problems.append(f"direction {d.code}: the learner already turned this one down")
        return problems

    return rules


def grow_rules(existing: dict[str, set[str]]) -> Any:
    """New branches for a path that already has a tree: the usual tree rules, codes that do not collide with
    the path's, prerequisites on new or existing skills, at most `GROW_MAX_LESSONS` lessons."""

    def rules(tree: TreeDraft) -> list[str]:
        skills = existing.get("skill", set())
        problems = [
            p for p in tree_rules(tree, max_lessons=GROW_MAX_LESSONS)
            if not any(p.endswith(f"requires unknown skill {s!r}") for s in skills)
        ]  # fmt: skip
        if len(tree.branches) > 2:
            problems.append(f"add 1 or 2 branches, not {len(tree.branches)}")
        for b in tree.branches:
            if b.code in existing.get("branch", set()):
                problems.append(f"branch code {b.code!r} is already in the path")
            for s in b.skills:
                if s.code in skills:
                    problems.append(f"skill code {s.code!r} is already in the path")
                for o in s.objectives:
                    if o.code in existing.get("objective", set()):
                        problems.append(f"objective code {o.code!r} is already in the path")
                for lesson in s.lessons:
                    if lesson.code in existing.get("lesson", set()):
                        problems.append(f"lesson code {lesson.code!r} is already in the path")
        return problems

    return rules


def public_quiz(quiz: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"prompt": q["prompt"], "options": q["options"], "topic": q["topic"]} for q in quiz]


def score_quiz(quiz: list[dict[str, Any]], answers: list[int | None]) -> dict[str, Any]:
    answers = list(answers[: len(quiz)]) + [None] * max(0, len(quiz) - len(answers))
    right = [a is not None and a == q["answer"] for q, a in zip(quiz, answers, strict=True)]
    ready = [q["topic"] for q, ok in zip(quiz, right, strict=True) if ok]
    return {
        "right": sum(right),
        "total": len(quiz),
        "ready": ready,
        "not_yet": [
            q["topic"] for q, ok in zip(quiz, right, strict=True) if not ok and q["topic"] not in ready
        ],
        "answers": answers,
    }


def answered(questions: list[dict[str, Any]], answers: list[dict[str, Any]]) -> list[str]:
    """The direction questions with the learner's answers, one line each, for the prompt."""
    lines = []
    for q, a in zip(questions, list(answers) + [{}] * max(0, len(questions) - len(answers)), strict=False):
        picked = a.get("option")
        text = (a.get("text") or "").strip()
        choice = q["options"][picked] if isinstance(picked, int) and 0 <= picked < len(q["options"]) else None
        said = "; ".join(x for x in (choice, text) if x) or "(no answer)"
        lines.append(f"{q['prompt']} -> {said}")
    return lines


# --- diagnosis from what Yuo already knows ---------------------------------------------------------


def _col(c: sqlite3.Connection, sql: str, *args: Any) -> list[Any]:
    return [r[0] for r in c.execute(sql, args)]


def diagnose(c: sqlite3.Connection, path_id: str) -> dict[str, Any]:
    """Signals that need no model call: lessons done and left, branches finished, skills strong and weak,
    objectives that keep slipping (review lapses and wrong answers), the tutor's notes on misconceptions and
    the learner's lesson requests. Titles and statements only, for the learner's screen and the prompts."""
    learner = c.execute("SELECT learner_id FROM path WHERE id = ?", (path_id,)).fetchone()[0]
    done = set(
        _col(
            c,
            "SELECT DISTINCT v.lesson_id FROM learning_event e JOIN lesson_version v ON v.id = e.lesson_version_id "
            "JOIN lesson l ON l.id = v.lesson_id WHERE e.type = 'lesson.completed' AND l.path_id = ?",
            path_id,
        )
    )
    lessons = c.execute(
        "SELECT l.id, l.state, b.id AS branch_id FROM lesson l JOIN skill s ON s.id = l.skill_id "
        "JOIN branch b ON b.id = s.branch_id WHERE l.path_id = ? AND s.archived_at IS NULL "
        "AND b.archived_at IS NULL",
        (path_id,),
    ).fetchall()
    by_branch: dict[str, list[str]] = {}
    for lid, _, bid in lessons:
        by_branch.setdefault(bid, []).append(lid)
    finished = [bid for bid, ids in by_branch.items() if ids and all(i in done for i in ids)]
    titles = dict(c.execute("SELECT id, title FROM branch WHERE path_id = ?", (path_id,)).fetchall())
    left = sum(1 for lid, state, _ in lessons if lid not in done and state != "failed")
    skills = c.execute(
        "SELECT s.title, p.mastery, p.evidence_count FROM skill_progress p JOIN skill s ON s.id = p.skill_id "
        "WHERE s.path_id = ? AND p.learner_id = ? AND s.archived_at IS NULL ORDER BY s.position",
        (path_id, learner),
    ).fetchall()
    strong = [t for t, m, _ in skills if m >= 0.8]
    weak = [t for t, m, n in skills if n > 0 and m < 0.5]
    slipping = _col(
        c,
        "SELECT o.statement FROM objective_review_state r JOIN learning_objective o ON o.id = r.objective_id "
        "WHERE o.path_id = ? AND r.learner_id = ? AND r.lapses > 0 ORDER BY r.lapses DESC LIMIT 5",
        path_id,
        learner,
    )
    wrong = _col(
        c,
        "SELECT o.statement FROM response r JOIN item_version_objective io ON io.item_version_id = r.item_version_id "
        "JOIN learning_objective o ON o.id = io.objective_id WHERE o.path_id = ? AND r.score IS NOT NULL "
        "AND r.score < 0.5 GROUP BY o.id HAVING count(*) >= 2 ORDER BY count(*) DESC LIMIT 5",
        path_id,
    )
    misconceptions = _col(
        c,
        "SELECT text FROM learner_memory_item WHERE learner_id = ? AND kind = 'misconception' "
        "AND archived_at IS NULL ORDER BY updated_at DESC LIMIT 5",
        learner,
    )
    requests = _col(
        c, "SELECT prompt FROM lesson_request WHERE path_id = ? ORDER BY created_at DESC LIMIT 5", path_id
    )
    shaky = list(dict.fromkeys([*slipping, *wrong]))[:5]
    return {
        "lessons_done": len(done),
        "lessons_left": left,
        "finished_branches": [titles[b] for b in finished],
        "finished_branch_ids": finished,
        "strong": strong,
        "weak": weak,
        "shaky": shaky,
        "misconceptions": misconceptions,
        "requests": requests,
    }


def has_weak_spots(d: dict[str, Any]) -> bool:
    return bool(d["weak"] or d["shaky"] or d["misconceptions"])


def summary(d: dict[str, Any]) -> str:
    """The diagnosis as text for the prompts (the tutor's notes and requests are the learner's data)."""

    def items(xs: list[str]) -> str:
        return "; ".join(xs) or "(none)"

    return (
        f"Lessons studied: {d['lessons_done']}; still planned: {d['lessons_left']}.\n"
        f"Branches finished: {items(d['finished_branches'])}.\n"
        f"Strong skills: {items(d['strong'])}.\n"
        f"Weak skills: {items(d['weak'])}.\n"
        f"Objectives that keep slipping: {items(d['shaky'])}.\n"
        f"Misconceptions the tutor noted: {items(d['misconceptions'])}.\n"
        f"Lessons the learner asked for: {items(d['requests'])}."
    )


# the checkpoint is offered once this share of the path's lessons is studied ("What
# next? shouldn't appear until at least 75% of the path is completed")
AVAILABLE_FROM = 0.75


def completion(d: dict[str, Any]) -> float:
    """Studied lessons over studied plus still planned ones (failed lessons are not counted)."""
    total = d["lessons_done"] + d["lessons_left"]
    return d["lessons_done"] / total if total else 0.0


def available(state: dict[str, Any] | None, d: dict[str, Any]) -> bool:
    """Whether the path page shows "What next?": from AVAILABLE_FROM on, or while a checkpoint is open."""
    return (state or {}).get("status") in ACTIVE or completion(d) >= AVAILABLE_FROM


def offer(state: dict[str, Any] | None, d: dict[str, Any]) -> str | None:
    """Why the path page invites the learner to the checkpoint now, or None. Only once AVAILABLE_FROM of the
    path is studied, and after progress since the last checkpoint (done or dismissed): a branch finished
    since then, or few lessons left."""
    state = state or {}
    if state.get("status") in ACTIVE or d["lessons_done"] == 0 or completion(d) < AVAILABLE_FROM:
        return None
    seen_done = int(state.get("seen_done", 0))
    if d["lessons_done"] <= seen_done:
        return None
    seen_branches = set(state.get("seen_branches", []))
    if any(b not in seen_branches for b in d["finished_branch_ids"]):
        return "branch_done"
    if d["lessons_left"] <= LOW_LESSONS:
        return "running_low"
    return None
