"""Enums of the logical model.

Closed enums become `CHECK (x IN (...))` columns. Open enums (`OPEN_ENUMS`) become lookup tables seeded
from these classes; a fitness test asserts the tables and the classes match.
"""

from enum import StrEnum


class DeploymentMode(StrEnum):
    LOCAL = "local"
    SERVER = "server"


class PathStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class Authorship(StrEnum):
    GENERATED = "generated"
    HUMAN = "human"
    HUMAN_EDITED = "human_edited"
    TRANSLATED = "translated"


class AcquiredVia(StrEnum):
    LOCAL = "local"
    IMPORT = "import"
    FORK = "fork"


class AuthorKind(StrEnum):
    SYSTEM = "system"
    LEARNER = "learner"
    CURATOR = "curator"
    EXTERNAL = "external"


class Difficulty(StrEnum):
    INTRODUCTORY = "introductory"
    FOUNDATIONAL = "foundational"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class GoalType(StrEnum):
    EXAM = "exam"
    PRACTICAL = "practical"
    UNDERSTANDING = "understanding"
    CURIOSITY = "curiosity"


class LessonKind(StrEnum):
    CORE = "core"
    REMEDIAL = "remedial"
    REQUESTED = "requested"


class RenditionKind(StrEnum):
    READING = "reading"
    VIDEO = "video"
    SLIDES = "slides"
    AUDIO = "audio"


class HeadState(StrEnum):
    PLANNED = "planned"
    QUEUED = "queued"
    GENERATING = "generating"
    IN_REVIEW = "in_review"
    READY = "ready"
    FAILED = "failed"


class GateStatus(StrEnum):
    IN_REVIEW = "in_review"
    PASSED = "passed"
    REJECTED = "rejected"


class SkillState(StrEnum):
    LOCKED = "locked"
    AVAILABLE = "available"
    IN_PROGRESS = "in_progress"
    MASTERED = "mastered"
    NEEDS_REVIEW = "needs_review"


class AssessmentPurpose(StrEnum):
    PRACTICE = "practice"
    SKILL_TEST = "skill_test"
    PLACEMENT = "placement"
    REVIEW = "review"


class GradingMethod(StrEnum):
    EXACT = "exact"
    RULE = "rule"
    MODEL = "model"
    SELF = "self"


class HelpKind(StrEnum):
    NONE = "none"
    HINT = "hint"
    SOLUTION = "solution"
    TUTOR = "tutor"


class TutorMode(StrEnum):
    FREE = "free"
    LESSON = "lesson"
    PRACTICE = "practice"
    TEST_LOCKED = "test_locked"
    TEST_HINTS = "test_hints"
    REVIEW = "review"
    SETUP = "setup"


class ConversationScope(StrEnum):
    LESSON = "lesson"
    SKILL = "skill"
    PATH = "path"
    ATTEMPT = "attempt"  # a test or placement attempt: sealed (test policy) until it is submitted
    GENERAL = "general"


class ProposalKind(StrEnum):
    ADD_LESSON = "add_lesson"
    CHANGE_PREREQUISITES = "change_prerequisites"
    EXTRA_REVIEW = "extra_review"
    CHANGE_DIFFICULTY = "change_difficulty"
    OTHER = "other"


class RequestStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunStatus(StrEnum):
    """`job_status` and `stage_status`."""

    QUEUED = "queued"
    WAITING_RESOURCE = "waiting_resource"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CheckVerdict(StrEnum):
    PASS = "pass"  # noqa: S105
    WARN = "warn"
    FAIL = "fail"


class DataClass(StrEnum):
    PERSONAL = "P"
    FREE_TEXT = "F"
    CONTENT = "C"
    CONFIG = "K"
    SECRET = "S"  # noqa: S105
    OPERATIONAL = "O"


class PackageProfile(StrEnum):
    STRUCTURE = "structure"
    FULL = "full"
    CUSTOM = "custom"


class SpecKind(StrEnum):
    # Scenes are model-written code only (no declarative scene format).
    AGENT_CODE = "agent_code"
    RENDERED = "rendered"  # received ready-made in a package: the media are the content, no scene code


# --- open enums: lookup tables -------------------------------------------------------------------


