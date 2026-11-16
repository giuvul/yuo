"""Response models: the API contract the web client's types are generated from."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class SetupOut(BaseModel):
    learner_id: str
    bindings: dict[str, dict[str, str]]
    warnings: list[str]
    desktop: bool  # this computer only, signed in by starting Yuo
    waitlist_url: str | None  # the hosted waitlist form, when this build names one
    video_unavailable: str | None = None  # why this installation makes no videos (a code), None when it can


class PathSummary(BaseModel):
    id: str
    title: str
    subject: str
    status: str
    difficulty: str
    content_lang: str
    created_at: str


class LessonRef(BaseModel):
    id: str
    code: str
    kind: str
    state: str
    title: str | None


class ObjectiveOut(BaseModel):
    id: str
    statement: str


class SkillOut(BaseModel):
    id: str
    code: str
    title: str
    summary: str
    requires: list[str]
    objectives: list[ObjectiveOut] = []
    lessons: list[LessonRef]


class BranchOut(BaseModel):
    id: str
    code: str
    title: str
    skills: list[SkillOut]


class JobRef(BaseModel):
    id: str
    kind: str
    status: str
    error: str | None
    attempt: int
    target_kind: str
    target_id: str
    title: str | None = Field(None, description="The lesson, skill or path the job is for, by name")
    step: str | None = Field(
        None, description="What a running job is doing now (a stage or a video step code), when known"
    )
    round: int | None = Field(None, description="A video's current round (1-based), when it has rounds")
    rounds: int | None = Field(None, description="At most this many rounds")
    running_s: int | None = Field(None, description="Seconds this attempt has been running")
    typical_s: int | None = Field(None, description="How long a job of this kind usually takes, in seconds")
    retry_at: str | None = Field(None, description="When a job that failed for now is tried again")
    lesson_id: str | None = Field(None, description="The lesson a lesson or video job is for")


class JobDone(JobRef):
    created_at: str
    finished_at: str | None
    started_at: str | None = Field(
        None, description="When its first stage started (none for a job with no stage)"
    )
    resolved: bool = Field(False, description="It failed, and a later job for the same target did the work")


class JobHistoryOut(BaseModel):
    jobs: list[JobDone]
    next: str | None = Field(None, description="Pass as `before` for the next, older page")


class DeviceOut(BaseModel):
    device_id: str


class PathCreated(BaseModel):
    path_id: str
    job_id: str


class JobStarted(BaseModel):
    job_id: str


class PathOut(BaseModel):
    id: str
    title: str
    subject: str
    goal: str
    status: str
    difficulty: str
    content_lang: str
    branches: list[BranchOut]
    jobs: list[JobRef]
    level_check: Literal["none", "preparing", "ready", "done", "skipped"] = "none"


class LevelQuestionOut(BaseModel):
    prompt: str
    options: list[str]
    topic: str


class LevelResultOut(BaseModel):
    level: int
    difficulty: str
    right: int
    total: int
    known: list[str]
    unknown: list[str]


class LevelCheckOut(BaseModel):
    status: Literal["none", "preparing", "ready", "done", "skipped"]
    questions: list[LevelQuestionOut]
    result: LevelResultOut | None
    job_id: str | None
    failed: bool  # writing the questions failed: the learner can skip


class NextQuestionOut(BaseModel):
    prompt: str
    options: list[str]


class NextQuizOut(BaseModel):
    prompt: str
    options: list[str]
    topic: str


class NextQuizResultOut(BaseModel):
    right: int
    total: int
    ready: list[str]
    not_yet: list[str]


class NextDiagnosisOut(BaseModel):
    lessons_done: int
    lessons_left: int
    finished_branches: list[str]
    strong: list[str]
    weak: list[str]
    shaky: list[str] = Field(description="objectives that keep slipping in reviews or practice")


class NextDirectionOut(BaseModel):
    code: str
    kind: Literal["deeper", "wider", "apply", "fix"]
    title: str
    reason: str
    preview: list[str]


class NextOut(BaseModel):
    """The "What next?" checkpoint of a path (yuo/curriculum/next_steps.py)."""

    status: Literal["none", "preparing", "ready", "proposing", "proposed", "growing", "done", "dismissed"]
    offer: Literal["branch_done", "running_low"] | None = Field(
        description="why the path page invites the learner now; null: no invitation"
    )
    available: bool = Field(
        description="the path page shows What next?: 75% of the lessons studied, or one is open"
    )
    completion: float = Field(description="studied lessons over studied and still planned ones, 0 to 1")
    diagnosis: NextDiagnosisOut
    questions: list[NextQuestionOut]
    quiz: list[NextQuizOut]
    quiz_result: NextQuizResultOut | None
    directions: list[NextDirectionOut]
    chosen: str | None
    added: list[str] = Field(description="titles of the branches the last checkpoint added")
    job_id: str | None
    failed: bool  # the writing step failed: the learner can retry or close the checkpoint


class VideoOut(BaseModel):
    rendition_id: str
    state: Literal["planned", "queued", "generating", "in_review", "ready", "failed"]
    version_id: str | None
    duration_s: float | None
    lang: str | None
    assets: dict[str, str]  # role (video, subtitles, poster) -> asset hash, served at /api/assets/{hash}


class LessonOut(BaseModel):
    id: str
    state: str
    path_id: str
    skill_id: str
    version_id: str | None
    title: str | None
    body: list[dict[str, Any]] | None
    est_minutes: int | None
    lang: str | None
    skill_title: str
    path_title: str
    practice_items: int
    video: VideoOut | None = None  # None: no video for this lesson (reading only, or video unavailable)
    video_unavailable: str | None = None  # why this installation makes no videos, when it makes none


class OptionOut(BaseModel):
    id: str
    text: str


class ChoiceView(BaseModel):
    prompt: str
    options: list[OptionOut]


class ClozeView(BaseModel):
    text: str
    gaps: int


class OrderingView(BaseModel):
    prompt: str
    steps: list[OptionOut]


class MatchingView(BaseModel):
    prompt: str
    left: list[str]
    right: list[str]


class FlashcardView(BaseModel):
    front: str


class PromptView(BaseModel):
    prompt: str


class ItemBase(BaseModel):
    item_version_id: str


class McqItem(ItemBase):
    type: Literal["mcq"]
    view: ChoiceView


class MultiItem(ItemBase):
    type: Literal["multi"]
    view: ChoiceView


class ClozeItem(ItemBase):
    type: Literal["cloze"]
    view: ClozeView


class OrderingItem(ItemBase):
    type: Literal["ordering"]
    view: OrderingView


class MatchingItem(ItemBase):
    type: Literal["matching"]
    view: MatchingView


class FlashcardItem(ItemBase):
    type: Literal["flashcard"]
    view: FlashcardView


class ShortAnswerItem(ItemBase):
    type: Literal["short_answer"]
    view: PromptView


PracticeItem = Annotated[
    McqItem | MultiItem | ClozeItem | OrderingItem | MatchingItem | FlashcardItem | ShortAnswerItem,
    Field(discriminator="type"),
]


class AssessmentOut(BaseModel):
    assessment_id: str | None
    purpose: Literal["practice", "skill_test", "placement", "review"]
    items: list[PracticeItem]
    due: int | None = None


PracticeOut = AssessmentOut


class HintOut(BaseModel):
    level: int
    text: str
    last: bool


class RevealOut(BaseModel):
    back: str


class Graded(BaseModel):
    pending: bool = False
    hidden: bool = False  # tests: results come with attempt.finished
    score: float | None = None
    correct: Any = None
    explanation: str | None = None
    solution: str | None = None
    rationale: str | None = None
    # review sessions: staged feedback. Before `resolved`, `correct` and `solution` are absent and
    # `rationales` holds only the options the learner tried.
    outcome: Literal["new", "open", "first", "second", "revealed"] | None = None
    resolved: bool | None = None
    tries: int | None = None
    tried: list[str] | None = None
    hints: int | None = None
    guessing: bool | None = None
    rationales: dict[str, str] | None = None
    concept: str | None = None
    revisit: str | None = None
    lesson_id: str | None = None
    lesson_title: str | None = None


class ReviewObjective(BaseModel):
    id: str
    statement: str
    retrievability: float
    due: bool
    due_at: str
    reviews: int


class ReviewSkill(BaseModel):
    id: str
    title: str
    branch_id: str
    retrievability: float
    due: int
    questions: int
    objectives: list[ReviewObjective]


class ReviewOpenSession(BaseModel):
    assessment_id: str
    attempt_id: str | None
    size: int
    answered: int


class ReviewRecent(BaseModel):
    attempt_id: str
    finished_at: str
    answered: int
    first_try: int


class ReviewBranch(BaseModel):
    id: str
    title: str


class ReviewHubOut(BaseModel):
    path_id: str
    memory: float | None  # mean chance of recalling a learned objective now; None before the first lesson
    objectives: int
    due: int
    fading: int
    strong: int
    questions: int  # ready to ask
    writing: int  # lessons whose questions are being written
    allowed_today: int
    sizes: list[int]
    open_session: ReviewOpenSession | None
    skills: list[ReviewSkill]
    branches: list[ReviewBranch]
    recent: list[ReviewRecent]
    cards_due: int


class ReviewItem(BaseModel):
    item_version_id: str
    item_id: str
    type: str
    view: dict[str, Any]
    skill_id: str
    skill_title: str
    objectives: list[str]
    cross: bool
    kind: Literal["recall", "apply", "scenario", "compare", "debug"]
    level: int
    state: Graded | None  # set when a session is resumed


class ReviewSessionIn(BaseModel):
    size: Literal[5, 10, 20] = 10
    skill_id: str | None = None
    branch_id: str | None = None


class ReviewSessionOut(BaseModel):
    assessment_id: str | None  # None: nothing to review (no questions yet, or today's cap is reached)
    attempt_id: str | None  # set when resuming a session already started
    purpose: Literal["review"] = "review"
    path_id: str | None = None
    size: int
    items: list[ReviewItem]
    reserves: list[ReviewItem]  # one per objective: asked at the end when a question on it was revealed


class ReviewResultItem(Graded):
    item_version_id: str
    prompt: str


class ReviewResultSkill(BaseModel):
    id: str
    title: str
    before: float
    after: float | None
    next_due: str | None


class ReviewResultOut(BaseModel):
    attempt_id: str
    finished: bool
    answered: int
    first_try: int
    second_try: int
    revealed: int
    score: float
    xp: int | None
    skills: list[ReviewResultSkill]
    items: list[ReviewResultItem]


class ReportIn(BaseModel):
    reason: str = Field(default="", max_length=300)


class NudgeOut(BaseModel):
    id: str
    trigger: Literal["repeated_error", "fast_guessing", "unsent_notes", "failed_test"]
    path_id: str | None
    params: dict[str, Any]
    level: Literal["off", "quiet", "coach", "active"]  # quiet: a dot only, never opens the tutor
    status: Literal["shown", "dismissed", "accepted", "expired"] = "shown"
    created_at: str | None = None


class IngestOut(BaseModel):
    accepted: list[str]
    duplicates: list[str]
    rejected: dict[str, str]
    graded: dict[str, Graded]
    outcomes: dict[str, dict[str, Any]]
    nudges: list[NudgeOut] = []


class DueOut(BaseModel):
    due: int
    allowed_today: int
    item_version_ids: list[str]


class SkillProgress(BaseModel):
    state: Literal["locked", "available", "in_progress", "mastered", "needs_review"]
    mastery: float
    evidence: int


class BranchProgress(BaseModel):
    id: str
    title: str
    xp: int
    level: int


class DayOut(BaseModel):
    learning_day: str
    xp: int
    sessions: int
    streak_len: int
    grace_used: int


class AchievementOut(BaseModel):
    key: str
    unlocked_at: str


class ProgressOut(BaseModel):
    skills: dict[str, SkillProgress]
    gamification: Literal["off", "minimal", "full"]
    branches: list[BranchProgress] | None = None
    xp_total: int | None = None
    streak: int | None = None
    days: list[DayOut] | None = None
    achievements: list[AchievementOut] | None = None


class RequestOut(BaseModel):
    request_id: str
    job_id: str


class RequestRow(BaseModel):
    id: str
    prompt: str
    status: str
    lesson_id: str | None
    error: str | None
    created_at: str


class NoteOut(BaseModel):
    id: str
    text: str
    bid: str | None
    lesson_version_id: str | None
    sent_message_id: str | None  # sent to the tutor with this message
    created_at: str
    updated_at: str
    rendition_version_id: str | None = None  # a note on the video (the notes bubble)
    t_s: float | None = Field(None, description="Where in the video, in seconds, for a note on the video")


class NoteCreated(BaseModel):
    note_id: str


class SettingOut(BaseModel):
    key: str
    cfg: str
    levels: list[str]
    value: Any
    source: str | None  # level the value comes from; None = default
    default: Any
    explanation: str
    example: str
    suggestion: str
    impact: list[str]
    weakens_learning: str | None


class StageOut(BaseModel):
    stage: str
    status: str
    adapter: str
    model_requested: str | None
    cache_hit_of_stage_run_id: str | None
    cost_micros: int
    notional: int | None


class JobOut(BaseModel):
    id: str
    kind: str
    status: str
    attempt: int
    error: str | None
    target_kind: str
    target_id: str
    stages: list[StageOut]


class EstimateLine(BaseModel):
    unit: str
    count: float
    adapter: str
    model: str
    low: float
    high: float
    billed: bool
    source: str


class PlanUsageOut(BaseModel):
    """Subscription use as a share of a plan's limits (yuo/data/plan_limits.json: user measurements, or for Codex
    an estimate from the published message ranges)."""

    cli: str
    plan: str
    label: str
    window_pct: float | None = Field(
        description="Share of one 5-hour window, in percent; null: no such limit"
    )
    week_pct: float | None = Field(description="Share of the weekly limit, in percent; null: not published")
    lessons_per_window: int | None
    lessons_per_week: int | None


class EstimateOut(BaseModel):
    low_usd: float
    high_usd: float
    notional_usd: float
    missing: list[str]
    lines: list[EstimateLine]
    plan_usage: list[PlanUsageOut] = []


# --- tutor ----------------------------------------------------------------------------------

TutorPolicyId = Literal[
    "free",
    "lesson",
    "practice.before_attempt",
    "practice.after_attempt",
    "test.locked",
    "test.hints",
    "placement",
    "test.debrief",
    "review.before_recall",
    "review.after_recall",
    "review.coach",
    "review.resolved",
    "setup",
]


class Chip(BaseModel):
    kind: Literal["path", "skill", "lesson", "item", "selection", "notes", "memory"]
    label: str  # titles and selections as they are; for item, notes and memory render from the fields below
    n: int | None = None  # item: question number; notes: how many
    of: int | None = None  # item: questions in the assessment


class TutorRefs(BaseModel):
    path_id: str | None
    skill_id: str | None
    lesson_id: str | None
    lesson_version_id: str | None
    attempt_id: str | None
    assessment_id: str | None
    item_version_id: str | None
    item_state: Literal["none", "unanswered", "answered"]
    position: str | None


class TutorContextOut(BaseModel):
    policy: TutorPolicyId
    mode: Literal["free", "lesson", "practice", "test_locked", "test_hints", "review", "setup"]
    checked: bool  # replies are checked for answer leaks before they are shown (no streaming)
    sealed: bool  # a test thread: no lesson, notes or memory in the context
    sealed_by_open_test: bool  # a skill test or placement is open: its policy applies on every screen
    scope: Literal["lesson", "skill", "path", "attempt", "general"]
    scope_ref: str | None
    conversation_id: str | None
    chips: list[Chip]
    refs: TutorRefs


class TutorMessageOut(BaseModel):
    id: str
    conversation_id: str
    role: Literal["learner", "tutor", "system"]
    status: Literal["queued", "streaming", "done", "failed", "withdrawn"]
    text: str
    template: (
        Literal["tutor.guess", "tutor.guess.test", "tutor.blocked", "tutor.review", "tutor.review.coach"]
        | None
    )
    error: str | None  # failed: budget, quota, auth, timeout, transport, empty, error
    proposal_id: str | None
    path_id: str | None  # the path a proposal belongs to
    retried: bool = False
    memory_ids: list[str]
    policy: str
    guard: Literal["template", "checked", "blocked"] | None
    chips: list[Chip]
    answers: list[str]  # a reply: the learner messages it answers
    created_at: str
    completed_at: str | None
    duplicate: bool = False


class RequeuedOut(BaseModel):
    requeued: list[TutorMessageOut]
    retried: TutorMessageOut


class ConversationOut(BaseModel):
    id: str
    scope: Literal["lesson", "skill", "path", "attempt", "general"]
    scope_ref: str | None
    title: str | None
    created_at: str
    last_at: str | None
    messages: int


class MemoryOut(BaseModel):
    id: str
    kind: Literal["preference", "misconception", "goal", "fact"]
    text: str
    source: Literal["tutor", "learner", "system"]
    evidence_ref: dict[str, Any] | None
    created_at: str
    updated_at: str


class MemoryCreated(BaseModel):
    memory_id: str


class ProposalOut(BaseModel):
    id: str
    path_id: str
    kind: Literal["add_lesson", "change_prerequisites", "extra_review", "change_difficulty", "other"]
    rationale: str
    change: dict[str, Any]
    origin: Literal["tutor", "system"]
    status: Literal["pending", "accepted", "rejected", "expired"]
    created_at: str
    expires_at: str | None


class ExportPreviewOut(BaseModel):
    contents: list[str]
    counts: dict[str, int]
    asset_bytes: int
    personal_included: list[str]  # learner-made or personal content in this export
    personal_available: list[str]  # what "include my own content" would add
    goal: str | None  # the path's goal, often personal: shown for review before sharing


class PackagePreviewOut(BaseModel):
    title: str
    profile: str
    contents: list[str]
    counts: dict[str, int]
    content_lang: str
    licence: str
    content_version: str
    format_version: str
    upgraded_from: str | None
    package_digest: str
    notices: list[str]
    personal: list[str]
    update_of: str | None  # the path an earlier import of this package made
    installed_version: str | None
    can_create: bool


class PackageUploadOut(BaseModel):
    token: str
    preview: PackagePreviewOut | None
    error: str | None  # why the package was refused (nothing is imported)


class ImportedOut(BaseModel):
    path_id: str


class ErasedOut(BaseModel):
    """What an erasure removed, by table: numbers only, never content."""

    counts: dict[str, int]
