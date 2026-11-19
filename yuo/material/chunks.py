"""Split what a reader extracted into the material's tree: chapters and sections from the file's own outline,
and chunks of about `TARGET` tokens that never cross a chapter or section boundary.

Pure functions: no database, no model. Tokens are estimated (four characters each), which is close enough for
budgets.
"""

from dataclasses import dataclass

from yuo.core.documents import Extracted, Page

TARGET = 1200  # tokens per chunk
MAX = 1800  # a chunk may grow to this to keep a page whole


def tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


@dataclass(frozen=True, slots=True)
class SectionDraft:
    level: str  # chapter, section, chunk
    title: str
    start: int
    end: int
    text: str | None  # chunks only
    parent: int | None  # index of the parent in the list, None at the top


def split(ex: Extracted, fallback_title: str = "") -> list[SectionDraft]:
    """The material's sections and chunks in reading order (a parent always comes before its children)."""
    pages = [p for p in ex.pages if p.text.strip()]
    if not pages:
        return []
    heads = sorted((h for h in ex.outline if h.level in (1, 2)), key=lambda h: (h.start, h.level))
    out: list[SectionDraft] = []
    if not heads:
        _chunks(out, pages, None, fallback_title, ex.loc_kind)
        return out
    # the pages before the first heading (a preface, a table of contents)
    first = heads[0].start
    before = [p for p in pages if p.start < first]
    if before:
        _chunks(out, before, None, fallback_title, ex.loc_kind)
    chapter: int | None = None
    for i, h in enumerate(heads):
        nxt = heads[i + 1].start if i + 1 < len(heads) else None
        own = [p for p in pages if p.start >= h.start and (nxt is None or p.start < nxt)]
        parent = None if h.level == 1 or chapter is None else chapter
        end = own[-1].end if own else h.start
        out.append(
            SectionDraft("chapter" if parent is None else "section", h.title, h.start, end, None, parent)
        )
        idx = len(out) - 1
        if parent is None:
            chapter = idx
        if own:
            _chunks(out, own, idx, h.title, ex.loc_kind)
    # a chapter's end is its last section's end
    for i, s in enumerate(out):
        if s.level == "chapter":
            ends = [c.end for c in out if c.parent == i]
            if ends and max(ends) > s.end:
                out[i] = SectionDraft(s.level, s.title, s.start, max(ends), None, s.parent)
    return out


def _chunks(out: list[SectionDraft], pages: list[Page], parent: int | None, title: str, kind: str) -> None:
    buf: list[Page] = []
    size = 0

    def flush() -> None:
        nonlocal size
        if buf:
            text = "\n\n".join(_labelled(p, kind) for p in buf)
            name = title or next((p.title for p in buf if p.title), "")
            out.append(SectionDraft("chunk", name, buf[0].start, buf[-1].end, text, parent))
        buf.clear()
        size = 0

    for p in pages:
        t = tokens(p.text)
        if t > MAX:  # one very long page or stretch: split it at paragraphs
            flush()
            for part in _paragraph_parts(p.text):
                buf.append(Page(p.start, p.end, part, p.title))
                size = tokens(part)
                flush()
            continue
        if (size and size + t > MAX) or size >= TARGET:
            flush()
        buf.append(p)
        size += t
    flush()


def _labelled(p: Page, kind: str) -> str:
    """Slides keep their number in the text, so a model can cite the slide; pages and times do not need it."""
    if kind == "slide":
        head = f"[Slide {p.start}" + (f": {p.title}]" if p.title else "]")
        return f"{head}\n{p.text}"
    return p.text


def _paragraph_parts(text: str) -> list[str]:
    parts: list[str] = []
    cur: list[str] = []
    size = 0
    for para in text.split("\n\n") if "\n\n" in text else text.split("\n"):
        t = tokens(para)
        if cur and size + t > TARGET:
            parts.append("\n\n".join(cur))
            cur, size = [], 0
        if t > MAX:  # a paragraph longer than a chunk: cut it at sentence ends
            for i in range(0, len(para), TARGET * 4):
                parts.append(para[i : i + TARGET * 4])
            continue
        cur.append(para)
        size += t
    if cur:
        parts.append("\n\n".join(cur))
    return parts


def batches(sizes: list[int], budget: int = 6000) -> list[list[int]]:
    """Indexes of chunks grouped so each group's tokens stay under the budget (a large chunk goes alone)."""
    out: list[list[int]] = []
    cur: list[int] = []
    total = 0
    for i, t in enumerate(sizes):
        if cur and total + t > budget:
            out.append(cur)
            cur, total = [], 0
        cur.append(i)
        total += t
    if cur:
        out.append(cur)
    return out


def locator(kind: str, start: int, end: int) -> str:
    """How a citation names the place: "p. 12", "pp. 12-15", "slides 3-7", "12:30-18:05"."""
    if kind == "time":
        return f"{_clock(start)}-{_clock(end)}"
    if kind == "slide":
        return f"slide {start}" if start == end else f"slides {start}-{end}"
    return f"p. {start}" if start == end else f"pp. {start}-{end}"


def _clock(ms: int) -> str:
    s = ms // 1000
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"
