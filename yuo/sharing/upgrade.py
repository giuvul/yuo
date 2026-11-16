"""Format upgraders (spec §11): pure JSON-to-JSON steps from an older format to the current one.

A newer minor version is read as it is (what it adds is kept and written back); a newer major is refused.
"""

from collections.abc import Callable
from typing import Any

from yuo.sharing.records import FORMAT_VERSION

Records = dict[str, list[dict[str, Any]]]
Step = Callable[[dict[str, Any], Records], tuple[dict[str, Any], Records]]


class UpgradeError(Exception):
    pass


def _v0_1_to_1_0(manifest: dict[str, Any], records: Records) -> tuple[dict[str, Any], Records]:
    """0.1 (the draft) carried scene specs (declarative or agent code). 1.0 carries rendered media only, so
    those rendition versions are dropped (the lesson's reading stays), and renditions left empty go too."""
    renditions = []
    for r in records.get("rendition", []):
        versions = [v for v in r.get("versions", []) if v.get("spec_kind") == "rendered"]
        if versions:
            current = r.get("current") if r.get("current") in {v["version_hash"] for v in versions} else None
            renditions.append(r | {"versions": versions, "current": current or versions[-1]["version_hash"]})
    out = dict(records)
    if "rendition" in records:
        out["rendition"] = renditions
    return manifest | {"format_version": "1.0.0"}, out


STEPS: dict[int, tuple[str, Step]] = {0: ("1.0.0", _v0_1_to_1_0)}  # from major -> (to version, step)


def _major(version: str) -> int:
    try:
        return int(str(version).split(".")[0])
    except ValueError:
        raise UpgradeError(f"format_version {version!r} is not a version") from None


def upgrade(manifest: dict[str, Any], records: Records) -> tuple[dict[str, Any], Records, str | None]:
    """Bring a package to the current major. Returns (manifest, records, the version it came from or None)."""
    from yuo.sharing.package import PackageError

    start = str(manifest.get("format_version", ""))
    try:
        major, current = _major(start), _major(FORMAT_VERSION)
    except UpgradeError as e:
        raise PackageError(str(e)) from None
    if major > current:
        raise PackageError(
            f"this package uses format {start}, newer than this Yuo ({FORMAT_VERSION}): update Yuo to import it"
        )
    if major == current:
        return manifest, records, None
    while major < current:
        if major not in STEPS:
            raise PackageError(f"no upgrade from format {manifest['format_version']}")
        _, step = STEPS[major]
        manifest, records = step(manifest, records)
        major = _major(manifest["format_version"])
    return manifest, records, start
