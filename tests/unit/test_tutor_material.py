from typing import Any

from yuo.app.tutor import _material_excerpts


def section(text: str, start: int) -> dict[str, Any]:
    return {"text": text, "material": "Book.pdf", "loc_kind": "page", "loc_start": start, "loc_end": start}


def test_all_the_pages_go_in_when_they_fit() -> None:
    out = _material_excerpts([section("One.\n\nTwo.", 3), section("Three.", 4)], "", 1000)  # type: ignore[list-item]
    assert out == [
        {"where": "Book.pdf, p. 3", "text": "One.\n\nTwo."},
        {"where": "Book.pdf, p. 4", "text": "Three."},
    ]


def test_over_budget_the_paragraphs_nearest_the_question_stay_in_reading_order() -> None:
    filler = "Unrelated words about something else entirely. " * 4
    text = "\n\n".join(
        [filler, "The derivative measures instantaneous change.", filler, "Limits define continuity."]
    )
    out = _material_excerpts([section(text, 7)], "what is a derivative and a limit", 120)  # type: ignore[list-item]
    assert len(out) == 1
    assert (
        out[0]["text"] == "The derivative measures instantaneous change.\n\n[…]\n\nLimits define continuity."
    )
