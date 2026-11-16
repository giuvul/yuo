"""Updates (CFG B11): know about a new release, fetch it, and hand it to the desktop launcher.

The app only downloads and checks; installing happens outside the running process. On the desktop the
launcher installs the staged release beside the current one and starts it; the new version migrates the
database after a checked backup, and if it does not come up the launcher restores that backup and
runs the previous version again (packaging/desktop/launcher.py). Servers update by pulling the new image;
the app tells them which version is out.

No feed configured (`YUO_UPDATE_FEED`, set in release builds) means no checks at all.
"""

import json
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import structlog

from yuo.core.errors import InvalidInput

log = structlog.get_logger(__name__)

CHECK_EVERY_S = 24 * 3600
EXIT_FOR_UPDATE = 75  # the launcher's signal: install what is staged, then start again
_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


def parse_version(v: str) -> tuple[int, int, int] | None:
    m = _VERSION.match(v)
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def newer(candidate: str, current: str) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    return a is not None and (b is None or a > b)


class Updates:
    def __init__(
        self,
        root: Path,
        current: str,
        feed_url: str | None,
        *,
        fetch: Callable[[str], dict[str, Any]],
        download: Callable[[str, Path, str, int], Path],
        enabled: Callable[[], bool],
        desktop: bool,
        exit_process: Callable[[int], None],
    ) -> None:
        self.dir = root / "updates"
        self.cache = root / "cache" / "update-check.json"
        self.current = current
        self.feed_url = feed_url
        self._fetch = fetch
        self._download = download
        self._enabled = enabled
        self.desktop = desktop
        self._exit = exit_process
        self._lock = threading.Lock()

    def _cached(self) -> dict[str, Any] | None:
        try:
            data: dict[str, Any] = json.loads(self.cache.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return None
        return data

    def check(self, *, force: bool = False) -> dict[str, Any] | None:
        """The latest release from the feed, at most once a day unless forced; None without a feed."""
        if not self.feed_url or not (force or self._enabled()):
            return None
        cached = self._cached()
        if cached and not force and time.time() - cached.get("checked_at", 0) < CHECK_EVERY_S:
            return cached
        feed = self._fetch(self.feed_url)
        version = str(feed.get("version", ""))
        desktop = feed.get("desktop") or {}
        if parse_version(version) is None:
            raise InvalidInput("the release feed has no valid version")
        latest = {
            "version": version,
            "published_at": str(feed.get("published_at", ""))[:40],
            "notes_url": str(feed.get("notes_url", ""))[:500]
            if str(feed.get("notes_url", "")).startswith("https://")
            else None,
            "desktop": {k: desktop[k] for k in ("url", "sha256", "bytes")} if desktop else None,
            "checked_at": time.time(),
        }
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        self.cache.write_text(json.dumps(latest), encoding="utf-8")
        return latest

    def staged(self) -> dict[str, Any] | None:
        try:
            data: dict[str, Any] = json.loads((self.dir / "pending.json").read_text(encoding="utf-8"))
        except OSError, ValueError:
            return None
        return data if newer(str(data.get("version", "")), self.current) else None

    def status(self) -> dict[str, Any]:
        latest = self._cached() if self.feed_url else None
        available = latest is not None and newer(latest["version"], self.current)
        staged = self.staged()
        return {
            "current": self.current,
            "feed": self.feed_url is not None,
            "latest": latest["version"] if latest else None,
            "published_at": latest.get("published_at") if latest else None,
            "notes_url": latest.get("notes_url") if latest else None,
            "available": available,
            "staged": staged["version"] if staged else None,
            "can_install": self.desktop,  # servers update their container image instead
        }

    def stage(self) -> dict[str, Any]:
        """Download and check the latest desktop release; the launcher installs it on restart."""
        if not self.desktop:
            raise InvalidInput("this install updates by pulling the new container image")
        with self._lock:
            latest = self.check(force=True)
            if latest is None or not newer(latest["version"], self.current):
                raise InvalidInput("there is no newer release")
            d = latest.get("desktop") or {}
            if not (
                isinstance(d.get("sha256"), str)
                and _SHA.match(d["sha256"])
                and isinstance(d.get("bytes"), int)
            ):
                raise InvalidInput("the release feed lists no desktop download")
            self.dir.mkdir(parents=True, exist_ok=True)
            target = self.dir / f"yuo-{latest['version']}-desktop.zip"
            if not target.exists():
                self._download(str(d["url"]), target, d["sha256"], d["bytes"])
            pending = {"version": latest["version"], "file": target.name, "sha256": d["sha256"]}
            (self.dir / "pending.json").write_text(json.dumps(pending), encoding="utf-8")
            log.info("update.staged", version=latest["version"])
            return self.status()

    def restart(self) -> None:
        """Desktop only: leave with the code the launcher reads as 'install what is staged, start again'."""
        if not self.desktop or self.staged() is None:
            raise InvalidInput("nothing to install")
        log.info("update.restart", version=self.staged())
        self._exit(EXIT_FOR_UPDATE)
