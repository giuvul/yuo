"""Path packages in and out of an install (docs/spec/path-package.md 1.0).

Export reads one path into package records: the tree, the current passed version of each lesson and item, and
(profile `full`) each lesson's current video as rendered media. Personal content stays out (spec §7): versions
made from personal inputs or by the learner, and requested lessons, unless the learner opts in, and then they
are marked `F`. Scene code never leaves (spec §5).

Import verifies the whole package first (yuo.sharing.package), then writes it in one transaction: a new path,
or an update of the path an earlier import of the same package made (matched by `package_uid` and the
import map, codes kept). An incoming version the install does not have becomes current, unless the learner
edited the current one: then a merge conflict is opened. Imported versions pass the gate through the
deterministic checks only. What a version brought that this install does not model (provenance, unknown
fields) is stored as it came and written back unchanged, so import then export is byte-identical (spec §14).
"""

import base64
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, get_args

import structlog

from yuo.app.context import AppContext, Part
from yuo.app.ports import Buffer, Learners
from yuo.app.repo import PathState, get_path
from yuo.assessment import types as xt
from yuo.content.lesson_body import check_body
from yuo.core import clock
from yuo.core.errors import Conflict, InvalidInput, NotFound
from yuo.core.ids import new_id
from yuo.sharing import package as pk
from yuo.sharing import records as R

log = structlog.get_logger(__name__)
COMPONENTS = ("curriculum", "lessons", "items", "renditions.video", "sources")
PROFILE_COMPONENTS = {
    "structure": {"curriculum", "lessons", "items", "sources"},
    "full": {"curriculum", "lessons", "items", "renditions.video", "sources"},
}
_KEEP = "yuo:import"  # version fields kept as they came: provenance extras and unknown fields


