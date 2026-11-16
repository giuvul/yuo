"""Skill tree drafts (stage `tree_outline` output) and writing them into the curriculum tables."""

import json
import re
import sqlite3
from typing import Literal

from pydantic import BaseModel, Field

from yuo.core import clock
from yuo.core.ids import new_id

CODE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
Bloom = Literal["remember", "understand", "apply", "analyze", "evaluate", "create"]


class ObjectiveDraft(BaseModel):
    code: str = Field(description="stable dotted code, unique in the path, e.g. sql.joins.inner.write")
    statement: str = Field(description="what the learner can do, one sentence starting with a verb")
    bloom_level: Bloom


class LessonPlan(BaseModel):
    code: str
    title: str


class SkillDraft(BaseModel):
    code: str
    title: str
    summary: str = Field(description="one or two sentences")
    requires: list[str] = Field(description="codes of skills in this path that must come first (direct only)")
    objectives: list[ObjectiveDraft]
    lessons: list[LessonPlan]


class BranchDraft(BaseModel):
    code: str
    title: str
    skills: list[SkillDraft]


class TreeDraft(BaseModel):
    branches: list[BranchDraft]


def tree_rules(tree: TreeDraft, *, max_lessons: int | None = None) -> list[str]:
    """Rules a schema cannot express : codes, references, DAG, sizes."""
    problems: list[str] = []
    seen: set[tuple[str, str]] = set()  # codes are unique per entity kind, not across kinds
    skills = [s for b in tree.branches for s in b.skills]

    def claim(code: str, kind: str) -> None:
        if not CODE.match(code):
            problems.append(f"{kind} code {code!r} must be lowercase letters, digits and . _ - separators")
        if (kind, code) in seen:
            problems.append(f"{kind} code {code!r} is used twice")
        seen.add((kind, code))

    if not tree.branches:
        problems.append("the tree needs at least one branch")
    for b in tree.branches:
        claim(b.code, "branch")
        if not b.skills:
            problems.append(f"branch {b.code} has no skills")
    for s in skills:
        claim(s.code, "skill")
        if not s.objectives:
            problems.append(f"skill {s.code} has no objectives")
        if not s.lessons:
            problems.append(f"skill {s.code} has no lessons")
        for o in s.objectives:
            claim(o.code, "objective")
        for lesson in s.lessons:
            claim(lesson.code, "lesson")
    skill_codes = {s.code for s in skills}
    for s in skills:
        for r in s.requires:
            if r not in skill_codes:
                problems.append(f"skill {s.code} requires unknown skill {r!r}")
            elif r == s.code:
                problems.append(f"skill {s.code} requires itself")
    if cycle := find_cycle({s.code: [r for r in s.requires if r in skill_codes] for s in skills}):
        problems.append("prerequisites form a cycle: " + " -> ".join(cycle))
    total = sum(len(s.lessons) for s in skills)
    if max_lessons is not None and total > max_lessons:
        problems.append(f"{total} lessons planned; at most {max_lessons}")
    return problems


def find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(n: str) -> list[str] | None:
        state[n] = 1
        stack.append(n)
        for m in graph.get(n, []):
            if state.get(m) == 1:
                return [*stack[stack.index(m) :], m]
            if state.get(m) is None and (found := visit(m)):
                return found
        stack.pop()
        state[n] = 2
        return None

    for node in graph:
        if state.get(node) is None and (found := visit(node)):
            return found
    return None


def apply_tree(
    c: sqlite3.Connection,
    path_id: str,
    tree: TreeDraft,
    *,
    origin: str = "generation",
    grow: dict[str, object] | None = None,
) -> dict[str, str]:
    """Write branches, skills, objectives, prerequisites and planned lessons; audit as one path_change.

    `grow`: the tree is added to a path that has one ("What next?"): branches go after the existing ones,
    `requires` may name existing skills, and the audit op is `grow_tree` with this direction.
    Returns lesson code -> lesson id. Runs inside the caller's unit of work.
    """
    base = c.execute("SELECT structure_version FROM path WHERE id = ?", (path_id,)).fetchone()[0]
    ids: dict[str, str] = {}
    lessons: dict[str, str] = {}
    first = 0
    if grow is not None:
        ids |= dict(c.execute("SELECT code, id FROM skill WHERE path_id = ?", (path_id,)).fetchall())
        first = c.execute(
            "SELECT coalesce(max(position) + 1, 0) FROM branch WHERE path_id = ?", (path_id,)
        ).fetchone()[0]
    for bpos, b in enumerate(tree.branches, start=first):
        ids[b.code] = new_id()
        c.execute(
            "INSERT INTO branch (id, path_id, code, title, position, extensions, archived_at) "
            "VALUES (?, ?, ?, ?, ?, '{}', NULL)",
            (ids[b.code], path_id, b.code, b.title, bpos),
        )
        for spos, s in enumerate(b.skills):
            ids[s.code] = new_id()
            c.execute(
                "INSERT INTO skill (id, branch_id, path_id, code, title, summary, position, mastery_threshold, "
                "optional, merged_into_skill_id, extensions, archived_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0, NULL, '{}', NULL)",
                (ids[s.code], ids[b.code], path_id, s.code, s.title, s.summary, spos),
            )
            for opos, o in enumerate(s.objectives):
                c.execute(
                    "INSERT INTO learning_objective (id, skill_id, path_id, code, statement, bloom_level, position, "
                    "extensions, archived_at) VALUES (?, ?, ?, ?, ?, ?, ?, '{}', NULL)",
                    (new_id(), ids[s.code], path_id, o.code, o.statement, o.bloom_level, opos),
                )
            for lpos, lesson in enumerate(s.lessons):
                lessons[lesson.code] = new_id()
                c.execute(
                    "INSERT INTO lesson (id, skill_id, path_id, code, kind, position, state, current_version_id, "
                    "extensions) VALUES (?, ?, ?, ?, 'core', ?, 'planned', NULL, ?)",
                    (
                        lessons[lesson.code],
                        ids[s.code],
                        path_id,
                        lesson.code,
                        lpos,
                        json.dumps({"yuo": {"planned_title": lesson.title}}),
                    ),
                )
    for b in tree.branches:
        for s in b.skills:
            for r in s.requires:
                c.execute(
                    "INSERT INTO skill_prerequisite (skill_id, requires_skill_id, path_id) VALUES (?, ?, ?)",
                    (ids[s.code], ids[r], path_id),
                )
    c.execute(
        "INSERT INTO path_change (id, path_id, base_structure_version, structure_version, ops, origin, proposal_id, "
        "device_id, at) VALUES (?, ?, ?, ?, json(?), ?, NULL, NULL, ?)",
        (
            new_id(),
            path_id,
            base,
            base + 1,
            json.dumps(
                [{"op": "add_tree", "tree": tree.model_dump(mode="json")}]
                if grow is None
                else [{"op": "grow_tree", "direction": grow, "tree": tree.model_dump(mode="json")}]
            ),
            origin,
            clock.now(),
        ),
    )
    c.execute(
        "UPDATE path SET structure_version = ?, updated_at = ? WHERE id = ?", (base + 1, clock.now(), path_id)
    )
    return lessons
