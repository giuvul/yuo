"""Row models: one per table, the single source of the physical schema.

JSON columns are typed `Json`; context modules validate their contents against their own Pydantic
payload schemas. Composite keys, deferred head pointers and version invariants are declared in `table`.
"""

from typing import Annotated, ClassVar

from pydantic import BaseModel

from yuo.core.enums import (
    AcquiredVia,
    AssessmentPurpose,
    AuthorKind,
    Authorship,
    Check,
    CheckVerdict,
    ConversationScope,
    DataClass,
    DeploymentMode,
    Difficulty,
    EntityKind,
    EventType,
    GateStatus,
    GoalType,
    GradingMethod,
    HeadState,
    HelpKind,
    LessonKind,
    PackageProfile,
    PathStatus,
    ProposalKind,
    RenditionKind,
    RequestStatus,
    RunStatus,
    SkillState,
    SpecKind,
    Stage,
    TutorMode,
)
from yuo.core.enums import (
    DataClass as DC,
)
from yuo.db.schema import (
    FK,
    Col,
    Currency,
    Date,
    Hash,
    Json,
    Lang,
    Micros,
    Row,
    Table,
    Time,
    Timestamp,
    Tz,
    Uuid7,
)

NonNeg = Col(check="{c} >= 0")
Unit = Col(check="{c} BETWEEN 0 AND 1")
ExtJson = Annotated[Json, Col(default="'{}'")]


def ref(table: str, col: str = "id") -> Col:
    return Col(fk=f"{table}({col})")


# --- lookups (open enums) ------------------------------------------------------------------------


class _Lookup(Row):
    key: str


class StageKind(_Lookup):
    table: ClassVar[Table] = Table("stage_kind", "lookup", DC.CONFIG, pk=("key",), without_rowid=True)


class CheckKind(_Lookup):
    table: ClassVar[Table] = Table("check_kind", "lookup", DC.CONFIG, pk=("key",), without_rowid=True)


class EntityKindRef(_Lookup):
    table: ClassVar[Table] = Table("entity_kind_ref", "lookup", DC.CONFIG, pk=("key",), without_rowid=True)


class EventTypeRow(_Lookup):
    table: ClassVar[Table] = Table("event_type", "lookup", DC.CONFIG, pk=("key",), without_rowid=True)


# --- 3.1 setup and access ------------------------------------------------------------------------


class Installation(Row):
    table: ClassVar[Table] = Table("installation", "entity", DC.CONFIG)
    id: Uuid7
    mode: DeploymentMode
    created_at: Timestamp
    env_profile: Json


class AdapterBinding(Row):
    table: ClassVar[Table] = Table(
        "adapter_binding", "entity", DC.CONFIG, unique=(("port", "role", "priority"),)
    )
    id: Uuid7
    port: str
    adapter: str
    role: str | None
    priority: Annotated[int, NonNeg]
    scope: Annotated[str, Col(check="{c} IN ('installation')")]
    settings: Json
    secret_ref: str | None
    enabled: bool


class SettingValue(Row):
    table: ClassVar[Table] = Table("setting_value", "entity", None, unique=(("key", "scope", "scope_ref"),))
    id: Uuid7
    key: str
    scope: Annotated[str, Col(check="{c} IN ('installation','learner','path','lesson')")]
    scope_ref: Uuid7 | None
    value: Json
    data_class: Annotated[DataClass, Col(check="{c} IN ('K','F')")]
    updated_at: Timestamp
    updated_by_device_id: Annotated[Uuid7 | None, ref("device")]


class SettingAudit(Row):
    table: ClassVar[Table] = Table("setting_audit", "entity", DC.OPERATIONAL)
    id: Uuid7
    key: str
    old: Json | None
    new: Json
    device_id: Annotated[Uuid7 | None, ref("device")]
    at: Timestamp


class ConsentRecord(Row):
    table: ClassVar[Table] = Table("consent_record", "entity", DC.PERSONAL)
    id: Uuid7
    learner_id: Annotated[Uuid7, ref("learner")]
    subject: str
    text_hash: Hash
    granted: bool
    at: Timestamp


class ModelCapability(Row):
    table: ClassVar[Table] = Table("model_capability", "entity", DC.CONFIG)
    id: Uuid7
    adapter: str
    model: str
    declared: Json
    measured: Json | None
    measured_at: Timestamp | None
    supported_roles: Json


class Device(Row):
    table: ClassVar[Table] = Table("device", "entity", DC.CONFIG)
    id: Uuid7
    label: str
    user_agent: str
    first_seen: Timestamp
    last_seen: Timestamp
    revoked_at: Timestamp | None


class AuthCredential(Row):
    table: ClassVar[Table] = Table(
        "auth_credential",
        "entity",
        DC.SECRET,
        checks=(
            "(kind = 'password') = (password_hash IS NOT NULL)",
            "(kind = 'passkey') = (public_key IS NOT NULL)",
            "(kind = 'passkey') = (credential_id IS NOT NULL)",
        ),
    )
    id: Uuid7
    learner_id: Annotated[Uuid7, ref("learner")]
    kind: Annotated[str, Col(check="{c} IN ('password','passkey')")]
    password_hash: str | None  # argon2id
    public_key: str | None  # COSE key, base64url
    credential_id: Annotated[str | None, Col(unique=True)]  # base64url
    sign_count: Annotated[int, NonNeg, Col(default="0")]
    transports: Json | None
    label: str
    created_at: Timestamp
    last_used_at: Timestamp | None


