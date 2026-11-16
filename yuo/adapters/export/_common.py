"""What every standard-format exporter shares: path order, current versions and items as plain text.

Records come from a package, so they are untrusted: payloads are validated against their exercise type
before use, unknown types are skipped (and named), and every output file name is checked.
"""

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from yuo.assessment.types import TYPES, seeded

type Records = dict[str, list[dict[str, Any]]]
type AssetFile = Callable[[str], Path]
type Files = dict[str, bytes]

_NAME = re.compile(r"^[A-Za-z0-9._/-]+$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f￾￿]")
_DIGITS = re.compile(r"(\d+)")
_GAP = re.compile(r"\{\{(\d+)\}\}")


def safe_name(name: str) -> str:
    """An output file name: relative, plain characters, no `..` (the package writer refuses anything else)."""
    if not _NAME.match(name) or name.startswith("/") or ".." in name.split("/"):
        raise ValueError(f"unsafe export file name {name!r}")
    return name


def clean(text: Any) -> str:
    """Text without control characters (they are invalid in XML and pointless elsewhere), NFC."""
    return _CONTROL.sub("", unicodedata.normalize("NFC", "" if text is None else str(text)))


def natural(code: str) -> tuple[Any, ...]:
    """`q2` before `q10`."""
    return tuple(int(p) if p.isdigit() else p for p in _DIGITS.split(code))


def current(record: dict[str, Any]) -> dict[str, Any] | None:
    """The record's current version, or None when it has none (retired or not yet written)."""
    want = record.get("current")
    return next((v for v in record.get("versions") or [] if v.get("version_hash") == want), None)


def path_record(records: Records) -> dict[str, Any]:
    paths = records.get("path") or [{}]
    return paths[0]


def skill_order(records: Records) -> dict[str, int]:
    """Skill code -> rank in path order (branch position, skill position, code)."""
    branch_pos = {b["code"]: b.get("position", 0) for b in records.get("branch", [])}
    skills = sorted(
        records.get("skill", []),
        key=lambda s: (
            branch_pos.get(s.get("branch", ""), 1 << 30),
            s.get("position", 0),
            natural(s["code"]),
        ),
    )
    return {s["code"]: i for i, s in enumerate(skills)}


