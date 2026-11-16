"""Items as an Anki deck (.apkg, written with genanki): one deck per path, cloze items as cloze notes and
every other type as a basic card (front: prompt and options; back: answer and explanation).

Note GUIDs come from the path and item codes, so importing a newer export updates the same cards instead
of duplicating them. Fields are HTML in Anki: all text is escaped, and `{`/`}`/`:` become entities so text
can never form a template or cloze marker. The collection is built in memory with a fixed timestamp and
zipped with a fixed date, so the same records give the same bytes (for one SQLite library version).
"""

import hashlib
import html
import io
import itertools
import re
import sqlite3
import zipfile
from typing import Any

import genanki  # type: ignore[import-untyped]

from yuo.adapters.export._common import AssetFile, Files, Item, Records, clean, items, path_record, represents

TIMESTAMP = 1_767_225_600  # 2026-01-01T00:00:00Z: note/card ids and `mod` fields, never the export time
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_CSS = ".card { font-family: sans-serif; font-size: 18px; text-align: left; } .muted { color: #666; }"


def _id(name: str) -> int:
    """A stable Anki id in genanki's recommended range [2^30, 2^31)."""
    return (1 << 30) + int.from_bytes(hashlib.sha256(name.encode()).digest()[:8]) % (1 << 30)


BASIC = genanki.Model(
    _id("yuo.anki.basic.v1"),
    "Yuo Basic",
    fields=[{"name": "Front"}, {"name": "Back"}, {"name": "Code"}],
    templates=[
        {"name": "Card 1", "qfmt": "{{Front}}", "afmt": "{{FrontSide}}<hr id=answer>{{Back}}"},
    ],
    css=_CSS,
    sort_field_index=0,
)
CLOZE = genanki.Model(
    _id("yuo.anki.cloze.v1"),
    "Yuo Cloze",
    fields=[{"name": "Text"}, {"name": "Back Extra"}, {"name": "Code"}],
    templates=[{"name": "Cloze", "qfmt": "{{cloze:Text}}", "afmt": "{{cloze:Text}}<br>{{Back Extra}}"}],
    css=_CSS,
    model_type=genanki.Model.CLOZE,
)


def field(text: str) -> str:
    """Plain text -> an inert Anki field: HTML-escaped, no braces or colons, newlines as <br>."""
    out = html.escape(clean(text), quote=True)
    out = out.replace("{", "&#123;").replace("}", "&#125;").replace(":", "&#58;")
    return out.replace("\r\n", "\n").replace("\n", "<br>")


def _basic(i: Item) -> tuple[Any, list[str]]:
    front = field(i.prompt) + ("<br><br>" + "<br>".join(field(o) for o in i.options) if i.options else "")
    back = field(i.answer)
    if i.explanation:
        back += '<br><br><div class="muted">' + field(i.explanation) + "</div>"
    return BASIC, [front, back, field(i.code)]


def _cloze(i: Item) -> tuple[Any, list[str]]:
    answers = {b["n"]: b["answers"] for b in i.payload["blanks"]}

    def gap(m: re.Match[str]) -> str:
        n = int(m.group(1))
        accepted = answers.get(n) or ["?"]
        return f"{{{{c{n}::{field(accepted[0])}}}}}"

    parts = re.split(r"(\{\{\d+\}\})", clean(i.payload["text"]))
    text = "".join(
        re.sub(r"\{\{(\d+)\}\}", gap, p) if re.fullmatch(r"\{\{\d+\}\}", p) else field(p) for p in parts
    )
    return CLOZE, [text, field(i.explanation), field(i.code)]


def _cards(records: Records) -> list[Item]:
    return items(records).items


def export_anki(records: Records, asset: AssetFile) -> Files:
    path = path_record(records)
    code = str(path.get("code", "path"))
    title = clean(path.get("title") or code).replace("::", ": ")
    deck = genanki.Deck(_id(f"yuo.deck:{code}"), title, description=field(path.get("goal") or ""))
    for i in _cards(records):
        model, fields = _cloze(i) if i.type == "cloze" else _basic(i)
        deck.add_note(
            genanki.Note(
                model=model,
                fields=fields,
                tags=["yuo", f"yuo::{i.skill}", f"yuo::type::{i.type}"],
                guid=genanki.guid_for("yuo", code, i.code),
            )
        )
    conn = sqlite3.connect(":memory:")
    try:
        cur = conn.cursor()
        genanki.Package(deck).write_to_db(cur, TIMESTAMP, itertools.count(TIMESTAMP * 1000))
        conn.commit()
        collection = conn.serialize()
    finally:
        conn.close()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in (("collection.anki2", collection), ("media", b"{}")):
            info = zipfile.ZipInfo(name, ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return {"flashcards.apkg": buf.getvalue()}


def represents_anki(records: Records) -> dict[str, Any]:
    return represents("item", [i.code for i in _cards(records)])
