"""Guards for choice questions against answering without knowing: models tend to make the right option the
longest and most detailed one, and to put it first. Every generated choice question is checked for the first
(the generator is asked to repair it) and its options are shuffled for the second."""

import hashlib
import random

LENGTH_RATIO = 1.2  # the right option may be at most this much longer than the longest wrong one...
LENGTH_SLACK = 8  # ...unless the difference is only a few characters

# for prompts: the rule the checks below enforce
LENGTH_RULE = (
    "Make the options similar in length, detail and style: the right one must not be the longest or the most "
    "precise, and the wrong ones must not be visibly shorter or vaguer. Learners must not be able to guess the "
    "answer from the shape of the options."
)


def longest_is_right(right: list[str], wrong: list[str]) -> bool:
    """The right option (on average, when several are right) is clearly longer than every wrong one."""
    if not right or not wrong:
        return False
    mean_right = sum(len(t.strip()) for t in right) / len(right)
    longest_wrong = max(len(t.strip()) for t in wrong)
    return mean_right > LENGTH_RATIO * longest_wrong and mean_right - longest_wrong > LENGTH_SLACK


def shuffled(options: list[str], answer: int, seed: str) -> tuple[list[str], int]:
    """The options in an order fixed by `seed`, and where the right one landed."""
    order = list(range(len(options)))
    random.Random(hashlib.sha256(seed.encode()).digest()).shuffle(order)  # noqa: S311 (an order, not a secret)
    return [options[i] for i in order], order.index(answer)
