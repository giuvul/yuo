"""What the models write about the learner's material: chunk digests and a material's outline, with the rules
checked before a repair round. Chunks are named in prompts by short codes (`c1`, `c2`, ...), in reading order.
"""

from typing import Literal

from pydantic import BaseModel, Field

ChunkKind = Literal["teaching", "exercises", "admin", "other"]


class ChunkDigest(BaseModel):
    chunk: str = Field(description="the chunk's code, e.g. c3")
    kind: ChunkKind = Field(
        description="teaching: explains the subject; exercises: tasks or solutions; admin: course logistics, "
        "table of contents, references; other"
    )
    summary: str = Field(description="two to four sentences: what this part teaches")
    concepts: list[str] = Field(description="the key terms it introduces or uses, as short noun phrases")
    definitions: list[str] = Field(description="definitions stated in it, one line each, in its own wording")
    formulas: list[str] = Field(description="formulas or rules stated in it, as written (LaTeX if possible)")
    notation: list[str] = Field(description="symbols and their meaning as this material uses them")


class DigestBatch(BaseModel):
    digests: list[ChunkDigest]


def digest_rules(out: DigestBatch, codes: list[str]) -> list[str]:
    got = [d.chunk for d in out.digests]
    problems = []
    missing = [c for c in codes if c not in got]
    extra = [c for c in got if c not in codes]
    if missing:
        problems.append(f"no digest for {', '.join(missing)}: write one digest per chunk")
    if extra:
        problems.append(f"unknown chunk codes {', '.join(extra)}: use only {', '.join(codes)}")
    if len(set(got)) != len(got):
        problems.append("a chunk has more than one digest")
    for d in out.digests:
        if not d.summary.strip():
            problems.append(f"{d.chunk}: the summary is empty")
    return problems


class Topic(BaseModel):
    title: str = Field(description="the topic, as a short heading in the material's language")
    summary: str = Field(description="one or two sentences")
    chunks: list[str] = Field(description="codes of the chunks that teach this topic, in order")
    concepts: list[str] = Field(description="the topic's key terms")


class Skipped(BaseModel):
    chunks: list[str]
    reason: str = Field(description="why no lesson needs this: exercises only, logistics, repeated, ...")


class MaterialOutline(BaseModel):
    topics: list[Topic]
    skipped: list[Skipped]


def outline_rules(out: MaterialOutline, codes: list[str]) -> list[str]:
    seen: list[str] = []
    problems = []
    for t in out.topics:
        if not t.chunks:
            problems.append(f"topic {t.title!r} has no chunks")
        seen.extend(t.chunks)
    for s in out.skipped:
        seen.extend(s.chunks)
    unknown = sorted({c for c in seen if c not in codes})
    if unknown:
        problems.append(f"unknown chunk codes {', '.join(unknown)}")
    missing = [c for c in codes if c not in seen]
    if missing:
        problems.append(f"chunks in no topic and not skipped: {', '.join(missing)}")
    if not out.topics:
        problems.append("the material needs at least one topic")
    return problems


class PageReading(BaseModel):
    page: int = Field(description="the page number, as given")
    text: str = Field(
        description="what the page says, as text: its words, every formula in LaTeX ($...$), and a short "
        "description of each figure or diagram"
    )


class PageReadings(BaseModel):
    pages: list[PageReading]


def reading_rules(out: PageReadings, pages: list[int]) -> list[str]:
    got = [p.page for p in out.pages]
    problems = []
    if missing := [p for p in pages if p not in got]:
        problems.append(f"no reading for page {', '.join(map(str, missing))}: write one per page")
    if extra := [p for p in got if p not in pages]:
        problems.append(f"unknown pages {', '.join(map(str, extra))}: use only {', '.join(map(str, pages))}")
    return problems


# --- studies_arrange: the path and its courses, proposed from the learner's files ------------------------


class ArrangedCourse(BaseModel):
    title: str = Field(description="the course's name, in the material's own terms")
    term: str = Field(default="", description="the year or term, only when the files say it")
    files: list[int] = Field(description="the numbers of the files that belong to this course")


class Arrangement(BaseModel):
    title: str = Field(description="the path's name: what the learner studies as a whole")
    goal: str = Field(default="", description="one sentence on what the material prepares for")
    courses: list[ArrangedCourse]
    message: str = Field(description="to the learner: how the files were grouped, or what changed")


MAX_ARRANGED_COURSES = 30


def arrange_rules(out: Arrangement, files: int) -> list[str]:
    problems = []
    if not out.title.strip():
        problems.append("`title` is empty")
    if not out.courses:
        problems.append("propose at least one course")
    if len(out.courses) > MAX_ARRANGED_COURSES:
        problems.append(f"at most {MAX_ARRANGED_COURSES} courses")
    names = [c.title.strip().casefold() for c in out.courses]
    if any(not n for n in names):
        problems.append("every course needs a title")
    if len(set(names)) != len(names):
        problems.append("two courses have the same title")
    placed = [f for c in out.courses for f in c.files]
    if unknown := sorted({f for f in placed if not 1 <= f <= files}):
        problems.append(f"unknown files {', '.join(map(str, unknown))}: use 1 to {files}")
    if twice := sorted({f for f in placed if placed.count(f) > 1}):
        problems.append(f"files {', '.join(map(str, twice))} are in more than one course: put each in one")
    if missing := [f for f in range(1, files + 1) if f not in placed]:
        problems.append(f"files {', '.join(map(str, missing))} are in no course: put each file in one")
    if any(not c.files for c in out.courses):
        problems.append("a course without files: leave it out")
    if not out.message.strip():
        problems.append("`message` is empty")
    return problems
