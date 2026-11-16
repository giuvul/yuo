"""The release feed: a small JSON file per channel, and the desktop zip it points at.

Feed shape (published with each release, see packaging/desktop/README.md):

    {"version": "1.0.1", "published_at": "2026-11-20T10:00:00Z", "notes_url": "https://...",
     "desktop": {"url": "https://.../yuo-1.0.1-desktop.zip", "sha256": "<64 hex>", "bytes": 123}}

Only https, no redirects to http; the download is checked against the feed's hash and size while it streams.
Signatures (Sigstore) are not checked yet; the hash proves the file is the one the feed names.
"""

import hashlib
from pathlib import Path
from typing import Any

import httpx

from yuo.core.errors import YuoError

MAX_FEED = 64 * 1024


class FeedError(YuoError):
    pass


def _https(url: str) -> str:
    if not url.startswith("https://"):
        raise FeedError(f"release URLs must use https: {url[:80]}")
    return url


def fetch(url: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    http = client or httpx.Client(timeout=15, follow_redirects=True)
    try:
        r = http.get(_https(url), headers={"Accept": "application/json"})
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise FeedError(f"cannot read the release feed ({type(e).__name__})") from e
    if len(r.content) > MAX_FEED or not str(r.url).startswith("https://"):
        raise FeedError("the release feed is not what Yuo expects")
    data: dict[str, Any] = r.json()
    return data


def download(url: str, target: Path, sha256: str, size: int, *, client: httpx.Client | None = None) -> Path:
    """Streams to `<target>.part`, checks size and hash, then renames; a mismatch leaves nothing behind."""
    http = client or httpx.Client(timeout=60, follow_redirects=True)
    part = target.with_name(target.name + ".part")
    digest, got = hashlib.sha256(), 0
    try:
        with http.stream("GET", _https(url)) as r, part.open("wb") as out:
            r.raise_for_status()
            if not str(r.url).startswith("https://"):
                raise FeedError("the download was redirected away from https")
            for chunk in r.iter_bytes(1 << 16):
                got += len(chunk)
                if got > size:
                    raise FeedError("the download is larger than the release feed says")
                digest.update(chunk)
                out.write(chunk)
        if got != size or digest.hexdigest() != sha256:
            raise FeedError("the download does not match the release feed (size or SHA-256)")
    except httpx.HTTPError as e:
        part.unlink(missing_ok=True)
        raise FeedError(f"the download failed ({type(e).__name__})") from e
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    part.replace(target)
    return target
