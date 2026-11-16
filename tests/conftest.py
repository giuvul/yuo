import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from yuo.db.blobs import BlobStore
from yuo.db.connection import ReadPool, Writer, open_connection
from yuo.db.migrate import migrate


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("YUO_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live provider call: set YUO_LIVE=1")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "yuo.db"
    migrate(path, "test")
    return path


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    c = open_connection(db_path)
    yield c
    c.close()


@pytest.fixture
def writer(db_path: Path) -> Iterator[Writer]:
    w = Writer(db_path)
    yield w
    w.close()


@pytest.fixture
def readers(db_path: Path) -> Iterator[ReadPool]:
    p = ReadPool(db_path)
    yield p
    p.close()


@pytest.fixture
def blobs(tmp_path: Path) -> BlobStore:
    return BlobStore(tmp_path / "assets")
