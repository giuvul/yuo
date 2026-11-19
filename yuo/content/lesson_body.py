"""The lesson body: what a model writes, and the stored block document.

Models write a flat draft: blocks with a `type` first (discriminator first) and markdown-lite text.
Python turns it into the stored `lesson_body`: stable block ids and inline runs with marks. No raw HTML
is ever stored.
"""

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class Heading(BaseModel):
    type: Literal["heading"]
    level: Literal[1, 2, 3]
    text: str


class Paragraph(BaseModel):
    type: Literal["paragraph"]
    text: str = Field(
        description="markdown-lite: **bold**, *italic*, `code`, $LaTeX$ for inline maths; no HTML, no links"
    )


class ListBlock(BaseModel):
    type: Literal["list"]
    ordered: bool
    items: list[str]


class Code(BaseModel):
    type: Literal["code"]
    language: str
    text: str
    caption: str | None


class Math(BaseModel):
    type: Literal["math"]
    latex: str
    display: bool


class Callout(BaseModel):
    type: Literal["callout"]
    variant: Literal["tip", "warning", "example", "definition"]
    text: str


class WorkedExample(BaseModel):
    type: Literal["worked_example"]
    title: str
    steps: list[str]


class GlossaryTerm(BaseModel):
    type: Literal["glossary_term"]
    term: str
    definition: str


Block = Annotated[
    Heading | Paragraph | ListBlock | Code | Math | Callout | WorkedExample | GlossaryTerm,
    Field(discriminator="type"),
]


class LessonDraft(BaseModel):
    title: str
    est_minutes: int = Field(description="reading time in minutes")
    blocks: list[Block]


# --- rules ---------------------------------------------------------------------------------------

LENGTH_WORDS = {"short": (450, 1100), "medium": (900, 2000), "long": (1500, 3200)}
_HTML = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")
_LINK = re.compile(r"\[[^\]]+\]\([^)]+\)|https?://")


def words(draft: LessonDraft) -> int:
    return sum(len(t.split()) for t in block_texts(draft.blocks))


def block_texts(blocks: list[Any]) -> list[str]:
    out: list[str] = []
    for b in blocks:
        match b:
            case Heading() | Paragraph() | Callout() | Code():
                out.append(b.text)
            case ListBlock():
                out.extend(b.items)
            case WorkedExample():
                out.append(b.title)
                out.extend(b.steps)
            case GlossaryTerm():
                out.extend([b.term, b.definition])
            case Math():
                out.append(b.latex)
    return out


def lesson_rules(draft: LessonDraft, *, length: str = "medium") -> list[str]:
    problems: list[str] = []
    if not draft.blocks or not isinstance(draft.blocks[0], Heading):
        problems.append("the first block must be a heading")
    if sum(isinstance(b, Paragraph) for b in draft.blocks) < 3:
        problems.append("write at least 3 paragraphs")
    lo, hi = LENGTH_WORDS[length]
    n = words(draft)
    if not lo <= n <= hi:
        problems.append(f"the lesson has {n} words; write between {lo} and {hi}")
    for i, text in enumerate(block_texts(draft.blocks)):
        if _HTML.search(text):
            problems.append(f"text {i} contains HTML; use markdown-lite only")
        if _LINK.search(text):
            problems.append(f"text {i} contains a link or URL; links come from cited sources, not the body")
    if not 1 <= draft.est_minutes <= 60:
        problems.append("est_minutes must be 1 to 60")
    return problems


# --- stored form ---------------------------------------------------------------------------------

_MARKS = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)")
# inline maths: $...$ with no space just inside the dollars, so "$5 and $10" stays text
MATH = re.compile(r"(?<![\\$])\$(?=\S)([^$\n]+?)(?<=\S)\$(?!\$)")


def inlines(text: str) -> list[dict[str, Any]]:
    """markdown-lite -> inline runs with marks; $...$ is a maths run (its LaTeX, not parsed further)."""
    out: list[dict[str, Any]] = []
    at = 0
    for m in MATH.finditer(text):
        out.extend(_marked(text[at : m.start()]))
        out.append({"text": m.group(1), "marks": ["math"]})
        at = m.end()
    out.extend(_marked(text[at:]))
    return out


