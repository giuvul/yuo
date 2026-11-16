"""Startup and code-shape rules."""

import ast
from pathlib import Path

import pytest

from yuo.core.errors import StartupError
from yuo.db.connection import check_sqlite_version, open_connection

pytestmark = pytest.mark.fitness
ROOT = Path(__file__).resolve().parents[2]
GPL_TOOLS = ("ffmpeg", "ffprobe", "espeak-ng", "espeak")


@pytest.mark.parametrize("version", ["3.45.1", "3.53.0", "3.37.2"])
def test_sqlite_version_check_fails_closed(version: str) -> None:
    with pytest.raises(StartupError, match=r"SQLite 3\.53\.1 or newer"):
        check_sqlite_version(version)


def test_sqlite_version_check_passes_on_the_uv_python() -> None:
    check_sqlite_version()


def test_connections_use_the_required_pragmas(tmp_path: Path) -> None:
    c = open_connection(tmp_path / "x.db")
    try:
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert c.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
        assert c.execute("PRAGMA trusted_schema").fetchone()[0] == 0
        assert c.execute("PRAGMA secure_delete").fetchone()[0] == 1
    finally:
        c.close()


def test_gpl_tools_are_spawned_only_from_adapters_tools() -> None:
    """GPL executables run as separate programs, from one adapter module per tool."""
    offenders = []
    for f in (ROOT / "yuo").rglob("*.py"):
        if f.is_relative_to(ROOT / "yuo" / "adapters" / "tools"):
            continue
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in GPL_TOOLS:
                offenders.append(f"{f.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []


def test_uvicorn_runs_with_one_worker_in_every_shipped_config() -> None:
    for f in [*(ROOT / "packaging").rglob("*"), *(ROOT / "yuo").rglob("*.py")]:
        if f.is_file():
            text = f.read_text(encoding="utf-8", errors="ignore")
            assert "--workers" not in text.replace("--workers 1", "").replace("--workers=1", ""), f
            assert "workers=" not in text.replace("workers=1", ""), f


def test_container_image_does_not_use_a_python_base() -> None:
    for f in (ROOT / "packaging").rglob("Dockerfile*"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip().upper().startswith("FROM"):
                assert "python:" not in line, f"{f}: {line}"


def test_text_pipes_name_their_encoding() -> None:
    """A text-mode pipe without an encoding decodes with the ANSI code page on Windows, which turned a CLI's
    UTF-8 en dash into "â€“". Every `text=True` call names UTF-8."""
    offenders = []
    for base in ("yuo", "packaging"):
        for path in (ROOT / base).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.Call):
                    continue
                kw = {k.arg: k.value for k in node.keywords}
                text = kw.get("text") or kw.get("universal_newlines")
                if isinstance(text, ast.Constant) and text.value is True and "encoding" not in kw:
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []
