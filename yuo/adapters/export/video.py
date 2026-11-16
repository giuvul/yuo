"""Lesson videos as plain files: `videos/<lesson code>.mp4` with its WebVTT subtitles and JPEG poster, from
each video rendition's current version. Bytes are copied as they are and checked against their hash."""

import hashlib
from typing import Any

from yuo.adapters.export._common import AssetFile, Files, Records, current, natural, represents, safe_name

ROLES = {"video": "mp4", "subtitles": "vtt", "poster": "jpg"}


def _renditions(records: Records) -> list[tuple[dict[str, Any], dict[str, str]]]:
    """(rendition, {extension: sha256}) for each video rendition whose assets are all present."""
    absent = {a.get("sha256") for a in records.get("asset", []) if a.get("present") is False}
    lessons = {x.get("code") for x in records.get("lesson", [])}
    out = []
    for r in sorted(records.get("rendition", []), key=lambda r: natural(r["code"])):
        v = current(r)
        if r.get("kind") != "video" or v is None or r.get("lesson") not in lessons:
            continue
        picked: dict[str, str] = {}
        uses = sorted(
            v.get("assets") or [], key=lambda a: (a.get("lang") != v.get("lang"), a.get("lang", ""))
        )
        for use in uses:
            ext = ROLES.get(use.get("role", ""))
            if ext and ext not in picked:
                picked[ext] = use["sha256"]
        if "mp4" in picked and not set(picked.values()) & absent:
            out.append((r, picked))
    return out


def export_video(records: Records, asset: AssetFile) -> Files:
    files: Files = {}
    for r, picked in _renditions(records):
        for ext, sha in sorted(picked.items()):
            data = asset(sha).read_bytes()
            if hashlib.sha256(data).hexdigest() != sha:
                raise ValueError(f"asset {sha} does not match its hash")
            files[safe_name(f"videos/{r['lesson']}.{ext}")] = data
    return files


def represents_video(records: Records) -> dict[str, Any]:
    return represents("rendition", [r["code"] for r, _ in _renditions(records)])