def _j(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _uid() -> str:
    return (
        "pkg_" + base64.b32encode(bytes.fromhex(new_id().replace("-", ""))).decode().lower().rstrip("=")[:26]
    )


class Sharing(Part):
    """A part of the application service (yuo.app.context), built with what it calls on the others."""

    def __init__(self, ctx: AppContext, *, learners: Learners, buffer: Buffer) -> None:
        super().__init__(ctx)
        self.learners = learners
        self.buffer = buffer

    # --- export --------------------------------------------------------------------------------------

    def export_package(
        self,
        path_id: str,
        out: Path,
        *,
        profile: str = "full",
        components: set[str] | None = None,
        include_personal: bool = False,
        standard: dict[str, bytes] | None = None,
        licence: str | None = None,
        formats: list[str] | None = None,
    ) -> dict[str, Any]:
        """Write the package to `out`; returns its manifest. `formats` adds standard-format copies of the content
        under `standard/` (CSV, Anki, Moodle XML, readings, videos, BibTeX, CSL-JSON)."""
        if profile not in ("structure", "full", "custom"):
            raise InvalidInput("profile is structure, full or custom")
        wanted = components if profile == "custom" else PROFILE_COMPONENTS[profile]
        if not wanted:
            raise InvalidInput("choose at least one component")
        with self.readers.connection() as c:
            snap = _snapshot(c, path_id, wanted or set(), include_personal)
            assets = {sha: (media, self._blob_path(sha)) for sha, media in snap.pop("_assets").items()}
            meta = snap.pop("_meta")
            records = {k: v for k, v in snap.items() if v}
            uid, content_version, parent, kept = _identity(c, meta["package_id"], records)
        mapping: list[dict[str, Any]] = []
        if formats:
            from yuo.adapters import export as fx

            unknown = sorted(set(formats) - set(fx.FORMATS))
            if unknown:
                raise InvalidInput(f"unknown export formats {unknown}; choose from {sorted(fx.FORMATS)}")
            standard = dict(standard or {})
            for fmt in sorted(set(formats)):
                files = fx.FORMATS[fmt](records, self._blob_path)
                standard |= files
                mapping += [{"path": f"standard/{name}", "format": fmt, "represents": fx.represents(fmt, records)}
                            for name in sorted(files)]  # fmt: skip
        contents = _contents(records, assets, standard)
        manifest: dict[str, Any] = {
            "format": R.FORMAT,
            "format_version": R.FORMAT_VERSION,
            "package_uid": uid,
            "content_version": content_version,
            "profile": profile,
            "contents": contents,
            "title": meta["title"],
            "content_lang": meta["content_lang"],
            "licence": licence or meta["licence"],
            "licences_used": sorted({licence or meta["licence"], *meta["licences"]}),
            "authors": meta["authors"],
            "parent_package_digest": parent,
            "translation_of_package_uid": None,
            "created_with": {"app": "yuo", "version": meta["app_version"]},
            "created_at": clock.now(),
            "required_exercise_types": sorted(
                ({"key": k, "version": v} for k, v in meta["types"].items()), key=lambda t: t["key"]
            ),
            "extensions": kept | ({"yuo:standard": mapping} if mapping else {}),
        }
        manifest = pk.write(out, manifest, records, assets, standard)
        self._record_package(path_id, uid, manifest, "export", out)
        return manifest

    def _record_package(
        self,
        path_id: str | None,
        uid: str,
        manifest: dict[str, Any],
        direction: str,
        file: Path,
        *,
        digest: str | None = None,
    ) -> str:
        file_hash = _file_hash(file)

        def unit(c: sqlite3.Connection) -> str:
            row = c.execute("SELECT id FROM package WHERE package_uid = ?", (uid,)).fetchone()
            pid = row[0] if row else new_id()
            if row is None:
                authors = manifest.get("authors") or []
                c.execute(
                    "INSERT INTO package (id, package_uid, title, origin_author, licence, parent_package_digest) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (pid, uid, manifest["title"], (authors[0].get("name", "") if authors else ""), manifest["licence"],
                     manifest.get("parent_package_digest")),
                )  # fmt: skip
            c.execute(
                "INSERT INTO package_record (id, package_id, direction, profile, format_version, content_version, "
                "package_digest, signature_ref, manifest, file_hash, path_id, at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)",
                (new_id(), pid, direction, manifest["profile"], manifest["format_version"], manifest["content_version"],
                 digest or pk.digest(manifest), json.dumps(manifest), file_hash, path_id, clock.now()),
            )  # fmt: skip
            if path_id is not None:
                c.execute(
                    "UPDATE path SET package_id = ? WHERE id = ? AND package_id IS NULL", (pid, path_id)
                )
            return str(pid)

        return str(self.writer.run(unit))

    def export_preview(
        self,
        path_id: str,
        *,
        profile: str = "full",
        components: set[str] | None = None,
        include_personal: bool = False,
    ) -> dict[str, Any]:
        """What an export would contain, and which personal content it would carry, before writing."""
        wanted = components if profile == "custom" else PROFILE_COMPONENTS.get(profile)
        if not wanted:
            raise InvalidInput("choose a profile, or components for a custom package")
        with self.readers.connection() as c:
            snap = _snapshot(c, path_id, wanted, include_personal)
            mine = _snapshot(c, path_id, wanted, True) if not include_personal else snap
        assets = snap.pop("_assets")
        snap.pop("_meta")
        mine.pop("_assets", None)
        mine.pop("_meta", None)

        def personal(records: dict[str, Any]) -> list[str]:
            return [
                f"{kind} {r.get('code')}"
                for kind, rows in records.items()
                for r in rows
                if any(v.get("data_class") == "F" for v in r.get("versions", []))
            ]

        records = {k: v for k, v in snap.items() if v}
        return {
            "contents": _contents(records, assets, None),
            "counts": {k: len(v) for k, v in records.items()},
            "asset_bytes": sum(self.blobs.path(sha).stat().st_size for sha in assets) if self.blobs else 0,
            "personal_included": personal(records),
            "personal_available": personal({k: v for k, v in mine.items() if v}),
            "goal": next(
                (r["goal"] for r in records.get("path", [])), None
            ),  # often personal: shown for review
        }

    def _blob_path(self, sha: str) -> Path:
        if self.blobs is None:
            raise Conflict("this process has no asset store")
        return self.blobs.path(sha)

    @property
    def package_dir(self) -> Path:
        d = self.media_dir / "packages"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def upload_file(self, token: str) -> Path:
        if not token.isalnum() or len(token) > 64:
            raise NotFound("no such upload")
        return self.package_dir / f"upload-{token}.zip"

    def drop_upload(self, token: str) -> None:
        self.upload_file(token).unlink(missing_ok=True)

    def sweep_packages(self, max_age_s: float = 86400) -> int:
        """Remove uploads nobody imported or cancelled (a closed tab) and exports a crash left behind."""
        import time

        cutoff, gone = time.time() - max_age_s, 0
        for f in self.package_dir.glob("*.zip"):
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
                gone += 1
        return gone

    # --- import --------------------------------------------------------------------------------------

    def read_package(self, file: Path) -> pk.Package:
        pkg = pk.read(file, body_check=check_body)
        _check_items(pkg.records)
        return pkg

    def preview_package(self, file: Path) -> dict[str, Any]:
        """What an import would do, before anything is written (personal content listed)."""
        pkg = self.read_package(file)
        m = pkg.manifest
        with self.readers.connection() as c:
            known = c.execute(
                "SELECT p.id, (SELECT r.path_id FROM package_record r WHERE r.package_id = p.id AND r.direction = 'import' "
                " AND r.path_id IN (SELECT id FROM path) ORDER BY r.at DESC LIMIT 1), "
                " (SELECT r.content_version FROM package_record r WHERE r.package_id = p.id AND r.direction = 'import' "
                " ORDER BY r.at DESC LIMIT 1) "
                "FROM package p WHERE p.package_uid = ?",
                (m["package_uid"],),
            ).fetchone()
        personal = [
            f"{kind} {r.get('code') or r.get('key')}"
            for kind, rows in pkg.records.items()
            for r in rows
            if any(v.get("data_class") == "F" for v in r.get("versions", []))
        ]
        return {
            "title": m["title"],
            "profile": m["profile"],
            "contents": m["contents"],
            "counts": m["inventory"]["counts"]["by_kind"],
            "content_lang": m["content_lang"],
            "licence": m["licence"],
            "content_version": m["content_version"],
            "format_version": m["format_version"],
            "upgraded_from": pkg.upgraded_from,
            "package_digest": pkg.digest,
            "notices": pkg.notices,
            "personal": personal,
            "update_of": known[1] if known else None,
            "installed_version": known[2] if known else None,
            "can_create": "curriculum" in m["contents"],
        }

    def import_package(self, file: Path, *, mode: str = "new") -> str:
        """Import a verified package as a new path or an update of the path it made before. Returns the path id."""
        pkg = self.read_package(file)
        preview = self.preview_package(file)
        if mode == "update" and not preview["update_of"]:
            raise InvalidInput("this package was not imported before: import it as a new path")
        if mode == "new" and not preview["can_create"]:
            raise InvalidInput("this package has no curriculum: it can only update a path")
        learner = self.learners.ensure_learner()
        target = preview["update_of"] if mode == "update" else None
        blobs = self.blobs
        for a in pkg.records.get("asset", []):
            if a["present"] and blobs is not None:
                data = b"".join(pkg.asset(a["sha256"]))
                if blobs.put(data) != a["sha256"]:
                    raise pk.PackageError(f"asset {a['sha256'][:12]} changed while importing")

        def unit(c: sqlite3.Connection) -> str:
            path_id = _write(c, pkg, learner, target)
            self.buffer.top_up_buffer(c, path_id)
            return path_id

        path_id = str(self.writer.run(unit))
        # what this install now has: after any upgrade, so a re-export of unchanged content keeps the identity
        imported = dict(pkg.manifest)
        records_now = [
            {"path": f"records/{k}.jsonl", "sha256": hashlib.sha256(pk.jsonl(k, v)).hexdigest(), "bytes": 0}
            for k, v in pkg.records.items()
            if v
        ]
        others = [f for f in imported["inventory"]["files"] if not f["path"].startswith("records/")]
        imported["inventory"] = imported["inventory"] | {"files": others + records_now}
        self._record_package(
            path_id, pkg.manifest["package_uid"], imported, "import", file, digest=pkg.digest
        )
        log.info("package.imported", path=path_id, mode=mode, digest=pkg.digest[:12])
        return path_id


# --- export helpers -------------------------------------------------------------------------------------


