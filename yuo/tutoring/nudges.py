"""Proactive nudges: when the tutor may speak first, and how often.

Nudges appear only at breakpoints (after an answer is graded, a lesson is finished, a test is
submitted), never during a test or a video. Each says why it appeared. Two dismissals of the same
trigger mute it for the day; "Don't suggest this" mutes it for good (a learner setting).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

TRIGGERS = ("repeated_error", "fast_guessing", "unsent_notes", "failed_test")
SESSION_GAP = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class Caps:
    every: timedelta
    per_session: int


LEVELS: dict[str, Caps | None] = {
    "off": None,
    "quiet": Caps(timedelta(minutes=10), 3),  # shown as a dot, never opens the tutor
    "coach": Caps(timedelta(minutes=10), 3),
    "active": Caps(timedelta(minutes=3), 6),
}


@dataclass(frozen=True, slots=True)
class Past:
    trigger: str
    status: str
    at: datetime


def may_nudge(
    level: str,
    trigger: str,
    *,
    now: datetime,
    session_start: datetime,
    past: list[Past],
    muted: list[str],
) -> bool:
    caps = LEVELS.get(level)
    if caps is None or trigger in muted:
        return False
    in_session = [p for p in past if p.at >= session_start]
    if len(in_session) >= caps.per_session:
        return False
    if any(now - p.at < caps.every for p in past):
        return False
    today = now.date()
    dismissed = sum(
        1 for p in past if p.trigger == trigger and p.status == "dismissed" and p.at.date() == today
    )
    if dismissed >= 2:
        return False
    # the same trigger once per session at most: a second offer for the same thing is nagging
    return not any(p.trigger == trigger for p in in_session)


def session_start(activity: list[datetime], now: datetime) -> datetime:
    """Start of the current session: the latest activity after a gap of 30 minutes or more."""
    start = now
    for at in sorted(activity, reverse=True):
        if start - at >= SESSION_GAP:
            break
        start = at
    return start
