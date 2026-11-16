"""Component exports in standard formats (path-package spec §9).

Each exporter is a pure function of the package records: `export(records, asset) -> {file name: bytes}`,
where `asset(sha256)` gives the file of an asset. Same records, same bytes, so a package that carries
these files under `standard/` stays byte-identical across exports. `represents` gives the spec §9 mapping
of what a format's files stand for; the records stay authoritative.
"""

from collections.abc import Callable
from typing import Any

from yuo.adapters.export import anki, bibtex, csljson, csvfile, moodle, readings, video
from yuo.adapters.export._common import AssetFile, Files, Records

type Exporter = Callable[[Records, AssetFile], Files]

FORMATS: dict[str, Exporter] = {
    "csv": csvfile.export_csv,
    "anki-apkg": anki.export_anki,
    "moodle-xml": moodle.export_moodle,
    "readings": readings.export_readings,
    "mp4-webvtt": video.export_video,
    "bibtex": bibtex.export_bibtex,
    "csl-json": csljson.export_csljson,
}
_REPRESENTS: dict[str, Callable[[Records], dict[str, Any]]] = {
    "csv": csvfile.represents_csv,
    "anki-apkg": anki.represents_anki,
    "moodle-xml": moodle.represents_moodle,
    "readings": readings.represents_readings,
    "mp4-webvtt": video.represents_video,
    "bibtex": bibtex.represents_bibtex,
    "csl-json": csljson.represents_csljson,
}


def represents(fmt: str, records: Records) -> dict[str, Any]:
    """`{"kind": ..., "codes": [...]}`: the records a format's files stand for (spec §9)."""
    if fmt not in _REPRESENTS:
        raise ValueError(f"unknown export format {fmt!r}")
    return _REPRESENTS[fmt](records)


__all__ = ["FORMATS", "AssetFile", "Exporter", "Files", "Records", "represents"]