def _file_hash(file: Path) -> str:
    h = hashlib.sha256()
    with file.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _identity(
    c: sqlite3.Connection, package_id: str | None, records: dict[str, list[dict[str, Any]]]
) -> tuple[str, str, str | None, dict[str, Any]]:
    """(package_uid, content_version, parent digest), from the last package of this path:

    records unchanged -> the same identity and version (a re-export, or a round trip through another install);
    changed, the path's own package -> the next minor version; changed, a package someone else made -> a fork
    with a new uid and the parent's digest (spec §3)."""
    if package_id is None:
        return _uid(), "1.0.0", None, {}
    (uid,) = c.execute("SELECT package_uid FROM package WHERE id = ?", (package_id,)).fetchone()
    last = c.execute(
        "SELECT direction, content_version, package_digest, manifest FROM package_record WHERE package_id = ? "
        "ORDER BY at DESC LIMIT 1",
        (package_id,),
    ).fetchone()
    if last is None:
        return uid, "1.0.0", None, {}
    direction, version, digest, manifest = last
    manifest = _j(manifest)
    before = {
        f["path"]: f["sha256"] for f in manifest["inventory"]["files"] if f["path"].startswith("records/")
    }
    now = {f"records/{k}.jsonl": hashlib.sha256(pk.jsonl(k, v)).hexdigest() for k, v in records.items() if v}
    if before == now:
        kept = {
            k: v for k, v in manifest.get("extensions", {}).items() if k != "yuo:standard"
        }  # made per export
        return uid, str(version), manifest.get("parent_package_digest"), kept
    if direction == "import":  # someone else's package, changed here: a fork
        return _uid(), "1.0.0", digest, {}
    major, minor, _ = (int(x) for x in str(version).split("."))
    return uid, f"{major}.{minor + 1}.0", None, {}


def _contents(
    records: dict[str, list[Any]], assets: dict[str, Any], standard: dict[str, bytes] | None
) -> list[str]:
    tags = []
    if records.get("path"):
        tags.append("curriculum")
    if any(r["versions"] for r in records.get("lesson", [])):
        tags.append("lessons")
    for kind in ("reading", "video", "slides", "audio"):
        if any(r["kind"] == kind for r in records.get("rendition", [])):
            tags.append(f"renditions.{kind}")
    if records.get("item"):
        tags.append("items")
        if any(r["type_key"] == "flashcard" for r in records["item"]):
            tags.append("flashcards")
    if records.get("source"):
        tags.append("sources")
    if assets:
        tags.append("assets")
    for name in sorted(standard or {}):
        tag = f"standard.{name.rsplit('.', 1)[-1]}"
        if tag not in tags:
            tags.append(tag)
    return tags


def _provenance(row: sqlite3.Row, model: str | None) -> dict[str, Any]:
    kept = _j(row["upstream"]) or {}
    if isinstance(kept, dict) and _KEEP in kept:  # imported: as it came
        return dict(kept[_KEEP]["provenance"])
    prov: dict[str, Any] = {"authorship": row["authorship"], "author_kind": row["author_kind"]}
    if row["licence"]:
        prov["licence"] = row["licence"]
    if kept:
        prov["upstream"] = kept
    if model and row["authorship"] == "generated":
        prov["generated_by"] = {"model": model}  # a model summary, never the prompt (spec §12)
    return prov


def _extras(row: sqlite3.Row) -> dict[str, Any]:
    kept = _j(row["upstream"]) or {}
    return dict(kept[_KEEP].get("unknown", {})) if isinstance(kept, dict) and _KEEP in kept else {}


def _personal(row: sqlite3.Row) -> bool:
    return bool(row["personal_inputs"]) or row["author_kind"] == "learner"


def _snapshot(c: sqlite3.Connection, path_id: str, wanted: set[str], personal: bool) -> dict[str, Any]:
    """The path's records as the package will hold them, plus `_meta` and `_assets` for the manifest."""
    return _Exporter(c, path_id, wanted, personal).run()


