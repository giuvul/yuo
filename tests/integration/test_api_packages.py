"""Packages over HTTP: export preview, download, upload with a preview, import; a refused upload writes nothing."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests import fakes
from tests.integration.test_slice import NoPrices, create, lessons_of
from yuo.api.app import create_app
from yuo.db.blobs import BlobStore
from yuo.db.migrate import migrate
from yuo.main import Media, Runtime, start

FIXTURES = Path(__file__).resolve().parents[2] / "docs" / "spec" / "fixtures"


@pytest.fixture
def two(tmp_path: Path) -> Iterator[tuple[tuple[Runtime, TestClient], tuple[Runtime, TestClient]]]:
    out = []
    for name in ("a", "b"):
        db = tmp_path / name / "yuo.db"
        db.parent.mkdir()
        migrate(db, "test")
        rt = start(db, {"openrouter": fakes.FakeLLM()}, NoPrices(), worker=False,
                   media=Media(blobs=BlobStore(db.parent / "blobs"), media_dir=db.parent / "media"))  # fmt: skip
        for role in ("generator", "reviewer", "grader", "utility"):
            rt.service.bind(role, "openrouter", "deepseek/deepseek-v4-pro")
        out.append((rt, TestClient(create_app(version="test", health=dict, service=rt.service))))
    yield out[0], out[1]
    for rt, _ in out:
        rt.close()


def test_export_then_import_over_http(
    two: tuple[tuple[Runtime, TestClient], tuple[Runtime, TestClient]],
) -> None:
    (a, http_a), (b, http_b) = two
    path_id = create(a)
    preview = http_a.post(f"/api/paths/{path_id}/export-preview", json={"profile": "structure"}).json()
    assert preview["counts"]["lesson"] >= 1 and preview["personal_included"] == []
    r = http_a.post(f"/api/paths/{path_id}/export", json={"profile": "structure"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert 'filename="SQL.yuo.zip"' in r.headers["content-disposition"]
    assert not list((a.service.package_dir).glob("export-*"))  # removed once sent

    up = http_b.post("/api/packages", content=r.content, headers={"Content-Type": "application/zip"}).json()
    assert up["error"] is None and up["preview"]["title"] == "SQL" and up["preview"]["can_create"]
    done = http_b.post(f"/api/packages/{up['token']}/import", json={"mode": "new"}).json()
    assert [lesson["code"] for lesson in lessons_of(b, done["path_id"])] == [
        lesson["code"] for lesson in lessons_of(a, path_id)
    ]
    assert http_b.post(f"/api/packages/{up['token']}/import", json={}).status_code == 404  # used once


def test_a_refused_upload_says_why_and_imports_nothing(
    two: tuple[tuple[Runtime, TestClient], tuple[Runtime, TestClient]],
) -> None:
    _, (b, http) = two
    bad = (FIXTURES / "invalid/path-traversal.yuo.zip").read_bytes()
    up = http.post("/api/packages", content=bad).json()
    assert up["preview"] is None and "bad file name" in up["error"]
    assert not list(b.service.package_dir.glob("upload-*"))
    with b.readers.connection() as c:
        assert c.execute("SELECT count(*) FROM path").fetchone()[0] == 0


def test_abandoned_uploads_are_swept(
    two: tuple[tuple[Runtime, TestClient], tuple[Runtime, TestClient]],
) -> None:
    import os

    _, (b, http) = two
    old = b.service.upload_file("stale")
    old.write_bytes(b"x")
    os.utime(old, (0, 0))
    http.post("/api/packages", content=b"not a zip")
    assert not old.exists()
