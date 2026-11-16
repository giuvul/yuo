"""Content-addressed asset store on disk: `<root>/<hash[:2]>/<hash>`."""

import os
from pathlib import Path

from yuo.core.hashing import bytes_hash


class BlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def path(self, digest: str) -> Path:
        return self.root / digest[:2] / digest

    def put(self, data: bytes) -> str:
        digest = bytes_hash(data)
        target = self.path(digest)
        if not target.exists():
            target.parent.mkdir(exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(target)
        return digest

    def delete(self, digest: str) -> bool:
        """Overwrite, then unlink: erased bytes should not linger in the file's old blocks."""
        target = self.path(digest)
        if not target.exists():
            return False
        size = target.stat().st_size
        with target.open("r+b") as f:
            f.write(b"\0" * size)
            f.flush()
            os.fsync(f.fileno())
        target.unlink()
        return True