class AuthRecoveryCode(Row):
    """Single-use codes to get back in without a passkey or password; only their hashes are kept."""

    table: ClassVar[Table] = Table("auth_recovery_code", "entity", DC.SECRET)
    id: Uuid7
    learner_id: Annotated[Uuid7, ref("learner")]
    code_hash: Annotated[Hash, Col(unique=True)]
    created_at: Timestamp
    used_at: Timestamp | None


class AuthSetupCode(Row):
    """The one-time code that enrols the first credential, so nobody else can claim a fresh install."""

    table: ClassVar[Table] = Table("auth_setup_code", "entity", DC.SECRET)
    id: Uuid7
    code_hash: Annotated[Hash, Col(unique=True)]
    created_at: Timestamp
    expires_at: Timestamp
    used_at: Timestamp | None


class AuthSession(Row):
    table: ClassVar[Table] = Table("auth_session", "entity", DC.OPERATIONAL)
    id: Uuid7
    device_id: Annotated[Uuid7, ref("device")]
    token_hash: Annotated[Hash, Col(unique=True)]
    created_at: Timestamp
    expires_at: Timestamp
    last_seen_at: Timestamp | None
    revoked_at: Timestamp | None
    user_agent: str | None


class BackupRecord(Row):
    table: ClassVar[Table] = Table("backup_record", "entity", DC.OPERATIONAL)
    id: Uuid7
    file: str
    created_at: Timestamp
    bytes: Annotated[int, NonNeg]
    integrity_ok: bool
    deleted_at: Timestamp | None


class Schedule(Row):
    table: ClassVar[Table] = Table("schedule", "entity", DC.OPERATIONAL, pk=("key",))
    key: str
    next_run_at: Timestamp
    tz: Tz
    last_run_at: Timestamp | None


class ErasureGuard(Row):
    """Present only inside the erasure routine's own transaction."""

    table: ClassVar[Table] = Table("erasure_guard", "guard", DC.OPERATIONAL, pk=("token",))
    token: Uuid7


class ErasureRecord(Row):
    table: ClassVar[Table] = Table("erasure_record", "entity", DC.OPERATIONAL)
    id: Uuid7
    kind: Annotated[
        str, Col(check="{c} IN ('full_wipe','conversation','note','video_history','path_personal','other')")
    ]
    counts: Json
    at: Timestamp


# --- 3.2 learning record -------------------------------------------------------------------------


class Learner(Row):
    table: ClassVar[Table] = Table("learner", "entity", DC.PERSONAL)
    id: Uuid7
    display_name: str
    ui_lang: Lang
    default_content_lang: Lang
    tz: Tz
    day_boundary: Annotated[Time, Col(default="'04:00'")]
    created_at: Timestamp


class LearnerProfile(Row):
    table: ClassVar[Table] = Table("learner_profile", "entity", DC.FREE_TEXT, pk=("learner_id",))
    learner_id: Annotated[Uuid7, ref("learner")]
    goals: str
    background: str
    interests: Json
    formats: Json
    weekly_time_min: Annotated[int, NonNeg]
    updated_at: Timestamp


class LearnerMemoryItem(Row):
    table: ClassVar[Table] = Table("learner_memory_item", "entity", DC.FREE_TEXT)
    id: Uuid7
    learner_id: Annotated[Uuid7, ref("learner")]
    kind: Annotated[str, Col(check="{c} IN ('preference','misconception','goal','fact')")]
    text: str
    source: Annotated[str, Col(check="{c} IN ('tutor','learner','system')")]
    evidence_ref: Json | None
    archived_at: Timestamp | None
    created_at: Timestamp
    updated_at: Timestamp


class LearningEvent(Row):
    table: ClassVar[Table] = Table(
        "learning_event",
        "event",
        DC.PERSONAL,
        pk=("server_seq",),
        checks=(
            "item_version_id IS payload ->> '$.item_version_id'",
            "lesson_version_id IS payload ->> '$.lesson_version_id'",
            "rendition_version_id IS payload ->> '$.rendition_version_id'",
            "attempt_id IS payload ->> '$.attempt_id'",
            "skill_id IS payload ->> '$.skill_id'",
        ),
    )
    server_seq: int | None = None  # assigned by SQLite (AUTOINCREMENT)
    id: Annotated[Uuid7, Col(unique=True)]
    payload_hash: Hash
    learner_id: Annotated[Uuid7, ref("learner")]
    type: EventType
    type_version: Annotated[int, Col(check="{c} >= 1")]
    device_id: Annotated[Uuid7, ref("device")]
    device_at: Timestamp
    server_at: Timestamp
    tz: Tz
    learning_day: Date
    item_version_id: Annotated[Uuid7 | None, ref("item_version")]
    lesson_version_id: Annotated[Uuid7 | None, ref("lesson_version")]
    rendition_version_id: Annotated[Uuid7 | None, ref("rendition_version")]
    attempt_id: Uuid7 | None
    skill_id: Annotated[Uuid7 | None, ref("skill")]
    payload: Json


class _Projection(Row):
    algo_version: Annotated[int, Col(check="{c} >= 1")]
    inputs_hash: Hash
    rebuilt_at: Timestamp


class Response(_Projection):
    table: ClassVar[Table] = Table("response", "projection", DC.PERSONAL, pk=("response_event_id",))
    response_event_id: Annotated[Uuid7, ref("learning_event")]
    attempt_id: Uuid7
    item_version_id: Annotated[Uuid7, ref("item_version")]
    answered_at: Timestamp
    help_kind: HelpKind
    hint_depth: Annotated[int, NonNeg]
    ms_to_answer: Annotated[int | None, NonNeg]
    latest_grade_event_id: Annotated[Uuid7 | None, ref("learning_event")]
    score: Annotated[float | None, Unit]
    grading_method: GradingMethod | None


