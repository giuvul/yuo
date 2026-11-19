"""How big a path is planned: the learner's choice (shorter, standard, deep) and, for a path from their own
material, how much material there is.

A goal path is planned in full at once; lessons are still written only a few at a time ahead of the learner
(the generation buffer), so a long plan costs nothing until the learner gets there. A course of the learner's
material is sized from what it holds: one recorded lecture is a lesson or two, a book is dozens.
"""

import math
from dataclasses import dataclass
from typing import Literal

Depth = Literal["short", "standard", "deep"]
DEPTHS: tuple[Depth, ...] = ("short", "standard", "deep")


@dataclass(frozen=True)
class TreeSize:
    branches: tuple[int, int]
    skills: tuple[int, int]  # per branch
    lessons: tuple[int, int]  # in total, what the plan aims for
    max_lessons: int  # the rule a plan is checked against (a little room above the aim)


TREE_SIZES: dict[Depth, TreeSize] = {
    "short": TreeSize((2, 4), (2, 4), (12, 24), 30),
    "standard": TreeSize((3, 6), (3, 6), (40, 70), 80),
    "deep": TreeSize((5, 8), (4, 7), (80, 120), 140),
}

# how much more or less of the material a course plan covers in depth
MATERIAL_FACTOR: dict[Depth, float] = {"short": 0.6, "standard": 1.0, "deep": 1.5}
MATERIAL_MAX_LESSONS = 150

# what one lesson covers (the course prompt says the same): 15 to 25 minutes of lecture, 8 to 15 pages of a book,
# about 20 slides
LECTURE_MINUTES_PER_LESSON = 20
PAGES_PER_LESSON = 10
SLIDES_PER_LESSON = 20
TOKENS_PER_LESSON = 5000  # a text with no pages


def depth_of(value: object) -> Depth:
    for d in DEPTHS:
        if value == d:
            return d
    return "standard"


@dataclass(frozen=True)
class MaterialAmount:
    role: str  # textbook, slides, lecture, notes, exercises, exams, other
    kind: str  # pdf, pptx, docx, text, audio, video, link
    pages: int | None
    duration_ms: int | None
    tokens: int


def _lessons_worth(m: MaterialAmount) -> tuple[str, float]:
    """Which group a file belongs to (recordings, slides, reading) and how many lessons it holds."""
    if m.duration_ms:
        return "recordings", m.duration_ms / 60_000 / LECTURE_MINUTES_PER_LESSON
    if m.kind == "pptx" or m.role == "slides":
        return "slides", (m.pages or 0) / SLIDES_PER_LESSON or m.tokens / TOKENS_PER_LESSON
    if m.pages:
        return "reading", m.pages / PAGES_PER_LESSON
    return "reading", m.tokens / TOKENS_PER_LESSON


def material_lessons(materials: list[MaterialAmount], depth: Depth) -> tuple[int, int]:
    """The range of lessons a course plan aims for. Exercises and past exams teach nothing new. A course's
    recordings, slides and book usually cover the same lectures: the largest of the three counts in full, the
    others a quarter (what they add beyond it)."""
    groups = {"recordings": 0.0, "slides": 0.0, "reading": 0.0}
    for m in materials:
        if m.role in ("exercises", "exams"):
            continue
        group, worth = _lessons_worth(m)
        groups[group] += worth
    ordered = sorted(groups.values(), reverse=True)
    estimate = (ordered[0] + 0.25 * sum(ordered[1:])) * MATERIAL_FACTOR[depth]
    low = max(1, round(estimate * 0.7))
    high = min(MATERIAL_MAX_LESSONS, max(2, low + 1, math.ceil(estimate * 1.3)))
    return low, high