class _Exporter:
    """One export, record kind by record kind; `wanted` holds the components, `personal` the learner's own."""

    def __init__(self, c: sqlite3.Connection, path_id: str, wanted: set[str], personal: bool) -> None:
        self.c, self.path_id, self.wanted, self.personal = c, path_id, wanted, personal
        self.c.row_factory = sqlite3.Row
        self.p = get_path(self.c, self.path_id)
        self.models = {
            r[0]: r[1]
            for r in self.c.execute("SELECT id, coalesce(model_resolved, model_requested) FROM stage_run WHERE job_id IN "
                               "(SELECT id FROM generation_job)")
        }  # fmt: skip
        self.out: dict[str, Any] = {k: [] for k in R.KINDS}
        self.meta: dict[str, Any] = {
            "title": self.p["title"], "content_lang": self.p["content_lang"], "licence": self.p["licence"], "authors": _j(self.p["authors"]),
            "package_id": self.p["package_id"], "licences": set(), "types": {}, "app_version": _app_version(),
        }  # fmt: skip
        self.assets: dict[str, str] = {}
        self.branches = {
            r["id"]: r
            for r in self.c.execute(
                "SELECT * FROM branch WHERE path_id = ? AND archived_at IS NULL", (self.path_id,)
            )
        }
        self.skills = {
            r["id"]: r
            for r in self.c.execute(
                "SELECT * FROM skill WHERE path_id = ? AND archived_at IS NULL", (self.path_id,)
            )
        }
        self.objectives = {
            r["id"]: r
            for r in self.c.execute(
                "SELECT * FROM learning_objective WHERE path_id = ? AND archived_at IS NULL", (self.path_id,)
            )
        }
        self.lesson_hashes: dict[str, str] = {}  # local lesson version id -> exported hash
        self.lesson_codes: dict[str, str] = {}
        self.sources: dict[str, sqlite3.Row] = {}

    def run(self) -> dict[str, Any]:
        if "curriculum" in self.wanted:
            self._curriculum()
        self._lessons()
        if "items" in self.wanted:
            self._items()
        if "sources" in self.wanted:
            self._sources()
        self._assets()
        self.meta["licences"].discard(None)
        self.out["_meta"], self.out["_assets"] = self.meta, self.assets
        return self.out

    def _curriculum(self) -> None:
        rec = _with_ext({
            "code": self.p["code"], "title": self.p["title"], "subject": self.p["subject"], "goal": self.p["goal"], "goal_type": self.p["goal_type"],
            "difficulty": self.p["difficulty"], "content_lang": self.p["content_lang"], "licence": self.p["licence"], "authors": _j(self.p["authors"]),
        }, self.p)  # fmt: skip
        self.out["path"].append(_without_learner_state(rec))
        self.out["branch"] = [
            _with_ext({"code": b["code"], "title": b["title"], "position": b["position"]}, b)
            for b in self.branches.values()
        ]
        prereq: dict[str, list[str]] = {}
        for s_id, r_id in self.c.execute(
            "SELECT skill_id, requires_skill_id FROM skill_prerequisite WHERE path_id = ?", (self.path_id,)
        ):
            if s_id in self.skills and r_id in self.skills:
                prereq.setdefault(s_id, []).append(self.skills[r_id]["code"])
        for s in self.skills.values():
            rec = {"code": s["code"], "branch": self.branches[s["branch_id"]]["code"], "title": s["title"], "summary": s["summary"],
                   "position": s["position"], "prerequisites": sorted(prereq.get(s["id"], [])), "optional": bool(s["optional"])}  # fmt: skip
            if s["mastery_threshold"] is not None:
                rec["mastery_threshold"] = s["mastery_threshold"]
            if s["merged_into_skill_id"] in self.skills:
                rec["merged_into"] = self.skills[s["merged_into_skill_id"]]["code"]
            self.out["skill"].append(_with_ext(rec, s))
        for o in self.objectives.values():
            rec = {
                "code": o["code"],
                "skill": self.skills[o["skill_id"]]["code"],
                "statement": o["statement"],
                "position": o["position"],
            }
            if o["bloom_level"]:
                rec["bloom_level"] = o["bloom_level"]
            self.out["objective"].append(_with_ext(rec, o))

    def _lessons(self) -> None:
        for lesson in self.c.execute(
            "SELECT * FROM lesson WHERE path_id = ? ORDER BY position", (self.path_id,)
        ).fetchall():
            if lesson["skill_id"] not in self.skills or (lesson["kind"] == "requested" and not self.personal):
                continue
            self.lesson_codes[lesson["id"]] = lesson["code"]
            if not self.wanted & {"lessons", "renditions.video"}:
                continue
            versions = []
            v = self.c.execute(
                "SELECT * FROM lesson_version WHERE id = ? AND status = 'passed'",
                (lesson["current_version_id"],),
            ).fetchone()
            if "lessons" in self.wanted and v is not None and (self.personal or not _personal(v)):
                objs = [{"code": self.objectives[o]["code"], "role": role} for o, role in
                        self.c.execute("SELECT objective_id, role FROM lesson_version_objective WHERE lesson_version_id = ?", (v["id"],))
                        if o in self.objectives]  # fmt: skip
                uses = []
                for s_id, locator, block_ids in self.c.execute(
                    "SELECT source_id, locator, block_ids FROM lesson_version_source WHERE lesson_version_id = ?",
                    (v["id"],),
                ):
                    src = self.c.execute("SELECT * FROM source WHERE id = ?", (s_id,)).fetchone()
                    self.sources[src["key"]] = src
                    use: dict[str, Any] = {"key": src["key"]}
                    if locator:
                        use["locator"] = locator
                    if block_ids:
                        use["block_ids"] = _j(block_ids)
                    uses.append(use)
                rec = {"version_no": 1, "lang": v["lang"], "title": v["title"], "body": _j(v["body"]), "est_minutes": v["est_minutes"],
                       "objectives": sorted(objs, key=lambda o: o["code"]), "sources": sorted(uses, key=lambda u: u["key"]),
                       "provenance": _provenance(v, self.models.get(v["produced_by_stage_run_id"]))}  # fmt: skip
                if v["translation_of_version_hash"]:
                    rec["translation_of_version_hash"] = v["translation_of_version_hash"]
                if _personal(v) or lesson["kind"] == "requested":
                    rec["data_class"] = "F"
                rec |= _extras(v)
                rec["version_hash"] = pk.lesson_hash(rec)
                self.lesson_hashes[v["id"]] = rec["version_hash"]
                self.meta["licences"].add(rec["provenance"].get("licence") or self.p["licence"])
                versions.append(rec)
            self.out["lesson"].append(_with_ext({
                "code": lesson["code"], "skill": self.skills[lesson["skill_id"]]["code"], "kind": lesson["kind"], "position": lesson["position"],
                "current": versions[0]["version_hash"] if versions else None, "versions": versions,
            }, lesson))  # fmt: skip
            if "renditions.video" in self.wanted and versions:
                _video(self.c, lesson, versions[0], self.lesson_hashes, self.out, self.assets, self.personal)

    def _items(self) -> None:
        types = {k: t.version for k, t in xt.TYPES.items()}
        for item in self.c.execute("SELECT * FROM item WHERE path_id = ?", (self.path_id,)).fetchall():
            if item["skill_id"] not in self.skills:
                continue
            v = self.c.execute(
                "SELECT * FROM item_version WHERE id = ? AND status = 'passed'", (item["current_version_id"],)
            ).fetchone()
            if v is None or (_personal(v) and not self.personal):
                continue
            objs = sorted(self.objectives[o]["code"] for (o,) in self.c.execute(
                "SELECT objective_id FROM item_version_objective WHERE item_version_id = ?", (v["id"],)) if o in self.objectives)  # fmt: skip
            origin = self.c.execute(
                "SELECT lesson_id FROM lesson_version WHERE id = ?", (v["origin_lesson_version_id"],)
            ).fetchone()
            type_version = types.get(item["type_key"], 1)
            rec = {"version_no": 1, "type_version": type_version, "lang": v["lang"], "difficulty": v["difficulty"],
                   "payload": _j(v["payload"]), "support": _j(v["support"]), "objectives": objs,
                   "resets_review": bool(v["resets_review"]), "provenance": _provenance(v, self.models.get(v["produced_by_stage_run_id"]))}  # fmt: skip
            if origin and origin[0] in self.lesson_codes:
                rec["origin_lesson"] = self.lesson_codes[origin[0]]
            if _personal(v):
                rec["data_class"] = "F"
            rec |= _extras(v)
            rec["version_hash"] = pk.item_hash(item["type_key"], rec)
            self.meta["types"][item["type_key"]] = type_version
            self.out["item"].append(_with_ext({"code": item["code"], "skill": self.skills[item["skill_id"]]["code"], "type_key": item["type_key"],
                                          "current": rec["version_hash"], "versions": [rec]}, item))  # fmt: skip

    def _sources(self) -> None:
        for src in self.sources.values():
            rec = {
                "key": src["key"],
                "kind": src["kind"],
                "title": src["title"],
                "citation": _j(src["citation"]),
            }
            for f in ("url", "accessed_at", "published_at"):
                if src[f]:
                    rec[f] = src[f]
            self.out["source"].append(_with_ext(rec, src))

    def _assets(self) -> None:
        for sha, media in self.assets.items():
            kind, size = self.c.execute("SELECT kind, bytes FROM asset WHERE hash = ?", (sha,)).fetchone()
            self.out["asset"].append(
                {"sha256": sha, "media_type": media, "kind": kind, "bytes": size, "present": True}
            )


