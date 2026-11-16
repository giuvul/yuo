"""Learning events: payload schemas and idempotent ingest from device outboxes.

The client generates the event id (uuid7); the server computes the payload hash. A retry with the same
id and the same payload is acknowledged as a duplicate; the same id with a different payload is rejected.
Server-side events (grades) use the installation's own device row.
"""

import json
import sqlite3
from datetime import UTC, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yuo.core import clock
from yuo.core.enums import EventType, GradingMethod
from yuo.core.hashing import content_hash
from yuo.core.ids import is_uuid7, new_id

FUTURE_TOLERANCE = timedelta(minutes=5)
SERVER_DEVICE_LABEL = "server"


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LessonActivity(_Payload):
    lesson_version_id: str
    rendition_version_id: str | None = None
    seconds: int = Field(ge=0)


class AttemptStarted(_Payload):
    attempt_id: str
    assessment_id: str
    purpose: Literal["practice", "skill_test", "placement", "review"]


class AttemptFinished(_Payload):
    attempt_id: str
    outcome: Literal["finished", "abandoned"]


class ResponseGiven(_Payload):
    attempt_id: str
    item_version_id: str
    answer: Any
    ms_to_answer: int = Field(ge=0)
    # review sessions: "I'm guessing". Absent means sure, so older events read the same.
    confidence: Literal["sure", "guessing"] | None = None


class ResponseGraded(_Payload):
    response_event_id: str
    attempt_id: str
    item_version_id: str
    grading_method: GradingMethod
    score: float = Field(ge=0, le=1)
    reason: Literal["initial", "regrade", "contest_upheld", "contest_rejected"]
    rationale: str | None = None
    grader_stage_run_id: str | None = None
    supersedes_grade_event_id: str | None = None


class SupportShown(_Payload):
    item_version_id: str
    attempt_id: str | None = None
    kind: Literal["hint", "solution", "explanation"]
    level: int = Field(ge=0)


class SkillTestResult(_Payload):
    skill_id: str
    attempt_id: str
    passed: bool
    score: float = Field(ge=0, le=1)
    pass_mark: float = Field(ge=0, le=1)


class SkillPlaced(_Payload):
    skill_id: str
    attempt_id: str
    result: Literal["mastered", "not_mastered"]


class SkillOverride(_Payload):
    skill_id: str
    new_state: Literal["locked", "available", "in_progress", "mastered"]
    reason: str = Field(max_length=500)


class GradeContested(_Payload):
    response_event_id: str
    grade_event_id: str
    reason_text: str = Field(max_length=1000)


class TutorHelpGiven(_Payload):
    message_id: str
    attempt_id: str | None = None
    item_version_id: str | None = None


class ProposalDecided(_Payload):
    proposal_id: str
    decision: Literal["accepted", "rejected"]


PAYLOADS: dict[EventType, type[_Payload]] = {
    EventType.LESSON_STARTED: LessonActivity,
    EventType.LESSON_COMPLETED: LessonActivity,
    EventType.ATTEMPT_STARTED: AttemptStarted,
    EventType.ATTEMPT_FINISHED: AttemptFinished,
    EventType.RESPONSE_GIVEN: ResponseGiven,
    EventType.RESPONSE_GRADED: ResponseGraded,
    EventType.SUPPORT_SHOWN: SupportShown,
    EventType.SKILL_TEST_RESULT: SkillTestResult,
    EventType.SKILL_PLACED: SkillPlaced,
    EventType.SKILL_OVERRIDE: SkillOverride,
    EventType.GRADE_CONTESTED: GradeContested,
    EventType.TUTOR_HELP_GIVEN: TutorHelpGiven,
    EventType.PROPOSAL_DECIDED: ProposalDecided,
}
# written only by the server: grades and test outcomes are never trusted from a device
SERVER_ONLY = frozenset(
    {
        EventType.RESPONSE_GRADED,
        EventType.SKILL_TEST_RESULT,
        EventType.SKILL_PLACED,
        EventType.TUTOR_HELP_GIVEN,
    }
)
# payload fields promoted to columns
PROMOTED = ("item_version_id", "lesson_version_id", "rendition_version_id", "attempt_id", "skill_id")


