"""The service is a facade over feature parts: callers keep one object."""

import re
from pathlib import Path

from tests import fakes
from tests.integration.test_slice import NoPrices
from yuo.app.context import Part
from yuo.main import start


def _public(part: Part) -> set[str]:
    return {n for n in dir(type(part)) if not n.startswith("_") and n not in dir(Part)}


def test_every_name_the_api_calls_resolves_on_the_service(db_path: Path) -> None:
    rt = start(db_path, {"openrouter": fakes.FakeLLM()}, NoPrices(), worker=False)
    try:
        api = Path(__file__).parents[2] / "yuo" / "api"
        called = {m for f in api.rglob("*.py") for m in re.findall(r"\bsvc\.([a-z_]+)", f.read_text())}
        assert len(called) > 50
        missing = sorted(n for n in called if not hasattr(rt.service, n))
        assert missing == []
    finally:
        rt.close()


def test_no_two_parts_answer_to_the_same_name(db_path: Path) -> None:
    rt = start(db_path, {"openrouter": fakes.FakeLLM()}, NoPrices(), worker=False)
    try:
        seen: dict[str, str] = {}
        own = {n for n in vars(type(rt.service)) if not n.startswith("_")}
        for part in rt.service._parts:
            for name in _public(part):
                assert name not in seen, f"{name} is on {seen[name]} and {type(part).__name__}"
                assert name not in own, f"{name} on the service hides {type(part).__name__}.{name}"
                seen[name] = type(part).__name__
        # a port set after construction (as yuo.main does) reaches every part
        marker = object()
        rt.service.access = marker
        assert all(p.access is marker for p in rt.service._parts)
    finally:
        rt.close()
