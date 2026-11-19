"""Row-model metadata and the DDL generator.

Every table is a Pydantic `Row` subclass. Column types come from the annotation (logical types below,
`StrEnum` subclasses, `bool`, `int`, `float`, `str`), constraints from `Col` metadata, and table-level
facts from the `table` class variable. `ddl()` turns the registry into migration 0001; the fitness tests
compare the migrated database with these models, so the two cannot drift.
"""

from __future__ import annotations

import inspect
import types
import typing
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, JsonValue

from yuo.core.enums import OPEN_ENUMS, DataClass

LogicalKind = Literal[
    "uuid7",
    "hash",
    "timestamp",
    "date",
    "time",
    "json",
    "lang",
    "tz",
    "text",
    "int",
    "decimal",
    "bool",
    "enum",
    "money_micros",
    "currency",
]


@dataclass(frozen=True, slots=True)
class Logical:
    kind: LogicalKind


@dataclass(frozen=True, slots=True)
class Col:
    """Column constraints beyond what the type implies."""

    fk: str | None = None  # "table" (-> its id) or "table(col)"
    check: str | None = None  # extra CHECK; `{c}` is replaced by the column name
    default: str | None = None  # SQL literal
    unique: bool = False


Uuid7 = Annotated[str, Logical("uuid7")]
Hash = Annotated[str, Logical("hash")]
Timestamp = Annotated[str, Logical("timestamp")]
Date = Annotated[str, Logical("date")]
Time = Annotated[str, Logical("time")]
Json = Annotated[JsonValue, Logical("json")]
Lang = Annotated[str, Logical("lang")]
Tz = Annotated[str, Logical("tz")]
Micros = Annotated[int, Logical("money_micros")]
Currency = Annotated[str, Logical("currency")]

TableKind = Literal["entity", "head", "version", "link", "projection", "event", "lookup", "guard"]


@dataclass(frozen=True, slots=True)
class FK:
    cols: tuple[str, ...]
    ref: str
    ref_cols: tuple[str, ...]
    deferred: bool = False


@dataclass(frozen=True, slots=True)
class Table:
    name: str
    kind: TableKind
    # None: the class is per row (a `data_class` column, or `row_class` below)
    data_class: DataClass | None
    pk: tuple[str, ...] = ("id",)
    unique: tuple[tuple[str, ...], ...] = ()
    fks: tuple[FK, ...] = ()
    checks: tuple[str, ...] = ()
    # version tables: the head table and the column pointing at it
    head: tuple[str, str] | None = None
    # SQL expression (over the row) for the path whose content_lang the row's `lang` must equal
    lang_of: str | None = None
    # SQL predicate (over the row) that makes a C row personal (F), e.g. learner-authored versions
    personal_when: str | None = None
    without_rowid: bool = False
    # the migration that creates the table: 1 is 0001_initial; later tables name their own migration
    since: int = 1


