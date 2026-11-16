"""FSRS scheduler adapter: the review state is the fsrs card as JSON. Fuzzing is off so a
rebuild from events reproduces the same due dates (projections are deterministic)."""

import json
from datetime import datetime
from typing import Any, cast

from fsrs import Card, Rating, Scheduler
from fsrs.card import CardDict

NAME = "fsrs-6"


class FsrsScheduler:
    name = NAME

    def __init__(
        self, desired_retention: float = 0.9, max_interval_days: int = 0, *, day_scale: bool = False
    ) -> None:
        extra: dict[str, Any] = {"learning_steps": (), "relearning_steps": ()} if day_scale else {}
        self._s = Scheduler(
            desired_retention=desired_retention,
            enable_fuzzing=False,
            maximum_interval=max_interval_days or 36500,
            **extra,
        )

    def tuned(self, desired_retention: float, max_interval_days: int) -> FsrsScheduler:
        """The scheduler for objective-level review with the learner's settings. No minute-scale
        learning steps: an objective is reviewed in sessions days apart, so every interval is in days."""
        return FsrsScheduler(desired_retention, max_interval_days, day_scale=True)

    def review(
        self, state: dict[str, Any] | None, rating: int, at: datetime
    ) -> tuple[dict[str, Any], datetime]:
        card = Card.from_dict(cast(CardDict, state)) if state else Card(card_id=1)
        card, _ = self._s.review_card(card, Rating(rating), at)
        out: dict[str, Any] = json.loads(json.dumps(card.to_dict()))
        return out, card.due

    def retrievability(self, state: dict[str, Any], at: datetime) -> float:
        return float(self._s.get_card_retrievability(Card.from_dict(cast(CardDict, state)), at))
