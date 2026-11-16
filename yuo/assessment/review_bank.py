"""The review question bank: what one writer call returns for a lesson, and the rules each question
must pass before it is blind-solved and published.

A review question is an ordinary single-choice item (`mcq`) with `extensions.yuo.use = "review"`. It is
written for retrieval practice some days after the lesson: a new angle on the lesson's ideas, never the
lesson's own practice questions. A single question tests one objective of the lesson's skill; a cross
question is a scenario that needs two or three objectives, at least one of them the lesson's own.

Feedback is written with the question: one rationale per option (a wrong option's rationale says why it is
wrong without naming the right one), three hints (review shows the first two) and an explanation. Rules
that guard against guessing without knowing: the right option may not be clearly the longest, and neither
the hints shown in review nor the rationales of wrong options may contain the right option's text.
"""

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from yuo.assessment.types import Choice, McqDraft, OptionWhy, Support, norm

Kind = Literal["recall", "apply", "scenario", "compare", "debug"]
MAX_OBJECTIVES = 3
LENGTH_RATIO = 1.2  # the right option may be at most this much longer than the longest wrong one...
LENGTH_SLACK = 8  # ...unless the difference is only a few characters
REPAIR_SHARE = 1 / 3  # more than this share of bad questions sends the whole bank back for repair


class ReviewQuestion(BaseModel):
    prompt: str = Field(description="the question; self-contained, no reference to 'the lesson'")
    options: list[Choice] = Field(description="exactly four options with ids a, b, c, d")
    answer: str = Field(description="id of the one right option")
    objective_codes: list[str] = Field(
        description="one code for a single-lesson question; two or three for a cross-lesson question"
    )
    kind: Kind
    level: int = Field(ge=1, le=3, description="1 recall, 2 use, 3 transfer")
    concept: str = Field(description="the idea tested, in two to five words")
    revisit: str = Field(description="where to look again, e.g. the section of the lesson")
    hints: list[str] = Field(description="three hints, from a nudge to almost the answer")
    rationales: list[OptionWhy] = Field(description="one per option: why it is right or wrong")
    explanation: str = Field(description="the full explanation, shown once the question is resolved")

    def mcq(self) -> McqDraft:
        return McqDraft(
            prompt=self.prompt,
            options=self.options,
            answer=self.answer,
            objective_code=self.objective_codes[0],
        )

    def support(self) -> Support:
        return Support(hints=self.hints, solution=self.explanation, explanations=self.rationales)

    def payload(self) -> dict[str, Any]:
        """The stored item payload: the single-choice fields plus the review fields."""
        return self.mcq().model_dump(mode="json") | {
            "objective_codes": self.objective_codes,
            "kind": self.kind,
            "level": self.level,
            "concept": self.concept,
            "revisit": self.revisit,
        }


class ReviewBankDraft(BaseModel):
    questions: list[ReviewQuestion]


# options are shuffled before they are shown: one that points at another by letter or position breaks
_REFERS = re.compile(
    r"\b(all|none|both|neither|any|either) of the (above|below|options|answers)\b|\b(both|neither|either) [a-d]\b"
    r"|\b[a-d] (and|or|nor) [a-d]\b|\boptions? [a-d]\b",
    re.IGNORECASE,
)


def _tokens(text: str) -> set[str]:
    return {w for w in norm(text).split() if len(w) > 2}


def near_duplicate(a: str, b: str) -> bool:
    """The same question in other words: equal after normalising, or sharing nearly all their words."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return norm(a) == norm(b)
    return norm(a) == norm(b) or len(ta & tb) / len(ta | tb) >= 0.8


def question_rules(q: ReviewQuestion, own: set[str], partners: set[str], avoid: list[str]) -> list[str]:
    """Problems of one question; an empty list means it may go on to the blind solver."""
    problems: list[str] = []
    ids = [o.id for o in q.options]
    if sorted(ids) != ["a", "b", "c", "d"]:
        return [f"options must have ids a, b, c, d exactly once (got {ids})"]
    if len({norm(o.text) for o in q.options}) != len(q.options):
        problems.append("two options have the same text")
    if q.answer not in ids:
        return [*problems, f"the answer {q.answer!r} is not one of the options"]
    if any(_REFERS.search(o.text) for o in q.options):
        problems.append("an option refers to other options (the options are shuffled): make each stand alone")
    codes = q.objective_codes
    if not 1 <= len(codes) <= MAX_OBJECTIVES or len(set(codes)) != len(codes):
        problems.append(f"give one to {MAX_OBJECTIVES} different objective codes")
    unknown = sorted(set(codes) - own - partners)
    if unknown:
        problems.append(f"unknown objective codes {unknown}")
    if not set(codes) & own:
        problems.append("a question must test at least one objective of this lesson's skill")
    right = next(o.text for o in q.options if o.id == q.answer)
    longest_wrong = max(len(o.text) for o in q.options if o.id != q.answer)
    if len(right) > LENGTH_RATIO * longest_wrong and len(right) - longest_wrong > LENGTH_SLACK:
        problems.append("the right option is clearly the longest: make the options similar in length")
    key = norm(right)
    if len(q.hints) != 3:
        problems.append("write exactly three hints")
    if len(key) >= 4:
        for i, hint in enumerate(q.hints[:2], start=1):
            if key in norm(hint):
                problems.append(f"hint {i} gives the answer away")
        for r in q.rationales:
            if r.id != q.answer and key in norm(r.why):
                problems.append(f"the rationale of option {r.id} names the right answer")
    if sorted(r.id for r in q.rationales) != sorted(ids):
        problems.append("give one rationale per option")
    if any(near_duplicate(q.prompt, a) for a in avoid):
        problems.append("the question repeats one the learner has already seen")
    return problems


def bank_rules(
    draft: ReviewBankDraft, own: set[str], partners: set[str], avoid: list[str], single: int, cross: int
) -> list[str]:
    """Rules for the whole reply. A few bad questions are dropped later; many send the bank back for repair."""
    wanted = single + (cross if partners else 0)
    if len(draft.questions) < max(1, wanted // 2):
        return [f"write {wanted} questions (got {len(draft.questions)})"]
    problems: list[str] = []
    bad = 0
    for n, q in enumerate(draft.questions, start=1):
        found = question_rules(q, own, partners, avoid)
        if found:
            bad += 1
            problems += [f"question {n}: {p}" for p in found]
    return problems if bad > len(draft.questions) * REPAIR_SHARE else []


def keep(draft: ReviewBankDraft, own: set[str], partners: set[str], avoid: list[str]) -> list[ReviewQuestion]:
    """The questions that pass their rules and do not repeat an earlier one of the same bank."""
    out: list[ReviewQuestion] = []
    seen = list(avoid)
    for q in draft.questions:
        if question_rules(q, own, partners, seen):
            continue
        out.append(q)
        seen.append(q.prompt)
    return out