class Attempt(_Projection):
    table: ClassVar[Table] = Table("attempt", "projection", DC.PERSONAL)
    id: Uuid7
    assessment_id: Annotated[Uuid7, ref("assessment")]
    learner_id: Annotated[Uuid7, ref("learner")]
    started_at: Timestamp
    finished_at: Timestamp | None
    outcome: Annotated[str | None, Col(check="{c} IN ('finished','abandoned')")]
    score: Annotated[float | None, Unit]


class SkillProgress(_Projection):
    table: ClassVar[Table] = Table("skill_progress", "projection", DC.PERSONAL, pk=("learner_id", "skill_id"))
    learner_id: Annotated[Uuid7, ref("learner")]
    skill_id: Annotated[Uuid7, ref("skill")]
    state: SkillState
    mastery: Annotated[float, Unit]
    evidence_count: Annotated[int, NonNeg]
    last_activity_at: Timestamp | None


class ReviewState(_Projection):
    table: ClassVar[Table] = Table(
        "review_state", "projection", DC.PERSONAL, pk=("learner_id", "item_id", "facet")
    )
    learner_id: Annotated[Uuid7, ref("learner")]
    item_id: Annotated[Uuid7, ref("item")]
    facet: Annotated[str, Col(default="''")]
    scheduler: str
    state: Json
    due_at: Timestamp
    last_review_at: Timestamp | None


class ObjectiveReviewState(_Projection):
    """Memory of one learning objective, scheduled from review sessions: one FSRS review per objective
    per session, whatever questions carried it. Rebuilt from events like every projection."""

    table: ClassVar[Table] = Table(
        "objective_review_state", "projection", DC.PERSONAL, pk=("learner_id", "objective_id"), since=3
    )
    learner_id: Annotated[Uuid7, ref("learner")]
    objective_id: Annotated[Uuid7, ref("learning_objective")]
    scheduler: str
    state: Json
    due_at: Timestamp
    last_review_at: Timestamp | None
    reviews: Annotated[int, NonNeg]
    lapses: Annotated[int, NonNeg]


class XpDaily(_Projection):
    table: ClassVar[Table] = Table("xp_daily", "projection", DC.PERSONAL, pk=("learner_id", "learning_day"))
    learner_id: Annotated[Uuid7, ref("learner")]
    learning_day: Date
    xp: Annotated[int, NonNeg]
    sessions: Annotated[int, NonNeg]
    streak_len: Annotated[int, NonNeg]
    grace_used: Annotated[int, NonNeg]


class Achievement(_Projection):
    table: ClassVar[Table] = Table("achievement", "projection", DC.PERSONAL, pk=("learner_id", "key"))
    learner_id: Annotated[Uuid7, ref("learner")]
    key: str
    unlocked_at: Timestamp


class WatchCoverage(_Projection):
    table: ClassVar[Table] = Table(
        "watch_coverage", "projection", DC.PERSONAL, pk=("learner_id", "rendition_version_id")
    )
    learner_id: Annotated[Uuid7, ref("learner")]
    rendition_version_id: Annotated[Uuid7, ref("rendition_version")]
    covered: Json
    share: Annotated[float, Unit]


# --- 3.3 curriculum ------------------------------------------------------------------------------


class Path(Row):
    table: ClassVar[Table] = Table("path", "entity", DC.CONTENT)
    id: Uuid7
    code: Annotated[str, Col(unique=True)]
    learner_id: Annotated[Uuid7, ref("learner")]
    title: str
    subject: str
    goal: str
    goal_type: GoalType
    target_date: Date | None
    difficulty: Difficulty
    content_lang: Lang
    status: PathStatus
    authorship: Authorship
    acquired_via: AcquiredVia
    package_id: Annotated[Uuid7 | None, ref("package")]
    translation_of_path_id: Annotated[Uuid7 | None, ref("path")]
    structure_version: Annotated[int, NonNeg]
    licence: str
    authors: Json
    extensions: ExtJson
    created_at: Timestamp
    updated_at: Timestamp


class PathChange(Row):
    table: ClassVar[Table] = Table(
        "path_change", "entity", DC.CONTENT, checks=("structure_version > base_structure_version",)
    )
    id: Uuid7
    path_id: Annotated[Uuid7, ref("path")]
    base_structure_version: Annotated[int, NonNeg]
    structure_version: Annotated[int, NonNeg]
    ops: Json
    origin: Annotated[str, Col(check="{c} IN ('learner','proposal','import','generation')")]
    proposal_id: Annotated[Uuid7 | None, ref("proposal")]
    device_id: Annotated[Uuid7 | None, ref("device")]
    at: Timestamp


class Branch(Row):
    table: ClassVar[Table] = Table(
        "branch", "entity", DC.CONTENT, unique=(("path_id", "code"), ("id", "path_id"))
    )
    id: Uuid7
    path_id: Annotated[Uuid7, ref("path")]
    code: str
    title: str
    position: Annotated[int, NonNeg]
    extensions: ExtJson
    archived_at: Timestamp | None


