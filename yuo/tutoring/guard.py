"""Deterministic parts of the tutor's control: the guess detector, the fixed replies, and the
parsing of what the tutor proposes or remembers.

Most hard leaks in testing (44 of 73) answered a learner's guess ("Is it B?", "I'm going with A, right?"),
typically with "Not quite!". When a guess is detected the server answers with a localised template and
the model is never called, so it cannot confirm or deny anything.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

# reply texts the client shows by id (i18n catalog); the English text is stored for the record
TEMPLATES = {
    "tutor.guess": "I can't say whether that's right until you submit your answer. Want a hint instead, or "
    "should I rephrase the question?",
    "tutor.guess.test": "I can't say whether that's right during the test. I can rephrase the question or "
    "explain a word in it.",
    "tutor.blocked": "Let's look at the wording of the question together instead. Which part is unclear?",
    "tutor.review.coach": "I can't say whether that's right: finding it yourself is what makes the review "
    "work. Give it a try, or ask me for a hint or a guiding question.",
    "tutor.review": "Try to recall it first: the review works best without help. If the card is broken or "
    "unclear, tell me what is wrong with it.",
}

_CONFIRM = re.compile(
    r"\b(am i (right|correct)|is (that|this|it) (right|correct)|(that'?s|it'?s) (right|correct),? (isn'?t it|right)"
    r"|right\?|correct\?|yes or no|true or false|did i get it|is the answer|was i right)",
    re.IGNORECASE,
)
_CHOOSE = r"(?:i think(?: it'?s| it is)?|i'?m going with|i'?ll go with|going with|i pick|i choose|i'?d say|my answer is|it'?s|it is|is it)"


_OPEN_GUESS = re.compile(
    r"\b(is it|is the answer|my answer is|i think it'?s|i think it is|would it be|could it be|should it be)\b"
    r"[^.?!]{1,80}\?",
    re.IGNORECASE,
)
_CHOOSE_NORM = (
    r"(?:i think(?: it s| it is)?|i m going with|i ll go with|going with|i pick|i choose|i d say|my answer is"
    r"|it s|it is|is it)"
)


def _norm(s: str) -> str:
    return re.sub(r"[\s\W_]+", " ", s.lower()).strip()


@dataclass(frozen=True, slots=True)
class Guess:
    kind: str  # option, text, confirm
    value: str


def detect_guess(
    message: str, options: list[dict[str, Any]] | None = None, *, open_answer: bool = False
) -> Guess | None:
    """A guess at the answer: an option named by its letter or its text, or a request to confirm.

    Options are `{"id": "a", "text": "..."}`. Letters are matched only in guess phrasing ("option b",
    "(c)", "I think it's D", a message that is just "B?"), so "a" in ordinary English is not a guess.
    `open_answer` items (fill-the-gap, short answer) also treat "is it X?" phrasing as a guess.
    """
    text = message.strip()
    low = text.lower()
    norm = _norm(text)
    confirm = bool(_CONFIRM.search(text))
    by_text: list[tuple[int, str]] = []
    for opt in options or []:
        otext = _norm(str(opt.get("text", "")))
        if len(otext) >= 3:
            named = rf"(?<![a-z0-9]){re.escape(otext)}(?![a-z0-9])"
            if re.search(rf"\b{_CHOOSE_NORM}\s+(?:the\s+)?{named}", norm) or (
                confirm and re.search(named, norm)
            ):
                by_text.append((len(otext), str(opt["id"])))
    if by_text:  # the longest match: "DENSE_RANK()" names D, not "RANK()"
        return Guess("text", max(by_text)[1])
    for opt in options or []:
        oid = re.escape(str(opt["id"]).lower())
        patterns = (
            rf"\b(?:option|answer|choice|letter|number)\s*\(?{oid}\)?(?![\w'])",
            rf"\({oid}\)",
            rf"^\W*{oid}\W*$",
            rf"\b{_CHOOSE}\s*\(?{oid}\)?(?=[\s?.!,)]|$)",
            rf"^\s*{oid}[.)]",
        )
        if any(re.search(p, low) for p in patterns):
            # a lone "a" in prose is not a guess: require an uppercase letter or explicit phrasing
            if (
                oid == "a"
                and not re.search(r"(?<![\w'])A(?![\w'])", text)
                and not re.search(r"\b(?:option|answer|choice|letter)\s*\(?a\)?|\(a\)|^\W*a\W*$", low)
            ):
                continue
            return Guess("option", str(opt["id"]))
    if confirm:
        return Guess("confirm", "")
    if open_answer and _OPEN_GUESS.search(text):
        return Guess("open", "")
    return None


@dataclass(slots=True)
class Actions:
    proposal: dict[str, Any] | None = None
    memory: list[dict[str, str]] = field(default_factory=list)


_ACTIONS = re.compile(r"<actions>(.*?)(?:</actions>|$)", re.DOTALL | re.IGNORECASE)
PROPOSAL_KINDS = ("add_lesson", "extra_review", "change_difficulty")
MEMORY_KINDS = ("preference", "misconception", "goal", "fact")


def split_actions(reply: str) -> tuple[str, Actions]:
    """The reply text without its trailing `<actions>{...}</actions>` block, and the parsed block.

    Anything malformed is dropped: the learner sees the text, the server ignores the rest."""
    m = _ACTIONS.search(reply)
    if not m:
        return reply.strip(), Actions()
    text = (reply[: m.start()] + reply[m.end() :]).strip()
    acts = Actions()
    try:
        raw = json.loads(m.group(1).strip())
    except ValueError:
        return text, acts
    if not isinstance(raw, dict):
        return text, acts
    prop = raw.get("proposal")
    if (
        isinstance(prop, dict)
        and prop.get("kind") in PROPOSAL_KINDS
        and isinstance(prop.get("rationale"), str)
    ):
        acts.proposal = {
            "kind": prop["kind"],
            "rationale": prop["rationale"][:500],
            "change": {k: v for k, v in prop.items() if k not in ("kind", "rationale")},
        }
    for item in raw.get("memory") or []:
        if isinstance(item, dict) and item.get("kind") in MEMORY_KINDS and isinstance(item.get("text"), str):
            acts.memory.append({"kind": item["kind"], "text": item["text"][:300]})
    acts.memory = acts.memory[:3]
    return text, acts


class StreamFilter:
    """Forwards streamed text but holds back anything from `<actions>` on, so the block never shows."""

    TAG = "<actions>"

    def __init__(self) -> None:
        self.buf = ""
        self.sent = 0
        self.closed = False

    def feed(self, chunk: str) -> str:
        if self.closed:
            return ""
        self.buf += chunk
        i = self.buf.lower().find(self.TAG)
        if i >= 0:
            self.closed = True
            out = self.buf[self.sent : i]
            self.sent = i
            return out
        # keep a tail that could be the start of the tag
        safe = len(self.buf)
        for k in range(1, len(self.TAG)):
            if self.buf.lower().endswith(self.TAG[:k]):
                safe = len(self.buf) - k
                break
        out = self.buf[self.sent : safe]
        self.sent = safe
        return out
