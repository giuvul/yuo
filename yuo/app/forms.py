"""Plain inputs of the application service (no database imports: the API uses these)."""

from dataclasses import dataclass


@dataclass
class PathForm:
    title: str
    subject: str
    goal: str
    goal_type: str = "understanding"
    difficulty: str = "foundational"
    content_lang: str | None = None
    custom_instructions: str = ""
    level_check: bool = False