class IncomingEvent(BaseModel):
    id: str
    type: str
    type_version: int = 1
    device_at: str
    tz: str
    payload: dict[str, Any]


class IngestResult(BaseModel):
    accepted: list[str] = []
    duplicates: list[str] = []
    rejected: dict[str, str] = {}


def learning_day(at: datetime, tz: str, boundary: str) -> str:
    """The day an instant counts for: local date, shifted back before the day boundary (default 04:00)."""
    local = at.astimezone(ZoneInfo(tz))
    h, m = (int(x) for x in boundary.split(":"))
    if local.time() < time(h, m):
        local -= timedelta(days=1)
    return local.date().isoformat()


def validate(event: IncomingEvent) -> tuple[EventType, dict[str, Any]]:
    if not is_uuid7(event.id):
        raise ValueError("id must be a lowercase uuid7")
    try:
        etype = EventType(event.type)
    except ValueError:
        raise ValueError(f"unknown event type {event.type!r}") from None
    model = PAYLOADS.get(etype)
    if model is None:
        raise ValueError(f"event type {etype} is not accepted from devices yet")
    try:
        payload = model.model_validate(event.payload).model_dump(mode="json", exclude_none=True)
    except ValidationError as e:
        raise ValueError(f"payload: {e.errors()[0]['msg']}") from e
    try:
        ZoneInfo(event.tz)
    except ZoneInfoNotFoundError, ValueError:
        raise ValueError(f"unknown time zone {event.tz!r}") from None
    return etype, payload


def insert_event(
    c: sqlite3.Connection,
    *,
    event_id: str,
    etype: EventType,
    payload: dict[str, Any],
    learner_id: str,
    device_id: str,
    device_at: str,
    tz: str,
    boundary: str,
    type_version: int = 1,
) -> str:
    """Insert one event; returns 'accepted', 'duplicate', or raises ValueError on an id/payload clash."""
    server_at = clock.now()
    device_dt = min(clock.parse_timestamp(device_at), clock.parse_timestamp(server_at) + FUTURE_TOLERANCE)
    device_at = clock.to_timestamp(device_dt)
    digest = content_hash(payload)
    refs = {k: payload.get(k) for k in PROMOTED}
    row = c.execute(
        "INSERT INTO learning_event (id, payload_hash, learner_id, type, type_version, device_id, device_at, "
        "server_at, tz, learning_day, item_version_id, lesson_version_id, rendition_version_id, attempt_id, "
        "skill_id, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, json(?)) "
        "ON CONFLICT(id) DO NOTHING RETURNING server_seq",
        (
            event_id,
            digest,
            learner_id,
            etype.value,
            type_version,
            device_id,
            device_at,
            server_at,
            tz,
            learning_day(device_dt.astimezone(UTC), tz, boundary),
            refs["item_version_id"],
            refs["lesson_version_id"],
            refs["rendition_version_id"],
            refs["attempt_id"],
            refs["skill_id"],
            json.dumps(payload, ensure_ascii=False),
        ),
    ).fetchone()
    if row is not None:
        return "accepted"
    prior = c.execute("SELECT payload_hash FROM learning_event WHERE id = ?", (event_id,)).fetchone()[0]
    if prior != digest:
        raise ValueError("an event with this id but a different payload exists")
    return "duplicate"


def server_device(c: sqlite3.Connection) -> str:
    row = c.execute(
        "SELECT id FROM device WHERE label = ? AND user_agent = 'yuo'", (SERVER_DEVICE_LABEL,)
    ).fetchone()
    if row:
        return str(row[0])
    did = new_id()
    now = clock.now()
    c.execute(
        "INSERT INTO device (id, label, user_agent, first_seen, last_seen, revoked_at) VALUES (?, ?, 'yuo', ?, ?, NULL)",
        (did, SERVER_DEVICE_LABEL, now, now),
    )
    return did
