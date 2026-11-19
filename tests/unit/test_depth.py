from yuo.curriculum.depth import TREE_SIZES, MaterialAmount, depth_of, material_lessons


def _m(
    role: str, kind: str, pages: int | None = None, minutes: int | None = None, tokens: int = 0
) -> MaterialAmount:
    return MaterialAmount(role, kind, pages, minutes * 60_000 if minutes else None, tokens)


def test_one_lecture_is_a_lesson_or_two_and_a_book_is_dozens() -> None:
    assert material_lessons([_m("lecture", "audio", minutes=45)], "standard") == (2, 3)
    low, high = material_lessons([_m("textbook", "pdf", pages=400)], "standard")
    assert 25 <= low < high <= 60


def test_slides_and_recordings_of_the_same_lectures_are_not_counted_twice() -> None:
    both = material_lessons(
        [_m("lecture", "audio", minutes=12 * 90), _m("slides", "pptx", pages=12 * 40)], "standard"
    )
    alone = material_lessons([_m("lecture", "audio", minutes=12 * 90)], "standard")
    assert alone[0] <= both[0] <= alone[0] * 1.3


def test_depth_scales_the_material_and_exercises_add_nothing() -> None:
    book = [_m("textbook", "pdf", pages=200), _m("exams", "pdf", pages=50)]
    short, standard, deep = (material_lessons(book, d) for d in ("short", "standard", "deep"))
    assert short[1] < standard[1] < deep[1]
    assert material_lessons([_m("exams", "pdf", pages=80)], "standard") == (1, 2)


def test_tree_sizes_grow_with_depth() -> None:
    assert (
        TREE_SIZES["short"].max_lessons < TREE_SIZES["standard"].lessons[0] <= TREE_SIZES["deep"].lessons[0]
    )
    assert depth_of("deep") == "deep" and depth_of(None) == "standard" and depth_of("huge") == "standard"
