"""Fitness functions for the physical schema."""

import sqlite3
from pathlib import Path

import pytest

from yuo.core.enums import OPEN_ENUMS
from yuo.db import rows  # noqa: F401
from yuo.db.migrate import MIGRATIONS, available, migrate
from yuo.db.schema import SEEDED_LATER, Row, columns, ddl, ddl_for, full_ddl

pytestmark = pytest.mark.fitness

# created by the migration runner, SQLite or FTS5 rather than by row models
INFRA = {"schema_migration", "sqlite_sequence", "lesson_fts", "material_fts"}


def _tables(conn: sqlite3.Connection) -> set[str]:
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")}
    return {n for n in names if not n.startswith(("lesson_fts_", "material_fts_"))} - INFRA


def test_migration_0001_is_generated_from_the_row_models() -> None:
    committed = (MIGRATIONS / "0001_initial.sql").read_text(encoding="utf-8")
    assert committed == ddl(), "0001 is applied on real installs: new objects go in a new numbered migration"


def test_migrations_build_the_schema_of_the_row_models() -> None:
    """A database migrated 0001..N equals one built from the models (what gen_schema.py --check runs)."""
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "scripts" / "gen_schema.py"
    spec = importlib.util.spec_from_file_location("gen_schema", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.compare() == []


def test_every_later_table_and_seed_names_an_existing_migration() -> None:
    versions = {m.version for m in available()}
    later = {m.table.since for m in Row.registry.values()} | {
        n for v in SEEDED_LATER.values() for n in v.values()
    }
    assert later <= versions
    for version in sorted(later - {1}):
        sql = next(m.sql for m in available() if m.version == version)
        for line in ddl_for(version).splitlines():
            assert line in sql, f"migration {version:04d} lacks: {line}"
    assert "objective_review_state" in full_ddl() and "objective_review_state" not in ddl()


def test_an_install_on_0002_upgrades_in_place(tmp_path: Path) -> None:
    """An existing database has 0001 and 0002 applied and data in it: the later migrations apply on top."""
    import shutil

    old = tmp_path / "migrations"
    old.mkdir()
    for name in ("0001_initial.sql", "0002_level_check.sql"):
        shutil.copy(MIGRATIONS / name, old / name)
    db = tmp_path / "yuo.db"
    assert migrate(db, "0.7.4", old) == [1, 2]
    c = sqlite3.connect(db)
    c.execute(
        "INSERT INTO setting_value (id, key, scope, value, data_class, updated_at) VALUES "
        "('01900000-0000-7000-8000-000000000001', 'probe', 'installation', '1', 'K', '2026-11-12T00:00:00.000Z')"
    )
    c.commit()
    c.close()
    assert migrate(db, "0.7.5") == [3, 4, 5, 6, 7, 8, 9]
    c = sqlite3.connect(db)
    assert c.execute("SELECT value FROM setting_value WHERE key = 'probe'").fetchone() == ("1",)
    assert c.execute("SELECT count(*) FROM objective_review_state").fetchone() == (0,)
    assert c.execute("SELECT 1 FROM stage_kind WHERE key = 'review_bank'").fetchone() == (1,)
    assert c.execute("SELECT count(*) FROM stage_kind WHERE key LIKE 'next_%'").fetchone() == (3,)
    assert c.execute("SELECT count(*) FROM material").fetchone() == (0,)
    c.close()


def test_every_row_model_has_a_table_and_no_table_lacks_one(conn: sqlite3.Connection) -> None:
    assert _tables(conn) == set(Row.registry)


@pytest.mark.parametrize("name", sorted(Row.registry))
def test_columns_match_the_row_model(conn: sqlite3.Connection, name: str) -> None:
    model = Row.registry[name]
    found = {r["name"]: r for r in conn.execute(f"PRAGMA table_xinfo({name})")}
    expected = columns(model)
    assert list(found) == [c.name for c in expected], "column names or order differ"
    for c in expected:
        row = found[c.name]
        assert row["type"] == c.sql_type, f"{name}.{c.name} type"
        is_rowid_alias = row["pk"] and c.sql_type == "INTEGER" and len(model.table.pk) == 1
        if not is_rowid_alias:
            assert bool(row["notnull"]) == (not c.nullable), f"{name}.{c.name} nullability"
    pk = [r["name"] for r in sorted(found.values(), key=lambda r: r["pk"]) if r["pk"]]
    assert pk == list(model.table.pk)


def test_all_tables_are_strict(conn: sqlite3.Connection) -> None:
    lax = [
        r["name"]
        for r in conn.execute("PRAGMA table_list")
        if r["schema"] == "main" and r["type"] == "table" and r["name"] in Row.registry and not r["strict"]
    ]
    assert lax == []


def test_open_enum_lookup_tables_match_the_python_enums(conn: sqlite3.Connection) -> None:
    for table, enum in OPEN_ENUMS.items():
        assert {r[0] for r in conn.execute(f'SELECT "key" FROM {table}')} == {v.value for v in enum}, table


def test_every_version_table_has_its_invariant_triggers(conn: sqlite3.Connection) -> None:
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_schema WHERE type = 'trigger'")}
    versions = [m.table for m in Row.registry.values() if m.table.kind == "version"]
    assert {t.name for t in versions} == {"lesson_version", "rendition_version", "item_version"}
    for t in versions:
        assert t.head is not None
        head = t.head[0]
        for trg in (
            f"{t.name}_immutable",
            f"{t.name}_no_delete",
            f"{t.name}_lang",
            f"{head}_current_passed_insert",
            f"{head}_current_passed_update",
        ):
            assert trg in triggers, trg
    assert {"learning_event_no_update", "learning_event_no_delete"} <= triggers


def test_immutability_trigger_covers_every_column() -> None:
    """A new column on a version table cannot be silently exempt."""
    sql = ddl()
    for model in Row.registry.values():
        if model.table.kind != "version":
            continue
        body = sql.split(f"CREATE TRIGGER {model.table.name}_immutable", 1)[1].split("END;", 1)[0]
        for c in columns(model):
            if c.name not in ("status", "published_at"):
                assert f"OLD.{c.name} IS NOT NEW.{c.name}" in body, f"{model.table.name}.{c.name}"


def test_every_table_has_a_data_class() -> None:
    for name, model in Row.registry.items():
        if model.table.data_class is None:
            has_column = any(c.name == "data_class" for c in columns(model))
            assert has_column or model.table.personal_when, f"{name}: no table or row data class"
