"""Exercise types: each type is a plugin that declares its generation schema, its
rules, what the learner sees, how it is graded and the answer shape a blind solver gives.

The payload stored in `item_version.payload` is the type's draft (`model_dump`), key included; the
learner view never contains the key. Grading returns a score in [0, 1], or None when the type
is graded by a model (short answer) and the server grades it in a job.
"""

import hashlib
import random
import re
import sqlite3
import unicodedata
from collections.abc import Sequence
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, create_model

from yuo.core.choices import LENGTH_RULE, longest_is_right
from yuo.core.enums import GradingMethod

# --- shared pieces -------------------------------------------------------------------------------


class Choice(BaseModel):
    id: str = Field(description="a, b, c, ...")
    text: str


class OptionWhy(BaseModel):
    id: str
    why: str = Field(description="why this option is right or wrong")


class Support(BaseModel):
    hints: list[str] = Field(description="three hints, from a gentle nudge to almost the answer")
    solution: str = Field(description="worked solution")
    explanations: list[OptionWhy] = Field(description="one per option for choice questions, else empty")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).casefold()
    return re.sub(r"[\s\W_]+", " ", s).strip()


def seeded(seed: str) -> random.Random:
    return random.Random(hashlib.sha256(seed.encode()).digest())  # noqa: S311  (layout, not security)


def leak_rules(keys: Sequence[str], support: Support) -> list[str]:
    """Hints 1 and 2 must not contain a key text."""
    problems = []
    for i, hint in enumerate(support.hints[:2], start=1):
        h = norm(hint)
        if any(len(norm(k)) >= 4 and norm(k) in h for k in keys):
            problems.append(f"hint {i} gives the answer away")
    if len(support.hints) != 3:
        problems.append("write exactly three hints")
    return problems


Confidence = Literal["low", "medium", "high"]


class ExerciseType:
    key: ClassVar[str]
    version: ClassVar[int] = 1
    method: ClassVar[GradingMethod]
    Draft: ClassVar[type[BaseModel]]
    Answer: ClassVar[Any]  # the type of a learner's or blind solver's answer
    instructions: ClassVar[str]  # what the generator is asked for, after the common item prompt
    blind_solvable: ClassVar[bool] = True
    needs_support: ClassVar[bool] = True

    def rules(self, draft: Any, objective_codes: set[str]) -> list[str]:
        out = (
            []
            if draft.objective_code in objective_codes
            else [f"objective_code {draft.objective_code!r} is not one of {sorted(objective_codes)}"]
        )
        return out + self.own_rules(draft)

    def own_rules(self, draft: Any) -> list[str]:
        return []

    def view(self, payload: dict[str, Any], seed: str) -> dict[str, Any]:
        """What the learner sees: never the key."""
        raise NotImplementedError

    def grade(self, payload: dict[str, Any], answer: Any) -> float | None:
        raise NotImplementedError

    def keys(self, payload: dict[str, Any]) -> list[str]:
        """Texts that reveal the answer (leak checks)."""
        return []

    def support_rules(self, payload: dict[str, Any], support: Support) -> list[str]:
        problems = leak_rules(self.keys(payload), support)
        ids = self.option_ids(payload)
        if ids and sorted(e.id for e in support.explanations) != sorted(ids):
            problems.append("give one explanation per option")
        return problems

    def option_ids(self, payload: dict[str, Any]) -> list[str]:
        return []

    def correct(self, payload: dict[str, Any]) -> Any:
        """The right answer, shown after grading."""
        raise NotImplementedError

    def blind_model(self) -> type[BaseModel]:
        fields: dict[str, Any] = {
            "answer": (self.Answer, ...),
            "confidence": (Confidence, ...),
            "reason": (str, ...),
        }
        model: type[BaseModel] = create_model(f"Blind{type(self).__name__}", **fields)
        return model


# --- single choice -------------------------------------------------------------------------------


class McqDraft(BaseModel):
    prompt: str = Field(description="the question; self-contained, no reference to 'the lesson above'")
    options: list[Choice] = Field(description="exactly four options with ids a, b, c, d")
    answer: str = Field(description="id of the one right option")
    objective_code: str


