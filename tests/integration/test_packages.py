"""Path packages (spec 1.0): conformance fixtures, the round trip on a second install, updates, merge
conflicts, and personal content kept out by default."""

import json
import sqlite3
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tests import fakes
from tests.integration.test_slice import NoPrices, create, drain, lessons_of
from tests.package_fixtures import EXPECT, build
from yuo.core.ids import new_id
from yuo.db.blobs import BlobStore
from yuo.db.migrate import migrate
from yuo.main import Media, Runtime, start
from yuo.sharing import package as pk

FIXTURES = Path(__file__).resolve().parents[2] / "docs" / "spec" / "fixtures"
type Install = Callable[[str], Runtime]


@pytest.fixture
def install(tmp_path: Path) -> Iterator[Install]:
    made: list[Runtime] = []

    def make(name: str) -> Runtime:
        db = tmp_path / name / "yuo.db"
        db.parent.mkdir()
        migrate(db, "test")
        rt = start(
            db,
            {"openrouter": fakes.FakeLLM()},
            NoPrices(),
            worker=False,
            media=Media(blobs=BlobStore(db.parent / "blobs")),
        )
        for role in ("generator", "reviewer", "grader", "utility"):
            rt.service.bind(role, "openrouter", "deepseek/deepseek-v4-pro")
        made.append(rt)
        return rt

    yield make
    for rt in made:
        rt.close()


def record_files(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist() if n.startswith("records/")}


def test_the_committed_fixtures_are_current(tmp_path: Path) -> None:
    build(tmp_path)
    for name in EXPECT:
        made, kept = tmp_path / f"{name}.yuo.zip", FIXTURES / f"{name}.yuo.zip"
        assert made.read_bytes() == kept.read_bytes(), f"{name}: run `uv run scripts/gen_package_fixtures.py`"
    assert json.loads((FIXTURES / "expected.json").read_text()) == EXPECT


@pytest.mark.parametrize("name", [n for n, why in EXPECT.items() if why])
def test_invalid_packages_are_refused(name: str, install: Install) -> None:
    rt = install("a")
    with pytest.raises(pk.PackageError, match=EXPECT[name] or ""):
        rt.service.preview_package(FIXTURES / f"{name}.yuo.zip")
    with rt.readers.connection() as c:
        assert c.execute("SELECT count(*) FROM path").fetchone()[0] == 0  # nothing written


@pytest.mark.parametrize("name", ["valid/minimal", "valid/structure", "valid/full", "valid/older-version",
                                  "valid/unknown-extension", "valid/unknown-exercise-type"])  # fmt: skip
def test_valid_packages_round_trip_through_a_second_install(
    name: str, install: Install, tmp_path: Path
) -> None:
    """Spec §14: import then export yields byte-identical record files and the same inventory."""
    rt = install("b")
    fixture = FIXTURES / f"{name}.yuo.zip"
    incoming = pk.read(fixture)
    preview = rt.service.preview_package(fixture)
    assert preview["update_of"] is None and preview["can_create"]
    path_id = rt.service.import_package(fixture)
    out = tmp_path / "again.yuo.zip"
    manifest = rt.service.export_package(path_id, out, profile=incoming.manifest["profile"])
    again = pk.read(out)
    for kind, rows in incoming.records.items():
        assert pk.jsonl(kind, again.records.get(kind, [])) == pk.jsonl(kind, rows), kind
    assert manifest["package_uid"] == incoming.manifest["package_uid"]
    assert manifest["content_version"] == incoming.manifest["content_version"]
    if incoming.upgraded_from is None:
        assert record_files(out) == record_files(fixture)
        assert manifest["inventory"] == incoming.manifest["inventory"]
        assert manifest["extensions"] == incoming.manifest["extensions"]
    drain(rt)
    for lesson in lessons_of(
        rt, path_id
    ):  # the imported path is usable: practice works where there are items
        if lesson["state"] == "ready":
            rt.service.start_practice(lesson["id"])
            drain(rt)


def test_a_component_package_updates_the_path_it_came_with(install: Install, tmp_path: Path) -> None:
    rt = install("b")
    path_id = rt.service.import_package(FIXTURES / "valid/structure.yuo.zip")
    items = FIXTURES / "valid/custom-items-only.yuo.zip"
    preview = rt.service.preview_package(items)
    assert preview["update_of"] == path_id and not preview["can_create"]
    with pytest.raises(ValueError, match="only update"):
        rt.service.import_package(items, mode="new")
    assert rt.service.import_package(items, mode="update") == path_id
    out = tmp_path / "items.yuo.zip"
    rt.service.export_package(path_id, out, profile="custom", components={"items"})
    assert record_files(out) == record_files(items)


