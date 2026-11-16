"""The standard-format exporters (spec §9) on a small hand-written package: every item type and
block type, a video rendition, sources; each format parsed back, deterministic, and inert on hostile text."""

import csv
import hashlib
import io
import json
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

import pytest

from yuo.adapters.export import FORMATS, represents
from yuo.adapters.export._common import safe_name

EVIL = "</textarea><script>alert(1)</script> {{c1::x}} ]]> <b>bold</b> & \\ % {"
H = "0" * 64


def sha(n: int) -> str:
    return hashlib.sha256(str(n).encode()).hexdigest()


def run(n: int) -> list[dict[str, Any]]:
    return [
        {"text": f"Text {n} "},
        {"text": "bold", "marks": ["bold"]},
        {"text": " and "},
        {"text": "x < y", "marks": ["code"]},
        {"text": " in "},
        {"text": "italic", "marks": ["italic"]},
    ]


def item(code: str, skill: str, type_key: str, payload: dict[str, Any], **support: Any) -> dict[str, Any]:
    h = hashlib.sha256(code.encode()).hexdigest()
    return {
        "code": code,
        "skill": skill,
        "type_key": type_key,
        "current": h,
        "versions": [
            {
                "version_hash": h,
                "version_no": 1,
                "type_version": 1,
                "lang": "en",
                "difficulty": "foundational",
                "payload": payload | {"objective_code": f"{skill}.o1"},
                "objectives": [f"{skill}.o1"],
                "support": {"hints": ["h1", "h2", "h3"], "solution": "Because.", "explanations": []}
                | support,
                "origin_lesson": f"{skill}.l1",
                "provenance": {"authorship": "generated"},
            }
        ],
    }


