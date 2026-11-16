"""The package container (spec §2, §3, §10): version hashes, a deterministic writer, a reader for untrusted input.

Writing: records as JSON Lines in RFC 8785 form, sorted; zip entries in a fixed order with a fixed timestamp,
so two exports of the same content are byte-identical; media already compressed are stored, the rest deflated.
Reading: every limit is checked before anything is decompressed into memory; names, sizes, ratios and
hashes are verified; records are validated against their models, version hashes recomputed, the skill graph
checked for cycles, asset bytes sniffed against their media type. Any problem rejects the whole package.
"""

import hashlib
import json
import re
import stat
import unicodedata
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from yuo.core.hashing import canonical, content_hash
from yuo.sharing import records as R
from yuo.sharing.upgrade import upgrade

ZIP_TIME = (1980, 1, 1, 0, 0, 0)
STORED_TYPES = {"video/mp4", "video/webm", "image/png", "image/jpeg", "image/webp", "image/gif", "audio/mp4",
                "audio/ogg", "audio/mpeg", "application/pdf", "application/zip"}  # fmt: skip
_NAME = re.compile(r"^[A-Za-z0-9._/-]+$")
_TOP = ("records/", "assets/sha256/", "standard/")


type BodyCheck = Callable[[Any], list[str]]


class PackageError(Exception):
    """The package was refused; the message says why (shown in the import preview)."""


@dataclass(frozen=True)
class Limits:
    """Defaults from spec §10: a 5-minute lesson video is about 6-12 MB, so 10 GB is generous."""

    total_bytes: int = 10 * 1024**3
    files: int = 20_000
    record_file_bytes: int = 50 * 1024**2
    ratio: float = 100.0


# --- version hashes (spec §5) ------------------------------------------------------------------------


def lesson_hash(v: dict[str, Any]) -> str:
    return content_hash(
        {
            "lang": v["lang"],
            "title": v["title"],
            "body": v["body"],
            "est_minutes": v["est_minutes"],
            "objectives": sorted(([o["code"], o["role"]] for o in v.get("objectives", [])), key=str),
            "sources": sorted(
                ([s["key"], s.get("locator"), s.get("block_ids")] for s in v.get("sources", [])), key=str
            ),
        }
    )


def item_hash(type_key: str, v: dict[str, Any]) -> str:
    return content_hash(
        {
            "type_key": type_key,
            "type_version": v["type_version"],
            "lang": v["lang"],
            "difficulty": v["difficulty"],
            "payload": v["payload"],
            "support": v["support"],
            "objectives": sorted(v.get("objectives", [])),
            "resets_review": v.get("resets_review", False),
        }
    )


def rendition_hash(kind: str, v: dict[str, Any]) -> str:
    return content_hash(
        {
            "kind": kind,
            "lang": v["lang"],
            "lesson_version_hash": v["lesson_version_hash"],
            "renderer": v["renderer"],
            "spec_kind": v["spec_kind"],
            "narration": v.get("narration"),
            "theme": v.get("theme"),
            "voice": v.get("voice"),
            "assets": sorted(
                ([a["role"], a["lang"], a["recipe_hash"]] for a in v.get("assets", [])), key=str
            ),
        }
    )


def version_hash(kind: str, head: dict[str, Any], v: dict[str, Any]) -> str:
    if kind == "lesson":
        return lesson_hash(v)
    if kind == "item":
        return item_hash(head["type_key"], v)
    return rendition_hash(head["kind"], v)


def digest(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(manifest)).hexdigest()


# --- writing -------------------------------------------------------------------------------------------


def jsonl(kind: str, rows: list[dict[str, Any]]) -> bytes:
    rows = sorted(rows, key=lambda r: R.sort_key(kind, r))
    return b"".join(canonical(r) + b"\n" for r in rows)


