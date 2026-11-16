"""Time: UTC instants as `YYYY-MM-DDTHH:MM:SS.sssZ`, written by Python only."""

from collections.abc import Callable
from datetime import UTC, datetime


def to_timestamp(at: datetime) -> str:
    if at.tzinfo is None:
        raise ValueError("naive datetime: pass an aware UTC instant")
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{at.microsecond // 1000:03d}Z"


_source: Callable[[], datetime] | None = None


def set_source(source: Callable[[], datetime] | None) -> None:
    """Tests and simulations only: replace the wall clock (None restores it)."""
    global _source
    _source = source


def now() -> str:
    return to_timestamp(_source() if _source else datetime.now(UTC))


def parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