def records(evil: str = "") -> dict[str, list[dict[str, Any]]]:
    e = f" {evil}" if evil else ""
    body = [
        {"type": "heading", "bid": "b1", "level": 1, "text": f"Joins{e}"},
        {"type": "paragraph", "bid": "b2", "inlines": [*run(1), {"text": e}]},
        {"type": "list", "bid": "b3", "ordered": True, "items": [run(2), [{"text": f"two{e}"}]]},
        {"type": "list", "bid": "b4", "ordered": False, "items": [run(3)]},
        {"type": "code", "bid": "b5", "language": "sql", "text": "SELECT 1 -- ```", "caption": f"A query{e}"},
        {"type": "math", "bid": "b6", "latex": r"\frac{a}{b} < c", "display": True},
        {"type": "math", "bid": "b7", "latex": "x^2", "display": False},
        {
            "type": "callout",
            "bid": "b8",
            "variant": "warning",
            "blocks": [{"type": "paragraph", "bid": "b8.1", "inlines": [{"text": f"Careful{e}"}]}],
        },
        {
            "type": "worked_example",
            "bid": "b9",
            "title": f"Two tables{e}",
            "steps": [run(4), [{"text": "done"}]],
        },
        {"type": "glossary_term", "bid": "b10", "term": f"Join{e}", "definition": f"Combining rows{e}"},
    ]

    def lesson(code: str, skill: str, pos: int, title: str) -> dict[str, Any]:
        h = sha(pos + 100 + len(skill))
        v = {
            "version_hash": h,
            "version_no": 1,
            "lang": "en",
            "title": title + e,
            "body": body,
            "est_minutes": 5,
            "sources": [{"key": "web-1"}],
            "provenance": {"authorship": "generated"},
        }
        return {"code": code, "skill": skill, "kind": "core", "position": pos, "current": h, "versions": [v]}

    choices = [
        {"id": "a", "text": f"INNER{e}"},
        {"id": "b", "text": "LEFT"},
        {"id": "c", "text": "CROSS"},
        {"id": "d", "text": "FULL"},
    ]
    whys = [{"id": o["id"], "why": f"why {o['id']}{e}"} for o in choices]
    s0, s1 = "sql.b0.s0", "sql.b1.s0"
    return {
        "path": [
            {
                "code": "sql",
                "title": f"SQL / joins{e}",
                "subject": "SQL",
                "goal": f"Write joins{e}",
                "goal_type": "practical",
                "difficulty": "foundational",
                "content_lang": "en",
                "licence": "CC-BY-4.0",
            }
        ],
        "branch": [
            {"code": "sql.b1", "title": f"Later{e}", "position": 1},
            {"code": "sql.b0", "title": f"Basics{e}", "position": 0},
        ],
        "skill": [
            {"code": s1, "branch": "sql.b1", "title": f"Outer{e}", "position": 0},
            {"code": s0, "branch": "sql.b0", "title": f"Inner/{e}", "position": 0},
        ],
        "lesson": [
            lesson(f"{s1}.l1", s1, 0, "Outer joins"),
            lesson(f"{s0}.l2", s0, 1, "More"),
            lesson(f"{s0}.l1", s0, 0, "Inner joins"),
            {"code": f"{s0}.l3", "skill": s0, "kind": "core", "position": 2, "current": None, "versions": []},
        ],
        "item": [
            item(
                f"{s0}.q1",
                s0,
                "mcq",
                {"prompt": f"Which keeps matches?{e}", "options": choices, "answer": "a"},
                explanations=whys,
            ),
            item(
                f"{s0}.q2",
                s0,
                "multi",
                {"prompt": f"Pick two{e}", "options": choices, "answers": ["a", "c"]},
                explanations=whys,
            ),
            item(
                f"{s0}.q3",
                s0,
                "cloze",
                {
                    "text": f"A {{{{1}}}} join and {{{{2}}}}.{e}",
                    "blanks": [
                        {"n": 1, "answers": ["inner", "INNER} #~"]},
                        {"n": 2, "answers": [f"x{e}"[:30]]},
                    ],
                },
            ),
            item(
                f"{s0}.q4",
                s0,
                "ordering",
                {
                    "prompt": f"Order{e}",
                    "steps": [
                        {"id": "a", "text": f"FROM{e}"},
                        {"id": "b", "text": "WHERE"},
                        {"id": "c", "text": "SELECT"},
                    ],
                },
            ),
            item(
                f"{s0}.q5",
                s0,
                "matching",
                {
                    "prompt": f"Match{e}",
                    "pairs": [
                        {"left": f"INNER{e}", "right": "both"},
                        {"left": "LEFT", "right": "all left"},
                        {"left": "CROSS", "right": "every pair"},
                    ],
                },
            ),
            item(f"{s1}.q1", s1, "flashcard", {"front": f"LEFT JOIN?{e}", "back": f"All left rows{e}"}),
            item(
                f"{s1}.q2",
                s1,
                "short_answer",
                {
                    "prompt": f"Why outer?{e}",
                    "model_answer": f"To keep{e}",
                    "rubric": [{"point": f"keeps rows{e}", "weight": 2}, {"point": "nulls", "weight": 1}],
                },
            ),
            item(f"{s1}.q3", s1, "drawing", {"prompt": "Unknown type"}),
            item(f"{s1}.q4", s1, "mcq", {"prompt": "Broken", "options": []}),
        ],
        "rendition": [
            {
                "code": f"{s0}.l1.video",
                "lesson": f"{s0}.l1",
                "kind": "video",
                "current": H,
                "versions": [
                    {
                        "version_hash": H,
                        "version_no": 1,
                        "lang": "en",
                        "lesson_version_hash": H,
                        "renderer": "remotion",
                        "spec_kind": "rendered",
                        "provenance": {"authorship": "generated"},
                        "assets": [
                            {"role": "video", "lang": "en", "recipe_hash": H, "sha256": sha(1)},
                            {"role": "subtitles", "lang": "en", "recipe_hash": H, "sha256": sha(2)},
                            {"role": "poster", "lang": "en", "recipe_hash": H, "sha256": sha(3)},
                        ],
                    }
                ],
            },
            {
                "code": f"{s0}.l1.reading",
                "lesson": f"{s0}.l1",
                "kind": "reading",
                "current": None,
                "versions": [],
            },
        ],
        "source": [
            {
                "key": "web-1",
                "kind": "web",
                "title": f"Joins explained{e}",
                "url": "https://example.org/a b{c}",
                "accessed_at": "2026-10-01T10:00:00Z",
                "citation": {
                    "type": "webpage",
                    "title": f"Joins explained{e}",
                    "author": [{"family": "Codd", "given": "E. F."}, {"literal": f"SQL Group{e}"}],
                    "issued": {"date-parts": [[2020, 3]]},
                },
            },
            {
                "key": "book 2",
                "kind": "book",
                "title": "Databases",
                "url": None,
                "citation": {"type": "book", "publisher": "P & Q", "page": "1-10", "DOI": "10.1/x"},
            },
        ],
        "asset": [
            {"sha256": sha(n), "media_type": "x", "kind": "x", "bytes": 1, "present": True} for n in (1, 2, 3)
        ],
    }


