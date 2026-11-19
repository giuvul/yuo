"""Erasure: the only path that deletes personal rows, including from the event log.

The routine works from the schema metadata, not from hand-kept lists:
1. seed rows for the erasure kind are marked in a temp table (by rowid);
2. marks spread along foreign keys until nothing changes: a child row is erased with its parent when the
   reference is NOT NULL or the child is an append-only event; otherwise the reference is set to NULL;
3. link rows and asset references of erased rows go too; assets left with no reference lose their bytes;
4. after commit: checkpoint, VACUUM, checkpoint, so no copy survives in the file or the WAL.
"""

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from yuo.core import clock
from yuo.core.enums import EntityKind
from yuo.core.ids import new_id
from yuo.db.blobs import BlobStore
from yuo.db.connection import Writer
from yuo.db.schema import Row, columns

type Seed = tuple[str, str]  # (table, WHERE predicate with named parameters)


@dataclass(frozen=True, slots=True)
class Edge:
    child: str
    cols: tuple[str, ...]
    parent: str
    parent_cols: tuple[str, ...]
    nullable: tuple[str, ...]  # child columns that may be set to NULL


def _tables() -> dict[str, type[Row]]:
    from yuo.db import rows  # noqa: F401

    return Row.registry


def edges() -> list[Edge]:
    out: list[Edge] = []
    for name, model in _tables().items():
        cols = {c.name: c for c in columns(model)}
        for c in cols.values():
            if (r := c.references()) is not None:
                out.append(Edge(name, (c.name,), r[0], (r[1],), (c.name,) if c.nullable else ()))
        for fk in model.table.fks:
            nullable = tuple(x for x in fk.cols if cols[x].nullable)
            out.append(Edge(name, fk.cols, fk.ref, fk.ref_cols, nullable))
    return out


def _marked(table: str) -> str:
    return f"SELECT rid FROM temp.erase_set WHERE tbl = '{table}'"


def _parent_values(e: Edge) -> str:
    return f"SELECT {', '.join(e.parent_cols)} FROM {e.parent} WHERE rowid IN ({_marked(e.parent)})"


def _match(e: Edge) -> str:
    lhs = e.cols[0] if len(e.cols) == 1 else f"({', '.join(e.cols)})"
    return f"{lhs} IN ({_parent_values(e)})"


@dataclass
class Plan:
    kind: str
    seeds: list[Seed]
    params: dict[str, Any] = field(default_factory=dict)


def _mark(conn: sqlite3.Connection, plan: Plan) -> None:
    tables = _tables()
    conn.execute(
        "CREATE TEMP TABLE IF NOT EXISTS erase_set (tbl TEXT NOT NULL, rid INTEGER NOT NULL, "
        "PRIMARY KEY (tbl, rid)) WITHOUT ROWID"
    )
    conn.execute("DELETE FROM temp.erase_set")
    for table, where in plan.seeds:
        conn.execute(
            f"INSERT OR IGNORE INTO temp.erase_set SELECT '{table}', rowid FROM {table} WHERE {where}",
            plan.params,
        )
    cascading = [
        e
        for e in edges()
        if not tables[e.child].table.without_rowid
        and not tables[e.parent].table.without_rowid
        and (not e.nullable or tables[e.child].table.kind == "event")
    ]
    while True:
        before = conn.total_changes
        for e in cascading:
            conn.execute(
                f"INSERT OR IGNORE INTO temp.erase_set SELECT '{e.child}', rowid FROM {e.child} "
                f"WHERE {_match(e)}"
            )
        # personal model outputs of erased stage runs (stage_output is keyed by hash, not by a foreign key)
        conn.execute(
            "INSERT OR IGNORE INTO temp.erase_set SELECT 'stage_output', rowid FROM stage_output "
            "WHERE data_class IN ('P','F') AND hash IN "
            f"(SELECT output_hash FROM stage_run WHERE rowid IN ({_marked('stage_run')}))"
        )
        if conn.total_changes == before:
            return