class Skill(Row):
    table: ClassVar[Table] = Table(
        "skill",
        "entity",
        DC.CONTENT,
        unique=(("path_id", "code"), ("id", "path_id")),
        fks=(FK(("branch_id", "path_id"), "branch", ("id", "path_id")),),
    )
    id: Uuid7
    branch_id: Uuid7
    path_id: Annotated[Uuid7, ref("path")]
    code: str
    title: str
    summary: str
    position: Annotated[int, NonNeg]
    mastery_threshold: Annotated[float | None, Unit]
    optional: bool
    merged_into_skill_id: Annotated[Uuid7 | None, ref("skill")]
    extensions: ExtJson
    archived_at: Timestamp | None


class SkillPrerequisite(Row):
    table: ClassVar[Table] = Table(
        "skill_prerequisite",
        "link",
        DC.CONTENT,
        pk=("skill_id", "requires_skill_id"),
        without_rowid=True,
        fks=(
            FK(("skill_id", "path_id"), "skill", ("id", "path_id")),
            FK(("requires_skill_id", "path_id"), "skill", ("id", "path_id")),
        ),
        checks=("skill_id <> requires_skill_id",),
    )
    skill_id: Uuid7
    requires_skill_id: Uuid7
    path_id: Annotated[Uuid7, ref("path")]


class LearningObjective(Row):
    table: ClassVar[Table] = Table(
        "learning_objective",
        "entity",
        DC.CONTENT,
        unique=(("path_id", "code"),),
        fks=(FK(("skill_id", "path_id"), "skill", ("id", "path_id")),),
    )
    id: Uuid7
    skill_id: Uuid7
    path_id: Annotated[Uuid7, ref("path")]
    code: str
    statement: str
    bloom_level: str | None
    position: Annotated[int, NonNeg]
    extensions: ExtJson
    archived_at: Timestamp | None


# --- 3.4 content ---------------------------------------------------------------------------------


class Provenance(BaseModel):
    """The provenance block every content version carries."""

    authorship: Authorship
    acquired_via: AcquiredVia
    author_kind: AuthorKind
    author_ref: str | None
    produced_by_stage_run_id: Annotated[Uuid7 | None, ref("stage_run")]
    upstream: Json | None
    licence: str | None
    personal_inputs: bool


PERSONAL_VERSION = "author_kind = 'learner' OR personal_inputs = 1"


class Lesson(Row):
    table: ClassVar[Table] = Table(
        "lesson",
        "head",
        DC.CONTENT,
        unique=(("path_id", "code"), ("id", "path_id")),
        fks=(
            FK(("skill_id", "path_id"), "skill", ("id", "path_id")),
            FK(("current_version_id", "id"), "lesson_version", ("id", "lesson_id"), deferred=True),
        ),
    )
    id: Uuid7
    skill_id: Uuid7
    path_id: Annotated[Uuid7, ref("path")]
    code: str
    kind: LessonKind
    position: Annotated[int, NonNeg]
    state: HeadState
    current_version_id: Uuid7 | None
    extensions: ExtJson


class LessonVersion(Row, Provenance):
    table: ClassVar[Table] = Table(
        "lesson_version",
        "version",
        None,
        unique=(("lesson_id", "version_no"), ("id", "lesson_id")),
        head=("lesson", "lesson_id"),
        lang_of="SELECT p.content_lang FROM lesson l JOIN path p ON p.id = l.path_id WHERE l.id = {row}.lesson_id",
        personal_when=PERSONAL_VERSION,
    )
    id: Uuid7
    lesson_id: Annotated[Uuid7, ref("lesson")]
    version_no: Annotated[int, Col(check="{c} >= 1")]
    version_hash: Hash
    lang: Lang
    translation_of_version_hash: Hash | None
    derived_from_version_id: Annotated[Uuid7 | None, ref("lesson_version")]
    title: str
    body: Json
    est_minutes: Annotated[int, NonNeg]
    status: GateStatus
    published_at: Timestamp | None
    created_at: Timestamp


class LessonVersionObjective(Row):
    table: ClassVar[Table] = Table(
        "lesson_version_objective",
        "link",
        DC.CONTENT,
        pk=("lesson_version_id", "objective_id"),
        without_rowid=True,
    )
    lesson_version_id: Annotated[Uuid7, ref("lesson_version")]
    objective_id: Annotated[Uuid7, ref("learning_objective")]
    role: Annotated[str, Col(check="{c} IN ('primary','secondary')")]


class Rendition(Row):
    table: ClassVar[Table] = Table(
        "rendition",
        "head",
        DC.CONTENT,
        unique=(("id", "lesson_id"),),
        fks=(FK(("current_version_id", "id"), "rendition_version", ("id", "rendition_id"), deferred=True),),
    )
    id: Uuid7
    lesson_id: Annotated[Uuid7, ref("lesson")]
    kind: RenditionKind
    state: HeadState
    current_version_id: Uuid7 | None


class RenditionVersion(Row, Provenance):
    table: ClassVar[Table] = Table(
        "rendition_version",
        "version",
        None,
        unique=(("rendition_id", "version_no"), ("id", "rendition_id")),
        head=("rendition", "rendition_id"),
        lang_of=(
            "SELECT p.content_lang FROM rendition r JOIN lesson l ON l.id = r.lesson_id"
            " JOIN path p ON p.id = l.path_id WHERE r.id = {row}.rendition_id"
        ),
        personal_when=PERSONAL_VERSION,
    )
    id: Uuid7
    rendition_id: Annotated[Uuid7, ref("rendition")]
    version_no: Annotated[int, Col(check="{c} >= 1")]
    version_hash: Hash
    lesson_version_id: Annotated[Uuid7, ref("lesson_version")]
    lang: Lang
    renderer: str
    spec_kind: SpecKind
    spec: Json
    narration: Json | None
    theme_id: Annotated[Uuid7 | None, ref("theme")]
    voice: str | None
    duration_s: Annotated[float | None, NonNeg]
    derived_from_version_id: Annotated[Uuid7 | None, ref("rendition_version")]
    status: GateStatus
    published_at: Timestamp | None
    created_at: Timestamp


