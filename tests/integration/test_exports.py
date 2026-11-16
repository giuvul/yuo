"""Standard-format exports on a generated path (scripted model): every v1 format inside a package, listed in
`yuo:standard` with what it represents, read back by the package reader, byte-identical across exports."""

import csv
import io
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests import fakes
from tests.integration.test_slice import NoPrices, create
from yuo.adapters.export import FORMATS
from yuo.main import Runtime, start
from yuo.sharing import package


@pytest.fixture
def rt(db_path: Path) -> Iterator[Runtime]:
    r = start(db_path, {"openrouter": fakes.FakeLLM()}, NoPrices(), worker=False)
    for role in ("generator", "reviewer", "grader", "utility"):
        r.service.bind(role, "openrouter", "deepseek/deepseek-v4-pro")
    yield r
    r.close()


def test_every_format_in_a_package(rt: Runtime, tmp_path: Path) -> None:
    path_id = create(rt)
    a, b = tmp_path / "a.zip", tmp_path / "b.zip"
    manifest = rt.service.export_package(path_id, a, profile="full", formats=sorted(FORMATS))
    rt.service.export_package(path_id, b, profile="full", formats=sorted(FORMATS))

    pkg = package.read(a)
    standard = manifest["extensions"]["yuo:standard"]
    assert {s["format"] for s in standard} >= {"csv", "anki-apkg", "moodle-xml", "readings"}
    for entry in standard:
        assert entry["represents"]["kind"] in ("item", "lesson", "rendition", "source")
    lessons = {x["code"] for x in pkg.records["lesson"] if x.get("current")}
    readings = next(s for s in standard if s["path"] == "standard/readings/index.html")["represents"]
    assert set(readings["codes"]) == lessons

    with zipfile.ZipFile(a) as za, zipfile.ZipFile(b) as zb:
        names = sorted(n for n in za.namelist() if n.startswith("standard/"))
        assert names == sorted(n for n in zb.namelist() if n.startswith("standard/"))
        assert all(za.read(n) == zb.read(n) for n in names)  # deterministic: same bytes every export
        rows = list(csv.DictReader(io.StringIO(za.read("standard/items.csv").decode(), newline="")))
        assert {r["code"] for r in rows} == {i["code"] for i in pkg.records["item"] if i.get("current")}
        quiz = ET.fromstring(za.read("standard/questions.xml"))
        assert quiz.find("question[@type='multichoice']") is not None
        with zipfile.ZipFile(io.BytesIO(za.read("standard/flashcards.apkg"))) as apkg:
            assert "collection.anki2" in apkg.namelist()
        for code in lessons:
            assert f"standard/readings/{code}.md" in names and f"standard/readings/{code}.html" in names