def _apply(conn: sqlite3.Connection, plan: Plan) -> tuple[dict[str, int], set[str]]:
    tables = _tables()
    counts: dict[str, int] = {}
    conn.execute("PRAGMA defer_foreign_keys = ON")
    for e in edges():
        if tables[e.child].table.without_rowid or tables[e.parent].table.without_rowid or not e.nullable:
            continue
        sets = ", ".join(f"{c} = NULL" for c in e.nullable)
        conn.execute(f"UPDATE {e.child} SET {sets} WHERE rowid NOT IN ({_marked(e.child)}) AND {_match(e)}")
    touched: set[str] = set()
    for kind in EntityKind:
        owner = tables.get(kind.value)
        if owner is not None and not owner.table.without_rowid and len(owner.table.pk) == 1:
            where = (
                f"owner_kind = '{kind.value}' AND owner_id IN "
                f"(SELECT {owner.table.pk[0]} FROM {kind.value} WHERE rowid IN ({_marked(kind.value)}))"
            )
            touched |= {r[0] for r in conn.execute(f"SELECT asset_hash FROM asset_ref WHERE {where}")}
            n = conn.execute(f"DELETE FROM asset_ref WHERE {where}").rowcount
            if n:
                counts["asset_ref"] = counts.get("asset_ref", 0) + n
    for e in edges():
        child = tables[e.child]
        if child.table.without_rowid and e.child != "asset_ref" and not tables[e.parent].table.without_rowid:
            if e.child == "rendition_asset":
                touched |= {
                    r[0] for r in conn.execute(f"SELECT asset_hash FROM rendition_asset WHERE {_match(e)}")
                }
            n = conn.execute(f"DELETE FROM {e.child} WHERE {_match(e)}").rowcount
            if n:
                counts[e.child] = counts.get(e.child, 0) + n
    for (table,) in conn.execute("SELECT DISTINCT tbl FROM temp.erase_set").fetchall():
        n = conn.execute(f"DELETE FROM {table} WHERE rowid IN ({_marked(table)})").rowcount
        counts[table] = counts.get(table, 0) + n
    # assets nothing refers to any more: drop the bytes; keep the row for content, drop it for personal
    orphaned: set[str] = set()
    for digest in sorted(touched):
        if conn.execute(
            "SELECT 1 FROM asset_ref WHERE asset_hash = ? UNION ALL "
            "SELECT 1 FROM rendition_asset WHERE asset_hash = ?",
            (digest, digest),
        ).fetchone():
            continue
        orphaned.add(digest)
        if conn.execute("DELETE FROM asset WHERE hash = ? AND data_class = 'F'", (digest,)).rowcount == 0:
            conn.execute(
                "UPDATE asset SET evicted_at = ?, stored_at = NULL WHERE hash = ? AND evicted_at IS NULL",
                (clock.now(), digest),
            )
    if orphaned:
        counts["asset_bytes"] = len(orphaned)
    return counts, orphaned


def erase(writer: Writer, blobs: BlobStore | None, plan: Plan) -> dict[str, int]:
    """`blobs` is None where this process keeps no asset bytes (scripted tests): only rows are erased."""
    token = new_id()

    def unit(conn: sqlite3.Connection) -> tuple[dict[str, int], set[str]]:
        conn.execute("INSERT INTO erasure_guard (token) VALUES (?)", (token,))
        _mark(conn, plan)
        result = _apply(conn, plan)
        conn.execute("DELETE FROM erasure_guard WHERE token = ?", (token,))
        conn.execute("DELETE FROM temp.erase_set")
        return result

    counts, orphaned = writer.run(unit)
    if blobs is not None:
        for digest in orphaned:
            blobs.delete(digest)
    # FTS5 secure-delete already removed the tokens; now leave no copy in the WAL or free pages
    writer.maintenance("PRAGMA wal_checkpoint(TRUNCATE)")
    writer.maintenance("VACUUM")
    writer.maintenance("PRAGMA wal_checkpoint(TRUNCATE)")
    writer.run(
        lambda c: c.execute(
            "INSERT INTO erasure_record (id, kind, counts, at) VALUES (?, ?, json(?), ?)",
            (new_id(), plan.kind, _json(counts), clock.now()),
        )
    )
    # the caller rebuilds the learner's projections from what is left (yuo.app.erasure)
    return counts


def _json(counts: dict[str, int]) -> str:
    import json

    return json.dumps(dict(sorted(counts.items())))


# --- erasure kinds -----------------------------------------------------------------------


def conversation(conversation_id: str) -> Plan:
    return Plan(
        "conversation",
        [
            ("conversation", "id = :c"),
            (
                "stage_run",
                "data_class IN ('P','F') AND id IN (SELECT stage_run_id FROM message WHERE conversation_id = :c)",
            ),
        ],
        {"c": conversation_id},
    )


def video_history(learner_id: str) -> Plan:
    return Plan(
        "video_history",
        [
            ("learning_event", "learner_id = :l AND type = 'video.watched'"),
            ("watch_coverage", "learner_id = :l"),
        ],
        {"l": learner_id},
    )


