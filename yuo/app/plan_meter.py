"""The subscription plan meter: the last reading each CLI reported of the account's 5-hour window and
week, kept in `cache/plan-meter.json` so it survives a restart. It covers the whole account, other devices
included, so it says how much is left, not what Yuo used."""

import json
import threading
from pathlib import Path
from typing import Any

from yuo.core import clock

CLIS = ("claude", "codex")


class PlanMeter:
    def __init__(self, file: Path) -> None:
        self.file = file
        self._lock = threading.Lock()
        try:
            self._last: dict[str, dict[str, Any]] = json.loads(file.read_text(encoding="utf-8"))
        except OSError, ValueError:
            self._last = {}

    def record(self, cli: str, meter: dict[str, Any]) -> None:
        with self._lock:
            self._last[cli] = meter | {"observed_at": clock.now()}
            self.file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._last), encoding="utf-8")
            tmp.replace(self.file)

    def reporter(self, cli: str) -> Any:
        """The `on_meter` callback for one CLI adapter."""
        return lambda meter: self.record(cli, meter)

    def snapshot(self) -> dict[str, dict[str, Any] | None]:
        with self._lock:
            return {cli: self._last.get(cli) for cli in CLIS}
