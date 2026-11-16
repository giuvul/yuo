"""What one feature part of the application service asks of another.

Parts depend on these Protocols, never on each other's modules; `yuo.app.service.Service` wires the real
objects in. A test can hand a part a small fake instead of the whole service.
"""

import sqlite3
from typing import Any, Protocol

from yuo.app.items import ItemContext
from yuo.core.enums import DataClass
from yuo.core.llm import Binding, Role
from yuo.setup import settings


class Learners(Protocol):
    def ensure_learner(self) -> str:
        """The learner's id, made with the installation row on first use."""
        ...


class Models(Protocol):
    def binding(self, role: Role) -> Binding:
        """The model bound to a role."""
        ...

    def require_ai_ready(self) -> None:
        """Raises AiNotReady when a chosen subscription program is missing or signed out."""
        ...


class PathInputs(Protocol):
    def path_inputs(self, c: sqlite3.Connection, path_id: str) -> tuple[dict[str, Any], DataClass]:
        """What generation needs to know about a path (language, level, goal...) and its data class."""
        ...


class SettingsReader(Protocol):
    def setting(self, key: str, scopes: dict[settings.Level, str | None] | None = None) -> Any:
        """A setting's effective value."""
        ...


class Buffer(Protocol):
    def top_up_buffer(self, c: sqlite3.Connection, path_id: str) -> list[str]:
        """Queue the next lessons of a path so a few are always ready; the job ids queued."""
        ...


class ItemWriting(Protocol):
    def skill_context(
        self,
        c: sqlite3.Connection,
        skill_id: str,
        use: str,
        body: list[dict[str, Any]] | None = None,
        origin: str | None = None,
    ) -> ItemContext:
        """What item writing needs to know about a skill."""
        ...

    def generator_and_reviewer(self) -> tuple[Any, Any, bool]:
        """The generator and reviewer bindings, and whether they are independent."""
        ...


class StudyRecords(Protocol):
    def project_events(self, c: sqlite3.Connection, learner: str, event_ids: list[str]) -> None:
        """Apply learning events to the learner's projections."""
        ...

    def insert_request(
        self, c: sqlite3.Connection, learner: str, path_id: str, prompt: str, skill_id: str | None
    ) -> tuple[str, str]:
        """Record a lesson request and queue its job: (request id, job id)."""
        ...


class LessonRequests(Protocol):
    def request_lesson(self, lesson_id: str) -> str:
        """Queue a lesson to be written now; the job id."""
        ...


class VideoRetry(Protocol):
    def retry_video(self, lesson_id: str) -> str:
        """Make a lesson's video again after it failed; the job id."""
        ...