_SKILLS = "SELECT id FROM skill WHERE path_id = :p"
_LESSONS = "SELECT id FROM lesson WHERE path_id = :p"
_ITEMS = "SELECT id FROM item WHERE path_id = :p"
_LVS = "SELECT v.id FROM lesson_version v JOIN lesson h ON h.id = v.lesson_id WHERE h.path_id = :p"
_IVS = "SELECT v.id FROM item_version v JOIN item h ON h.id = v.item_id WHERE h.path_id = :p"
_RVS = (
    "SELECT v.id FROM rendition_version v JOIN rendition r ON r.id = v.rendition_id "
    "JOIN lesson h ON h.id = r.lesson_id WHERE h.path_id = :p"
)
_PERSONAL_VERSION = "(author_kind = 'learner' OR personal_inputs = 1)"
# the path's assessments: a skill's, or one whose pinned items are the path's (placement has no skill)
_ASSESSMENTS = (
    f"SELECT id FROM assessment WHERE skill_id IN ({_SKILLS}) OR EXISTS "
    f"(SELECT 1 FROM json_each(item_version_ids) j WHERE j.value IN ({_IVS}))"
)
# every event of their attempts: `attempt.started` and `attempt.finished` name the assessment in the payload only
_ATTEMPTS = (
    "SELECT attempt_id FROM learning_event WHERE type = 'attempt.started' "
    f"AND payload ->> '$.assessment_id' IN ({_ASSESSMENTS})"
)


def path_personal(path_id: str) -> Plan:
    """The learner's personal data in one path; the path's shared content stays."""
    targets = " UNION ".join(["SELECT :p", _SKILLS, _LESSONS, _ITEMS, _LVS, _IVS, _RVS])
    return Plan(
        "path_personal",
        [
            (
                "learning_event",
                f"skill_id IN ({_SKILLS}) OR lesson_version_id IN ({_LVS}) OR item_version_id IN ({_IVS}) "
                f"OR rendition_version_id IN ({_RVS}) "
                "OR (type = 'path.status_changed' AND payload ->> '$.path_id' = :p) "
                f"OR attempt_id IN ({_ATTEMPTS})",
            ),
            ("assessment", f"id IN ({_ASSESSMENTS})"),
            ("skill_progress", f"skill_id IN ({_SKILLS})"),
            ("review_state", f"item_id IN ({_ITEMS})"),
            (
                "objective_review_state",
                "objective_id IN (SELECT id FROM learning_objective WHERE path_id = :p)",
            ),
            ("watch_coverage", f"rendition_version_id IN ({_RVS})"),
            (
                "conversation",
                f"(scope = 'path' AND scope_ref = :p) OR (scope = 'skill' AND scope_ref IN ({_SKILLS})) "
                f"OR (scope = 'lesson' AND scope_ref IN ({_LESSONS}))",
            ),
            ("proposal", "path_id = :p"),
            ("lesson_request", "path_id = :p"),
            ("note", f"rendition_version_id IN ({_RVS}) OR anchor ->> '$.lesson_version_id' IN ({_LVS})"),
            ("lesson_version", f"{_PERSONAL_VERSION} AND lesson_id IN ({_LESSONS})"),
            ("item_version", f"{_PERSONAL_VERSION} AND item_id IN ({_ITEMS})"),
            ("rendition_version", f"{_PERSONAL_VERSION} AND id IN ({_RVS})"),
            (
                "stage_run",
                f"data_class IN ('P','F') AND job_id IN (SELECT id FROM generation_job WHERE target_id IN ({targets}))",
            ),
            (
                "source",
                "data_class = 'F' AND id IN (SELECT source_id FROM lesson_version_source "
                f"WHERE lesson_version_id IN ({_LVS}) AND lesson_version_id IN "
                f"(SELECT id FROM lesson_version WHERE {_PERSONAL_VERSION}))",
            ),
        ],
        {"p": path_id},
    )


def path_whole(path_id: str) -> Plan:
    """The whole path: its plan, lessons, questions, files and courses, and everything the learner did in it.
    The personal seeds reach rows that only name the path in a payload or a scope; the rest follows the
    foreign keys from the path row. Its jobs go too (they name their target without a foreign key)."""
    personal = path_personal(path_id)
    targets = " UNION ".join(["SELECT :p", _SKILLS, _LESSONS, _ITEMS, _LVS, _IVS, _RVS])
    courses = "SELECT id FROM course WHERE path_id = :p UNION SELECT id FROM material WHERE path_id = :p"
    return Plan(
        "other",
        [
            *personal.seeds,
            (
                "stage_run",
                f"job_id IN (SELECT id FROM generation_job WHERE target_id IN ({targets}) "
                f"OR target_id IN ({courses}))",
            ),
            ("generation_job", f"target_id IN ({targets}) OR target_id IN ({courses})"),
            ("path", "id = :p"),
        ],
        {"p": path_id},
    )