def write(
    path: Path,
    manifest: dict[str, Any],
    records: dict[str, list[dict[str, Any]]],
    assets: dict[str, tuple[str, Path]],
    standard: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    """Write a package to `path`; `manifest` lacks the inventory, which is computed here. Returns the manifest.

    `assets`: sha256 -> (media type, file). Asset files are named by their hash (the blob store), so the
    inventory is known before writing and the zip is written once; each hash is checked while it streams."""
    data_files: list[tuple[str, bytes, str]] = []
    for kind in R.KINDS:
        if records.get(kind):
            data_files.append((f"records/{kind}.jsonl", jsonl(kind, records[kind]), ""))
    for name, data in sorted((standard or {}).items()):
        data_files.append((f"standard/{name}", data, _standard_type(name)))
    inventory = [
        {"path": n, "sha256": hashlib.sha256(d).hexdigest(), "bytes": len(d)} for n, d, _ in data_files
    ]
    inventory += [
        {"path": f"assets/sha256/{sha}", "sha256": sha, "bytes": file.stat().st_size}
        for sha, (_, file) in assets.items()
    ]
    full = dict(manifest)
    full["inventory"] = {
        "files": sorted(inventory, key=lambda f: f["path"]),
        "counts": counts(records),
        "total_bytes": sum(f["bytes"] for f in inventory),
    }
    entries: list[tuple[str, bytes | Path, str]] = [(n, d, t) for n, d, t in data_files]
    entries += [(f"assets/sha256/{sha}", file, media) for sha, (media, file) in assets.items()]
    tmp = path.with_name(f".{path.name}.part")
    try:
        with zipfile.ZipFile(tmp, "w") as z:
            body = json.dumps(full, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
            z.writestr(_info("yuo.json", False), body.encode())
            for name, item, media in sorted(entries, key=lambda e: e[0]):
                info = _info(name, media in STORED_TYPES)
                if isinstance(item, bytes):
                    z.writestr(info, item)
                    continue
                h = hashlib.sha256()
                with z.open(info, "w", force_zip64=True) as dst, item.open("rb") as src:
                    while chunk := src.read(1 << 20):
                        h.update(chunk)
                        dst.write(chunk)
                if h.hexdigest() != name.rsplit("/", 1)[1]:
                    raise PackageError(f"asset {name} changed on disk")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return full


def _standard_type(name: str) -> str:
    """Files already compressed are stored, not deflated again."""
    return {".mp4": "video/mp4", ".apkg": "application/zip", ".jpg": "image/jpeg"}.get(Path(name).suffix, "")


def _info(name: str, stored: bool) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


def counts(records: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, int]]:
    by_kind = {k: len(v) for k, v in records.items() if v}
    by_class = {"C": 0, "F": 0}
    for rows in records.values():
        for r in rows:
            classes = [v.get("data_class", "C") for v in r.get("versions", [])] or ["C"]
            by_class["F" if "F" in classes else "C"] += 1
    return {"by_kind": dict(sorted(by_kind.items())), "by_data_class": by_class}


# --- reading -------------------------------------------------------------------------------------------


@dataclass
class Package:
    manifest: dict[str, Any]
    records: dict[str, list[dict[str, Any]]]
    zip_path: Path
    upgraded_from: str | None = None
    notices: list[str] = field(default_factory=list)
    source_manifest: dict[str, Any] = field(default_factory=dict)  # as it was in the file (the digest)

    def asset(self, sha: str) -> Iterator[bytes]:
        with zipfile.ZipFile(self.zip_path) as z, z.open(f"assets/sha256/{sha}") as f:
            while chunk := f.read(1 << 20):
                yield chunk

    @property
    def digest(self) -> str:
        return digest(self.source_manifest or self.manifest)


def _check_names(z: zipfile.ZipFile, limits: Limits) -> list[zipfile.ZipInfo]:
    infos = z.infolist()
    if len(infos) > limits.files:
        raise PackageError(f"too many files ({len(infos)} > {limits.files})")
    if not infos or infos[0].filename != "yuo.json":
        raise PackageError("not a Yuo package: yuo.json must be the first entry")
    total, seen = 0, set()
    for info in infos:
        name = info.filename
        if unicodedata.normalize("NFC", name) != name or len(name.encode()) > 255 or not _NAME.match(name):
            raise PackageError(f"bad file name {name!r}")
        if name.startswith("/") or ".." in name.split("/") or info.is_dir():
            raise PackageError(f"bad file name {name!r}")
        if stat.S_ISLNK(info.external_attr >> 16):
            raise PackageError(f"symbolic link {name!r}")
        if name not in ("yuo.json", "yuo.sig") and not name.startswith(_TOP):
            raise PackageError(f"file outside the package layout: {name!r}")
        if name in seen:
            raise PackageError(f"duplicate entry {name!r}")
        seen.add(name)
        if (
            info.file_size > 1024
            and info.compress_size
            and info.file_size / info.compress_size > limits.ratio
        ):
            raise PackageError(f"{name}: compression ratio above {limits.ratio:.0f}:1 (zip bomb?)")
        if name.startswith("records/") and info.file_size > limits.record_file_bytes:
            raise PackageError(f"{name} is larger than {limits.record_file_bytes} bytes")
        total += info.file_size
    if total > limits.total_bytes:
        raise PackageError(f"uncompressed size {total} is above the limit {limits.total_bytes}")
    return infos


def _read_capped(z: zipfile.ZipFile, info: zipfile.ZipInfo, cap: int) -> bytes:
    """Read no more than the declared size (a lying header cannot make us inflate more)."""
    with z.open(info) as f:
        data = f.read(min(info.file_size, cap) + 1)
    if len(data) > info.file_size or len(data) > cap:
        raise PackageError(f"{info.filename}: more data than declared")
    return data


_MAGIC: dict[str, Callable[[bytes], bool]] = {
    "image/png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
    "image/gif": lambda b: b[:6] in (b"GIF87a", b"GIF89a"),
    "image/webp": lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP",
    "video/mp4": lambda b: b[4:8] == b"ftyp",
    "audio/mp4": lambda b: b[4:8] == b"ftyp",
    "video/webm": lambda b: b.startswith(b"\x1a\x45\xdf\xa3"),
    "audio/ogg": lambda b: b.startswith(b"OggS"),
    "audio/mpeg": lambda b: b[:3] == b"ID3" or b[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
    "text/vtt": lambda b: b.lstrip(b"\xef\xbb\xbf").startswith(b"WEBVTT"),
    "application/pdf": lambda b: b.startswith(b"%PDF-"),
}


def read(path: Path, limits: Limits | None = None, body_check: BodyCheck | None = None) -> Package:
    """Open and verify a package. Raises PackageError with the first problem; nothing is imported here.

    `body_check` validates a lesson body (the content context's, passed in by the app: contexts stay apart)."""
    limits = limits or Limits()
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise PackageError(f"not a zip file: {e}") from None
    with z:
        infos = {i.filename: i for i in _check_names(z, limits)}
        try:
            manifest = json.loads(_read_capped(z, infos["yuo.json"], 10 * 1024**2))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise PackageError(f"yuo.json is not JSON: {e}") from None
        if not isinstance(manifest, dict) or manifest.get("format") != R.FORMAT:
            raise PackageError("not a Yuo package (format)")
        raw: dict[str, list[dict[str, Any]]] = {}
        for name, info in infos.items():
            if name.startswith("records/"):
                kind = name.removeprefix("records/").removesuffix(".jsonl")
                if not name.endswith(".jsonl") or "/" in kind:
                    raise PackageError(f"unexpected record file {name!r}")
                text = _read_capped(z, info, limits.record_file_bytes).decode("utf-8", errors="strict")
                try:
                    raw[kind] = [json.loads(line) for line in text.splitlines() if line]
                except json.JSONDecodeError as e:
                    raise PackageError(f"{name}: {e}") from None
        source_manifest = manifest
        manifest, raw, upgraded_from = upgrade(manifest, raw)
        try:
            m = R.Manifest.model_validate(manifest)
        except ValidationError as e:
            raise PackageError(f"yuo.json: {_first(e)}") from None
        _check_inventory(z, infos, m)
        records = _validate_records(raw, body_check or (lambda _: []))
        _check_assets(z, records)
    pkg = Package(manifest, records, path, upgraded_from, source_manifest=source_manifest)
    if "yuo.sig" in infos:
        pkg.notices.append("signed package: signatures are not verified yet; treat it as unsigned")
    else:
        pkg.notices.append("unsigned package")
    unknown = sorted(set(raw) - set(R.KINDS))
    if unknown:
        pkg.notices.append(f"record kinds this version does not know were kept aside: {unknown}")
    return pkg


def _first(e: ValidationError) -> str:
    err = e.errors()[0]
    return f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}"


def _check_inventory(z: zipfile.ZipFile, infos: dict[str, zipfile.ZipInfo], m: R.Manifest) -> None:
    listed = {f.path: f for f in m.inventory.files}
    present = set(infos) - {"yuo.json", "yuo.sig"}
    if present != set(listed):
        extra, missing = sorted(present - set(listed)), sorted(set(listed) - present)
        raise PackageError(f"inventory mismatch: not listed {extra[:3]}, missing {missing[:3]}")
    for name, entry in listed.items():
        info = infos[name]
        if info.file_size != entry.bytes:
            raise PackageError(f"{name}: size differs from the inventory")
        h = hashlib.sha256()
        with z.open(info) as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
        if h.hexdigest() != entry.sha256:
            raise PackageError(f"{name}: hash differs from the inventory")


def _validate_records(
    raw: dict[str, list[dict[str, Any]]], body_check: BodyCheck
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for kind, rows in raw.items():
        model = R.KINDS.get(kind)
        if model is None:
            out[kind] = rows  # a newer minor's kind: kept as it is, re-exported unchanged
            continue
        checked = []
        for i, row in enumerate(rows):
            try:
                rec = model.model_validate(row)
            except ValidationError as e:
                raise PackageError(f"{kind} record {i + 1}: {_first(e)}") from None
            checked.append(row)
            for v in row.get("versions", []):
                if version_hash(kind, row, v) != v["version_hash"]:
                    raise PackageError(f"{kind} {row['code']}: version hash does not match its content")
                if kind == "lesson" and (problems := body_check(v["body"])):
                    raise PackageError(f"lesson {row['code']}: {problems[0]}")
            current = getattr(rec, "current", None)
            if current and current not in {v["version_hash"] for v in row["versions"]}:
                raise PackageError(f"{kind} {row['code']}: current version not in the package")
        codes = [R.sort_key(kind, r) for r in rows]
        if len(set(codes)) != len(codes):
            raise PackageError(f"duplicate {kind} codes")
        out[kind] = checked
    if len(out.get("path", [])) > 1:
        raise PackageError("one path per package")
    _check_refs(out)
    return out


def _check_refs(rec: dict[str, list[dict[str, Any]]]) -> None:
    skills = {s["code"]: s for s in rec.get("skill", [])}
    branches = {b["code"] for b in rec.get("branch", [])}
    for s in skills.values():
        if branches and s["branch"] not in branches:
            raise PackageError(f"skill {s['code']}: unknown branch {s['branch']}")
    seen: dict[str, int] = {}  # 1 visiting, 2 done

    def visit(code: str, trail: list[str]) -> None:
        if seen.get(code) == 2:
            return
        if seen.get(code) == 1:
            raise PackageError(f"prerequisite cycle: {' -> '.join([*trail, code])}")
        seen[code] = 1
        for p in skills[code].get("prerequisites", []):
            if p in skills:
                visit(p, [*trail, code])
        seen[code] = 2

    for code in skills:
        visit(code, [])


def _check_assets(z: zipfile.ZipFile, rec: dict[str, list[dict[str, Any]]]) -> None:
    for a in rec.get("asset", []):
        name = f"assets/sha256/{a['sha256']}"
        if not a["present"]:
            continue
        if name not in z.namelist():
            raise PackageError(f"asset {a['sha256'][:12]} is marked present but missing")
        sniff = _MAGIC.get(a["media_type"])
        if sniff is None:
            raise PackageError(f"asset media type {a['media_type']!r} is not allowed")
        with z.open(name) as f:
            head = f.read(64)
        if not sniff(head):
            raise PackageError(f"asset {a['sha256'][:12]}: its bytes are not {a['media_type']}")
