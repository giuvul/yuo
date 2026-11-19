"""Request bodies of the API (pydantic models); responses are in `yuo.api.schemas`."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from yuo.learning.events import IncomingEvent


class PathIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    subject: str = Field(default="", max_length=300)  # optional: the title and goal say what the path covers
    goal: str = Field(min_length=1, max_length=600)
    goal_type: Literal["exam", "practical", "understanding", "curiosity"] = "understanding"
    difficulty: Literal["introductory", "foundational", "intermediate", "advanced", "expert"] = "foundational"
    content_lang: str | None = Field(default=None, min_length=2, max_length=35)
    custom_instructions: str = Field(default="", max_length=1000)
    level_check: bool = (
        False  # a short check of what the learner knows before the path is planned (the app asks)
    )
    preview: bool = False  # the learner sees the plan and can change it before it is built (the app asks)


class PreviewFeedbackIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class LevelAnswersIn(BaseModel):
    answers: list[int | None] = Field(
        default_factory=list, max_length=10
    )  # option index; None: "I don't know"
    skip: bool = False  # no level check: the path is planned from the stated level


class NextAnswerIn(BaseModel):
    option: int | None = Field(default=None, ge=0, le=9)
    text: str = Field(default="", max_length=300)


class NextAnswersIn(BaseModel):
    quiz: list[int | None] = Field(default_factory=list, max_length=5)  # option index; None: "I don't know"
    answers: list[NextAnswerIn] = Field(default_factory=list, max_length=4)


class NextChoiceIn(BaseModel):
    code: str = Field(min_length=1, max_length=80)


class PresetIn(BaseModel):
    preset: Literal["claude", "codex", "local", "open"]
    consent: bool = False  # the learner agreed to the consent text for a subscription CLI


class DeviceIn(BaseModel):
    label: str = Field(default="browser", max_length=80)


class RequestIn(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)
    links: list[str] = Field(default_factory=list, max_length=10)
    skill_id: str | None = None


class NoteIn(BaseModel):
    """A note on a lesson (its version, optionally a block) or on a moment of its video (the notes bubble)."""

    text: str = Field(min_length=1, max_length=5000)
    lesson_version_id: str | None = None
    bid: str | None = None
    rendition_version_id: str | None = None
    t_s: float | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _one_anchor(self) -> NoteIn:
        video = self.rendition_version_id is not None
        if video == (self.lesson_version_id is not None) or video != (self.t_s is not None):
            raise ValueError("a note is on a lesson version, or on a video version at a time")
        return self


class NoteEdit(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class SettingIn(BaseModel):
    value: Any
    level: Literal["learner", "path"] = "learner"
    ref: str | None = None


class TutorSelection(BaseModel):
    text: str = Field(default="", max_length=2000)
    bid: str | None = None


class TutorContextIn(BaseModel):
    """What the screen shows, as references; the server resolves content and policy."""

    screen: str = Field(default="other", max_length=40)
    path_id: str | None = None
    skill_id: str | None = None
    lesson_id: str | None = None
    attempt_id: str | None = None
    item_version_id: str | None = None
    selection: TutorSelection | None = None
    note_ids: list[str] = Field(default_factory=list, max_length=20)
    excluded: list[Literal["path", "skill", "lesson", "selection", "notes", "memory", "material"]] = Field(
        default_factory=list
    )
    video_s: float | None = None
    locale: str | None = Field(default=None, max_length=35)


class TutorMessageIn(BaseModel):
    id: str  # client uuid7: a retry from the outbox is answered once
    text: str = Field(min_length=1, max_length=4000)
    context: TutorContextIn = Field(default_factory=TutorContextIn)


class TutorEdit(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class MemoryIn(BaseModel):
    kind: Literal["preference", "misconception", "goal", "fact"]
    text: str = Field(min_length=1, max_length=300)


class MemoryEdit(BaseModel):
    text: str = Field(min_length=1, max_length=300)


class ExportIn(BaseModel):
    profile: Literal["structure", "full", "custom"] = "full"
    components: list[Literal["curriculum", "lessons", "items", "renditions.video", "sources"]] = Field(
        default_factory=list
    )
    include_personal: bool = False  # learner-made and personal content, off by default (spec §7)
    formats: list[str] = Field(default_factory=list, max_length=10)  # standard-format copies under standard/


class ImportIn(BaseModel):
    mode: Literal["new", "update"] = "new"


class EventsIn(BaseModel):
    device_id: str
    events: list[IncomingEvent] = Field(max_length=500)


class CourseIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    term: str | None = Field(default=None, max_length=60)
    exam_date: date | None = None
    adherence: Literal["only", "grounded", "open"] = "grounded"
    keep_order: bool = True


class CourseChangeIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    term: str | None = Field(default=None, max_length=60)
    exam_date: date | None = None
    adherence: Literal["only", "grounded", "open"] | None = None
    keep_order: bool | None = None


class StudiesIn(BaseModel):
    # the studies, e.g. "Mechanical Engineering"; empty with no courses: both are proposed from the files
    title: str = Field(default="", max_length=120)
    goal: str = Field(default="", max_length=600)
    content_lang: str | None = Field(default=None, min_length=2, max_length=35)
    courses: list[CourseIn] = Field(default_factory=list, max_length=60)


class ArrangeIn(BaseModel):
    feedback: str | None = Field(
        default=None, max_length=2000
    )  # a change to the proposal, in the learner's words


class ArrangeAcceptIn(BaseModel):
    title: str | None = Field(default=None, max_length=120)  # the path's name, when the learner changed it
    adherence: list[Literal["only", "grounded", "open"]] = Field(
        default_factory=list, max_length=60
    )  # per course


class MaterialIn(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    role: Literal["textbook", "slides", "lecture", "notes", "exercises", "exams", "other"] | None = None
    title: str | None = Field(default=None, max_length=200)


class MaterialChangeIn(BaseModel):
    role: Literal["textbook", "slides", "lecture", "notes", "exercises", "exams", "other"] | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
