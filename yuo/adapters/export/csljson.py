"""Sources as CSL-JSON (`sources.json`), the citation format of Zotero, Pandoc and most reference tools.
A source's `citation` is CSL-JSON already; this fills the id from its key and the title, URL and dates from
the record when the citation lacks them. `<`, `>` and `&` are written as \\u escapes, so the file stays
inert even when pasted into a page."""

import json
import re
from typing import Any

from yuo.adapters.export._common import AssetFile, Files, Records, clean, represents

_DATE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?")


def date_parts(value: Any) -> dict[str, Any] | None:
    m = _DATE.match(value) if isinstance(value, str) else None
    if not m:
        return None
    return {"date-parts": [[int(p) for p in m.groups() if p]]}


def _type(kind: str) -> str:
    return {"web": "webpage", "book": "book", "video": "motion_picture"}.get(kind, "document")


def csl(source: dict[str, Any]) -> dict[str, Any]:
    item = dict(source.get("citation") or {})
    item["id"] = clean(source.get("key"))
    item.setdefault("type", _type(str(source.get("kind", ""))))
    if source.get("title"):
        item.setdefault("title", clean(source["title"]))
    if source.get("url"):
        item.setdefault("URL", clean(source["url"]))
    for key, field in (("accessed", "accessed_at"), ("issued", "published_at")):
        parts = date_parts(source.get(field))
        if parts and key not in item:
            item[key] = parts
    return item


def sources(records: Records) -> list[dict[str, Any]]:
    return sorted(records.get("source", []), key=lambda s: str(s.get("key", "")))


def export_csljson(records: Records, asset: AssetFile) -> Files:
    text = json.dumps([csl(s) for s in sources(records)], ensure_ascii=False, indent=2, sort_keys=True)
    text = text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return {"sources.json": (text + "\n").encode("utf-8")} if records.get("source") else {}


def represents_csljson(records: Records) -> dict[str, Any]:
    return represents("source", [str(s.get("key")) for s in sources(records)])
