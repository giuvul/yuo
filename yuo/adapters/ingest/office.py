"""PowerPoint and Word files, read from their XML (a zip of parts), without a document library."""

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from yuo.core.documents import Extracted, Heading, Page, ReadError

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MAX_PART = 50 * 1024 * 1024  # a single XML part larger than this is not a real document


def _open(path: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise ReadError(f"the file cannot be opened: {e}") from e


def _xml(z: zipfile.ZipFile, name: str) -> ET.Element:
    info = z.getinfo(name)
    if info.file_size > MAX_PART:
        raise ReadError(f"{name} is too large")
    try:
        # ElementTree never fetches external entities, and the bundled expat (2.4 and later) refuses entity
        # expansion attacks; parts are also capped in size above
        return ET.fromstring(z.read(name))  # noqa: S314
    except ET.ParseError as e:
        raise ReadError(f"{name} is damaged: {e}") from e


def _num(name: str) -> int:
    m = re.search(r"(\d+)\.xml$", name)
    return int(m.group(1)) if m else 0


def _paragraphs(root: ET.Element, para: str, run_text: str) -> list[str]:
    out = []
    for p in root.iter(para):
        text = "".join(t.text or "" for t in p.iter(run_text)).strip()
        if text:
            out.append(text)
    return out


def read_pptx(path: Path) -> Extracted:
    with _open(path) as z:
        names = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=_num)
        if not names:
            raise ReadError("no slides in this file")
        notes = {_num(n): n for n in z.namelist() if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", n)}
        pages = []
        for i, name in enumerate(names, 1):
            root = _xml(z, name)
            title = ""
            for sp in root.iter(f"{P}sp"):
                ph = sp.find(f".//{P}nvPr/{P}ph")
                if ph is not None and ph.get("type") in ("title", "ctrTitle"):
                    title = " ".join(_paragraphs(sp, f"{A}p", f"{A}t"))
                    break
            lines = _paragraphs(root, f"{A}p", f"{A}t")
            text = "\n".join(lines)
            # the speaker notes follow the slide; notesSlideN is not always slideN, but usually is
            if (n := _num(name)) in notes:
                note_lines = [
                    line for line in _paragraphs(_xml(z, notes[n]), f"{A}p", f"{A}t") if not line.isdigit()
                ]
                if note_lines:
                    text += "\n\nNotes: " + "\n".join(note_lines)
            pages.append(Page(i, i, text.strip(), title=title))
        return Extracted(
            "slide", pages, [], count=len(pages), sparse=[p.start for p in pages if len(p.text) < 40]
        )


def read_docx(path: Path) -> Extracted:
    """Word has no pages in its file: each heading starts a section, numbered like pages (1, 2, ...)."""
    with _open(path) as z:
        if "word/document.xml" not in z.namelist():
            raise ReadError("not a Word document")
        body = _xml(z, "word/document.xml")
    pages: list[Page] = []
    outline: list[Heading] = []
    current: list[str] = []
    title = ""

    def flush() -> None:
        if current:
            n = len(pages) + 1
            pages.append(Page(n, n, "\n".join(current).strip()))
            current.clear()

    for p in body.iter(f"{W}p"):
        text = "".join(t.text or "" for t in p.iter(f"{W}t")).strip()
        if not text:
            continue
        style = p.find(f"{W}pPr/{W}pStyle")
        sid = (style.get(f"{W}val") or "") if style is not None else ""
        level = int(m.group(1)) if (m := re.match(r"(?i)heading\s*(\d)", sid)) else 0
        if sid.lower() == "title":
            title = text
            continue
        if level in (1, 2):
            flush()
            outline.append(Heading(text, level, len(pages) + 1))
        current.append(text)
        if sum(len(x) for x in current) > 6000:  # long stretches without headings: keep sections small
            flush()
    flush()
    if not pages:
        raise ReadError("the document has no text")
    return Extracted("page", pages, outline, title=title, count=len(pages))
