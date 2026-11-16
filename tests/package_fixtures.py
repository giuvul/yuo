"""Conformance fixtures for the path package format (spec §14): valid and invalid packages, made reproducibly.

The base is a path made on the scripted model (lessons, six exercise types), plus a source and a small video
added by hand, exported and frozen with a fixed identity and time. Each invalid package breaks one rule the
spec makes, so a reader that accepts it has a hole. `uv run scripts/gen_package_fixtures.py` writes them to
`docs/spec/fixtures/`; a test checks the committed files are what this module makes.
"""

import copy
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from yuo.core.hashing import content_hash
from yuo.sharing import package as pk

UID = "pkg_aaaaaaaaaaaaaaaaaaaaaaaaaa"
AT = "2026-10-29T00:00:00Z"
MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64
VTT = b"WEBVTT\n\n00:00.000 --> 00:02.000\nHello there.\n"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60 + b"\xff\xd9"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'

# name -> the reason a reader must give (a substring of the PackageError message), None for valid ones
EXPECT: dict[str, str | None] = {
    "valid/minimal": None,
    "valid/structure": None,
    "valid/full": None,
    "valid/custom-items-only": None,
    "valid/older-version": None,
    "valid/unknown-extension": None,
    "valid/unknown-exercise-type": None,
    "invalid/path-traversal": "bad file name",
    "invalid/zip-bomb": "compression ratio",
    "invalid/hash-mismatch": "hash differs",
    "invalid/not-listed": "inventory mismatch",
    "invalid/version-hash": "version hash does not match",
    "invalid/svg-with-script": "not allowed",
    "invalid/media-sniff": "its bytes are not",
    "invalid/html-in-body": "unknown block",
    "invalid/link-in-text": "text with marks only",
    "invalid/dag-cycle": "prerequisite cycle",
    "invalid/newer-major": "newer than this Yuo",
    "invalid/manifest-not-first": "first entry",
}


def base_records() -> dict[str, list[dict[str, Any]]]:
    """The scripted path's records, plus a source and a video (deterministic)."""
    from tests import fakes
    from tests.integration.test_slice import NoPrices, create
    from yuo.db.migrate import migrate
    from yuo.main import start

    saved = fakes._count["n"]
    fakes._count["n"] = 0  # the scripted items number themselves per process: start as a fresh process does
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "yuo.db"
        migrate(db, "fixtures")
        rt = start(db, {"openrouter": fakes.FakeLLM()}, NoPrices(), worker=False)
        try:
            for role in ("generator", "reviewer", "grader", "utility"):
                rt.service.bind(role, "openrouter", "deepseek/deepseek-v4-pro")
            path_id = create(rt)
            rt.service.export_package(path_id, Path(d) / "p.zip", profile="full")
            records = pk.read(Path(d) / "p.zip").records
        finally:
            rt.close()
            fakes._count["n"] = saved
    records["path"][0]["code"] = "sql-for-analysts"  # the app's own code comes from a random id
    lesson = records["lesson"][0]
    lv = lesson["versions"][0]
    lv["sources"] = [{"key": "sqlite-docs-select", "locator": "section 2"}]
    lv["version_hash"] = pk.lesson_hash(lv)
    lesson["current"] = lv["version_hash"]
    records["source"] = [{
        "key": "sqlite-docs-select", "kind": "web", "title": "SELECT", "url": "https://sqlite.org/lang_select.html",
        "citation": {"type": "webpage", "title": "SELECT", "URL": "https://sqlite.org/lang_select.html"},
    }]  # fmt: skip
    media = {
        "video": (MP4, "video/mp4", "video"),
        "subtitles": (VTT, "text/vtt", "subtitles"),
        "poster": (JPEG, "image/jpeg", "image"),
    }
    uses = [
        {"role": role, "lang": "en", "recipe_hash": content_hash({"role": role}), "sha256": hashlib.sha256(data).hexdigest()}
        for role, (data, _, _) in sorted(media.items())
    ]  # fmt: skip
    rv: dict[str, Any] = {
        "version_no": 1, "lang": "en", "lesson_version_hash": lv["version_hash"], "renderer": "remotion",
        "spec_kind": "rendered", "voice": "kokoro:af_heart", "duration_s": 2.0, "assets": uses,
        "narration": {"segments": [{"text": "Hello there.", "start": 0, "end": 60}]},
        "provenance": {"authorship": "generated", "author_kind": "system"},
    }  # fmt: skip
    rv["version_hash"] = pk.rendition_hash("video", rv)
    records["rendition"] = [{"code": f"{lesson['code']}.video", "lesson": lesson["code"], "kind": "video",
                             "current": rv["version_hash"], "versions": [rv]}]  # fmt: skip
    records["asset"] = [
        {
            "sha256": hashlib.sha256(data).hexdigest(),
            "media_type": mt,
            "kind": kind,
            "bytes": len(data),
            "present": True,
        }
        for data, mt, kind in media.values()
    ]
    return records


