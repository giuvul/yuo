from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from yuo.core import clock
from yuo.core.hashing import content_hash
from yuo.core.ids import is_uuid7, new_id
from yuo.core.logs import Metrics, redact
from yuo.core.money import Money


def test_ids_are_uuid7() -> None:
    a, b = new_id(), new_id()
    assert is_uuid7(a) and a < b


def test_timestamps_round_trip() -> None:
    at = datetime(2026, 10, 27, 15, 4, 5, 123456, tzinfo=UTC)
    assert clock.to_timestamp(at) == "2026-10-27T15:04:05.123Z"
    assert clock.parse_timestamp(clock.to_timestamp(at)) == at.replace(microsecond=123000)
    with pytest.raises(ValueError):
        clock.to_timestamp(datetime(2026, 1, 1))


@given(st.dictionaries(st.text(), st.integers(-(2**53) + 1, 2**53 - 1) | st.text()))
def test_content_hash_ignores_key_order(d: dict[str, int | str]) -> None:
    assert content_hash(d) == content_hash(dict(reversed(list(d.items()))))


def test_money_is_integer_micros() -> None:
    assert Money.of("0.09") + Money.of("0.38") == Money(470_000)
    with pytest.raises(ValueError):
        Money.of("1", "EUR") + Money.of("1")


def test_redaction_hides_secrets_and_free_text() -> None:
    out = redact(None, "info", {"event": "x", "prompt": "my goals", "note": "key sk-or-v1-abcdefghijklmnop"})
    assert out["prompt"] == "[redacted]" and "sk-or" not in out["note"]


def test_metrics_snapshot() -> None:
    m = Metrics()
    m.inc("jobs")
    m.observe("render", 1.5)
    assert m.snapshot() == {"counters": {"jobs": 1}, "timings": {"render": {"count": 1, "sum_s": 1.5}}}