class RenditionAsset(Row):
    table: ClassVar[Table] = Table(
        "rendition_asset", "link", DC.CONTENT, pk=("rendition_version_id", "role", "lang"), without_rowid=True
    )
    rendition_version_id: Annotated[Uuid7, ref("rendition_version")]
    role: Annotated[str, Col(check="{c} IN ('video','poster','audio','subtitles','image','attachment')")]
    lang: Lang
    recipe_hash: Hash
    asset_hash: Annotated[Hash, ref("asset", "hash")]


class Asset(Row):
    table: ClassVar[Table] = Table("asset", "entity", None, pk=("hash",))
    hash: Hash
    media_type: str
    kind: Annotated[str, Col(check="{c} IN ('video','audio','image','document','subtitles','other')")]
    bytes: Annotated[int, NonNeg]
    stored_at: str | None
    retention_class: Annotated[str, Col(check="{c} IN ('keep','renewable')")]
    evicted_at: Timestamp | None
    data_class: Annotated[DataClass, Col(check="{c} IN ('C','F')")]
    created_at: Timestamp


class AssetRef(Row):
    table: ClassVar[Table] = Table(
        "asset_ref",
        "link",
        DC.CONTENT,
        pk=("asset_hash", "owner_kind", "owner_id", "role"),
        without_rowid=True,
    )
    asset_hash: Annotated[Hash, ref("asset", "hash")]
    owner_kind: EntityKind
    owner_id: Uuid7
    role: str


class Source(Row):
    table: ClassVar[Table] = Table("source", "entity", None)
    id: Uuid7
    key: Annotated[str, Col(unique=True)]
    kind: Annotated[str, Col(check="{c} IN ('web','document','book','video','upload','other')")]
    title: str
    url: str | None
    accessed_at: Timestamp | None
    published_at: Date | None
    citation: Json
    data_class: Annotated[DataClass, Col(check="{c} IN ('C','F')")]
    extensions: ExtJson


class LessonVersionSource(Row):
    table: ClassVar[Table] = Table(
        "lesson_version_source", "link", DC.CONTENT, pk=("lesson_version_id", "source_id"), without_rowid=True
    )
    lesson_version_id: Annotated[Uuid7, ref("lesson_version")]
    source_id: Annotated[Uuid7, ref("source")]
    locator: str | None
    block_ids: Json | None


class LessonSearchDoc(Row):
    """Plain text of current published lesson versions; external content of `lesson_fts`."""

    table: ClassVar[Table] = Table("lesson_search_doc", "entity", DC.CONTENT, pk=("docid",))
    docid: int
    lesson_version_id: Annotated[Uuid7, Col(fk="lesson_version(id)", unique=True)]
    title: str
    body: str


class PromptTemplate(Row):
    table: ClassVar[Table] = Table(
        "prompt_template", "entity", DC.CONFIG, unique=(("key", "version", "lang"),)
    )
    id: Uuid7
    key: str
    version: Annotated[int, Col(check="{c} >= 1")]
    lang: Lang
    body: str
    body_hash: Hash
    input_schema: Json
    output_schema: Json
    created_at: Timestamp


class Theme(Row):
    table: ClassVar[Table] = Table("theme", "entity", DC.CONFIG)
    id: Uuid7
    kind: Annotated[str, Col(check="{c} IN ('ui','video')")]
    name: str
    tokens: Json
    inherits_ui_theme_id: Annotated[Uuid7 | None, ref("theme")]
    built_in: bool


# --- 3.5 assessment ------------------------------------------------------------------------------


class ExerciseType(Row):
    table: ClassVar[Table] = Table("exercise_type", "entity", DC.CONFIG, pk=("key",))
    key: str
    version: Annotated[int, Col(check="{c} >= 1")]
    payload_schema: Json
    grading_method: GradingMethod
    plugin: str
    status: Annotated[str, Col(check="{c} IN ('installed','unsupported')")]


class Item(Row):
    table: ClassVar[Table] = Table(
        "item",
        "head",
        DC.CONTENT,
        unique=(("path_id", "code"), ("id", "path_id")),
        fks=(
            FK(("skill_id", "path_id"), "skill", ("id", "path_id")),
            FK(("current_version_id", "id"), "item_version", ("id", "item_id"), deferred=True),
        ),
    )
    id: Uuid7
    skill_id: Uuid7
    path_id: Annotated[Uuid7, ref("path")]
    code: str
    type_key: Annotated[str, ref("exercise_type", "key")]
    state: HeadState
    current_version_id: Uuid7 | None
    extensions: ExtJson