def _manifest(profile: str, records: dict[str, list[dict[str, Any]]], **extra: Any) -> dict[str, Any]:
    contents = []
    if records.get("path"):
        contents.append("curriculum")
    if records.get("lesson"):
        contents.append("lessons")
    if records.get("rendition"):
        contents.append("renditions.video")
    if records.get("item"):
        contents.append("items")
    if records.get("source"):
        contents.append("sources")
    if records.get("asset"):
        contents.append("assets")
    return {
        "format": "yuo.package", "format_version": "1.0.0", "package_uid": UID, "content_version": "1.0.0",
        "profile": profile, "contents": contents, "title": "SQL", "content_lang": "en", "licence": "CC-BY-4.0",
        "licences_used": ["CC-BY-4.0"], "authors": [], "parent_package_digest": None,
        "translation_of_package_uid": None, "created_with": {"app": "yuo", "version": "fixtures"},
        "created_at": AT, "required_exercise_types": [], "extensions": {},
    } | extra  # fmt: skip


def _write(path: Path, profile: str, records: dict[str, list[dict[str, Any]]], **extra: Any) -> None:
    files = {hashlib.sha256(d).hexdigest(): d for d in (MP4, VTT, JPEG, SVG)}
    with tempfile.TemporaryDirectory() as d:
        assets: dict[str, tuple[str, Path]] = {}
        for a in records.get("asset", []):
            if a["present"]:
                f = Path(d) / a["sha256"]
                f.write_bytes(files[a["sha256"]])
                assets[a["sha256"]] = (a["media_type"], f)
        pk.write(path, _manifest(profile, records, **extra), records, assets)


def _rezip(path: Path, change: Any) -> None:
    """Rewrite a written package through `change(entries) -> entries` (a list of (name, bytes, stored))."""
    with zipfile.ZipFile(path) as z:
        entries = [(i.filename, z.read(i), i.compress_type == zipfile.ZIP_STORED) for i in z.infolist()]
    entries = change(entries)
    with zipfile.ZipFile(path, "w") as z:
        for name, data, stored in entries:
            info = zipfile.ZipInfo(name, pk.ZIP_TIME)
            info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, data)