def test_full_round_trip_from_a_generated_path(install: Install, tmp_path: Path) -> None:
    """On a path the app made itself: each profile, export -> import -> export."""
    a, b = install("a"), install("b")
    path_id = create(a)
    for profile, components in (("structure", None), ("full", None), ("custom", {"curriculum", "items"})):
        first, second = tmp_path / f"{profile}-a.zip", tmp_path / f"{profile}-b.zip"
        a.service.export_package(path_id, first, profile=profile, components=components)
        known = b.service.preview_package(first)["update_of"]
        imported = b.service.import_package(first, mode="update" if known else "new")
        b.service.export_package(imported, second, profile=profile, components=components)
        assert record_files(second) == record_files(first), profile
        assert pk.read(second).manifest["package_uid"] == pk.read(first).manifest["package_uid"]


def _new_lesson_version(
    rt: Runtime, lesson_id: str, title: str, authorship: str = "generated", personal: bool = False
) -> None:
    def unit(c: sqlite3.Connection) -> None:
        c.row_factory = sqlite3.Row
        v = c.execute(
            "SELECT v.* FROM lesson l JOIN lesson_version v ON v.id = l.current_version_id WHERE l.id = ?",
            (lesson_id,),
        ).fetchone()
        new = dict(v) | {"id": new_id(), "version_no": v["version_no"] + 1, "title": title, "authorship": authorship,
                         "version_hash": "f" * 64, "personal_inputs": int(personal)}  # fmt: skip
        c.execute(
            f"INSERT INTO lesson_version ({', '.join(new)}) VALUES ({', '.join('?' * len(new))})",
            tuple(new.values()),
        )
        c.execute("UPDATE lesson SET current_version_id = ? WHERE id = ?", (new["id"], lesson_id))

    rt.writer.run(unit)


def test_an_update_brings_new_versions_and_keeps_a_learners_edit(install: Install, tmp_path: Path) -> None:
    a, b = install("a"), install("b")
    path_id = create(a)
    a.service.export_package(path_id, tmp_path / "v1.zip", profile="structure")
    local = b.service.import_package(tmp_path / "v1.zip")
    ready = [lesson for lesson in lessons_of(a, path_id) if lesson["state"] == "ready"]
    first, second = ready[0], ready[1]
    _new_lesson_version(a, first["id"], "Select, corrected")
    _new_lesson_version(a, second["id"], "Where, corrected")
    m = a.service.export_package(path_id, tmp_path / "v2.zip", profile="structure")
    assert m["content_version"] == "1.1.0"
    mine = {lesson["code"]: lesson for lesson in lessons_of(b, local)}
    _new_lesson_version(b, mine[second["code"]]["id"], "My own notes on where", authorship="human_edited")

    preview = b.service.preview_package(tmp_path / "v2.zip")
    assert preview["update_of"] == local and preview["installed_version"] == "1.0.0"
    b.service.import_package(tmp_path / "v2.zip", mode="update")
    after = {
        lesson["code"]: b.service.lesson_view(lesson["id"])
        for lesson in lessons_of(b, local)
        if lesson["state"] == "ready"
    }
    assert after[first["code"]]["title"] == "Select, corrected"
    assert after[second["code"]]["title"] == "My own notes on where"  # the learner's edit stays current
    with b.readers.connection() as c:
        assert c.execute("SELECT count(*) FROM merge_conflict WHERE status = 'open'").fetchone()[0] == 1


def test_personal_content_stays_out_unless_chosen(install: Install, tmp_path: Path) -> None:
    a, b = install("a"), install("b")
    path_id = create(a)
    lesson = next(lesson for lesson in lessons_of(a, path_id) if lesson["state"] == "ready")
    _new_lesson_version(a, lesson["id"], "Select, for me", personal=True)  # versions are immutable: a new one
    a.service.export_package(path_id, tmp_path / "default.zip", profile="structure")
    shared = {r["code"]: r for r in pk.read(tmp_path / "default.zip").records["lesson"]}
    assert (
        shared[lesson["code"]]["versions"] == []
    )  # the lesson's place in the tree travels, its text does not
    m = a.service.export_package(path_id, tmp_path / "chosen.zip", profile="structure", include_personal=True)
    assert m["inventory"]["counts"]["by_data_class"]["F"] == 1
    preview = b.service.preview_package(tmp_path / "chosen.zip")
    assert preview["personal"] == [f"lesson {lesson['code']}"]
