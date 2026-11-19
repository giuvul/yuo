"""PDF: the text of every page and the bookmarks, with pypdfium2 (PDFium); page images for a vision model."""

import re
import struct
import zlib
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from yuo.core.documents import Extracted, Heading, Page, ReadError

SPARSE_CHARS = 200  # a page with less text than this is probably formulas, figures or a scan
GLYPH_PT = 14  # a drawn shape smaller than this, both ways, is a glyph drawn as a shape (a formula's symbol)
SHAPE_SHARE = 0.15  # glyph shapes against the page's characters from which its formulas count as missing
GAPS = 3  # or this many gaps in the text where symbols were left out
# a gap: punctuation after a space ("given by . ", "( , )"), a list label alone on its line ("a."), commas
# with nothing between them
GAP = re.compile(r"(?:(?<=[^\W\d])|(?<=[,;:]))[ \t]+[.,;:)](?=\s|$)|^\s*[a-z]\.\s*$|(?:,\s*){2,}", re.M)


def read_pdf(path: Path) -> Extracted:
    try:
        doc = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as e:
        raise ReadError(f"the PDF cannot be opened: {e}") from e
    try:
        pages: list[Page] = []
        sparse: list[int] = []
        formulas: dict[int, float] = {}
        for n in range(len(doc)):
            page = doc[n]
            textpage = page.get_textpage()
            raw = textpage.get_text_bounded()
            text = _clean(raw)
            textpage.close()
            missing = 0.0 if len(text) < SPARSE_CHARS else formulas_missing(page, raw)
            page.close()
            pages.append(Page(n + 1, n + 1, text))
            if len(text) < SPARSE_CHARS:
                sparse.append(n + 1)
            elif missing:
                formulas[n + 1] = missing
        outline = []
        for item in doc.get_toc(max_depth=2):
            dest = item.get_dest()
            index = dest.get_index() if dest is not None else None
            title = (item.get_title() or "").strip()
            if index is not None and title:
                outline.append(Heading(title, item.level + 1, index + 1))
        meta = doc.get_metadata_dict()
        return Extracted(
            "page",
            pages,
            outline,
            title=(meta.get("Title") or "").strip(),
            count=len(pages),
            sparse=sparse,
            formulas=formulas,
        )
    finally:
        doc.close()


def formulas_missing(page: pdfium.PdfPage, text: str) -> float:
    """How much of a page's formulas the text lacks, from 0 (nothing, or not enough to matter) to 1: glyphs
    drawn as shapes instead of text, or gaps in the text where symbols were left out."""
    shapes = 0
    for obj in page.get_objects(max_depth=4):
        if obj.type == pdfium_c.FPDF_PAGEOBJ_PATH:
            left, bottom, right, top = obj.get_bounds()
            if right - left < GLYPH_PT and top - bottom < GLYPH_PT:
                shapes += 1
    share = shapes / (shapes + len(text) + 1)
    gaps = len(GAP.findall(text))
    if share < SHAPE_SHARE and gaps < GAPS:
        return 0.0
    return round(min(1.0, share + 0.05 * gaps), 3)


def page_images(path: Path, pages: list[int], out_dir: Path, scale: float = 1.6) -> list[Path]:
    """Grayscale PNGs of the given pages (1-based), for a model to read formulas and figures from."""
    doc = pdfium.PdfDocument(str(path))
    out: list[Path] = []
    try:
        for n in pages:
            page = doc[n - 1]
            bitmap = page.render(scale=scale, grayscale=True)
            target = out_dir / f"page-{n}.png"
            target.write_bytes(_png(bytes(bitmap.buffer), bitmap.width, bitmap.height, bitmap.stride))
            bitmap.close()
            page.close()
            out.append(target)
    finally:
        doc.close()
    return out


def _png(gray: bytes, width: int, height: int, stride: int) -> bytes:
    """A grayscale PNG from 8-bit rows (no image library needed)."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = b"".join(b"\x00" + gray[y * stride : y * stride + width] for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows, 6))
        + chunk(b"IEND", b"")
    )


def _clean(text: str) -> str:
    # PDFium marks soft line ends with \r\n; hyphenated line breaks are joined
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    out: list[str] = []
    for line in lines:
        if out and out[-1].endswith("-") and line[:1].islower():
            out[-1] = out[-1][:-1] + line
        else:
            out.append(line)
    return "\n".join(out).strip()