class ItemVersion(Row, Provenance):
    table: ClassVar[Table] = Table(
        "item_version",
        "version",
        None,
        unique=(("item_id", "version_no"), ("id", "item_id")),
        head=("item", "item_id"),
        lang_of="SELECT p.content_lang FROM item i JOIN path p ON p.id = i.path_id WHERE i.id = {row}.item_id",
        personal_when=PERSONAL_VERSION,
    )
    id: Uuid7
    item_id: Annotated[Uuid7, ref("item")]
    version_no: Annotated[int, Col(check="{c} >= 1")]
    version_hash: Hash
    lang: Lang
    translation_of_version_hash: Hash | None
    derived_from_version_id: Annotated[Uuid7 | None, ref("item_version")]
    difficulty: Difficulty
    payload: Json
    support: Json
    origin_lesson_version_id: Annotated[Uuid7 | None, ref("lesson_version")]
    resets_review: bool
    status: GateStatus
    published_at: Timestamp | None
    created_at: Timestamp


class ItemVersionObjective(Row):
    table: ClassVar[Table] = Table(
        "item_version_objective",
        "link",
        DC.CONTENT,
        pk=("item_version_id", "objective_id"),
        without_rowid=True,
    )
    item_version_id: Annotated[Uuid7, ref("item_version")]
    objective_id: Annotated[Uuid7, ref("learning_objective")]


class Assessment(Row):
    table: ClassVar[Table] = Table("assessment", "entity", DC.PERSONAL)
    id: Uuid7
    learner_id: Annotated[Uuid7, ref("learner")]
    purpose: AssessmentPurpose
    skill_id: Annotated[Uuid7 | None, ref("skill")]
    item_version_ids: Json
    policy: TutorMode
    pass_mark: Annotated[float | None, Unit]
    settings_snapshot: Json
    created_at: Timestamp


# --- 3.6 tutoring --------------------------------------------------------------------------------


class Conversation(Row):
    table: ClassVar[Table] = Table("conversation", "entity", DC.PERSONAL)
    id: Uuid7
    learner_id: Annotated[Uuid7, ref("learner")]
    scope: ConversationScope
    scope_ref: Uuid7 | None
    title: str | None
    created_at: Timestamp
    archived_at: Timestamp | None


class Message(Row):
    table: ClassVar[Table] = Table("message", "entity", DC.FREE_TEXT)
    id: Uuid7
    conversation_id: Annotated[Uuid7, ref("conversation")]
    role: Annotated[str, Col(check="{c} IN ('learner','tutor','system')")]
    status: Annotated[str, Col(check="{c} IN ('queued','streaming','done','failed','withdrawn')")]
    content: Json
    context: Json
    policy: TutorMode
    stage_run_id: Annotated[Uuid7 | None, ref("stage_run")]
    leak_check: CheckVerdict | None
    guard: Annotated[str | None, Col(check="{c} IN ('template','checked','blocked')")]
    created_at: Timestamp
    completed_at: Timestamp | None


class Note(Row):
    table: ClassVar[Table] = Table(
        "note",
        "entity",
        DC.FREE_TEXT,
        checks=(
            "(rendition_version_id IS NULL) = (t_s IS NULL)",
            "NOT (rendition_version_id IS NOT NULL AND anchor IS NOT NULL)",
        ),
    )
    id: Uuid7
    learner_id: Annotated[Uuid7, ref("learner")]
    rendition_version_id: Annotated[Uuid7 | None, ref("rendition_version")]
    t_s: Annotated[float | None, NonNeg]
    anchor: Json | None
    text: str
    sent_message_id: Annotated[Uuid7 | None, ref("message")]
    created_at: Timestamp
    updated_at: Timestamp


class Proposal(Row):
    table: ClassVar[Table] = Table("proposal", "entity", DC.PERSONAL)
    id: Uuid7
    learner_id: Annotated[Uuid7, ref("learner")]
    path_id: Annotated[Uuid7, ref("path")]
    kind: ProposalKind
    rationale: str
    change: Json
    origin: Annotated[str, Col(check="{c} IN ('tutor','system')")]
    created_at: Timestamp
    expires_at: Timestamp | None


class Nudge(Row):
    """A proactive tutor suggestion: trigger, why it appeared, and what the learner did with it."""

    table: ClassVar[Table] = Table("nudge", "entity", DC.PERSONAL)
    id: Uuid7
    learner_id: Annotated[Uuid7, ref("learner")]
    path_id: Annotated[Uuid7 | None, ref("path")]
    trigger: Annotated[
        str, Col(check="{c} IN ('repeated_error','fast_guessing','unsent_notes','failed_test')")
    ]
    params: Json
    status: Annotated[str, Col(check="{c} IN ('shown','dismissed','accepted','expired')")]
    created_at: Timestamp
    decided_at: Timestamp | None


class LessonRequest(Row):
    table: ClassVar[Table] = Table("lesson_request", "entity", DC.FREE_TEXT)
    id: Uuid7
    learner_id: Annotated[Uuid7, ref("learner")]
    path_id: Annotated[Uuid7, ref("path")]
    skill_id: Annotated[Uuid7 | None, ref("skill")]
    prompt: str
    links: Json
    status: RequestStatus
    lesson_id: Annotated[Uuid7 | None, ref("lesson")]
    error: str | None
    created_at: Timestamp
    updated_at: Timestamp


# --- 3.7 generation ------------------------------------------------------------------------------


class GenerationJob(Row):
    table: ClassVar[Table] = Table("generation_job", "entity", DC.OPERATIONAL)
    id: Uuid7
    kind: Annotated[
        str,
        Col(
            check="{c} IN ('tree','lesson','rendition','items','translation','remedial','test_bank','placement',"
            "'grade','request','material','course','course_links')"
        ),
    ]
    target_kind: EntityKind
    target_id: Uuid7
    priority: int
    status: RunStatus
    attempt: Annotated[int, NonNeg]
    next_attempt_at: Timestamp | None
    requested_by: Annotated[str, Col(check="{c} IN ('learner','buffer','system')")]
    created_at: Timestamp
    finished_at: Timestamp | None
    error: str | None


