"""Reading the learner's files and splitting them into chunks."""

from pathlib import Path

import pytest

from tests.material_files import make_docx, make_pdf, make_pptx
from yuo.adapters.ingest import kind_of, read_document
from yuo.core.documents import Extracted, Heading, Page, ReadError
from yuo.material import chunks as ch


def test_a_pdf_gives_its_pages_and_bookmarks(tmp_path: Path) -> None:
    f = tmp_path / "book.pdf"
    f.write_bytes(
        make_pdf(
            [
                "Contents\nChapter 1 Limits",
                "Limits\nA limit describes the value a function approaches.",
                "Derivatives\nThe derivative is the slope.",
            ],
            outline=[("1 Limits", 1), ("2 Derivatives", 2)],
        )
    )
    ex = read_document(f, "pdf")
    assert ex.loc_kind == "page" and ex.count == 3
    assert "value a function approaches" in ex.pages[1].text
    assert [(h.title, h.start) for h in ex.outline] == [("1 Limits", 2), ("2 Derivatives", 3)]
    assert ex.sparse == [1, 2, 3]  # short pages: little text


def test_pages_missing_their_formulas_are_found(tmp_path: Path) -> None:
    prose = "The derivative measures how fast a quantity changes over time. " * 6
    f = tmp_path / "calculus.pdf"
    f.write_bytes(
        make_pdf(
            [
                prose,  # all text
                prose,  # its formulas drawn as shapes
                prose + "\nThe position is given by . The speed at is , and the rate is .\na.\nb. , , ,",
                prose + "\nIn the expression ( , ) the first value is the time.",  # one gap is not enough
            ],
            shapes={1: 200},
        )
    )
    ex = read_document(f, "pdf")
    assert sorted(ex.formulas) == [2, 3] and ex.sparse == []
    assert 0 < ex.formulas[3] <= 1 and ex.formulas[2] > 0.15


def test_the_pages_read_from_images_are_capped_most_missing_first() -> None:
    from yuo.app.material import VISION_MAX_PAGES, vision_pages

    formulas = {str(p): (0.9 if p % 2 else 0.2) for p in range(1, 2 * VISION_MAX_PAGES)}
    pages = vision_pages({"sparse": [4000, 4001], "formulas": formulas})
    assert len(pages) == VISION_MAX_PAGES and pages == sorted(pages)
    assert {4000, 4001} <= set(pages) and all(p % 2 for p in pages if p < 4000)  # the most missing first


def test_a_damaged_pdf_is_a_read_error(tmp_path: Path) -> None:
    f = tmp_path / "bad.pdf"
    f.write_bytes(b"%PDF-1.4 not really")
    with pytest.raises(ReadError):
        read_document(f, "pdf")


def test_word_headings_start_sections(tmp_path: Path) -> None:
    f = tmp_path / "notes.docx"
    f.write_bytes(
        make_docx(
            [
                ("Title", "Analysis notes"),
                ("Heading1", "Limits"),
                ("", "Epsilon and delta."),
                ("Heading1", "Series"),
                ("", "Geometric series converge when |q| < 1."),
            ]
        )
    )
    ex = read_document(f, "docx")
    assert ex.title == "Analysis notes"
    assert [h.title for h in ex.outline] == ["Limits", "Series"]
    assert "Geometric series" in ex.pages[-1].text


def test_slides_keep_their_titles_and_notes(tmp_path: Path) -> None:
    f = tmp_path / "week1.pptx"
    f.write_bytes(
        make_pptx(
            [("Newton's laws", ["F = m a", "Inertia"]), ("Momentum", ["p = m v"])],
            notes={2: "Say why it is conserved"},
        )
    )
    ex = read_document(f, "pptx")
    assert ex.loc_kind == "slide" and ex.count == 2
    assert ex.pages[0].title == "Newton's laws"
    assert "Notes: Say why it is conserved" in ex.pages[1].text


def test_file_kinds() -> None:
    assert kind_of("Lezione 3.MP4") == "video"
    assert kind_of("libro.pdf") == "pdf"
    assert kind_of("photo.heic") is None


def test_chunks_follow_chapters_and_never_cross_them() -> None:
    pages = [Page(n, n, f"page {n} " + "word " * 600) for n in range(1, 11)]
    ex = Extracted(
        "page", pages, [Heading("One", 1, 1), Heading("One.A", 2, 3), Heading("Two", 1, 6)], count=10
    )
    out = ch.split(ex)
    chapters = [s for s in out if s.level == "chapter"]
    assert [c.title for c in chapters] == ["One", "Two"]
    chunks = [s for s in out if s.level == "chunk"]
    assert all(c.parent is not None for c in chunks)
    for c in chunks:
        parent = out[c.parent]  # type: ignore[index]
        assert parent.start <= c.start and c.end <= max(parent.end, c.end)
    # no chunk spans pages 5 and 6 (the chapter boundary)
    assert not any(c.start <= 5 < c.end for c in chunks)
    assert all(ch.tokens(c.text or "") <= ch.MAX for c in chunks)
    assert out[0].level == "chapter" and out[0].end == 5


def test_a_transcript_is_split_into_minutes() -> None:
    pages = [Page(i * 60_000, (i + 1) * 60_000, "word " * 160) for i in range(30)]
    out = ch.split(Extracted("time", pages, [], count=30 * 60_000))
    assert all(s.level == "chunk" for s in out)
    assert out[0].start == 0 and out[-1].end == 30 * 60_000
    assert ch.locator("time", out[1].start, out[1].end).count(":") == 2


def test_batches_and_locators() -> None:
    assert ch.batches([3000, 3000, 3000, 7000, 100]) == [[0, 1], [2], [3], [4]]
    assert ch.locator("page", 12, 15) == "pp. 12-15"
    assert ch.locator("slide", 3, 3) == "slide 3"
    assert ch.locator("time", 750_000, 1_085_000) == "12:30-18:05"
