"""A course's plan from its material (stage `course_outline`), the links between courses (`course_links`),
and writing a built course into the curriculum tables.

Skills name the material topics they are built on (`m1.t3`: material 1, topic 3 of that course); the app turns
topics into the chunks they cover (`skill_anchor`).
"""

from typing import Literal

from pydantic import BaseModel, Field

from yuo.curriculum.tree import CODE, LessonPlan, ObjectiveDraft, find_cycle

Adherence = Literal["only", "grounded", "open"]


class CourseSkill(BaseModel):
    code: str = Field(description="stable dotted code, unique in the path, starting with the course code")
    title: str
    summary: str = Field(description="one or two sentences")
    unit: str = Field(
        description="the chapter, lecture or week this skill belongs to, as the material names it"
    )
    topics: list[str] = Field(description="codes of the material topics this skill is built on, e.g. m1.t3")
    not_in_material: bool = Field(
        description="true only for a prerequisite the material assumes but does not teach"
    )
    requires: list[str] = Field(
        description="codes of skills of this course that must come first (direct only)"
    )
    objectives: list[ObjectiveDraft]
    lessons: list[LessonPlan]


class CourseOutline(BaseModel):
    skills: list[CourseSkill]
    skipped: list[str] = Field(description="topic codes no skill uses, each followed by ': ' and the reason")


class RevisedCourse(BaseModel):
    changes: list[str] = Field(description="what changed and why, one short sentence each")
    outline: CourseOutline


def course_rules(
    out: CourseOutline,
    code: str,
    topics: set[str],
    teaching: set[str],
    adherence: Adherence,
    *,
    max_lessons: int,
) -> list[str]:
    problems: list[str] = []
    codes = [s.code for s in out.skills]
    seen: set[str] = set()
    for s in out.skills:
        if not CODE.match(s.code):
            problems.append(f"skill code {s.code!r} must be lowercase letters, digits and . _ - separators")
        if not s.code.startswith(code + "."):
            problems.append(f"skill code {s.code!r} must start with the course code {code}.")
        if s.code in seen:
            problems.append(f"skill code {s.code!r} is used twice")
        seen.add(s.code)
        if not s.objectives:
            problems.append(f"skill {s.code} has no objectives")
        if not s.lessons:
            problems.append(f"skill {s.code} has no lessons")
        unknown = [t for t in s.topics if t not in topics]
        if unknown:
            problems.append(f"skill {s.code} names unknown topics {', '.join(unknown)}")
        if not s.topics and not s.not_in_material:
            problems.append(
                f"skill {s.code} has no topics: build it on the material, or mark it not_in_material if it is a "
                "prerequisite the material does not teach"
            )
        if s.not_in_material and s.topics:
            problems.append(f"skill {s.code} is marked not_in_material but names topics")
        for r in s.requires:
            if r not in codes:
                problems.append(f"skill {s.code} requires unknown skill {r!r}")
            elif r == s.code:
                problems.append(f"skill {s.code} requires itself")
        for o in s.objectives:
            if not CODE.match(o.code):
                problems.append(f"objective code {o.code!r} is not a valid code")
        for lesson in s.lessons:
            if not CODE.match(lesson.code):
                problems.append(f"lesson code {lesson.code!r} is not a valid code")
    if cycle := find_cycle({s.code: [r for r in s.requires if r in codes] for s in out.skills}):
        problems.append("prerequisites form a cycle: " + " -> ".join(cycle))
    used = {t for s in out.skills for t in s.topics}
    skipped = {x.split(":", 1)[0].strip() for x in out.skipped}
    left = sorted(teaching - used - skipped)
    if left:
        problems.append(f"teaching topics in no skill and not skipped: {', '.join(left)}")
    if adherence != "open" and not any(s.topics for s in out.skills):
        problems.append("no skill is built on the material")
    lessons = sum(len(s.lessons) for s in out.skills)
    if lessons > max_lessons:
        problems.append(f"{lessons} lessons planned; at most {max_lessons}")
    if not out.skills:
        problems.append("the course needs at least one skill")
    lesson_codes = [lesson.code for s in out.skills for lesson in s.lessons]
    if len(set(lesson_codes)) != len(lesson_codes):
        problems.append("a lesson code is used twice")
    objective_codes = [o.code for s in out.skills for o in s.objectives]
    if len(set(objective_codes)) != len(objective_codes):
        problems.append("an objective code is used twice")
    return problems


class CrossRequire(BaseModel):
    skill: str = Field(description="the skill that needs the other one")
    requires: str = Field(description="a skill of another course that must come first")
    why: str


class Related(BaseModel):
    a: str
    b: str
    note: str = Field(description="what they share, a few words")


class CourseLinks(BaseModel):
    requires: list[CrossRequire]
    related: list[Related]


def links_rules(out: CourseLinks, course_of: dict[str, str], existing: dict[str, list[str]]) -> list[str]:
    problems = []
    for r in out.requires:
        if r.skill not in course_of or r.requires not in course_of:
            problems.append(f"unknown skill in {r.skill} -> {r.requires}")
        elif course_of[r.skill] == course_of[r.requires]:
            problems.append(f"{r.skill} -> {r.requires}: only links between different courses")
    for x in out.related:
        if x.a not in course_of or x.b not in course_of:
            problems.append(f"unknown skill in related {x.a} / {x.b}")
        elif x.a == x.b:
            problems.append(f"related {x.a} to itself")
    graph = {k: list(v) for k, v in existing.items()}
    for r in out.requires:
        if r.skill in course_of and r.requires in course_of:
            graph.setdefault(r.skill, []).append(r.requires)
    if cycle := find_cycle(graph):
        problems.append("these prerequisites form a cycle: " + " -> ".join(cycle))
    return problems
