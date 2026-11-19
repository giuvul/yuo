"""Markdown and plain text: `#` headings start sections, numbered like pages."""

import re
from pathlib import Path

from yuo.core.documents import Extracted, Heading, Page, ReadError

HEADING = re.compile(r"^(#{1,2})\s+(.+?)\s*#*$")


def read_text(path: Path) -> Extracted:
    try:
        raw = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        raw = path.read_bytes().decode("latin-1")
    except OSError as e:
        raise ReadError(str(e)) from e
    pages: list[Page] = []
    outline: list[Heading] = []
    current: list[str] = []

    def flush() -> None:
        text = "\n".join(current).strip()
        if text:
            n = len(pages) + 1
            pages.append(Page(n, n, text))
        current.clear()

    for line in raw.splitlines():
        if m := HEADING.match(line):
            flush()
            outline.append(Heading(m.group(2), len(m.group(1)), len(pages) + 1))
        current.append(line)
        if sum(len(x) for x in current) > 6000:
            flush()
    flush()
    if not pages:
        raise ReadError("the file has no text")
    return Extracted("page", pages, outline, count=len(pages))