def _manifest_edit(path: Path, edit: Any) -> None:
    def change(entries: list[tuple[str, bytes, bool]]) -> list[tuple[str, bytes, bool]]:
        out = []
        for name, data, stored in entries:
            if name == "yuo.json":
                m = json.loads(data)
                edit(m)
                data = (json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode()
            out.append((name, data, stored))
        return out

    _rezip(path, change)


def _relist(path: Path) -> None:
    """Recompute the inventory after a records file was changed on purpose (so only the intended rule breaks)."""
    with zipfile.ZipFile(path) as z:
        data = {i.filename: z.read(i) for i in z.infolist()}

    def edit(m: dict[str, Any]) -> None:
        for f in m["inventory"]["files"]:
            f["sha256"] = hashlib.sha256(data[f["path"]]).hexdigest()
            f["bytes"] = len(data[f["path"]])

    _manifest_edit(path, edit)


def _records_edit(path: Path, kind: str, edit: Any) -> None:
    def change(entries: list[tuple[str, bytes, bool]]) -> list[tuple[str, bytes, bool]]:
        out = []
        for name, data, stored in entries:
            if name == f"records/{kind}.jsonl":
                rows = [json.loads(line) for line in data.decode().splitlines()]
                edit(rows)
                data = pk.jsonl(kind, rows)
            out.append((name, data, stored))
        return out

    _rezip(path, change)
    _relist(path)


def build(out: Path) -> None:
    """Write every fixture under `out/valid` and `out/invalid`."""
    base = base_records()
    for sub in ("valid", "invalid"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    full = {k: v for k, v in base.items()}
    _write(out / "valid/full.yuo.zip", "full", full)
    structure = {k: v for k, v in base.items() if k not in ("rendition", "asset")}
    _write(out / "valid/structure.yuo.zip", "structure", structure)
    minimal = {
        "path": base["path"], "branch": base["branch"][:1],
        "skill": [s | {"prerequisites": []} for s in base["skill"] if s["branch"] == base["branch"][0]["code"]][:1],
    }  # fmt: skip
    _write(out / "valid/minimal.yuo.zip", "structure", minimal)
    _write(out / "valid/custom-items-only.yuo.zip", "custom", {"item": base["item"]})
    older = copy.deepcopy(full)
    for r in older["rendition"]:
        r["versions"].append(r["versions"][0] | {"spec_kind": "declarative", "version_hash": "0" * 64})
    _write(out / "valid/older-version.yuo.zip", "full", older)
    _manifest_edit(out / "valid/older-version.yuo.zip", lambda m: m.update(format_version="0.1.0"))
    ext = copy.deepcopy(structure)
    ext["skill"][0]["extensions"] = {"x-example:difficulty-curve": {"steps": [1, 2, 3]}}
    ext["skill"][0]["x_future_field"] = "kept as it is"
    _write(out / "valid/unknown-extension.yuo.zip", "structure", ext, extensions={"x-example:note": "kept"})
    odd = copy.deepcopy(structure)
    item = odd["item"][0]
    item["type_key"] = "x-example-hotspot"
    v = item["versions"][0]
    v["payload"] = {"image": "a map", "regions": [[1, 2, 3, 4]]}
    v["version_hash"] = pk.item_hash(item["type_key"], v)
    item["current"] = v["version_hash"]
    _write(out / "valid/unknown-exercise-type.yuo.zip", "structure", odd)

    bad = out / "invalid"
    _write(bad / "path-traversal.yuo.zip", "structure", minimal)
    _rezip(bad / "path-traversal.yuo.zip", lambda e: [*e, ("records/../../evil.txt", b"x", False)])
    _write(bad / "zip-bomb.yuo.zip", "structure", minimal)
    _rezip(bad / "zip-bomb.yuo.zip", lambda e: [*e, ("standard/zeros.bin", b"\x00" * 5_000_000, False)])
    _write(bad / "hash-mismatch.yuo.zip", "full", full)
    _rezip(
        bad / "hash-mismatch.yuo.zip",
        lambda e: [
            (n, (VTT[:-2] + b"!\n") if n.endswith(hashlib.sha256(VTT).hexdigest()) else d, s) for n, d, s in e
        ],
    )
    _write(bad / "not-listed.yuo.zip", "structure", minimal)
    _rezip(bad / "not-listed.yuo.zip", lambda e: [*e, ("standard/extra.txt", b"hello", False)])
    _write(bad / "version-hash.yuo.zip", "structure", structure)
    _records_edit(
        bad / "version-hash.yuo.zip",
        "lesson",
        lambda rows: rows[0]["versions"][0].update(title="Changed after hashing"),
    )
    svg = copy.deepcopy(full)
    svg["asset"].append(
        {
            "sha256": hashlib.sha256(SVG).hexdigest(),
            "media_type": "image/svg+xml",
            "kind": "image",
            "bytes": len(SVG),
            "present": True,
        }
    )
    _write(bad / "svg-with-script.yuo.zip", "full", svg)
    sniff = copy.deepcopy(full)
    sniff["asset"].append(
        {
            "sha256": hashlib.sha256(SVG).hexdigest(),
            "media_type": "image/png",
            "kind": "image",
            "bytes": len(SVG),
            "present": True,
        }
    )
    _write(bad / "media-sniff.yuo.zip", "full", sniff)
    for name, block in (
        ("html-in-body", {"type": "html", "bid": "b99", "html": "<script>alert(1)</script>"}),
        (
            "link-in-text",
            {
                "type": "paragraph",
                "bid": "b99",
                "inlines": [{"text": "click", "href": "javascript:alert(1)"}],
            },
        ),
    ):
        recs = copy.deepcopy(structure)
        lv = recs["lesson"][0]["versions"][0]
        lv["body"].append(block)
        lv["version_hash"] = pk.lesson_hash(lv)
        recs["lesson"][0]["current"] = lv["version_hash"]
        _write(bad / f"{name}.yuo.zip", "structure", recs)
    cyc = copy.deepcopy(structure)
    codes = [s["code"] for s in cyc["skill"]]
    cyc["skill"][0]["prerequisites"] = [codes[-1]]
    cyc["skill"][-1]["prerequisites"] = [codes[0]]
    _write(bad / "dag-cycle.yuo.zip", "structure", cyc)
    _write(bad / "newer-major.yuo.zip", "structure", minimal)
    _manifest_edit(bad / "newer-major.yuo.zip", lambda m: m.update(format_version="2.0.0"))
    _write(bad / "manifest-not-first.yuo.zip", "structure", minimal)
    _rezip(bad / "manifest-not-first.yuo.zip", lambda e: e[1:] + e[:1])
