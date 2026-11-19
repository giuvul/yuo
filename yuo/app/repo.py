"""Row lookups and the path's own state, shared by the service's parts.

Functions over a connection, so they work inside a writer unit and a read connection alike. The path keeps
three pieces of Yuo state in `path.extensions.yuo` (spec 1.0 lets an implementation keep its own data there):
`level_check` (the check before the tree is planned), `preview` (the plan the learner checks before it is
built) and `next` (the "What next?" checkpoint).
"""

import json
import sqlite3
from typing import Any, Literal

from yuo.core import clock
from yuo.core.errors import NotFound

PathState = Literal["level_check", "next", "preview", "arrange", "plan"]


def find_path(c: sqlite3.Connection, path_id: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = c.execute("SELECT * FROM path WHERE id = ?", (path_id,)).fetchone()
    return row


def get_path(c: sqlite3.Connection, path_id: str) -> sqlite3.Row:
    row = find_path(c, path_id)
    if row is None:
        raise NotFound(f"no such path {path_id}")
    return row


def get_skill(c: sqlite3.Connection, skill_id: str) -> sqlite3.Row:
    row: sqlite3.Row | None = c.execute("SELECT * FROM skill WHERE id = ?", (skill_id,)).fetchone()
    if row is None:
        raise NotFound(f"no such skill {skill_id}")
    return row


def path_state(path: sqlite3.Row | None, key: PathState) -> dict[str, Any] | None:
    """One piece of the path's Yuo state (from a `path` row), None when it has none."""
    if path is None:
        return None
    state = (json.loads(path["extensions"] or "{}").get("yuo") or {}).get(key)
    return state if isinstance(state, dict) else None


def save_path_state(
    c: sqlite3.Connection, path_id: str, key: PathState, state: dict[str, Any], *, touch: bool = False
) -> None:
    """Replace one piece of the path's Yuo state; `touch` also moves the path's `updated_at`."""
    c.execute(
        f"UPDATE path SET extensions = json_set(extensions, '$.yuo.{key}', json(?))"
        + (", updated_at = ?" if touch else "")
        + " WHERE id = ?",
        (json.dumps(state), *((clock.now(),) if touch else ()), path_id),
    )


def drop_path_state(c: sqlite3.Connection, path_id: str, key: PathState) -> None:
    c.execute(f"UPDATE path SET extensions = json_remove(extensions, '$.yuo.{key}') WHERE id = ?", (path_id,))