def _marked(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for part in _MARKS.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            out.append({"text": part[2:-2], "marks": ["bold"]})
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            out.append({"text": part[1:-1], "marks": ["code"]})
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            out.append({"text": part[1:-1], "marks": ["italic"]})
        else:
            out.append({"text": part})
    return out


def to_body(draft: LessonDraft) -> list[dict[str, Any]]:
    body: list[dict[str, Any]] = []
    for i, b in enumerate(draft.blocks, start=1):
        bid = f"b{i}"
        match b:
            case Paragraph():
                body.append({"type": "paragraph", "bid": bid, "inlines": inlines(b.text)})
            case ListBlock():
                body.append(
                    {
                        "type": "list",
                        "bid": bid,
                        "ordered": b.ordered,
                        "items": [inlines(item) for item in b.items],
                    }
                )
            case Callout():
                body.append(
                    {
                        "type": "callout",
                        "bid": bid,
                        "variant": b.variant,
                        "blocks": [{"type": "paragraph", "bid": f"{bid}.1", "inlines": inlines(b.text)}],
                    }
                )
            case WorkedExample():
                body.append(
                    {
                        "type": "worked_example",
                        "bid": bid,
                        "title": b.title,
                        "steps": [inlines(s) for s in b.steps],
                    }
                )
            case _:
                body.append({"bid": bid, **b.model_dump(mode="json")})
    return body


def plain_text(body: list[dict[str, Any]]) -> str:
    """Search text, extracted in Python from the stored body."""
    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("text", "term", "definition", "title", "latex"):
                if isinstance(node.get(key), str):
                    parts.append(node[key])
            for v in node.values():
                if isinstance(v, list | dict):
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(body)
    return " ".join(parts)


# --- the stored body from outside (a package) -------------------------------------------------

_BLOCK_KEYS: dict[str, set[str]] = {
    "heading": {"level", "text"},
    "paragraph": {"inlines"},
    "list": {"ordered", "items"},
    "code": {"language", "text", "caption"},
    "math": {"latex", "display"},
    "callout": {"variant", "blocks"},
    "worked_example": {"title", "steps"},
    "glossary_term": {"term", "definition"},
}
_INLINE_MARKS = {"bold", "italic", "code", "math"}


def _inlines_ok(runs: Any, where: str) -> list[str]:
    if not isinstance(runs, list):
        return [f"{where}: inlines must be a list"]
    out = []
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("text"), str) or set(run) - {"text", "marks"}:
            out.append(f"{where}: an inline run is text with marks only")
        elif not set(run.get("marks", [])) <= _INLINE_MARKS:
            out.append(f"{where}: unknown inline mark {sorted(set(run['marks']) - _INLINE_MARKS)}")
    return out


def check_body(body: Any) -> list[str]:
    """Problems with a stored lesson body: known block types and fields only, text runs with the three marks;
    nothing that a renderer could take as markup or a link (packages are untrusted input, spec §10)."""
    if not isinstance(body, list):
        return ["the body must be a list of blocks"]
    problems: list[str] = []

    def block(b: Any, where: str) -> None:
        if not isinstance(b, dict) or b.get("type") not in _BLOCK_KEYS or not isinstance(b.get("bid"), str):
            problems.append(
                f"{where}: unknown block {b.get('type') if isinstance(b, dict) else type(b).__name__!r}"
            )
            return
        kind = b["type"]
        extra = set(b) - _BLOCK_KEYS[kind] - {"type", "bid"}
        if extra:
            problems.append(f"{where}: unexpected fields {sorted(extra)} in a {kind} block")
        for key in ("text", "language", "latex", "title", "term", "definition"):
            if key in b and not isinstance(b[key], str | None):
                problems.append(f"{where}: {key} must be text")
        if kind == "paragraph":
            problems.extend(_inlines_ok(b.get("inlines"), where))
        elif kind == "list":
            for i, item in enumerate(b.get("items") or []):
                problems.extend(_inlines_ok(item, f"{where}.{i}"))
        elif kind == "worked_example":
            for i, step in enumerate(b.get("steps") or []):
                problems.extend(_inlines_ok(step, f"{where}.{i}"))
        elif kind == "callout":
            for i, inner in enumerate(b.get("blocks") or []):
                block(inner, f"{where}.{i}")

    for i, b in enumerate(body):
        block(b, f"block {i + 1}")
    return problems[:20]
