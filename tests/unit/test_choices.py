"""Choice questions: the right option may not stand out by its length, and stored options are shuffled."""

from collections import Counter

from yuo.core.choices import longest_is_right, shuffled


def test_a_right_option_clearly_the_longest_is_caught() -> None:
    wrong = ["A database", "A search engine", "A spreadsheet"]
    assert longest_is_right(["A model trained to predict the next token from huge amounts of text"], wrong)
    assert not longest_is_right(["A text predictor"], wrong)  # a few characters longer is fine
    assert not longest_is_right(["Short"], ["A much longer wrong option here"])


def test_several_right_options_count_on_average() -> None:
    assert longest_is_right(["a long right option, detailed", "another long right option"], ["no", "nope"])
    assert not longest_is_right(["a long right option, detailed", "ok"], ["a wrong one that is long too"])


def test_shuffling_is_fixed_by_the_seed_and_moves_the_answer() -> None:
    options = ["right", "w1", "w2", "w3"]
    assert shuffled(options, 0, "p:1") == shuffled(options, 0, "p:1")
    landed: Counter[int] = Counter()
    for n in range(200):
        out, answer = shuffled(options, 0, f"p:{n}")
        assert out[answer] == "right" and sorted(out) == sorted(options)
        landed[answer] += 1
    assert set(landed) == {0, 1, 2, 3} and min(landed.values()) > 25  # every position, roughly evenly