class StageRun(Row):
    table: ClassVar[Table] = Table("stage_run", "entity", None)
    id: Uuid7
    job_id: Annotated[Uuid7, ref("generation_job")]
    stage: Stage
    input_manifest: Json
    input_hash: Hash
    output_hash: Hash | None
    status: RunStatus
    resource: str | None
    adapter: str
    adapter_version: str
    model_requested: str | None
    model_resolved: str | None
    provider: str | None
    reasoning_effort: str | None
    role: str | None
    cache_hit_of_stage_run_id: Annotated[Uuid7 | None, ref("stage_run")]
    data_class: Annotated[DataClass, Col(check="{c} IN ('C','P','F','O')")]
    started_at: Timestamp | None
    finished_at: Timestamp | None
    error: str | None


class StageInput(Row):
    table: ClassVar[Table] = Table(
        "stage_input",
        "link",
        DC.OPERATIONAL,
        pk=("stage_run_id", "input_output_hash", "role"),
        without_rowid=True,
    )
    stage_run_id: Annotated[Uuid7, ref("stage_run")]
    input_output_hash: Hash
    role: str


class StageOutput(Row):
    table: ClassVar[Table] = Table("stage_output", "entity", None, pk=("hash",))
    hash: Hash
    schema_id: str
    schema_version: Annotated[int, Col(check="{c} >= 1")]
    raw: Json
    parsed: Json | None
    data_class: Annotated[DataClass, Col(check="{c} IN ('C','P','F','O')")]
    created_at: Timestamp


class QualityCheck(Row):
    table: ClassVar[Table] = Table("quality_check", "entity", DC.OPERATIONAL)
    id: Uuid7
    subject_kind: EntityKind
    subject_version_id: Uuid7
    check: Check
    verdict: CheckVerdict
    fix_round: Annotated[int, NonNeg]
    independent: bool | None
    details: Json
    stage_run_id: Annotated[Uuid7 | None, ref("stage_run")]
    at: Timestamp


class Publication(Row):
    table: ClassVar[Table] = Table("publication", "entity", DC.OPERATIONAL)
    id: Uuid7
    head_kind: EntityKind
    head_id: Uuid7
    version_id: Uuid7
    at: Timestamp
    by: Annotated[str, Col(check="{c} IN ('gate','learner','import')")]


class BudgetEntry(Row):
    table: ClassVar[Table] = Table("budget_entry", "entity", DC.OPERATIONAL)
    id: Uuid7
    stage_run_id: Annotated[Uuid7 | None, ref("stage_run")]
    message_id: Annotated[Uuid7 | None, ref("message")]
    adapter: str
    provider: str | None
    in_tokens: Annotated[int, NonNeg]
    out_tokens: Annotated[int, NonNeg]
    reasoning_tokens: Annotated[int, NonNeg]
    cost_micros: Annotated[Micros, NonNeg]
    cost_currency: Currency
    price_ref: str | None
    estimated: bool
    at: Timestamp


class EgressRecord(Row):
    table: ClassVar[Table] = Table("egress_record", "entity", DC.OPERATIONAL)
    id: Uuid7
    adapter: str
    data_classes: Json
    bytes_out: Annotated[int, NonNeg]
    purpose: str
    stage_run_id: Annotated[Uuid7 | None, ref("stage_run")]
    message_id: Annotated[Uuid7 | None, ref("message")]
    at: Timestamp


class CostProfile(Row):
    table: ClassVar[Table] = Table(
        "cost_profile",
        "entity",
        DC.CONFIG,
        unique=(("adapter", "model", "provider", "unit", "settings_hash"),),
    )
    id: Uuid7
    adapter: str
    model: str
    provider: str
    unit: str
    settings_hash: Hash
    median_in_tokens: Annotated[int, NonNeg]
    median_out_tokens: Annotated[int, NonNeg]
    p90_in_tokens: Annotated[int, NonNeg]
    p90_out_tokens: Annotated[int, NonNeg]
    source: Annotated[str, Col(check="{c} IN ('shipped','ledger')")]
    updated_at: Timestamp


# --- 3.8 sharing ---------------------------------------------------------------------------------


class Package(Row):
    table: ClassVar[Table] = Table("package", "entity", DC.OPERATIONAL)
    id: Uuid7
    package_uid: Annotated[str, Col(unique=True)]
    title: str
    origin_author: str
    licence: str
    parent_package_digest: Hash | None


class PackageRecord(Row):
    table: ClassVar[Table] = Table("package_record", "entity", DC.OPERATIONAL)
    id: Uuid7
    package_id: Annotated[Uuid7, ref("package")]
    direction: Annotated[str, Col(check="{c} IN ('export','import')")]
    profile: PackageProfile
    format_version: str
    content_version: str
    package_digest: Hash
    signature_ref: str | None
    manifest: Json
    file_hash: Hash
    path_id: Annotated[Uuid7 | None, ref("path")]
    at: Timestamp


class ImportMap(Row):
    table: ClassVar[Table] = Table(
        "import_map",
        "link",
        DC.OPERATIONAL,
        pk=("package_id", "entity_kind", "external_code"),
        without_rowid=True,
    )
    package_id: Annotated[Uuid7, ref("package")]
    entity_kind: EntityKind
    external_code: str
    local_id: Uuid7
    last_content_version: str
    last_version_hash: Hash | None


