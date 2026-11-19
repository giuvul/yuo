"""Plain inputs of the application service (no database imports: the API uses these)."""

from dataclasses import dataclass, field


@dataclass
class PathForm:
    title: str
    subject: str
    goal: str
    goal_type: str = "understanding"
    goal_types: list[str] = field(
        default_factory=list
    )  # every reason the learner gave; goal_type is the first
    depth: str = "standard"  # short, standard or deep (yuo.curriculum.depth)
    difficulty: str = "foundational"
    content_lang: str | None = None
    custom_instructions: str = ""
    level_check: bool = False
    preview: bool = False
