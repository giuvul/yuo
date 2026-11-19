"""Small PDF, Word and PowerPoint files made in code, for the material readers' tests."""

import io
import textwrap
import zipfile
from xml.sax.saxutils import escape


def _pdf_text(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(
    pages: list[str],
    outline: list[tuple[str, int]] = (),  # type: ignore[assignment]
    shapes: dict[int, int] | None = None,
) -> bytes:
    """A PDF with one text page per entry (lines split on newlines), optional bookmarks (title, page index) and,
    per page index, a number of glyph-sized shapes (a formula drawn as shapes, not text)."""
    objs: list[str] = []
    n_pages = len(pages)
    # 1 catalog, 2 pages, 3 font, then per page: page, content; then outlines
    first_page = 4
    page_ids = [first_page + 2 * i for i in range(n_pages)]
    outline_root = first_page + 2 * n_pages
    catalog = "<< /Type /Catalog /Pages 2 0 R" + (f" /Outlines {outline_root} 0 R" if outline else "") + " >>"
    objs.append(catalog)
    objs.append(f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {n_pages} >>")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, text in enumerate(pages):
        lines = [w for line in text.split("\n") for w in textwrap.wrap(line, 90) or [""]]  # inside the page
        body = (
            "BT /F1 11 Tf 14 TL 50 760 Td " + " ".join(f"({_pdf_text(line)}) Tj T*" for line in lines) + " ET"
        )
        body += "".join(
            f" {50 + (k % 60) * 8} {100 + (k // 60) * 12} 6 8 re f" for k in range((shapes or {}).get(i, 0))
        )
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {page_ids[i] + 1} 0 R "
            "/Resources << /Font << /F1 3 0 R >> >> >>"
        )
        objs.append(f"<< /Length {len(body)} >>\nstream\n{body}\nendstream")
    if outline:
        items = [outline_root + 1 + k for k in range(len(outline))]
        objs.append(f"<< /Type /Outlines /First {items[0]} 0 R /Last {items[-1]} 0 R /Count {len(items)} >>")
        for k, (title, page) in enumerate(outline):
            prev = f" /Prev {items[k - 1]} 0 R" if k else ""
            nxt = f" /Next {items[k + 1]} 0 R" if k + 1 < len(items) else ""
            objs.append(
                f"<< /Title ({_pdf_text(title)}) /Parent {outline_root} 0 R{prev}{nxt} "
                f"/Dest [{page_ids[page]} 0 R /Fit] >>"
            )
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def make_docx(paragraphs: list[tuple[str, str]]) -> bytes:
    """(style, text) pairs: style "" for body text, "Heading1", "Heading2" or "Title"."""
    body = ""
    for style, text in paragraphs:
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        body += f"<w:p>{ppr}<w:r><w:t>{escape(text)}</w:t></w:r></w:p>"
    doc = f'<?xml version="1.0" encoding="UTF-8"?><w:document {W}><w:body>{body}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
P = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'


def make_pptx(slides: list[tuple[str, list[str]]], notes: dict[int, str] | None = None) -> bytes:
    """(title, bullet lines) per slide; notes by slide number from 1."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        for i, (title, lines) in enumerate(slides, 1):
            paras = "".join(f"<a:p><a:r><a:t>{escape(line)}</a:t></a:r></a:p>" for line in lines)
            xml = (
                f'<?xml version="1.0"?><p:sld {A} {P}><p:cSld><p:spTree>'
                f'<p:sp><p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr><p:txBody><a:p><a:r><a:t>{escape(title)}</a:t>'
                f"</a:r></a:p></p:txBody></p:sp><p:sp><p:txBody>{paras}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
            )
            z.writestr(f"ppt/slides/slide{i}.xml", xml)
        for i, text in (notes or {}).items():
            z.writestr(
                f"ppt/notesSlides/notesSlide{i}.xml",
                f'<?xml version="1.0"?><p:notes {A} {P}><a:p><a:r><a:t>{escape(text)}</a:t></a:r></a:p></p:notes>',
            )
    return buf.getvalue()