class SingleChoice(ExerciseType):
    key = "mcq"
    method = GradingMethod.EXACT
    Draft = McqDraft
    Answer = str
    instructions = (
        "A single-choice question: four options a, b, c, d; exactly one is right; the wrong ones are "
        "plausible mistakes a learner makes. " + LENGTH_RULE
    )

    def own_rules(self, d: McqDraft) -> list[str]:
        problems = []
        ids = [o.id for o in d.options]
        if sorted(ids) != ["a", "b", "c", "d"]:
            problems.append(f"options must have ids a, b, c, d exactly once (got {ids})")
        if len({norm(o.text) for o in d.options}) != len(d.options):
            problems.append("two options have the same text")
        if d.answer not in ids:
            problems.append(f"the answer {d.answer!r} is not one of the options")
        elif longest_is_right(
            [o.text for o in d.options if o.id == d.answer], [o.text for o in d.options if o.id != d.answer]
        ):
            problems.append("the right option is clearly the longest: make the options similar in length")
        return problems

    def view(self, p: dict[str, Any], seed: str) -> dict[str, Any]:
        return {"prompt": p["prompt"], "options": p["options"]}

    def grade(self, p: dict[str, Any], answer: Any) -> float:
        return 1.0 if answer == p["answer"] else 0.0

    def keys(self, p: dict[str, Any]) -> list[str]:
        return [o["text"] for o in p["options"] if o["id"] == p["answer"]]

    def option_ids(self, p: dict[str, Any]) -> list[str]:
        return [o["id"] for o in p["options"]]

    def correct(self, p: dict[str, Any]) -> Any:
        return p["answer"]


# --- multiple choice (select all) ----------------------------------------------------------------


class MultiDraft(BaseModel):
    prompt: str = Field(description="the question; say that more than one option can be right")
    options: list[Choice] = Field(description="four to six options with ids a, b, c, ...")
    answers: list[str] = Field(description="ids of all right options (at least two, not all)")
    objective_code: str


class MultipleChoice(ExerciseType):
    key = "multi"
    method = GradingMethod.EXACT
    Draft = MultiDraft
    Answer = list[str]
    instructions = (
        "A multiple-choice question where the learner selects all right options: four to six options "
        "a, b, c, ...; at least two right and at least one wrong. " + LENGTH_RULE
    )

    def own_rules(self, d: MultiDraft) -> list[str]:
        ids = [o.id for o in d.options]
        problems = []
        if not 4 <= len(ids) <= 6 or ids != [chr(ord("a") + i) for i in range(len(ids))]:
            problems.append("use four to six options with ids a, b, c, ... in order")
        if len(set(d.answers)) < 2 or set(d.answers) >= set(ids) or not set(d.answers) <= set(ids):
            problems.append("at least two options must be right and at least one wrong, all from the options")
        elif longest_is_right(
            [o.text for o in d.options if o.id in d.answers],
            [o.text for o in d.options if o.id not in d.answers],
        ):
            problems.append(
                "the right options are clearly longer than the wrong ones: make them similar in length"
            )
        return problems

    def view(self, p: dict[str, Any], seed: str) -> dict[str, Any]:
        return {"prompt": p["prompt"], "options": p["options"]}

    def grade(self, p: dict[str, Any], answer: Any) -> float:
        return 1.0 if isinstance(answer, list) and set(answer) == set(p["answers"]) else 0.0

    def keys(self, p: dict[str, Any]) -> list[str]:
        return []  # several right options: naming one in a hint is not a full leak

    def option_ids(self, p: dict[str, Any]) -> list[str]:
        return [o["id"] for o in p["options"]]

    def correct(self, p: dict[str, Any]) -> Any:
        return sorted(p["answers"])


# --- cloze ---------------------------------------------------------------------------------------


class Blank(BaseModel):
    n: int = Field(description="the number used in the marker, 1, 2, ...")
    answers: list[str] = Field(description="every accepted answer; the first is the canonical one")


class ClozeDraft(BaseModel):
    text: str = Field(description="sentence(s) with gaps marked {{1}}, {{2}}, ...")
    blanks: list[Blank]
    objective_code: str


_MARK = re.compile(r"\{\{(\d+)\}\}")


class Cloze(ExerciseType):
    key = "cloze"
    method = GradingMethod.RULE
    Draft = ClozeDraft
    Answer = list[str]
    instructions = (
        "A fill-the-gap item: one to three gaps marked {{1}}, {{2}}, ... in a short text; each gap "
        "is a key term or value with a short, unambiguous answer; list accepted variants."
    )

    def own_rules(self, d: ClozeDraft) -> list[str]:
        marks = [int(m) for m in _MARK.findall(d.text)]
        problems = []
        if not marks or marks != list(range(1, len(marks) + 1)):
            problems.append("number the gaps {{1}}, {{2}}, ... in order, each once")
        if sorted(b.n for b in d.blanks) != sorted(marks):
            problems.append("give exactly one blank entry per gap marker")
        if any(not b.answers or any(len(a.split()) > 4 for a in b.answers) for b in d.blanks):
            problems.append("each gap needs accepted answers of at most four words")
        return problems

    def view(self, p: dict[str, Any], seed: str) -> dict[str, Any]:
        return {"text": p["text"], "gaps": len(p["blanks"])}

    def grade(self, p: dict[str, Any], answer: Any) -> float:
        if not isinstance(answer, list):
            return 0.0
        blanks = sorted(p["blanks"], key=lambda b: b["n"])
        hits = sum(
            1
            for b, a in zip(blanks, answer, strict=False)
            if isinstance(a, str) and norm(a) in {norm(x) for x in b["answers"]}
        )
        return hits / len(blanks)

    def keys(self, p: dict[str, Any]) -> list[str]:
        return [a for b in p["blanks"] for a in b["answers"]]

    def correct(self, p: dict[str, Any]) -> Any:
        return [b["answers"][0] for b in sorted(p["blanks"], key=lambda b: b["n"])]


