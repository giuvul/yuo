"""Answers an AI assistant collected before Yuo started (SETUP.md): the wizard is pre-filled from them, once.

The assistant that installs Yuo may ask the learner about themselves and what they want to learn, then write
`setup-answers.json` into Yuo's data folder (or pass it to `yuo setup-answers`). The wizard's "About you" and
"Your first path" steps start from these answers; the learner checks and changes them before anything is
saved. The file is deleted when the wizard finishes, or earlier when the learner says not to use it. It never
holds keys or passwords: those are typed into Yuo itself.

Each part is checked on its own: a part that does not fit is left out (and logged), the rest is still used.
"""

import json
from pathlib import Path
from typing import Any, Literal
from zoneinfo import available_timezones

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

log = structlog.get_logger()

FILE_NAME = "setup-answers.json"
LANG = r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$"


class Profile(BaseModel):
    """The wizard's "About you" fields (as in `PATCH /api/me`, without the theme); every one optional."""

    model_config = ConfigDict(extra="ignore")
    display_name: str | None = Field(default=None, min_length=1, max_length=60)
    ui_lang: str | None = Field(default=None, pattern=LANG, max_length=35)
    content_lang: str | None = Field(default=None, pattern=LANG, max_length=35)
    tz: str | None = Field(default=None, max_length=64)
    session_minutes: int | None = Field(default=None, ge=5, le=120)
    interests: str | None = Field(default=None, max_length=500)

    @field_validator("tz")
    @classmethod
    def _known_zone(cls, v: str | None) -> str | None:
        if v is not None and v not in available_timezones():
            raise ValueError(f"unknown time zone {v!r}")
        return v


class FirstPath(BaseModel):
    """The wizard's "Your first path" step. The level is not asked here: Yuo checks it with a few questions."""

    model_config = ConfigDict(extra="ignore")
    title: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=600)
    goal_type: Literal["exam", "practical", "understanding", "curiosity"] = "understanding"
    custom_instructions: str = Field(default="", max_length=1000)


_PARTS: dict[str, type[BaseModel]] = {"profile": Profile, "first_path": FirstPath}


def parse(raw: Any) -> tuple[dict[str, Any], list[str]]:
    """The usable answers and, for everything left out, why (in English). A field that does not fit is left
    out on its own; a first path without a usable title or goal is left out whole."""
    if not isinstance(raw, dict):
        return {}, ["the file must hold one JSON object"]
    usable: dict[str, Any] = {}
    problems: list[str] = []
    unknown = sorted(set(raw) - set(_PARTS) - {"version"})
    if unknown:
        problems.append(f"unknown parts, left out: {', '.join(unknown)}")
    for key, model in _PARTS.items():
        part = raw.get(key)
        if part is None:
            continue
        if not isinstance(part, dict):
            problems.append(f"{key}: must be an object, left out")
            continue
        fields = dict(part)
        for _ in range(2):  # once as given, once without the fields that did not fit
            try:
                usable[key] = model.model_validate(fields).model_dump(exclude_none=True)
                break
            except ValidationError as e:
                bad = {str(err["loc"][0]) for err in e.errors(include_url=False) if err["loc"]}
                for err in e.errors(include_url=False):
                    where = ".".join(str(x) for x in (key, *err["loc"]))
                    problems.append(f"{where}: {err['msg']}, left out")
                if not bad & set(fields):
                    break
                fields = {k: v for k, v in fields.items() if k not in bad}
        if key in usable and usable[key] == {}:
            del usable[key]
    return usable, problems


def read(path: Path) -> dict[str, Any]:
    """The usable answers in the file: `{}` without a file, or when nothing in it fits."""
    try:
        # utf-8-sig: Windows PowerShell writes a byte order mark
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        log.warning("setup_answers.unreadable", file=str(path), error=str(e))
        return {}
    usable, problems = parse(raw)
    if problems:
        log.warning("setup_answers.left_out", problems=problems)
    return usable


def check(text: str) -> tuple[dict[str, Any], list[str]]:
    """For `yuo setup-answers`: what the wizard would use, and what it would leave out."""
    try:
        raw = json.loads(text.removeprefix("\ufeff"))
    except json.JSONDecodeError as e:
        return {}, [f"not valid JSON: {e}"]
    return parse(raw)


def discard(path: Path) -> None:
    path.unlink(missing_ok=True)
