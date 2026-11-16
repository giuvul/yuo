"""Sources as BibTeX (`sources.bib`) for LaTeX, from the CSL-JSON each source carries. A small writer of
our own (citeproc libraries are CPAL/AGPL): CSL types map to the classic entry types, every value is
braced and LaTeX-escaped, URLs are percent-encoded where a brace or backslash would break the entry.
UTF-8 is kept as it is (biber and bibtexu read it)."""

import re
from typing import Any

from yuo.adapters.export._common import AssetFile, Files, Records, clean, represents
from yuo.adapters.export.csljson import csl, sources

ENTRY_TYPES = {"article-journal": "article", "article-magazine": "article", "article-newspaper": "article",
               "book": "book", "chapter": "incollection", "paper-conference": "inproceedings",
               "report": "techreport", "thesis": "phdthesis", "manual": "manual"}  # fmt: skip
_LATEX = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$", "&": r"\&", "%": r"\%", "#": r"\#",
          "_": r"\_", "^": r"\textasciicircum{}", "~": r"\textasciitilde{}", "<": r"\textless{}",
          ">": r"\textgreater{}"}  # fmt: skip
_LATEX_RE = re.compile("|".join(re.escape(c) for c in _LATEX))
_URL_UNSAFE = re.compile(r'[{}\\\s"<>]')
_KEY = re.compile(r"[^A-Za-z0-9_:.-]")
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def latex(text: Any) -> str:
    return _LATEX_RE.sub(lambda m: _LATEX[m.group(0)], clean(text).replace("\n", " "))


def url(text: Any) -> str:
    """Percent-encode what would unbalance braces or break the value (a URL is never LaTeX-escaped)."""
    return _URL_UNSAFE.sub(lambda m: "".join(f"%{b:02X}" for b in m.group(0).encode()), clean(text))


def _names(names: Any) -> str:
    out = []
    for n in names if isinstance(names, list) else []:
        if not isinstance(n, dict):
            continue
        if n.get("literal"):
            out.append("{" + latex(n["literal"]) + "}")  # an organisation: never split into first/last
        elif n.get("family"):
            family = " ".join(latex(n[k]) for k in ("non-dropping-particle", "family") if n.get(k))
            given = latex(n.get("given", ""))
            out.append(f"{{{family}}}, {given}" if given else f"{{{family}}}")
    return " and ".join(out)


def _date(value: Any) -> list[int]:
    try:
        parts = value["date-parts"][0]
        return [int(p) for p in parts[:3]]
    except KeyError, IndexError, TypeError, ValueError:
        return []


def key(raw: str, taken: set[str]) -> str:
    base = _KEY.sub("_", clean(raw)) or "source"
    out, n = base, 2
    while out in taken:
        out, n = f"{base}_{n}", n + 1
    taken.add(out)
    return out


def entry(item: dict[str, Any], cite_key: str) -> str:
    kind = ENTRY_TYPES.get(str(item.get("type", "")), "misc")
    fields: list[str] = []

    def add(name: str, value: str, macro: bool = False) -> None:
        if value:
            fields.append(f"  {name} = {value}" if macro else f"  {name} = {{{value}}}")

    add("author", _names(item.get("author")))
    add("editor", _names(item.get("editor")))
    add("title", latex(item.get("title", "")))
    container = latex(item.get("container-title", ""))
    if kind == "article":
        add("journal", container)
    elif kind in ("incollection", "inproceedings"):
        add("booktitle", container)
    elif container:
        add("howpublished", container)
    add("publisher" if kind != "techreport" else "institution", latex(item.get("publisher", "")))
    add("address", latex(item.get("publisher-place", "")))
    add("edition", latex(item.get("edition", "")))
    add("volume", latex(item.get("volume", "")))
    add("number", latex(item.get("issue", "") or item.get("number", "")))
    add("pages", latex(str(item.get("page", "")).replace("-", "--")))
    issued = _date(item.get("issued"))
    if issued:
        add("year", str(issued[0]))
    if len(issued) > 1 and 1 <= issued[1] <= 12:
        add("month", MONTHS[issued[1] - 1], macro=True)  # a BibTeX macro, unbraced
    add("doi", url(item.get("DOI", "")))
    add("isbn", latex(item.get("ISBN", "")))
    add("issn", latex(item.get("ISSN", "")))
    add("url", url(item.get("URL", "")))
    accessed = _date(item.get("accessed"))
    if accessed:
        add("urldate", "-".join(f"{p:02d}" for p in accessed))
    add("note", latex(item.get("note", "")))
    return f"@{kind}{{{cite_key},\n" + ",\n".join(fields) + "\n}\n"


def export_bibtex(records: Records, asset: AssetFile) -> Files:
    taken: set[str] = set()
    entries = [entry(csl(s), key(str(s.get("key", "")), taken)) for s in sources(records)]
    return {"sources.bib": "\n".join(entries).encode("utf-8")} if entries else {}


def represents_bibtex(records: Records) -> dict[str, Any]:
    return represents("source", [str(s.get("key")) for s in sources(records)])