def _without_learner_state(rec: dict[str, Any]) -> dict[str, Any]:
    """A path's own state on this machine (its level check, plan choices, preview, next steps) is the learner's,
    not part of what they share."""
    ours = rec.get("extensions", {}).get("yuo")
    if isinstance(ours, dict):
        kept = {k: v for k, v in ours.items() if k not in get_args(PathState)}
        rest = {k: v for k, v in rec["extensions"].items() if k != "yuo"} | ({"yuo": kept} if kept else {})
        rec = {k: v for k, v in rec.items() if k != "extensions"} | ({"extensions": rest} if rest else {})
    return rec


def _with_ext(rec: dict[str, Any], row: sqlite3.Row) -> dict[str, Any]:
    ext = _j(row["extensions"]) or {}
    unknown = ext.pop("yuo:unknown", {}) if isinstance(ext, dict) else {}
    if ext:
        rec["extensions"] = ext
    return rec | unknown


def _video(c: sqlite3.Connection, lesson: sqlite3.Row, lv: dict[str, Any], hashes: dict[str, str], out: dict[str, Any],
           assets: dict[str, str], personal: bool) -> None:  # fmt: skip
    r = c.execute(
        "SELECT * FROM rendition WHERE lesson_id = ? AND kind = 'video'", (lesson["id"],)
    ).fetchone()
    if r is None or r["current_version_id"] is None:
        return
    v = c.execute(
        "SELECT * FROM rendition_version WHERE id = ? AND status = 'passed'", (r["current_version_id"],)
    ).fetchone()
    if (
        v is None
        or hashes.get(v["lesson_version_id"]) != lv["version_hash"]
        or (_personal(v) and not personal)
    ):
        return  # a video of an older lesson version does not travel with the new one
    uses = []
    for a in c.execute(
        "SELECT ra.role, ra.lang, ra.recipe_hash, ra.asset_hash, a.media_type FROM rendition_asset ra "
        "JOIN asset a ON a.hash = ra.asset_hash WHERE ra.rendition_version_id = ? AND a.evicted_at IS NULL",
        (v["id"],),
    ):
        uses.append(
            {"role": a["role"], "lang": a["lang"], "recipe_hash": a["recipe_hash"], "sha256": a["asset_hash"]}
        )
        assets[a["asset_hash"]] = a["media_type"]
    if not any(u["role"] == "video" for u in uses):
        return
    rec: dict[str, Any] = {"version_no": 1, "lang": v["lang"], "lesson_version_hash": lv["version_hash"], "renderer": v["renderer"],
                           "spec_kind": "rendered", "assets": sorted(uses, key=lambda u: (u["role"], u["lang"])),
                           "provenance": _provenance(v, None)}  # fmt: skip
    for f in ("voice", "duration_s"):
        if v[f] is not None:
            rec[f] = v[f]
    if v["narration"]:
        rec["narration"] = _j(v["narration"])
    if _personal(v):
        rec["data_class"] = "F"
    rec |= _extras(v)
    rec["version_hash"] = pk.rendition_hash("video", rec)
    out["rendition"].append({"code": f"{lesson['code']}.video", "lesson": lesson["code"], "kind": "video",
                             "current": rec["version_hash"], "versions": [rec]})  # fmt: skip


def _app_version() -> str:
    from importlib.metadata import version

    return version("yuo")


# --- import helpers -------------------------------------------------------------------------------------


def _check_items(records: dict[str, list[dict[str, Any]]]) -> None:
    """Item payloads must work with their exercise type (an unknown type is kept but not playable, spec §6)."""
    for item in records.get("item", []):
        t = xt.TYPES.get(item["type_key"])
        if t is None:
            continue
        for v in item["versions"]:
            try:
                t.view(v["payload"], "check")
                t.correct(v["payload"])
                problems = (
                    t.support_rules(v["payload"], xt.Support.model_validate(v["support"]))
                    if t.needs_support
                    else []
                )  # the same checks as the app's own gate (yuo.app.items)
            except Exception as e:  # a payload the type cannot read
                raise pk.PackageError(
                    f"item {item['code']}: not a valid {item['type_key']} item ({type(e).__name__})"
                ) from None
            if problems:
                raise pk.PackageError(f"item {item['code']}: {problems[0]}")


_KNOWN_VERSION = {
    "lesson": set(R.LessonVersionRecord.model_fields),
    "item": set(R.ItemVersionRecord.model_fields),
    "rendition": set(R.RenditionVersionRecord.model_fields),
}
_KNOWN_HEAD = {k: set(m.model_fields) for k, m in R.KINDS.items()}


def _keep(kind: str, v: dict[str, Any]) -> str:
    """The upstream column of an imported version: what to write back on export, as it came."""
    unknown = {k: val for k, val in v.items() if k not in _KNOWN_VERSION[kind]}
    return json.dumps({_KEEP: {"provenance": v["provenance"], "unknown": unknown}})


def _ext(kind: str, rec: dict[str, Any]) -> str:
    ext = dict(rec.get("extensions", {}))
    unknown = {k: v for k, v in rec.items() if k not in _KNOWN_HEAD[kind]}
    if unknown:
        ext["yuo:unknown"] = unknown
    return json.dumps(ext)