# --- ordering ------------------------------------------------------------------------------------


class OrderingDraft(BaseModel):
    prompt: str = Field(description="what to put in order, and by what criterion")
    steps: list[Choice] = Field(
        description="three to six steps with ids a, b, c, ... listed in the RIGHT order"
    )
    objective_code: str


class Ordering(ExerciseType):
    key = "ordering"
    method = GradingMethod.EXACT
    Draft = OrderingDraft
    Answer = list[str]
    instructions = (
        "An ordering item: three to six steps or items the learner puts in the right order; list them "
        "in the right order with ids a, b, c, ... (the app shuffles them)."
    )

    def own_rules(self, d: OrderingDraft) -> list[str]:
        ids = [s.id for s in d.steps]
        if not 3 <= len(ids) <= 6 or ids != [chr(ord("a") + i) for i in range(len(ids))]:
            return ["use three to six steps with ids a, b, c, ... in the right order"]
        return []

    def view(self, p: dict[str, Any], seed: str) -> dict[str, Any]:
        steps = list(p["steps"])
        rng = seeded(seed)
        while len(steps) > 1 and [s["id"] for s in steps] == [s["id"] for s in p["steps"]]:
            rng.shuffle(steps)
        return {"prompt": p["prompt"], "steps": steps}

    def grade(self, p: dict[str, Any], answer: Any) -> float:
        return 1.0 if answer == [s["id"] for s in p["steps"]] else 0.0

    def correct(self, p: dict[str, Any]) -> Any:
        return [s["id"] for s in p["steps"]]


# --- matching ------------------------------------------------------------------------------------


class Pair(BaseModel):
    left: str
    right: str


class MatchingDraft(BaseModel):
    prompt: str
    pairs: list[Pair] = Field(
        description="three to six pairs that belong together; every left and right unique"
    )
    objective_code: str


class Matching(ExerciseType):
    key = "matching"
    method = GradingMethod.RULE
    Draft = MatchingDraft
    Answer = list[Pair]
    instructions = (
        "A matching item: three to six pairs (term and definition, cause and effect, ...); every left "
        "and every right text unique and only one way to match them."
    )

    def own_rules(self, d: MatchingDraft) -> list[str]:
        lefts, rights = [norm(p.left) for p in d.pairs], [norm(p.right) for p in d.pairs]
        if not 3 <= len(d.pairs) <= 6:
            return ["use three to six pairs"]
        if len(set(lefts)) != len(lefts) or len(set(rights)) != len(rights):
            return ["every left and every right text must be unique"]
        return []

    def view(self, p: dict[str, Any], seed: str) -> dict[str, Any]:
        rights = [x["right"] for x in p["pairs"]]
        seeded(seed).shuffle(rights)
        return {"prompt": p["prompt"], "left": [x["left"] for x in p["pairs"]], "right": rights}

    def grade(self, p: dict[str, Any], answer: Any) -> float:
        if not isinstance(answer, list):
            return 0.0
        truth = {norm(x["left"]): norm(x["right"]) for x in p["pairs"]}
        given = {norm(a.get("left", "")): norm(a.get("right", "")) for a in answer if isinstance(a, dict)}
        return sum(1 for k, v in truth.items() if given.get(k) == v) / len(truth)

    def correct(self, p: dict[str, Any]) -> Any:
        return p["pairs"]


# --- flashcard (self-rated recall) ---------------------------------------------------------------


class FlashcardDraft(BaseModel):
    front: str = Field(description="a question or cue")
    back: str = Field(description="the answer, short")
    objective_code: str


SELF_SCORE = {1: 0.0, 2: 0.5, 3: 0.8, 4: 1.0}  # FSRS ratings Again, Hard, Good, Easy


