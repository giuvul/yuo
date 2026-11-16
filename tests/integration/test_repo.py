"""The path's own state in `extensions.yuo`."""

from pathlib import Path

import pytest

from tests import fakes
from tests.integration.test_slice import NoPrices
from yuo.app.forms import PathForm
from yuo.app.repo import drop_path_state, find_path, get_path, path_state, save_path_state
from yuo.core.errors import NotFound
from yuo.core.ids import new_id
from yuo.main import start


def test_path_state_round_trip(db_path: Path) -> None:
    rt = start(db_path, {"openrouter": fakes.FakeLLM()}, NoPrices(), worker=False)
    try:
        rt.service.apply_preset("open")
        path_id, _ = rt.service.create_path(PathForm(title="SQL", subject="SQL", goal="joins"))
        with rt.service.readers.connection() as c:
            assert find_path(c, new_id()) is None
            with pytest.raises(NotFound):
                get_path(c, new_id())
            before = get_path(c, path_id)
        assert path_state(before, "next") is None and path_state(None, "next") is None

        rt.service.writer.run(lambda c: save_path_state(c, path_id, "next", {"status": "ready"}))
        rt.service.writer.run(lambda c: save_path_state(c, path_id, "level_check", {"status": "done"}))
        with rt.service.readers.connection() as c:
            p = get_path(c, path_id)
        assert path_state(p, "next") == {"status": "ready"} and path_state(p, "level_check") == {
            "status": "done"
        }
        assert p["updated_at"] == before["updated_at"]  # not touched unless asked

        rt.service.writer.run(lambda c: save_path_state(c, path_id, "next", {"status": "done"}, touch=True))
        rt.service.writer.run(lambda c: drop_path_state(c, path_id, "level_check"))
        with rt.service.readers.connection() as c:
            p = get_path(c, path_id)
        assert path_state(p, "next") == {"status": "done"} and path_state(p, "level_check") is None
        assert p["updated_at"] >= before["updated_at"]
    finally:
        rt.close()