def ordered_lessons(records: Records) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(lesson, current version) in path order; lessons without a current version are left out."""
    rank = skill_order(records)
    lessons = sorted(
        records.get("lesson", []),
        key=lambda x: (rank.get(x.get("skill", ""), 1 << 30), x.get("position", 0), natural(x["code"])),
    )
    out = []
    for lesson in lessons:
        v = current(lesson)
        if v is not None:
            out.append((lesson, v))
    return out


# --- items as plain text -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    """One item as plain text, the common ground of CSV, Anki and Moodle."""

    code: str
    skill: str
    type: str
    difficulty: str
    lang: str
    prompt: str
    options: list[str]
    answer: str
    explanation: str
    hints: list[str]
    objectives: list[str]
    lesson: str
    payload: dict[str, Any] = field(repr=False)
    support: dict[str, Any] = field(repr=False)


@dataclass(frozen=True)
class Items:
    items: list[Item]
    skipped: list[tuple[str, str]]  # (code, why)


def gap(n: int | str) -> str:
    return f"[{n}: ____]"


def _letters(n: int) -> list[str]:
    return [chr(ord("a") + i) for i in range(n)]


def _explanation(payload: dict[str, Any], support: dict[str, Any], type_key: str) -> str:
    parts = []
    if type_key == "short_answer":
        rubric = [f"- {clean(c.get('point'))} (weight {c.get('weight')})" for c in payload.get("rubric", [])]
        parts.append("Rubric:\n" + "\n".join(rubric))
    if support.get("solution"):
        parts.append(clean(support["solution"]))
    whys = [f"{clean(e.get('id'))}) {clean(e.get('why'))}" for e in support.get("explanations") or []]
    if whys:
        parts.append("\n".join(whys))
    return "\n\n".join(p for p in parts if p)


def _text(type_key: str, p: dict[str, Any], code: str) -> tuple[str, list[str], str]:
    """(prompt, options, answer) for one validated payload."""
    match type_key:
        case "mcq":
            opts = [f"{clean(o['id'])}) {clean(o['text'])}" for o in p["options"]]
            right = [f"{clean(o['id'])}) {clean(o['text'])}" for o in p["options"] if o["id"] == p["answer"]]
            return clean(p["prompt"]), opts, "\n".join(right)
        case "multi":
            opts = [f"{clean(o['id'])}) {clean(o['text'])}" for o in p["options"]]
            right = [f"{clean(o['id'])}) {clean(o['text'])}" for o in p["options"] if o["id"] in p["answers"]]
            return clean(p["prompt"]), opts, "\n".join(right)
        case "cloze":
            text = _GAP.sub(lambda m: gap(m.group(1)), clean(p["text"]))
            blanks = sorted(p["blanks"], key=lambda b: b["n"])
            answer = [f"{b['n']}: " + " | ".join(clean(a) for a in b["answers"]) for b in blanks]
            return text, [], "\n".join(answer)
        case "ordering":
            steps = [clean(s["text"]) for s in p["steps"]]
            shown = list(steps)
            rng = seeded(code)
            while len(shown) > 1 and shown == steps:
                rng.shuffle(shown)
            labels = dict(zip(shown, _letters(len(shown)), strict=True))
            opts = [f"{labels[s]}) {s}" for s in shown]
            return clean(p["prompt"]), opts, "\n".join(f"{labels[s]}) {s}" for s in steps)
        case "matching":
            lefts = [clean(x["left"]) for x in p["pairs"]]
            rights = [clean(x["right"]) for x in p["pairs"]]
            seeded(code).shuffle(rights)
            opts = [f"{i}. {left}" for i, left in enumerate(lefts, start=1)]
            opts += [
                f"{letter}) {right}" for letter, right in zip(_letters(len(rights)), rights, strict=True)
            ]
            answer = [f"{clean(x['left'])} = {clean(x['right'])}" for x in p["pairs"]]
            return clean(p["prompt"]), opts, "\n".join(answer)
        case "flashcard":
            return clean(p["front"]), [], clean(p["back"])
        case "short_answer":
            return clean(p["prompt"]), [], clean(p["model_answer"])
    raise AssertionError(type_key)


def items(records: Records) -> Items:
    """Every item with a current version and a known, valid payload, in path order."""
    rank = skill_order(records)
    out: list[Item] = []
    skipped: list[tuple[str, str]] = []
    rows = sorted(
        records.get("item", []), key=lambda i: (rank.get(i.get("skill", ""), 1 << 30), natural(i["code"]))
    )
    for row in rows:
        code, type_key = row["code"], row.get("type_key", "")
        v = current(row)
        if v is None:
            skipped.append((code, "no current version"))
            continue
        t = TYPES.get(type_key)
        if t is None:
            skipped.append((code, f"exercise type {type_key!r} has no standard form"))
            continue
        try:
            payload = t.Draft.model_validate(v.get("payload") or {}).model_dump(mode="json")
        except ValidationError:
            skipped.append((code, f"payload is not a valid {type_key}"))
            continue
        raw = v.get("support")
        support: dict[str, Any] = raw if isinstance(raw, dict) else {}
        prompt, options, answer = _text(type_key, payload, code)
        out.append(
            Item(
                code=code,
                skill=row.get("skill", ""),
                type=type_key,
                difficulty=clean(v.get("difficulty")),
                lang=clean(v.get("lang")),
                prompt=prompt,
                options=options,
                answer=answer,
                explanation=_explanation(payload, support, type_key),
                hints=[clean(h) for h in support.get("hints") or [] if isinstance(h, str)],
                objectives=[clean(o) for o in v.get("objectives") or []],
                lesson=clean(v.get("origin_lesson")),
                payload=payload,
                support=support,
            )
        )
    return Items(out, skipped)


def represents(kind: str, codes: list[str]) -> dict[str, Any]:
    return {"kind": kind, "codes": sorted(codes, key=natural)}
