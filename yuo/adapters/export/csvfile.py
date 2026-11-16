"""Items and flashcards as CSV (RFC 4180: CRLF, quoted where needed, UTF-8 without BOM), for spreadsheets
and the many tools that import a table. Cells hold plain text; multi-line cells (options) are quoted.

A cell that a spreadsheet would read as a formula (it starts with = + - @, a tab or a carriage return) gets a
leading apostrophe, which spreadsheets hide: package content is untrusted, and an author must not be able to
plant a formula that runs when the learner opens the file (OWASP CSV injection)."""

import csv
import io
from typing import Any

from yuo.adapters.export._common import AssetFile, Files, Records, items, represents

ITEM_COLUMNS = ("code", "skill", "type", "difficulty", "lang", "prompt", "options", "answer", "explanation",
                "hints", "objectives", "lesson")  # fmt: skip
CARD_COLUMNS = ("front", "back", "skill", "tags")


_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _cell(text: str) -> str:
    return f"'{text}" if text.startswith(_FORMULA) else text


def _table(header: tuple[str, ...], rows: list[list[str]]) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    w.writerow(header)
    w.writerows([[_cell(c) for c in row] for row in rows])
    return buf.getvalue().encode("utf-8")


def export_csv(records: Records, asset: AssetFile) -> Files:
    found = items(records).items
    item_rows = [
        [
            i.code,
            i.skill,
            i.type,
            i.difficulty,
            i.lang,
            i.prompt,
            "\n".join(i.options),
            i.answer,
            i.explanation,
            "\n".join(i.hints),
            " ".join(i.objectives),
            i.lesson,
        ]
        for i in found
    ]
    cards = [[i.prompt, i.answer, i.skill, f"yuo {i.skill} {i.code}"] for i in found if i.type == "flashcard"]
    return {"items.csv": _table(ITEM_COLUMNS, item_rows), "flashcards.csv": _table(CARD_COLUMNS, cards)}


def represents_csv(records: Records) -> dict[str, Any]:
    return represents("item", [i.code for i in items(records).items])