class Stage(StrEnum):
    TREE_OUTLINE = "tree_outline"
    RESEARCH = "research"
    LESSON_BODY = "lesson_body"
    ITEMS_GENERATE = "items_generate"
    ITEMS_SUPPORT = "items_support"
    VIDEO_SCRIPT = "video_script"
    VIDEO_SCENE = "video_scene"
    TTS = "tts"
    RENDER = "render"
    REVIEW = "review"
    VIDEO_REVIEW = "video_review"  # the video's visual and consistency critics
    BLIND_SOLVE = "blind_solve"  # answer_key check by a second model
    TRANSLATE = "translate"
    LEVEL_CHECK = "level_check"  # the learner's level before the path is planned (0.7.4, migration 0002)
    REVIEW_BANK = "review_bank"  # a lesson's review questions, written in one call (migration 0003)
    NEXT_CHECK = "next_check"  # "What next?": direction questions and a quiz beyond the frontier (0004)
    NEXT_DIRECTIONS = "next_directions"  # "What next?": 2 or 3 directions with reasons (0004)
    NEXT_GROW = "next_grow"  # "What next?": the chosen direction's new branches (0004)
    TREE_REVISE = "tree_revise"  # the plan preview, revised with the learner's feedback (0005)
    MATERIAL_DIGEST = "material_digest"  # a batch of the learner's material chunks, summarised (0005)
    MATERIAL_OUTLINE = "material_outline"  # one material's topics, from its chunk digests (0005)
    COURSE_OUTLINE = "course_outline"  # a course's skills, anchored in its materials (0005)
    COURSE_REVISE = "course_revise"  # a course's plan, revised with the learner's feedback (0005)
    COURSE_LINKS = "course_links"  # prerequisites and related skills across courses (0005)
    MATERIAL_VISION = "material_vision"  # pages with formulas or figures, read from their images (0006)
    STUDIES_ARRANGE = "studies_arrange"  # a path's name and courses, proposed from the learner's files (0007)


class Check(StrEnum):
    SCHEMA = "schema"
    LINKS = "links"
    ANSWER_KEY = "answer_key"
    SUPPORT_CONSISTENCY = "support_consistency"
    LEAK = "leak"
    REVIEWER = "reviewer"
    LEVEL_FIT = "level_fit"
    DAG = "dag"
    LICENCE = "licence"


class EntityKind(StrEnum):
    PATH = "path"
    BRANCH = "branch"
    SKILL = "skill"
    OBJECTIVE = "objective"
    LESSON = "lesson"
    RENDITION = "rendition"
    ITEM = "item"
    SOURCE = "source"
    ASSET = "asset"
    LESSON_VERSION = "lesson_version"
    RENDITION_VERSION = "rendition_version"
    ITEM_VERSION = "item_version"
    MESSAGE = "message"
    NOTE = "note"
    LESSON_REQUEST = "lesson_request"
    CONVERSATION = "conversation"
    RESPONSE = "response"  # a learner answer (its response_given event id), target of grading jobs
    MATERIAL = "material"  # a file of the learner's own material (0005)
    COURSE = "course"  # a course of a path built from material (0005)


class EventType(StrEnum):
    PATH_STATUS_CHANGED = "path.status_changed"
    LESSON_STARTED = "lesson.started"
    LESSON_COMPLETED = "lesson.completed"
    VIDEO_WATCHED = "video.watched"
    ATTEMPT_STARTED = "attempt.started"
    ATTEMPT_FINISHED = "attempt.finished"
    RESPONSE_GIVEN = "assessment.response_given"
    RESPONSE_GRADED = "assessment.response_graded"
    GRADE_CONTESTED = "assessment.grade_contested"
    SUPPORT_SHOWN = "item.support_shown"
    TUTOR_HELP_GIVEN = "tutor.help_given"
    SKILL_TEST_RESULT = "skill.test_result"
    SKILL_PLACED = "skill.placed"
    SKILL_OVERRIDE = "skill.override"
    PROPOSAL_DECIDED = "tutor.proposal_decided"
    SETTING_CHANGED = "setting.changed"


# lookup table name -> enum (open enums as rows)
OPEN_ENUMS: dict[str, type[StrEnum]] = {
    "stage_kind": Stage,
    "check_kind": Check,
    "entity_kind_ref": EntityKind,
    "event_type": EventType,
}
