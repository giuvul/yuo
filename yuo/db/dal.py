"""Thin typed helpers between row models and SQL. Hand-written SQL stays the norm; these cover the
mechanical insert/load of whole rows."""

import json
import sqlite3
from enum import StrEnum
from typing import Any

from yuo.db.schema import Row, columns


def _to_sql(logical: str, value: Any) -> Any:
    if value is None:
        return None
    if logical == "json":
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, StrEnum):
        return value.value
    return value


def insert(conn: sqlite3.Connection, row: Row) -> None:
    cols = [c for c in columns(type(row)) if not (row.table.kind == "event" and c.name == "server_seq")]
    names = ", ".join(f'"{c.name}"' for c in cols)
    marks = ", ".join("?" for _ in cols)
    values = [_to_sql(c.logical, getattr(row, c.name)) for c in cols]
    conn.execute(f"INSERT INTO {row.table.name} ({names}) VALUES ({marks})", values)


def load[R: Row](model: type[R], record: sqlite3.Row) -> R:
    data: dict[str, Any] = {}
    for c in columns(model):
        v = record[c.name]
        if v is not None and c.logical == "json":
            v = json.loads(v)
        elif v is not None and c.logical == "bool":
            v = bool(v)
        data[c.name] = v
    return model.model_validate(data)