@pytest.fixture
def asset(tmp_path: Path) -> Any:
    for n in (1, 2, 3):
        (tmp_path / sha(n)).write_bytes(str(n).encode())
    return lambda h: tmp_path / h


def every(recs: dict[str, list[dict[str, Any]]], asset: Any) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for fmt, export in FORMATS.items():
        files = export(recs, asset)
        assert files, fmt
        for name in files:
            assert safe_name(name) == name and name not in out, (fmt, name)
        out |= files
    return out


def test_formats_are_the_v1_set() -> None:
    assert sorted(FORMATS) == [
        "anki-apkg",
        "bibtex",
        "csl-json",
        "csv",
        "moodle-xml",
        "mp4-webvtt",
        "readings",
    ]
    with pytest.raises(ValueError, match="unknown"):
        represents("qti", records())


def test_deterministic(asset: Any) -> None:
    assert every(records(EVIL), asset) == every(records(EVIL), asset)


def test_csv(asset: Any) -> None:
    files = FORMATS["csv"](records(EVIL), asset)
    assert not files["items.csv"].startswith(b"\xef\xbb\xbf") and b"\r\n" in files["items.csv"]
    rows = list(csv.DictReader(io.StringIO(files["items.csv"].decode(), newline="")))
    assert [r["code"] for r in rows] == [f"sql.b0.s0.q{n}" for n in range(1, 6)] + [
        "sql.b1.s0.q1",
        "sql.b1.s0.q2",
    ]
    by = {r["type"]: r for r in rows}
    assert by["mcq"]["answer"].startswith("a) INNER") and by["mcq"]["options"].count("\n") == 3
    assert by["multi"]["answer"].splitlines()[1] == "c) CROSS"
    assert (
        by["cloze"]["prompt"].startswith("A [1: ____] join")
        and "1: inner | INNER} #~" in by["cloze"]["answer"]
    )
    assert by["ordering"]["answer"].splitlines()[0].endswith(f"FROM {EVIL}")
    assert f"INNER {EVIL} = both" in by["matching"]["answer"]
    assert "Rubric" in by["short_answer"]["explanation"] and by["short_answer"]["hints"] == "h1\nh2\nh3"
    assert by["mcq"]["prompt"] == f"Which keeps matches? {EVIL}"  # quoting round-trips hostile text exactly
    cards = list(csv.DictReader(io.StringIO(files["flashcards.csv"].decode(), newline="")))
    assert cards == [
        {
            "front": f"LEFT JOIN? {EVIL}",
            "back": f"All left rows {EVIL}",
            "skill": "sql.b1.s0",
            "tags": "yuo sql.b1.s0 sql.b1.s0.q1",
        }
    ]
    assert represents("csv", records())["codes"][-1] == "sql.b1.s0.q2"


def test_anki(asset: Any, tmp_path: Path) -> None:
    files = FORMATS["anki-apkg"](records(EVIL), asset)
    with zipfile.ZipFile(io.BytesIO(files["flashcards.apkg"])) as z:
        assert sorted(z.namelist()) == ["collection.anki2", "media"]
        (tmp_path / "c.anki2").write_bytes(z.read("collection.anki2"))
    c = sqlite3.connect(tmp_path / "c.anki2")
    notes = c.execute("SELECT guid, flds, tags, mid FROM notes ORDER BY id").fetchall()
    decks = json.loads(c.execute("SELECT decks FROM col").fetchone()[0])
    assert any(d["name"] == f"SQL / joins {EVIL}".replace("::", ": ") for d in decks.values())
    assert (
        len(notes) == 7 and c.execute("SELECT count(*) FROM cards").fetchone()[0] == 8
    )  # the cloze has 2 gaps
    fields = [n[1].split("\x1f") for n in notes]
    assert (
        fields[0][2] == "sql.b0.s0.q1" and "a) INNER" in fields[0][0] and fields[0][1].startswith("a) INNER")
    )
    cloze = fields[2][0]
    assert "{{c1::inner}}" in cloze and "{{c2::" in cloze and cloze.count("{{c") == 2
    for f in (x for n in fields for x in n):
        assert "<script" not in f and "<b>" not in f and "{{c1::x" not in f
    assert "&lt;script&gt;" in fields[0][0]
    again = FORMATS["anki-apkg"](records(), asset)
    with zipfile.ZipFile(io.BytesIO(again["flashcards.apkg"])) as z:
        (tmp_path / "d.anki2").write_bytes(z.read("collection.anki2"))
    guids = [
        r[0] for r in sqlite3.connect(tmp_path / "d.anki2").execute("SELECT guid FROM notes ORDER BY id")
    ]
    assert guids == [n[0] for n in notes]  # same item codes, same notes, whatever the text


