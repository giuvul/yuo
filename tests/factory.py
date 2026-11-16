"""Minimal valid rows for tests: one learner with one path, skill, lesson and item."""

import sqlite3
from dataclasses import dataclass
from typing import Any

from yuo.core import clock
from yuo.core.enums import (
    AcquiredVia,
    AuthorKind,
    Authorship,
    DeploymentMode,
    Difficulty,
    GateStatus,
    GoalType,
    GradingMethod,
    HeadState,
    LessonKind,
    PathStatus,
)
from yuo.core.hashing import content_hash
from yuo.core.ids import new_id
from yuo.db import rows as r
from yuo.db.dal import insert

LANG = "en"


@dataclass
class World:
    learner: str
    device: str
    path: str
    branch: str
    skill: str
    objective: str
    lesson: str
    item: str


def provenance(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "authorship": Authorship.GENERATED,
        "acquired_via": AcquiredVia.LOCAL,
        "author_kind": AuthorKind.SYSTEM,
        "author_ref": None,
        "produced_by_stage_run_id": None,
        "upstream": None,
        "licence": None,
        "personal_inputs": False,
    }
    return base | over


def world(conn: sqlite3.Connection) -> World:
    now = clock.now()
    w = World(*(new_id() for _ in range(8)))
    insert(conn, r.Installation(id=new_id(), mode=DeploymentMode.LOCAL, created_at=now, env_profile={}))
    insert(
        conn,
        r.Learner(
            id=w.learner,
            display_name="Ada",
            ui_lang=LANG,
            default_content_lang=LANG,
            tz="Europe/Rome",
            day_boundary="04:00",
            created_at=now,
        ),
    )
    insert(
        conn,
        r.Device(
            id=w.device, label="laptop", user_agent="test", first_seen=now, last_seen=now, revoked_at=None
        ),
    )
    insert(
        conn,
        r.Path(
            id=w.path,
            code="sql",
            learner_id=w.learner,
            title="SQL",
            subject="SQL",
            goal="Joins",
            goal_type=GoalType.PRACTICAL,
            target_date=None,
            difficulty=Difficulty.FOUNDATIONAL,
            content_lang=LANG,
            status=PathStatus.ACTIVE,
            authorship=Authorship.GENERATED,
            acquired_via=AcquiredVia.LOCAL,
            package_id=None,
            translation_of_path_id=None,
            structure_version=1,
            licence="CC-BY-4.0",
            authors=[],
            extensions={},
            created_at=now,
            updated_at=now,
        ),
    )
    insert(
        conn,
        r.Branch(
            id=w.branch,
            path_id=w.path,
            code="sql.basics",
            title="Basics",
            position=0,
            extensions={},
            archived_at=None,
        ),
    )
    insert(
        conn,
        r.Skill(
            id=w.skill,
            branch_id=w.branch,
            path_id=w.path,
            code="sql.joins",
            title="Joins",
            summary="Inner joins",
            position=0,
            mastery_threshold=None,
            optional=False,
            merged_into_skill_id=None,
            extensions={},
            archived_at=None,
        ),
    )
    insert(
        conn,
        r.LearningObjective(
            id=w.objective,
            skill_id=w.skill,
            path_id=w.path,
            code="sql.joins.inner",
            statement="Write an inner join",
            bloom_level="apply",
            position=0,
            extensions={},
            archived_at=None,
        ),
    )
    insert(
        conn,
        r.Lesson(
            id=w.lesson,
            skill_id=w.skill,
            path_id=w.path,
            code="sql.joins.l1",
            kind=LessonKind.CORE,
            position=0,
            state=HeadState.PLANNED,
            current_version_id=None,
            extensions={},
        ),
    )
    insert(
        conn,
        r.ExerciseType(
            key="mcq",
            version=1,
            payload_schema={},
            grading_method=GradingMethod.EXACT,
            plugin="builtin",
            status="installed",
        ),
    )
    insert(
        conn,
        r.Item(
            id=w.item,
            skill_id=w.skill,
            path_id=w.path,
            code="sql.joins.q1",
            type_key="mcq",
            state=HeadState.PLANNED,
            current_version_id=None,
            extensions={},
        ),
    )
    return w


def lesson_version(
    conn: sqlite3.Connection,
    lesson: str,
    *,
    no: int = 1,
    body: Any = None,
    status: GateStatus = GateStatus.IN_REVIEW,
    lang: str = LANG,
    **prov: Any,
) -> str:
    vid = new_id()
    body = body if body is not None else [{"type": "paragraph", "bid": "b1", "inlines": [{"text": "JOIN"}]}]
    insert(
        conn,
        r.LessonVersion(
            id=vid,
            lesson_id=lesson,
            version_no=no,
            version_hash=content_hash(body),
            lang=lang,
            translation_of_version_hash=None,
            derived_from_version_id=None,
            title="Inner joins",
            body=body,
            est_minutes=5,
            status=status,
            published_at=None,
            created_at=clock.now(),
            **provenance(**prov),
        ),
    )
    return vid


def item_version(conn: sqlite3.Connection, item: str, *, payload: Any = None, **prov: Any) -> str:
    vid = new_id()
    payload = payload if payload is not None else {"prompt": "Which join keeps unmatched rows?"}
    insert(
        conn,
        r.ItemVersion(
            id=vid,
            item_id=item,
            version_no=1,
            version_hash=content_hash(payload),
            lang=LANG,
            translation_of_version_hash=None,
            derived_from_version_id=None,
            difficulty=Difficulty.FOUNDATIONAL,
            payload=payload,
            support={},
            origin_lesson_version_id=None,
            resets_review=False,
            status=GateStatus.PASSED,
            published_at=None,
            created_at=clock.now(),
            **provenance(**prov),
        ),
    )
    return vid