class MergeConflict(Row):
    table: ClassVar[Table] = Table("merge_conflict", "entity", DC.OPERATIONAL)
    id: Uuid7
    head_kind: EntityKind
    head_id: Uuid7
    local_version_id: Uuid7
    incoming_version_hash: Hash
    status: Annotated[str, Col(check="{c} IN ('open','kept_local','took_incoming')")]
    created_at: Timestamp
    resolved_at: Timestamp | None


# --- learning from the learner's own material (migration 0005) ----------------------------------


class Course(Row):
    """A course or exam of a path built from material; once the plan is built it is one branch."""

    table: ClassVar[Table] = Table("course", "entity", DC.FREE_TEXT, unique=(("path_id", "code"),), since=5)
    id: Uuid7
    path_id: Annotated[Uuid7, ref("path")]
    code: str
    title: str
    term: str | None  # "Year 1, autumn": groups and orders the courses
    exam_date: Date | None
    adherence: Annotated[str, Col(check="{c} IN ('only','grounded','open')")]
    keep_order: bool
    position: Annotated[int, NonNeg]
    branch_id: Annotated[Uuid7 | None, ref("branch")]
    outline: Json | None  # the course's plan before it is built (skills with their anchors)
    extensions: ExtJson
    created_at: Timestamp
    archived_at: Timestamp | None


class Material(Row):
    """One file or link the learner brought; its text lives in `material_section`."""

    table: ClassVar[Table] = Table("material", "entity", DC.FREE_TEXT, since=5)
    id: Uuid7
    path_id: Annotated[Uuid7, ref("path")]
    course_id: Annotated[Uuid7, ref("course")]
    source_id: Annotated[Uuid7, ref("source")]
    role: Annotated[
        str, Col(check="{c} IN ('textbook','slides','lecture','notes','exercises','exams','other')")
    ]
    kind: Annotated[str, Col(check="{c} IN ('pdf','pptx','docx','text','audio','video','link')")]
    title: str
    file_name: str | None
    asset_hash: Hash | None  # the original file, or only its audio for a video
    size_bytes: Annotated[int, NonNeg]
    pages: Annotated[int | None, NonNeg]  # pages or slides
    duration_ms: Annotated[int | None, NonNeg]
    keep_original: bool
    state: Annotated[
        str,
        Col(
            check="{c} IN ('uploading','reading','read','transcribing','digesting','outlining','ready','failed')"
        ),
    ]
    progress: Annotated[float, Unit]
    error: str | None
    outline: Json | None  # the material's topics with the chunks they cover
    position: Annotated[int, NonNeg]
    extensions: ExtJson
    created_at: Timestamp
    updated_at: Timestamp


class MaterialSection(Row):
    """The material's tree: parts, chapters, sections, and the chunks that hold the text."""

    table: ClassVar[Table] = Table(
        "material_section", "entity", DC.FREE_TEXT, unique=(("material_id", "position"),), since=5
    )
    id: Uuid7
    material_id: Annotated[Uuid7, ref("material")]
    parent_id: Annotated[Uuid7 | None, ref("material_section")]
    position: Annotated[int, NonNeg]  # reading order over the whole material
    level: Annotated[str, Col(check="{c} IN ('part','chapter','section','chunk')")]
    title: str
    loc_kind: Annotated[str, Col(check="{c} IN ('page','slide','time')")]
    loc_start: Annotated[int, NonNeg]  # page or slide number from 1, or milliseconds
    loc_end: Annotated[int, NonNeg]
    text: str | None  # chunks only
    tokens: Annotated[int, NonNeg]
    digest: Json | None  # summary, concepts, definitions, formulas, notation
    content_hash: Hash | None


class SkillAnchor(Row):
    """A skill is built on these chunks of the learner's material."""

    table: ClassVar[Table] = Table(
        "skill_anchor",
        "link",
        DC.FREE_TEXT,
        pk=("skill_id", "section_id"),
        without_rowid=True,
        fks=(FK(("skill_id", "path_id"), "skill", ("id", "path_id")),),
        since=5,
    )
    skill_id: Uuid7
    section_id: Annotated[Uuid7, ref("material_section")]
    path_id: Annotated[Uuid7, ref("path")]
    role: Annotated[str, Col(check="{c} IN ('primary','supporting')")]


class SkillLink(Row):
    """Two skills, usually in different courses, that use the same idea without one needing the other."""

    table: ClassVar[Table] = Table(
        "skill_link",
        "link",
        DC.CONTENT,
        pk=("skill_id", "other_skill_id"),
        without_rowid=True,
        fks=(
            FK(("skill_id", "path_id"), "skill", ("id", "path_id")),
            FK(("other_skill_id", "path_id"), "skill", ("id", "path_id")),
        ),
        checks=("skill_id <> other_skill_id",),
        since=5,
    )
    skill_id: Uuid7
    other_skill_id: Uuid7
    path_id: Annotated[Uuid7, ref("path")]
    kind: Annotated[str, Col(check="{c} IN ('related')")]
    note: str | None


class ItemVersionSource(Row):
    """The chunks of the learner's material an item was written from."""

    table: ClassVar[Table] = Table(
        "item_version_source",
        "link",
        DC.FREE_TEXT,
        pk=("item_version_id", "section_id"),
        without_rowid=True,
        since=5,
    )
    item_version_id: Annotated[Uuid7, ref("item_version")]
    section_id: Annotated[Uuid7, ref("material_section")]