class Flashcard(ExerciseType):
    key = "flashcard"
    method = GradingMethod.SELF
    Draft = FlashcardDraft
    Answer = int
    instructions = "A flashcard for recall: a short cue on the front, a short answer on the back."
    blind_solvable = False
    needs_support = False

    def own_rules(self, d: FlashcardDraft) -> list[str]:
        return ["keep the back under 40 words"] if len(d.back.split()) > 40 else []

    def view(self, p: dict[str, Any], seed: str) -> dict[str, Any]:
        return {"front": p["front"]}

    def grade(self, p: dict[str, Any], answer: Any) -> float:
        if answer not in SELF_SCORE:
            raise ValueError("a flashcard answer is a self-rating 1 to 4")
        return SELF_SCORE[answer]

    def correct(self, p: dict[str, Any]) -> Any:
        return p["back"]


# --- short answer (model-graded with a rubric) ---------------------------------------------------


class Criterion(BaseModel):
    point: str = Field(description="one thing a good answer contains")
    weight: int = Field(description="1 to 3")


class ShortAnswerDraft(BaseModel):
    prompt: str = Field(description="a question answered in one to three sentences")
    rubric: list[Criterion] = Field(description="two to four criteria")
    model_answer: str
    objective_code: str


class ShortAnswer(ExerciseType):
    key = "short_answer"
    method = GradingMethod.MODEL
    Draft = ShortAnswerDraft
    Answer = str
    instructions = (
        "A short-answer question answered in one to three sentences, with a rubric of two to four "
        "weighted criteria and a model answer."
    )
    blind_solvable = False

    def own_rules(self, d: ShortAnswerDraft) -> list[str]:
        if not 2 <= len(d.rubric) <= 4 or any(not 1 <= c.weight <= 3 for c in d.rubric):
            return ["give two to four criteria with weights 1 to 3"]
        return []

    def view(self, p: dict[str, Any], seed: str) -> dict[str, Any]:
        return {"prompt": p["prompt"]}

    def grade(self, p: dict[str, Any], answer: Any) -> None:
        return None  # graded by the grader model in a job

    def keys(self, p: dict[str, Any]) -> list[str]:
        return [p["model_answer"]]

    def correct(self, p: dict[str, Any]) -> Any:
        return p["model_answer"]


class RubricGrade(BaseModel):
    met: list[bool] = Field(description="one per rubric criterion, in order")
    rationale: str = Field(
        description="two or three sentences for the learner: what was right, what was missing"
    )


def rubric_score(payload: dict[str, Any], grade: RubricGrade) -> float:
    weights = [c["weight"] for c in payload["rubric"]]
    if len(grade.met) != len(weights):
        raise ValueError("one verdict per criterion")
    return float(sum(w for w, m in zip(weights, grade.met, strict=True) if m) / sum(weights))


# --- registry ------------------------------------------------------------------------------------

TYPES: dict[str, ExerciseType] = {
    t.key: t
    for t in (SingleChoice(), MultipleChoice(), Cloze(), Ordering(), Matching(), Flashcard(), ShortAnswer())
}


def get(key: str) -> ExerciseType:
    try:
        return TYPES[key]
    except KeyError:
        raise ValueError(f"exercise type {key!r} is not installed") from None


def register_all(c: sqlite3.Connection) -> None:
    """Install every built-in type in `exercise_type`; idempotent, run at startup."""
    import json

    for t in TYPES.values():
        c.execute(
            "INSERT INTO exercise_type (key, version, payload_schema, grading_method, plugin, status) "
            "VALUES (?, ?, json(?), ?, 'builtin', 'installed') ON CONFLICT(key) DO UPDATE SET "
            "version = excluded.version, payload_schema = excluded.payload_schema, status = 'installed'",
            (t.key, t.version, json.dumps(t.Draft.model_json_schema()), t.method.value),
        )


def shuffle_choices(
    t: ExerciseType, payload: dict[str, Any], support: Support, seed: str
) -> tuple[dict[str, Any], Support]:
    """Models put the key first: reorder and relabel choice options (single and multiple choice)."""
    if t.key not in ("mcq", "multi"):
        return payload, support
    order = list(payload["options"])
    seeded(seed).shuffle(order)
    relabel = {o["id"]: chr(ord("a") + i) for i, o in enumerate(order)}
    new = dict(payload)
    new["options"] = [{"id": relabel[o["id"]], "text": o["text"]} for o in order]
    if t.key == "mcq":
        new["answer"] = relabel[payload["answer"]]
    else:
        new["answers"] = sorted(relabel[a] for a in payload["answers"])
    why = sorted(
        (OptionWhy(id=relabel[e.id], why=e.why) for e in support.explanations if e.id in relabel),
        key=lambda e: e.id,
    )
    return new, support.model_copy(update={"explanations": why})