def test_moodle(asset: Any) -> None:
    files = FORMATS["moodle-xml"](records(EVIL), asset)
    root = ET.fromstring(files["questions.xml"])
    qs = root.findall("question")
    E2 = EVIL.replace("/", "//")  # a slash separates category levels in Moodle
    cats = [q.findtext("category/text") for q in qs if q.get("type") == "category"]
    assert len(cats) == 2 and cats[0] == f"$course$/top/SQL // joins {E2}/Inner// {E2}"
    by = {q.findtext("name/text"): q for q in qs if q.get("type") != "category"}
    assert {k: v.get("type") for k, v in by.items()} == {
        "sql.b0.s0.q1": "multichoice",
        "sql.b0.s0.q2": "multichoice",
        "sql.b0.s0.q3": "multianswer",
        "sql.b0.s0.q4": "ordering",
        "sql.b0.s0.q5": "matching",
        "sql.b1.s0.q2": "essay",
    }
    mcq, multi = by["sql.b0.s0.q1"], by["sql.b0.s0.q2"]
    assert mcq.findtext("single") == "true" and multi.findtext("single") == "false"
    assert [a.get("fraction") for a in mcq.findall("answer")] == ["100", "0", "0", "0"]
    assert [a.get("fraction") for a in multi.findall("answer")] == ["50", "-50", "50", "-50"]
    assert mcq.findtext("questiontext/text") == f"Which keeps matches? {EVIL}"
    assert mcq.find("questiontext").get("format") == "plain_text"  # type: ignore[union-attr]
    cloze = by["sql.b0.s0.q3"].findtext("questiontext/text") or ""
    assert "{1:SHORTANSWER:=inner~=INNER\\} \\#\\~}" in cloze and cloze.count("{1:SHORTANSWER:") == 2
    assert "<script" not in cloze and "&lt;script&gt;" in cloze and "{{c1" not in cloze
    assert [a.findtext("text") for a in by["sql.b0.s0.q4"].findall("answer")][1:] == ["WHERE", "SELECT"]
    assert len(by["sql.b0.s0.q5"].findall("subquestion")) == 3
    assert "Model answer" in (by["sql.b1.s0.q2"].findtext("graderinfo/text") or "")
    assert len(mcq.findall("hint")) == 3
    raw = files["questions.xml"].decode()
    assert "<script" not in raw and "]]>" not in raw and "<b>" not in raw
    notes = files["export-notes.txt"].decode()
    for code in ("sql.b1.s0.q1", "sql.b1.s0.q3", "sql.b1.s0.q4"):
        assert code in notes
    assert represents("moodle-xml", records())["codes"] == sorted(str(c) for c in by)


