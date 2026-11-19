from yuo.material.align import align, paragraphs, slides_at, slides_of

SLIDES = [
    "[Slide 1: Limits]\nLimits describe approaching values epsilon delta definition\n\n"
    "[Slide 2: Continuity]\nContinuous functions have no jumps, intermediate value theorem",
    "[Slide 3: Derivatives]\nDerivative as slope of tangent, difference quotient\n\n"
    "[Slide 4: Chain rule]\nChain rule composite functions inner outer derivative",
]


def test_a_lecture_follows_its_slides_in_order() -> None:
    slides = slides_of(SLIDES)
    assert sorted(slides) == [1, 2, 3, 4]
    talk = paragraphs(
        [
            (0, 600_000, "Today limits: approaching values, with the epsilon delta definition.\n\n"
             "Continuous functions have no jumps; the intermediate value theorem follows."),
            (600_000, 1_200_000, "A short break, questions from the room about the exam date and logistics.\n\n"
             "The derivative is the slope of the tangent: the difference quotient.\n\n"
             "For composite functions the chain rule: outer derivative times inner derivative."),
        ]
    )  # fmt: skip
    runs = align(talk, slides)
    assert [r[2] for r in runs] == [1, 2, 3, 4]  # the aside about the exam matches no slide
    assert runs[0][0] == 0 and runs[-1][1] == 1_200_000
    assert slides_at(runs, 700_000, 1_200_000) == (3, 4)
    assert slides_at(runs, 0, 100_000) == (1, 1)
    assert align([], slides) == [] and align(talk, {}) == []