def _write(c: sqlite3.Connection, pkg: pk.Package, learner: str, target: str | None) -> str:
    """Write an incoming package into the install: a new path, or the update of `target`; the path id."""
    return _Importer(c, pkg).run(learner, target)


class _Importer:
    """One package import, record kind by record kind; `ids` maps (kind, package code) to the local id."""

    def __init__(self, c: sqlite3.Connection, pkg: pk.Package) -> None:
        self.c, self.rec, self.manifest, self.now = c, pkg.records, pkg.manifest, clock.now()
        self.package_row = c.execute(
            "SELECT id FROM package WHERE package_uid = ?", (self.manifest["package_uid"],)
        ).fetchone()
        self.ids: dict[tuple[str, str], str] = {}
        self.lesson_versions: dict[str, str] = {}  # version hash -> local lesson version id
        self.path_id = ""

    def local(self, kind: str, code: str) -> str | None:
        return self.ids.get((kind, code))

    def ref(self, kind: str, code: str) -> str:
        """A record the package refers to: imported now, or already in the path."""
        return self.local(kind, code) or _by_code(self.c, kind, self.path_id, code)

    def run(self, learner: str, target: str | None) -> str:
        if target and self.package_row:
            self.ids = {(k, code): lid for k, code, lid in self.c.execute(
                "SELECT entity_kind, external_code, local_id FROM import_map WHERE package_id = ?", (self.package_row[0],))}  # fmt: skip
        if target is None:
            path = self.rec["path"][0] if self.rec.get("path") else None
            if path is None:
                raise InvalidInput("no path record: this package can only update a path")
            self._new_path(path, learner)
        else:
            self.path_id = target
        self._branches()
        self._skills()
        self._prerequisites()
        self._objectives()
        self._sources_and_assets()
        self._lessons()
        self._renditions()
        self._items()
        self._record_package()
        return self.path_id

    def _new_path(self, path: dict[str, Any], learner: str) -> None:
        self.path_id = new_id()
        code = path["code"]
        while self.c.execute("SELECT 1 FROM path WHERE code = ?", (code,)).fetchone():
            code = f"{path['code']}-{new_id()[-6:]}"  # a second copy of the same path
        self.c.execute(
            "INSERT INTO path (id, code, learner_id, title, subject, goal, goal_type, target_date, difficulty, content_lang, "
            "status, authorship, acquired_via, package_id, translation_of_path_id, structure_version, licence, authors, "
            "extensions, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, 'active', 'generated', 'import', "
            "NULL, NULL, 1, ?, ?, ?, ?, ?)",
            (self.path_id, code, learner, path["title"], path["subject"], path["goal"], path["goal_type"], path["difficulty"],
             path["content_lang"], path["licence"], json.dumps(path.get("authors", [])), _ext("path", path), self.now, self.now),
        )  # fmt: skip
        self.ids[("path", path["code"])] = self.path_id

    def _branches(self) -> None:
        for b in self.rec.get("branch", []):
            bid = self.local("branch", b["code"])
            if bid:
                self.c.execute(
                    "UPDATE branch SET title = ?, position = ?, extensions = ? WHERE id = ?",
                    (b["title"], b["position"], _ext("branch", b), bid),
                )
            else:
                self.ids[("branch", b["code"])] = bid = new_id()
                self.c.execute("INSERT INTO branch (id, path_id, code, title, position, extensions, archived_at) VALUES (?, ?, ?, ?, ?, ?, NULL)",
                          (bid, self.path_id, b["code"], b["title"], b["position"], _ext("branch", b)))  # fmt: skip

    def _skills(self) -> None:
        for s in self.rec.get("skill", []):
            branch = self.ref("branch", s["branch"])
            sid = self.local("skill", s["code"])
            values = (
                branch,
                s["title"],
                s.get("summary", ""),
                s["position"],
                s.get("mastery_threshold"),
                int(s.get("optional", False)),
                _ext("skill", s),
            )
            if sid:
                self.c.execute("UPDATE skill SET branch_id = ?, title = ?, summary = ?, position = ?, mastery_threshold = ?, optional = ?, "
                          "extensions = ? WHERE id = ?", (*values, sid))  # fmt: skip
            else:
                self.ids[("skill", s["code"])] = sid = new_id()
                self.c.execute("INSERT INTO skill (id, branch_id, path_id, code, title, summary, position, mastery_threshold, optional, "
                          "merged_into_skill_id, extensions, archived_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL)",
                          (sid, branch, self.path_id, s["code"], *values[1:]))  # fmt: skip

    def _prerequisites(self) -> None:
        if self.rec.get("skill"):
            for s in self.rec["skill"]:
                self.c.execute(
                    "DELETE FROM skill_prerequisite WHERE skill_id = ?", (self.ids[("skill", s["code"])],)
                )
            for s in self.rec["skill"]:
                for p in s.get("prerequisites", []):
                    req = self.ref("skill", p)
                    self.c.execute("INSERT INTO skill_prerequisite (skill_id, requires_skill_id, path_id) VALUES (?, ?, ?)",
                              (self.ids[("skill", s["code"])], req, self.path_id))  # fmt: skip
                if s.get("merged_into"):
                    self.c.execute("UPDATE skill SET merged_into_skill_id = ? WHERE id = ?",
                              (self.ref("skill", s["merged_into"]), self.ids[("skill", s["code"])]))  # fmt: skip

    def _objectives(self) -> None:
        for o in self.rec.get("objective", []):
            skill = self.ref("skill", o["skill"])
            oid = self.local("objective", o["code"])
            if oid:
                self.c.execute("UPDATE learning_objective SET skill_id = ?, statement = ?, bloom_level = ?, position = ?, extensions = ? WHERE id = ?",
                          (skill, o["statement"], o.get("bloom_level"), o["position"], _ext("objective", o), oid))  # fmt: skip
            else:
                self.ids[("objective", o["code"])] = oid = new_id()
                self.c.execute("INSERT INTO learning_objective (id, skill_id, path_id, code, statement, bloom_level, position, extensions, "
                          "archived_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                          (oid, skill, self.path_id, o["code"], o["statement"], o.get("bloom_level"), o["position"], _ext("objective", o)))  # fmt: skip

    def _sources_and_assets(self) -> None:
        for s in self.rec.get("source", []):
            row = self.c.execute("SELECT id FROM source WHERE key = ?", (s["key"],)).fetchone()
            if row is None:
                self.c.execute("INSERT INTO source (id, key, kind, title, url, accessed_at, published_at, citation, data_class, extensions) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'C', ?)",
                          (new_id(), s["key"], s["kind"], s["title"], s.get("url"), s.get("accessed_at"), s.get("published_at"),
                           json.dumps(s.get("citation", {})), _ext("source", s)))  # fmt: skip
        for a in self.rec.get("asset", []):
            if a["present"]:
                self.c.execute("INSERT INTO asset (hash, media_type, kind, bytes, stored_at, retention_class, evicted_at, data_class, created_at) "
                          "VALUES (?, ?, ?, ?, ?, 'keep', NULL, 'C', ?) ON CONFLICT(hash) DO NOTHING",
                          (a["sha256"], a["media_type"], a["kind"], a["bytes"], self.now, self.now))  # fmt: skip

    def _lessons(self) -> None:
        for lesson in self.rec.get("lesson", []):
            skill = self.ref("skill", lesson["skill"])
            lid = self.local("lesson", lesson["code"])
            if lid is None:
                self.ids[("lesson", lesson["code"])] = lid = new_id()
                self.c.execute("INSERT INTO lesson (id, skill_id, path_id, code, kind, position, state, current_version_id, extensions) "
                          "VALUES (?, ?, ?, ?, ?, ?, 'planned', NULL, ?)",
                          (lid, skill, self.path_id, lesson["code"], lesson["kind"], lesson["position"], _ext("lesson", lesson)))  # fmt: skip
            else:
                self.c.execute("UPDATE lesson SET skill_id = ?, position = ?, extensions = ? WHERE id = ?",
                          (skill, lesson["position"], _ext("lesson", lesson), lid))  # fmt: skip
            for v in lesson["versions"]:
                vid = _version(
                    self.c, "lesson", lid, v, lesson.get("current"), self.now, self.path_id, self.ids
                )
                self.lesson_versions[v["version_hash"]] = vid

    def _renditions(self) -> None:
        for r in self.rec.get("rendition", []):
            lid = self.ref("lesson", r["lesson"])
            row = self.c.execute(
                "SELECT id FROM rendition WHERE lesson_id = ? AND kind = ?", (lid, r["kind"])
            ).fetchone()
            rid = row[0] if row else new_id()
            if row is None:
                self.c.execute("INSERT INTO rendition (id, lesson_id, kind, state, current_version_id) VALUES (?, ?, ?, 'planned', NULL)",
                          (rid, lid, r["kind"]))  # fmt: skip
            for v in r["versions"]:
                lv = self.lesson_versions.get(v["lesson_version_hash"]) or _lesson_version_by_hash(
                    self.c, lid, v["lesson_version_hash"]
                )
                _version(
                    self.c,
                    "rendition",
                    rid,
                    v,
                    r.get("current"),
                    self.now,
                    self.path_id,
                    self.ids,
                    lesson_version=lv,
                )

    def _items(self) -> None:
        for item in self.rec.get("item", []):
            _exercise_type(
                self.c, item["type_key"], item["versions"][0]["type_version"] if item["versions"] else 1
            )
            skill = self.ref("skill", item["skill"])
            iid = self.local("item", item["code"])
            if iid is None:
                self.ids[("item", item["code"])] = iid = new_id()
                self.c.execute("INSERT INTO item (id, skill_id, path_id, code, type_key, state, current_version_id, extensions) "
                          "VALUES (?, ?, ?, ?, ?, 'planned', NULL, ?)",
                          (iid, skill, self.path_id, item["code"], item["type_key"], _ext("item", item)))  # fmt: skip
            for v in item["versions"]:
                origin = self.local("lesson", v["origin_lesson"]) if v.get("origin_lesson") else None
                origin_v = (
                    self.c.execute("SELECT current_version_id FROM lesson WHERE id = ?", (origin,)).fetchone()
                    if origin
                    else None
                )
                _version(
                    self.c,
                    "item",
                    iid,
                    v,
                    item.get("current"),
                    self.now,
                    self.path_id,
                    self.ids,
                    origin=origin_v[0] if origin_v else None,
                )

    def _record_package(self) -> None:
        if self.package_row is None:
            pid = new_id()
            authors = self.manifest.get("authors") or []
            self.c.execute("INSERT INTO package (id, package_uid, title, origin_author, licence, parent_package_digest) VALUES (?, ?, ?, ?, ?, ?)",
                      (pid, self.manifest["package_uid"], self.manifest["title"], authors[0].get("name", "") if authors else "", self.manifest["licence"],
                       self.manifest.get("parent_package_digest")))  # fmt: skip
        else:
            pid = self.package_row[0]
        self.c.execute(
            "UPDATE path SET package_id = ?, updated_at = ? WHERE id = ?", (pid, self.now, self.path_id)
        )
        for (kind, code), lid in self.ids.items():
            self.c.execute("INSERT INTO import_map (package_id, entity_kind, external_code, local_id, last_content_version, last_version_hash) "
                      "VALUES (?, ?, ?, ?, ?, NULL) ON CONFLICT DO UPDATE SET local_id = excluded.local_id, "
                      "last_content_version = excluded.last_content_version",
                      (pid, kind, code, lid, self.manifest["content_version"]))  # fmt: skip


def _by_code(c: sqlite3.Connection, kind: str, path_id: str, code: str) -> str:
    table = {"objective": "learning_objective"}.get(kind, kind)
    row = c.execute(f"SELECT id FROM {table} WHERE path_id = ? AND code = ?", (path_id, code)).fetchone()
    if row is None:
        raise pk.PackageError(f"{kind} {code} is referred to but not in the package or the path")
    return str(row[0])


def _lesson_version_by_hash(c: sqlite3.Connection, lesson_id: str, h: str) -> str:
    row = c.execute(
        "SELECT id FROM lesson_version WHERE lesson_id = ? AND version_hash = ?", (lesson_id, h)
    ).fetchone()
    if row is None:
        raise pk.PackageError("a video refers to a lesson version that is not in the package")
    return str(row[0])


def _exercise_type(c: sqlite3.Connection, key: str, version: int) -> None:
    if c.execute("SELECT 1 FROM exercise_type WHERE key = ?", (key,)).fetchone() is None:
        c.execute("INSERT INTO exercise_type (key, version, payload_schema, grading_method, plugin, status) "
                  "VALUES (?, ?, '{}', 'model', '', 'unsupported')", (key, version))  # fmt: skip


def _version(
    c: sqlite3.Connection, kind: str, head_id: str, v: dict[str, Any], current: str | None, now: str,
    path_id: str, ids: dict[tuple[str, str], str], *, lesson_version: str | None = None, origin: str | None = None,
) -> str:  # fmt: skip
    """Add one incoming version (unless the install has it) and make it current when it should be."""
    table, head = f"{kind}_version", kind
    fk = {"lesson": "lesson_id", "item": "item_id", "rendition": "rendition_id"}[kind]
    row = c.execute(
        f"SELECT id FROM {table} WHERE {fk} = ? AND version_hash = ?", (head_id, v["version_hash"])
    ).fetchone()
    if row:
        return str(row[0])
    vid = new_id()
    no = c.execute(
        f"SELECT coalesce(max(version_no), 0) + 1 FROM {table} WHERE {fk} = ?", (head_id,)
    ).fetchone()[0]
    prov = v["provenance"]
    common = (prov["authorship"], "import", prov.get("author_kind", "system"), None, None, _keep(kind, v), prov.get("licence"),
              int(v.get("data_class") == "F" and prov.get("author_kind") != "learner"))  # fmt: skip
    if kind == "lesson":
        c.execute(
            "INSERT INTO lesson_version (id, lesson_id, version_no, version_hash, lang, translation_of_version_hash, "
            "derived_from_version_id, title, body, est_minutes, status, published_at, created_at, authorship, acquired_via, "
            "author_kind, author_ref, produced_by_stage_run_id, upstream, licence, personal_inputs) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, 'passed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (vid, head_id, no, v["version_hash"], v["lang"], v.get("translation_of_version_hash"), v["title"],
             json.dumps(v["body"]), v["est_minutes"], now, now, *common),
        )  # fmt: skip
        for o in v.get("objectives", []):
            c.execute("INSERT INTO lesson_version_objective (lesson_version_id, objective_id, role) VALUES (?, ?, ?)",
                      (vid, ids.get(("objective", o["code"])) or _by_code(c, "objective", path_id, o["code"]), o["role"]))  # fmt: skip
        for s in v.get("sources", []):
            sid = c.execute("SELECT id FROM source WHERE key = ?", (s["key"],)).fetchone()
            if sid:
                c.execute("INSERT INTO lesson_version_source (lesson_version_id, source_id, locator, block_ids) VALUES (?, ?, ?, ?)",
                          (vid, sid[0], s.get("locator"), json.dumps(s["block_ids"]) if s.get("block_ids") is not None else None))  # fmt: skip
    elif kind == "item":
        c.execute(
            "INSERT INTO item_version (id, item_id, version_no, version_hash, lang, translation_of_version_hash, "
            "derived_from_version_id, difficulty, payload, support, origin_lesson_version_id, resets_review, status, "
            "published_at, created_at, authorship, acquired_via, author_kind, author_ref, produced_by_stage_run_id, upstream, "
            "licence, personal_inputs) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, 'passed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (vid, head_id, no, v["version_hash"], v["lang"], v["difficulty"], json.dumps(v["payload"]),
             json.dumps(v["support"]), origin, int(v.get("resets_review", False)), now, now, *common),
        )  # fmt: skip
        for code in v.get("objectives", []):
            c.execute("INSERT INTO item_version_objective (item_version_id, objective_id) VALUES (?, ?)",
                      (vid, ids.get(("objective", code)) or _by_code(c, "objective", path_id, code)))  # fmt: skip
    else:
        c.execute(
            "INSERT INTO rendition_version (id, rendition_id, version_no, version_hash, lesson_version_id, lang, renderer, "
            "spec_kind, spec, narration, theme_id, voice, duration_s, derived_from_version_id, status, published_at, created_at, "
            "authorship, acquired_via, author_kind, author_ref, produced_by_stage_run_id, upstream, licence, personal_inputs) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'rendered', '{}', ?, NULL, ?, ?, NULL, 'passed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (vid, head_id, no, v["version_hash"], lesson_version, v["lang"], v["renderer"],
             json.dumps(v["narration"]) if v.get("narration") is not None else None, v.get("voice"), v.get("duration_s"),
             now, now, *common),
        )  # fmt: skip
        for a in v["assets"]:
            c.execute("INSERT INTO rendition_asset (rendition_version_id, role, lang, recipe_hash, asset_hash) VALUES (?, ?, ?, ?, ?)",
                      (vid, a["role"], a["lang"], a["recipe_hash"], a["sha256"]))  # fmt: skip
            c.execute("INSERT INTO asset_ref (asset_hash, owner_kind, owner_id, role) VALUES (?, 'rendition_version', ?, ?) "
                      "ON CONFLICT DO NOTHING", (a["sha256"], vid, a["role"]))  # fmt: skip
    for check in ("schema", "leak") if kind == "item" else ("schema",):
        c.execute("INSERT INTO quality_check (id, subject_kind, subject_version_id, \"check\", verdict, fix_round, independent, "
                  "details, stage_run_id, at) VALUES (?, ?, ?, ?, 'pass', 0, NULL, ?, NULL, ?)",
                  (new_id(), f"{kind}_version", vid, check, json.dumps({"on": "import"}), now))  # fmt: skip
    if v["version_hash"] == current:
        cur = c.execute(f"SELECT v.id, v.authorship FROM {head} h JOIN {table} v ON v.id = h.current_version_id WHERE h.id = ?",
                        (head_id,)).fetchone()  # fmt: skip
        if cur is not None and cur[1] == "human_edited":
            c.execute("INSERT INTO merge_conflict (id, head_kind, head_id, local_version_id, incoming_version_hash, status, "
                      "created_at, resolved_at) VALUES (?, ?, ?, ?, ?, 'open', ?, NULL)",
                      (new_id(), head, head_id, cur[0], v["version_hash"], now))  # fmt: skip
        else:
            c.execute(
                f"UPDATE {head} SET current_version_id = ?, state = 'ready' WHERE id = ?", (vid, head_id)
            )
    return vid
