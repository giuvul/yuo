"""Items as Moodle XML (`questions.xml`), the question-bank format every Moodle imports: one category per
skill, plain-text questions, the worked solution as general feedback and the hints as Moodle hints.

Mapping: mcq and multi -> multichoice (single true/false), short answer -> essay (rubric and model answer
for the grader), matching -> matching, cloze -> multianswer, ordering -> ordering (core since Moodle 4.4).
Flashcards have no question form and are skipped; `export-notes.txt` lists every skipped item and why.
The XML is built with ElementTree, so all text is escaped; cloze text, the one place Moodle parses
markup inside text, is HTML with braces as entities and answers backslash-escaped.
"""

import html
import re
import xml.etree.ElementTree as ET
from typing import Any

from yuo.adapters.export._common import AssetFile, Files, Item, Records, clean, items, path_record, represents

PLAIN = "plain_text"
_GAP = re.compile(r"\{\{(\d+)\}\}")
_CLOZE_SPECIAL = re.compile(r'([\\}#~/"{])')
MULTI_RIGHT = {2: "50", 3: "33.33333", 4: "25", 5: "20"}  # Moodle accepts only its fixed grade fractions
MULTI_WRONG = {1: "-100", 2: "-50", 3: "-33.33333", 4: "-25", 5: "-20"}
SKIP = {"flashcard": "a flashcard has no Moodle question type (use the Anki or CSV export)"}


def _text(parent: ET.Element, tag: str, text: str, fmt: str | None = PLAIN, **attrs: str) -> ET.Element:
    el = ET.SubElement(parent, tag, {"format": fmt, **attrs} if fmt else attrs)
    ET.SubElement(el, "text").text = clean(text)
    return el


def _value(parent: ET.Element, tag: str, value: str) -> None:
    ET.SubElement(parent, tag).text = value


def _category(path: str) -> str:
    return "/".join(clean(p).replace("/", "//") for p in path.split("\0"))


def _cloze_answer(text: str) -> str:
    return _CLOZE_SPECIAL.sub(r"\\\1", html.escape(clean(text), quote=False))


def _cloze_html(text: str) -> str:
    return (
        html.escape(clean(text), quote=True)
        .replace("{", "&#123;")
        .replace("}", "&#125;")
        .replace("\n", "<br>")
    )


def _question(quiz: ET.Element, i: Item) -> None:
    p = i.payload
    qtype = {"mcq": "multichoice", "multi": "multichoice", "short_answer": "essay", "matching": "matching",
             "cloze": "multianswer", "ordering": "ordering"}[i.type]  # fmt: skip
    q = ET.SubElement(quiz, "question", {"type": qtype})
    _text(q, "name", i.code, fmt=None)
    if i.type == "cloze":
        blanks = {b["n"]: b["answers"] for b in p["blanks"]}
        parts = _GAP.split(clean(p["text"]))
        body = "".join(
            _cloze_html(part)
            if k % 2 == 0
            else "{1:SHORTANSWER:" + "~".join(f"={_cloze_answer(a)}" for a in blanks.get(int(part), [])) + "}"
            for k, part in enumerate(parts)
        )
        _text(q, "questiontext", body, fmt="html")
    else:
        _text(q, "questiontext", i.prompt)
    choice = i.type in ("mcq", "multi")  # option whys go in each answer's feedback instead
    _text(q, "generalfeedback", clean(i.support.get("solution")) if choice else i.explanation)
    _value(q, "defaultgrade", "1")
    _value(q, "penalty", "0.3333333")
    _value(q, "hidden", "0")
    _value(q, "idnumber", i.code)
    whys = {e.get("id"): clean(e.get("why")) for e in i.support.get("explanations") or []}
    match i.type:
        case "mcq" | "multi":
            single = i.type == "mcq"
            right = {p["answer"]} if single else set(p["answers"])
            n_right, n_wrong = len(right), len(p["options"]) - len(right)
            _value(q, "single", "true" if single else "false")
            _value(q, "shuffleanswers", "true")
            _value(q, "answernumbering", "abc")
            for o in p["options"]:
                if single:
                    fraction = "100" if o["id"] in right else "0"
                else:
                    fraction = (
                        MULTI_RIGHT.get(n_right, "0") if o["id"] in right else MULTI_WRONG.get(n_wrong, "0")
                    )
                a = _text(q, "answer", o["text"], fraction=fraction)
                _text(a, "feedback", whys.get(o["id"], ""))
        case "short_answer":
            _value(q, "responseformat", "plain")
            _value(q, "responserequired", "1")
            _value(q, "responsefieldlines", "5")
            _value(q, "attachments", "0")
            _value(q, "attachmentsrequired", "0")
            _text(q, "graderinfo", f"Model answer: {i.answer}\n\n{i.explanation}")
            _text(q, "responsetemplate", "")
        case "matching":
            _value(q, "shuffleanswers", "true")
            for pair in p["pairs"]:
                sub = _text(q, "subquestion", pair["left"])
                ET.SubElement(ET.SubElement(sub, "answer"), "text").text = clean(pair["right"])
        case "ordering":
            _value(q, "layouttype", "VERTICAL")
            _value(q, "selecttype", "ALL")
            _value(q, "selectcount", "0")
            _value(q, "gradingtype", "ABSOLUTE_POSITION")
            _value(q, "showgrading", "SHOW")
            _value(q, "numberingstyle", "none")
            for n, step in enumerate(p["steps"], start=1):
                _text(q, "answer", step["text"], fraction=f"{n}.0000000")
    for hint in i.hints:
        _text(q, "hint", hint)


def _split(records: Records) -> tuple[list[Item], list[tuple[str, str]]]:
    found = items(records)
    keep = [i for i in found.items if i.type not in SKIP]
    skipped = found.skipped + [(i.code, SKIP[i.type]) for i in found.items if i.type in SKIP]
    return keep, skipped


def export_moodle(records: Records, asset: AssetFile) -> Files:
    keep, skipped = _split(records)
    path = path_record(records)
    path_title = clean(path.get("title") or path.get("code") or "Yuo")
    skills = {s["code"]: clean(s.get("title") or s["code"]) for s in records.get("skill", [])}
    quiz = ET.Element("quiz")
    category = None
    for i in keep:
        if i.skill != category:
            category = i.skill
            cat = ET.SubElement(quiz, "question", {"type": "category"})
            _text(
                cat,
                "category",
                "$course$/top/" + _category(f"{path_title}\0{skills.get(i.skill, i.skill)}"),
                fmt=None,
            )
            _value(cat, "idnumber", i.skill)
        _question(quiz, i)
    ET.indent(quiz, space=" ")
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(quiz, encoding="unicode") + "\n"
    lines = [
        "Moodle XML export notes",
        "",
        "Import into the question bank as 'Moodle XML format'. Ordering questions need Moodle 4.4 or later.",
        "",
        f"Exported: {len(keep)} questions.",
        f"Skipped: {len(skipped)} items." + ("" if skipped else " None."),
    ]
    lines += [f"- {code}: {why}" for code, why in skipped]
    return {
        "questions.xml": xml.encode("utf-8"),
        "export-notes.txt": ("\n".join(lines) + "\n").encode("utf-8"),
    }


def represents_moodle(records: Records) -> dict[str, Any]:
    return represents("item", [i.code for i in _split(records)[0]])
