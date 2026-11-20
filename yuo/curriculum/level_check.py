"""The level check before a path is planned: a few multiple-choice questions from the basics to advanced.

The learner answers them (or says they don't know) before the skill tree exists, so the tree starts at
the right depth: what they already know is compressed or skipped, the rest is taught. The questions are
a diagnostic, not a test: they are not reviewed item by item and leave no learning events. The answer
keys stay on the server.
"""

from typing import Any

from pydantic import BaseModel, Field

from yuo.core.choices import longest_is_right, shuffled

LEVELS = range(1, 6)
MIN_QUESTIONS, MAX_QUESTIONS = 6, 10
# the level reached -> the path's difficulty (05 path.difficulty)
DIFFICULTY = {
    0: "introductory",
    1: "foundational",
    2: "foundational",
    3: "intermediate",
    4: "advanced",
    5: "expert",
}


class LevelQuestion(BaseModel):
    topic: str = Field(description="the topic of the path this question samples, a few words")
    level: int = Field(description="1 = the very basics ... 5 = advanced, close to the goal")
    prompt: str
    options: list[str] = Field(description="3 or 4 options, exactly one correct")
    answer: int = Field(description="index of the correct option, from 0")


class LevelCheckDraft(BaseModel):
    questions: list[LevelQuestion]


def level_check_rules(draft: LevelCheckDraft) -> list[str]:
    problems: list[str] = []
    qs = draft.questions
    if not MIN_QUESTIONS <= len(qs) <= MAX_QUESTIONS:
        problems.append(f"write {MIN_QUESTIONS} to {MAX_QUESTIONS} questions, not {len(qs)}")
    for n, q in enumerate(qs, 1):
        if q.level not in LEVELS:
            problems.append(f"question {n}: level must be 1 to 5")
        if not 3 <= len(q.options) <= 4:
            problems.append(f"question {n}: give 3 or 4 options")
        elif not 0 <= q.answer < len(q.options):
            problems.append(f"question {n}: answer must be the index of one of its options")
        elif longest_is_right([q.options[q.answer]], [o for i, o in enumerate(q.options) if i != q.answer]):
            problems.append(
                f"question {n}: the right option is clearly the longest; make the options similar in length"
            )
        if len({o.strip().lower() for o in q.options}) != len(q.options):
            problems.append(f"question {n}: options must differ")
        if not q.prompt.strip():
            problems.append(f"question {n}: the prompt is empty")
    if len({q.level for q in qs}) < 3:
        problems.append("spread the questions over at least 3 levels, from the basics to advanced")
    return problems


def stored(draft: LevelCheckDraft, seed: str) -> list[dict[str, Any]]:
    """The questions as kept in path state, each with its options shuffled (models put the right one first)."""
    out = []
    for n, q in enumerate(draft.questions):
        options, answer = shuffled(q.options, q.answer, f"{seed}:{n}")
        out.append(q.model_dump() | {"options": options, "answer": answer})
    return out


def public(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the learner sees: no answer keys and no levels."""
    return [{"prompt": q["prompt"], "options": q["options"], "topic": q["topic"]} for q in questions]


def score(questions: list[dict[str, Any]], answers: list[int | None]) -> dict[str, Any]:
    """The level reached and the topics known and not known yet. `None` is "I don't know"; a missing
    answer counts as one. The level is the highest one where the learner got at least half right, at it
    and at every level below (a lucky guess at level 5 does not skip levels 2 to 4)."""
    answers = list(answers[: len(questions)]) + [None] * max(0, len(questions) - len(answers))
    right = [a is not None and a == q["answer"] for q, a in zip(questions, answers, strict=True)]
    by_level: dict[int, list[bool]] = {}
    for q, ok in zip(questions, right, strict=True):
        by_level.setdefault(int(q["level"]), []).append(ok)
    reached = 0
    for lvl in sorted(by_level):
        xs = by_level[lvl]
        if sum(xs) * 2 < len(xs):
            break
        reached = lvl
    known = _unique(q["topic"] for q, ok in zip(questions, right, strict=True) if ok)
    unknown = _unique(q["topic"] for q, ok in zip(questions, right, strict=True) if not ok)
    return {
        "level": reached,
        "difficulty": DIFFICULTY[reached],
        "right": sum(right),
        "total": len(questions),
        "known": known,
        "unknown": [t for t in unknown if t not in known],
        "answers": answers,
    }


def summary(result: dict[str, Any]) -> str:
    """One line for the tree prompt."""
    known = "; ".join(result["known"]) or "(none)"
    unknown = "; ".join(result["unknown"]) or "(none)"
    return (
        f"Level check: {result['right']} of {result['total']} right, level reached {result['level']} of 5. "
        f"Already knows: {known}. Does not know yet: {unknown}."
    )


def _unique(xs: Any) -> list[str]:
    out: list[str] = []
    for x in xs:
        if x not in out:
            out.append(x)
    return out