class Row(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)
    table: ClassVar[Table]
    registry: ClassVar[dict[str, type[Row]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "table" in cls.__dict__:
            if cls.table.name in Row.registry:
                raise ValueError(f"duplicate table {cls.table.name}")
            Row.registry[cls.table.name] = cls


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    logical: LogicalKind
    sql_type: Literal["TEXT", "INTEGER", "REAL"]
    nullable: bool
    enum: type[StrEnum] | None = None
    col: Col = field(default_factory=Col)

    def checks(self) -> list[str]:
        c = _quote(self.name)
        out: list[str] = []
        match self.logical:
            case "uuid7":
                out.append(f"length({c})=36 AND substr({c},15,1)='7' AND {c}=lower({c})")
            case "hash":
                out.append(f"length({c})=64 AND {c} NOT GLOB '*[^0-9a-f]*'")
            case "timestamp":
                out.append(f"{c} = strftime('%Y-%m-%dT%H:%M:%fZ', {c})")
            case "date":
                out.append(f"{c} = date({c})")
            case "time":
                out.append(f"{c} = strftime('%H:%M', '2000-01-01 ' || {c})")
            case "bool":
                out.append(f"{c} IN (0,1)")
            case "json":
                out.append(f"json_valid({c})")
            case "lang":
                out.append(f"length({c}) BETWEEN 2 AND 35")
            case "tz":
                out.append(f"length({c}) BETWEEN 1 AND 64")
            case "currency":
                out.append(f"length({c})=3 AND {c}=upper({c})")
            case "enum" if self.enum is not None and not is_open(self.enum):
                values = ",".join(f"'{v.value}'" for v in self.enum)
                out.append(f"{c} IN ({values})")
            case _:
                pass
        if self.col.check:
            out.append(self.col.check.format(c=c))
        return out

    def references(self) -> tuple[str, str] | None:
        if self.col.fk:
            ref = self.col.fk
            if "(" in ref:
                t, rest = ref.split("(", 1)
                return t, rest.rstrip(")")
            return ref, "id"
        if self.enum is not None and is_open(self.enum):
            return lookup_table(self.enum), "key"
        return None


def is_open(enum: type[StrEnum]) -> bool:
    return enum in OPEN_ENUMS.values()


def lookup_table(enum: type[StrEnum]) -> str:
    return next(name for name, e in OPEN_ENUMS.items() if e is enum)


def _unwrap(annotation: Any) -> tuple[Any, bool, Logical | None, Col]:
    nullable = False
    logical: Logical | None = None
    col = Col()
    tp = annotation
    while True:
        origin = typing.get_origin(tp)
        if origin is Annotated:
            base, *meta = typing.get_args(tp)
            for m in meta:
                if isinstance(m, Logical):
                    logical = logical or m
                elif isinstance(m, Col):
                    col = m
            tp = base
        elif origin in (types.UnionType, typing.Union):
            args = [a for a in typing.get_args(tp) if a is not type(None)]
            if len(args) != len(typing.get_args(tp)):
                nullable = True
            if len(args) != 1:
                # JsonValue is itself a union; treat any remaining union as json if marked so
                if logical is not None and logical.kind == "json":
                    return tp, nullable, logical, col
                raise TypeError(f"unsupported union {tp!r}")
            tp = args[0]
        elif isinstance(tp, typing.TypeAliasType):
            tp = tp.__value__
        else:
            return tp, nullable, logical, col


def columns(model: type[Row]) -> list[Column]:
    out: list[Column] = []
    hints = typing.get_type_hints(model, include_extras=True)
    own = inspect.get_annotations(model)
    # the table's own columns first, inherited blocks (provenance, projection metadata) after
    names = [n for n in model.model_fields if n in own] + [n for n in model.model_fields if n not in own]
    for name in names:
        tp, nullable, logical, col = _unwrap(hints[name])
        enum: type[StrEnum] | None = None
        if logical is not None:
            kind = logical.kind
        elif isinstance(tp, type) and issubclass(tp, StrEnum):
            kind, enum = "enum", tp
        elif tp is bool:
            kind = "bool"
        elif tp is int:
            kind = "int"
        elif tp is float:
            kind = "decimal"
        elif tp is str:
            kind = "text"
        else:
            raise TypeError(f"{model.table.name}.{name}: unsupported type {tp!r}")
        sql = {"int": "INTEGER", "bool": "INTEGER", "money_micros": "INTEGER", "decimal": "REAL"}.get(
            kind, "TEXT"
        )
        out.append(Column(name, kind, sql, nullable, enum, col))  # type: ignore[arg-type]
    return out


def _quote(name: str) -> str:
    return f'"{name}"' if name in {"check", "key", "order", "by", "at", "role", "text"} else name


# A column CHECK that a later migration widened (only ever more allowed values): the migration it changed in, and
# the CHECK as an older migration created it, so migration 0001's text never changes.
WIDENED: dict[tuple[str, str], tuple[int, str]] = {
    ("generation_job", "kind"): (
        5,
        "kind IN ('tree','lesson','rendition','items','translation','remedial','test_bank','placement','grade',"
        "'request')",
    ),
}


def create_table(model: type[Row], as_of: int | None = None) -> str:
    """The table's CREATE statement as the row model says today, or as migration `as_of` created it."""
    t = model.table
    cols = columns(model)
    lines: list[str] = []
    single_pk = t.pk if len(t.pk) == 1 else ()
    for c in cols:
        parts = [_quote(c.name).ljust(28), c.sql_type]
        if t.kind == "event" and c.name == "server_seq":
            lines.append(f"  {_quote(c.name).ljust(28)} INTEGER PRIMARY KEY AUTOINCREMENT")
            continue
        if c.name in single_pk:
            parts.append("PRIMARY KEY")
        if not c.nullable:
            parts.append("NOT NULL")
        if c.col.unique:
            parts.append("UNIQUE")
        if c.col.default is not None:
            parts.append(f"DEFAULT {c.col.default}")
        checks = c.checks()
        widened = WIDENED.get((t.name, c.name))
        if widened is not None and as_of is not None and as_of < widened[0]:
            checks = [widened[1] if chk.startswith(f"{_quote(c.name)} IN (") else chk for chk in checks]
        for chk in checks:
            parts.append(f"CHECK ({chk})")
        ref = c.references()
        if ref:
            parts.append(f"REFERENCES {ref[0]}({_quote(ref[1])})")
        lines.append("  " + " ".join(parts))
    if len(t.pk) > 1:
        lines.append(f"  PRIMARY KEY ({', '.join(_quote(p) for p in t.pk)})")
    for u in t.unique:
        lines.append(f"  UNIQUE ({', '.join(_quote(x) for x in u)})")
    for fk in t.fks:
        tail = " DEFERRABLE INITIALLY DEFERRED" if fk.deferred else ""
        lines.append(
            f"  FOREIGN KEY ({', '.join(fk.cols)}) REFERENCES {fk.ref} ({', '.join(fk.ref_cols)}){tail}"
        )
    for chk in t.checks:
        lines.append(f"  CHECK ({chk})")
    opts = "STRICT, WITHOUT ROWID" if t.without_rowid else "STRICT"
    return f"CREATE TABLE {t.name} (\n" + ",\n".join(lines) + f"\n) {opts};"


def _changed(cols: list[Column], allowed: set[str]) -> str:
    return " OR ".join(
        f"OLD.{_quote(c.name)} IS NOT NEW.{_quote(c.name)}" for c in cols if c.name not in allowed
    )


GUARD = "NOT EXISTS (SELECT 1 FROM erasure_guard)"


def triggers(model: type[Row]) -> list[str]:
    """Row-local invariants, generated from the column list."""
    t = model.table
    cols = columns(model)
    out: list[str] = []
    if t.kind == "event":
        out.append(
            f"CREATE TRIGGER {t.name}_no_update BEFORE UPDATE ON {t.name}\n"
            f"BEGIN SELECT RAISE(ABORT, '{t.name} is append-only'); END;"
        )
    if t.kind in ("event", "version"):
        out.append(
            f"CREATE TRIGGER {t.name}_no_delete BEFORE DELETE ON {t.name}\nWHEN {GUARD}\n"
            f"BEGIN SELECT RAISE(ABORT, '{t.name} rows are deleted only by erasure'); END;"
        )
    if t.kind == "version":
        changed = _changed(cols, {"status", "published_at"})
        out.append(
            f"CREATE TRIGGER {t.name}_immutable BEFORE UPDATE ON {t.name}\n"
            f"WHEN {GUARD} AND ({changed}\n"
            f"  OR (OLD.status IS NOT NEW.status AND (OLD.status <> 'in_review' OR NEW.status = 'in_review'))\n"
            f"  OR (OLD.published_at IS NOT NULL AND OLD.published_at IS NOT NEW.published_at))\n"
            f"BEGIN SELECT RAISE(ABORT, '{t.name} is immutable except status and published_at, set once'); END;"
        )
        assert t.head is not None
        head, _ = t.head
        for ev in ("INSERT", "UPDATE OF current_version_id"):
            suffix = "insert" if ev == "INSERT" else "update"
            out.append(
                f"CREATE TRIGGER {head}_current_passed_{suffix} BEFORE {ev} ON {head}\n"
                f"WHEN NEW.current_version_id IS NOT NULL\n"
                f"  AND (SELECT status FROM {t.name} WHERE id = NEW.current_version_id) IS NOT 'passed'\n"
                f"BEGIN SELECT RAISE(ABORT, '{head}.current_version_id must point to a passed version'); END;"
            )
    if t.lang_of:
        out.append(
            f"CREATE TRIGGER {t.name}_lang BEFORE INSERT ON {t.name}\n"
            f"WHEN NEW.lang IS NOT ({t.lang_of.replace('{row}', 'NEW')})\n"
            f"BEGIN SELECT RAISE(ABORT, '{t.name}.lang must equal path.content_lang'); END;"
        )
    return out


# Lookup values added after 0001 was applied somewhere: a later migration seeds them, so 0001 stays the
# same text (an applied migration that changes is refused).
SEEDED_LATER: dict[str, dict[str, int]] = {
    "stage_kind": {
        "level_check": 2,
        "review_bank": 3,
        "next_check": 4,
        "next_directions": 4,
        "next_grow": 4,
        "tree_revise": 5,
        "material_digest": 5,
        "material_outline": 5,
        "course_outline": 5,
        "course_revise": 5,
        "course_links": 5,
        "material_vision": 6,
        "studies_arrange": 7,
    },
    "entity_kind_ref": {
        "material": 5,
        "course": 5,
    },
}


def _objects(since: int | None) -> list[str]:
    """Tables, then their triggers, in a stable order; `since` picks one migration's share (None: all)."""
    from yuo.db import extras, rows  # noqa: F401  (registers the row models)

    names = [n for n in sorted(Row.registry) if since is None or Row.registry[n].table.since == since]
    parts: list[str] = []
    for name in names:
        parts.append(create_table(Row.registry[name], as_of=since))
        parts.append("")
    for name in names:
        for trg in triggers(Row.registry[name]):
            parts.append(trg)
            parts.append("")
    return parts


def ddl() -> str:
    """Migration 0001: every table of the first schema, with triggers, indexes and lookup seeds.

    0001 is applied on real installs and an applied migration that changes is refused, so this text never
    changes: later tables carry `Table.since`, later lookup values are in `SEEDED_LATER`, later indexes in
    `extras.LATER`, and each has its own numbered migration (`ddl_for`).
    """
    from yuo.db import extras

    parts = [
        "-- 0001_initial: generated by `uv run scripts/gen_schema.py` from yuo/db/rows.py. Do not edit.",
        "",
    ]
    parts.extend(_objects(1))
    parts.extend(extras.EXTRA)
    parts.append("")
    for table, enum in sorted(OPEN_ENUMS.items()):
        values = ", ".join(f"('{v.value}')" for v in enum if v.value not in SEEDED_LATER.get(table, {}))
        parts.append(f'INSERT INTO {table} ("key") VALUES {values};')
    return "\n".join(parts).rstrip() + "\n"


def ddl_for(version: int) -> str:
    """The generated share of a later migration: its tables, triggers, indexes and lookup seeds."""
    from yuo.db import extras

    parts = _objects(version)
    parts.extend(extras.LATER.get(version, []))
    parts.append("")
    for table, later in sorted(SEEDED_LATER.items()):
        for value in sorted(v for v, n in later.items() if n == version):
            parts.append(f"INSERT INTO {table} (\"key\") VALUES ('{value}');")
    return "\n".join(parts).rstrip() + "\n"


def full_ddl() -> str:
    """The whole schema as the row models describe it today: what every migrated database must equal."""
    from yuo.db import extras

    parts = _objects(None)
    parts.extend(extras.EXTRA)
    for version in sorted(extras.LATER):
        parts.extend(extras.LATER[version])
    parts.append("")
    for table, enum in sorted(OPEN_ENUMS.items()):
        values = ", ".join(f"('{v.value}')" for v in enum)
        parts.append(f'INSERT INTO {table} ("key") VALUES {values};')
    return "\n".join(parts).rstrip() + "\n"
