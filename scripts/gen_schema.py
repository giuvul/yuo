"""The schema and its migrations: `uv run scripts/gen_schema.py --check`.

The row models in `yuo/db/rows.py` are the source. Migration 0001 is generated from them and never changes
once applied; later tables, indexes and lookup values each belong to a numbered migration
(`Table.since`, `extras.LATER`, `schema.SEEDED_LATER`).

    uv run scripts/gen_schema.py --check       0001 is unchanged, and a database built from migrations
                                               0001..N has exactly the schema the row models describe
    uv run scripts/gen_schema.py --print N     the generated share of migration N, to start its file from
    uv run scripts/gen_schema.py               rewrite 0001 (only before a first release of a new project)
"""

import sqlite3
import sys
import tempfile
from pathlib import Path

from yuo.core.enums import OPEN_ENUMS
from yuo.db.migrate import _statements, migrate
from yuo.db.schema import ddl, ddl_for, full_ddl

TARGET = Path(__file__).resolve().parents[1] / "yuo" / "db" / "migrations" / "0001_initial.sql"
# made by the migration runner or by SQLite itself, not by the row models
INFRA = ("schema_migration", "sqlite_")


def snapshot(conn: sqlite3.Connection) -> dict[tuple[str, str], str]:
    """Every schema object with its SQL, whitespace-normalised, plus the lookup tables' values."""
    out: dict[tuple[str, str], str] = {}
    for kind, name, sql in conn.execute("SELECT type, name, sql FROM sqlite_schema"):
        if name.startswith(INFRA):
            continue
        out[(kind, name)] = " ".join((sql or "").split())
    for table in OPEN_ENUMS:
        keys = sorted(r[0] for r in conn.execute(f'SELECT "key" FROM {table}'))
        out[("lookup", table)] = ",".join(keys)
    return out


def compare() -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        migrated = Path(tmp) / "migrated.db"
        migrate(migrated, "schema-check")
        a = sqlite3.connect(migrated)
        b = sqlite3.connect(Path(tmp) / "models.db")
        try:
            for statement in _statements(full_ddl()):
                b.execute(statement)
            b.commit()
            have, want = snapshot(a), snapshot(b)
        finally:
            a.close()
            b.close()
    problems = []
    for key in sorted(set(have) | set(want)):
        if key not in have:
            problems.append(f"{key[0]} {key[1]}: in the row models, missing from the migrations")
        elif key not in want:
            problems.append(f"{key[0]} {key[1]}: made by a migration, not in the row models")
        elif have[key] != want[key]:
            problems.append(
                f"{key[0]} {key[1]}: differs\n  migrations: {have[key]}\n  row models: {want[key]}"
            )
    return problems


def main() -> int:
    if "--print" in sys.argv:
        print(ddl_for(int(sys.argv[sys.argv.index("--print") + 1])), end="")
        return 0
    if "--check" in sys.argv:
        if TARGET.read_text(encoding="utf-8") != ddl():
            print(
                f"{TARGET.name} no longer matches the row models. It is applied on real installs and must not "
                "change: put new tables (Table.since), indexes (extras.LATER) and lookup values "
                "(schema.SEEDED_LATER) in a new numbered migration."
            )
            return 1
        problems = compare()
        for p in problems:
            print(p)
        if problems:
            print("the migrations and the row models disagree: add or fix a numbered migration")
        return 1 if problems else 0
    TARGET.write_text(ddl(), encoding="utf-8")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