def test_readings(asset: Any) -> None:
    files = FORMATS["readings"](records(EVIL), asset)
    assert sorted(files) == [
        f"readings/{n}"
        for n in (
            "index.html",
            "index.md",
            "sql.b0.s0.l1.html",
            "sql.b0.s0.l1.md",
            "sql.b0.s0.l2.html",
            "sql.b0.s0.l2.md",
            "sql.b1.s0.l1.html",
            "sql.b1.s0.l1.md",
        )
    ]
    page = files["readings/sql.b0.s0.l1.html"].decode()
    assert "<script" not in page.lower() and "&lt;script&gt;" in page and "&lt;b&gt;bold&lt;/b&gt;" in page
    assert "<strong>bold</strong>" in page and "<code>x &lt; y</code>" in page and "<em>italic</em>" in page
    assert '<code class="math display">\\frac{a}{b} &lt; c</code>' in page
    assert "<ol>" in page and "<ul>" in page and 'class="callout warning"' in page and "<dt>Join" in page
    assert (
        "Content-Security-Policy" in page and 'href="http' not in page
    )  # the source URL has a space: no link
    assert "src=" not in page and "<link" not in page and "@import" not in page
    md = files["readings/sql.b0.s0.l1.md"].decode()
    assert md.startswith("# Inner joins") and "**bold**" in md and "`x < y`" in md and "```sql" in md
    assert "<script" not in md and "&lt;script&gt;" in md and "&lt;b&gt;" in md and "\\{\\{c1::x\\}\\}" in md
    assert "```latex\n\\frac{a}{b} < c\n```" in md and "`x^2`" in md and "> **Warning:**" in md
    assert "````" in md  # the code text contains ```, so the fence is longer
    index = files["readings/index.md"].decode()
    assert index.index("sql.b0.s0.l1.md") < index.index("sql.b0.s0.l2.md") < index.index("sql.b1.s0.l1.md")
    assert "sql.b0.s0.l3" not in index  # no current version: nothing to read
    assert 'href="sql.b0.s0.l1.html"' in files["readings/index.html"].decode()
    assert represents("readings", records())["codes"] == ["sql.b0.s0.l1", "sql.b0.s0.l2", "sql.b1.s0.l1"]


def test_video(asset: Any) -> None:
    files = FORMATS["mp4-webvtt"](records(), asset)
    base = "videos/sql.b0.s0.l1"
    assert files == {f"{base}.mp4": b"1", f"{base}.vtt": b"2", f"{base}.jpg": b"3"}
    assert represents("mp4-webvtt", records()) == {"kind": "rendition", "codes": ["sql.b0.s0.l1.video"]}
    absent = records()
    absent["asset"][1]["present"] = False
    assert FORMATS["mp4-webvtt"](absent, asset) == {}


def test_sources(asset: Any) -> None:
    items = json.loads(FORMATS["csl-json"](records(EVIL), asset)["sources.json"])
    assert [i["id"] for i in items] == ["book 2", "web-1"]
    assert items[1]["accessed"] == {"date-parts": [[2026, 10, 1]]} and items[1]["URL"].startswith("https://")
    raw = FORMATS["csl-json"](records(EVIL), asset)["sources.json"].decode()
    assert "<" not in raw and ">" not in raw and "\\u003cscript\\u003e" in raw
    bib = FORMATS["bibtex"](records(EVIL), asset)["sources.bib"].decode()
    assert bib.startswith("@book{book_2,\n") and "@misc{web-1," in bib
    assert (
        "author = {{Codd}, E. F. and {SQL Group" in bib and "month = mar," in bib and "year = {2020}" in bib
    )
    assert "pages = {1--10}" in bib and "publisher = {P \\& Q}" in bib and "urldate = {2026-10-01}" in bib
    assert "url = {https://example.org/a%20b%7Bc%7D}" in bib
    assert "\\textless{}script\\textgreater{}" in bib and "<" not in bib and "\\{\\{c1::x\\}\\}" in bib
    depth = 0
    for ch in bib.replace("\\{", "").replace("\\}", ""):
        depth += {"{": 1, "}": -1}.get(ch, 0)
        assert depth >= 0
    assert depth == 0  # balanced: hostile braces cannot end an entry
    assert represents("bibtex", records()) == {"kind": "source", "codes": ["book 2", "web-1"]}


def test_hostile_text_is_inert_everywhere(asset: Any) -> None:
    for name, data in every(records(EVIL), asset).items():
        if name.endswith((".mp4", ".vtt", ".jpg", ".apkg", ".csv")):
            continue  # media are copied bytes; apkg fields and CSV cells are checked above
        text = data.decode()
        assert "<script" not in text.lower() and "]]>" not in text, (
            name
        )  # `{{c1::` only means something to Anki


def test_safe_name() -> None:
    for bad in ("../x", "/abs", "a/../b", "a b", "ä"):
        with pytest.raises(ValueError):
            safe_name(bad)


def test_csv_cells_cannot_start_a_formula() -> None:
    from yuo.adapters.export.csvfile import _cell

    assert [_cell(t) for t in ("=HYPERLINK(1)", "+1", "-2 + 3", "@SUM(A1)", "plain", "")] == [
        "'=HYPERLINK(1)", "'+1", "'-2 + 3", "'@SUM(A1)", "plain", "",
    ]  # fmt: skip
