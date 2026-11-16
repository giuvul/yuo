"""The path package's records and manifest (docs/spec/path-package.md, format 1.0).

These models are the normative shape: `scripts/gen_package_schemas.py` writes their JSON Schemas to
`docs/spec/schemas/`. Records refer to each other by code, never by local id. Every record keeps fields it does
not know (`extra="allow"`), so a package made by a newer minor version round-trips without losing them.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FORMAT = "yuo.package"
FORMAT_VERSION = "1.0.0"
CODE = r"^[a-z0-9]+([._-][a-z0-9]+)*$"
SHA256 = r"^[0-9a-f]{64}$"

Profile = Literal["structure", "full", "custom"]
DataClassTag = Literal["C", "F"]


class _Record(BaseModel):
    model_config = ConfigDict(extra="allow")
    extensions: dict[str, Any] = Field(default_factory=dict)


class Provenance(BaseModel):
    """Who made a version; never part of its hash (spec §5)."""

    model_config = ConfigDict(extra="allow")
    authorship: Literal["generated", "human", "human_edited", "translated"]
    author_kind: Literal["system", "learner"] = "system"
    licence: str | None = None
    upstream: dict[str, Any] | None = None  # package_uid, code, version_hash, authorship, generated_by


class PathRecord(_Record):
    code: str = Field(pattern=CODE, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    subject: str = Field(max_length=2000)
    goal: str = Field(max_length=4000)
    goal_type: Literal["exam", "practical", "understanding", "curiosity"]
    difficulty: Literal["introductory", "foundational", "intermediate", "advanced", "expert"]
    content_lang: str = Field(min_length=2, max_length=35)
    licence: str = Field(min_length=1, max_length=200)
    authors: list[dict[str, Any]] = Field(default_factory=list)


class BranchRecord(_Record):
    code: str = Field(pattern=CODE, max_length=128)
    title: str = Field(max_length=200)
    position: int = Field(ge=0)


class SkillRecord(_Record):
    code: str = Field(pattern=CODE, max_length=128)
    branch: str = Field(pattern=CODE, json_schema_extra={"x-ref": "branch"})
    title: str = Field(max_length=200)
    summary: str = Field(default="", max_length=4000)
    position: int = Field(ge=0)
    prerequisites: list[str] = Field(default_factory=list, json_schema_extra={"x-ref": "skill"})
    mastery_threshold: float | None = Field(default=None, ge=0, le=1)
    optional: bool = False
    merged_into: str | None = Field(default=None, json_schema_extra={"x-ref": "skill"})


class ObjectiveRecord(_Record):
    code: str = Field(pattern=CODE, max_length=128)
    skill: str = Field(pattern=CODE, json_schema_extra={"x-ref": "skill"})
    statement: str = Field(max_length=2000)
    bloom_level: str | None = Field(default=None, max_length=40)
    position: int = Field(ge=0)


class ObjectiveRole(BaseModel):
    code: str = Field(pattern=CODE, json_schema_extra={"x-ref": "objective"})
    role: Literal["primary", "secondary"]


class SourceUse(BaseModel):
    key: str = Field(max_length=200, json_schema_extra={"x-ref": "source"})
    locator: str | None = Field(default=None, max_length=200)
    block_ids: list[str] | None = None


class LessonVersionRecord(_Record):
    version_hash: str = Field(pattern=SHA256)
    version_no: int = Field(ge=1)
    lang: str = Field(min_length=2, max_length=35)
    title: str = Field(max_length=300)
    body: list[dict[str, Any]]  # lesson_body blocks
    est_minutes: int = Field(ge=0)
    objectives: list[ObjectiveRole] = Field(default_factory=list)
    sources: list[SourceUse] = Field(default_factory=list)
    translation_of_version_hash: str | None = Field(default=None, pattern=SHA256)
    provenance: Provenance
    data_class: DataClassTag = "C"


class LessonRecord(_Record):
    code: str = Field(pattern=CODE, max_length=128)
    skill: str = Field(pattern=CODE, json_schema_extra={"x-ref": "skill"})
    kind: Literal["core", "remedial", "requested"]
    position: int = Field(ge=0)
    current: str | None = Field(default=None, pattern=SHA256)
    versions: list[LessonVersionRecord] = Field(default_factory=list)


class RenditionAssetUse(BaseModel):
    role: Literal["video", "subtitles", "poster", "audio", "image"]
    lang: str
    recipe_hash: str = Field(pattern=SHA256)
    sha256: str = Field(pattern=SHA256, json_schema_extra={"x-ref": "asset"})


class RenditionVersionRecord(_Record):
    version_hash: str = Field(pattern=SHA256)
    version_no: int = Field(ge=1)
    lang: str
    lesson_version_hash: str = Field(pattern=SHA256)
    renderer: str = Field(max_length=80)
    spec_kind: Literal["rendered"]  # model-written scene code never travels (spec §5)
    narration: dict[str, Any] | None = None  # timeline and segments: captions, the tutor's video context
    theme: str | None = None
    voice: str | None = None
    duration_s: float | None = Field(default=None, ge=0)
    assets: list[RenditionAssetUse]
    provenance: Provenance
    data_class: DataClassTag = "C"


class RenditionRecord(_Record):
    code: str = Field(pattern=CODE, max_length=160)  # `<lesson code>.<kind>`: one rendition per kind
    lesson: str = Field(pattern=CODE, json_schema_extra={"x-ref": "lesson"})
    kind: Literal["reading", "video", "slides", "audio"]
    current: str | None = Field(default=None, pattern=SHA256)
    versions: list[RenditionVersionRecord] = Field(default_factory=list)


class ItemVersionRecord(_Record):
    version_hash: str = Field(pattern=SHA256)
    version_no: int = Field(ge=1)
    type_version: int = Field(ge=1)
    lang: str
    difficulty: Literal["introductory", "foundational", "intermediate", "advanced", "expert"]
    payload: dict[str, Any]
    support: dict[str, Any]
    objectives: list[str] = Field(default_factory=list, json_schema_extra={"x-ref": "objective"})
    resets_review: bool = False
    origin_lesson: str | None = Field(default=None, json_schema_extra={"x-ref": "lesson"})
    provenance: Provenance
    data_class: DataClassTag = "C"


class ItemRecord(_Record):
    code: str = Field(pattern=CODE, max_length=128)
    skill: str = Field(pattern=CODE, json_schema_extra={"x-ref": "skill"})
    type_key: str = Field(max_length=60)
    current: str | None = Field(default=None, pattern=SHA256)
    versions: list[ItemVersionRecord] = Field(default_factory=list)


class SourceRecord(_Record):
    key: str = Field(max_length=200)
    kind: str = Field(max_length=40)
    title: str = Field(max_length=500)
    url: str | None = Field(default=None, max_length=2000)
    accessed_at: str | None = None
    published_at: str | None = None
    citation: dict[str, Any] = Field(default_factory=dict)  # CSL-JSON


class AssetRecord(_Record):
    sha256: str = Field(pattern=SHA256)
    media_type: str = Field(max_length=100)
    kind: str = Field(max_length=40)
    bytes: int = Field(ge=0)
    present: bool


KINDS: dict[str, type[_Record]] = {
    "path": PathRecord,
    "branch": BranchRecord,
    "skill": SkillRecord,
    "objective": ObjectiveRecord,
    "lesson": LessonRecord,
    "rendition": RenditionRecord,
    "item": ItemRecord,
    "source": SourceRecord,
    "asset": AssetRecord,
}


def sort_key(kind: str, record: dict[str, Any]) -> str:
    return str(
        record.get("key") if kind == "source" else record.get("sha256") if kind == "asset" else record["code"]
    )


class InventoryFile(BaseModel):
    path: str
    sha256: str = Field(pattern=SHA256)
    bytes: int = Field(ge=0)


class Inventory(BaseModel):
    files: list[InventoryFile]
    counts: dict[str, dict[str, int]]
    total_bytes: int = Field(ge=0)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    format: Literal["yuo.package"]
    format_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    package_uid: str = Field(pattern=r"^pkg_[0-9a-z]{26}$")
    content_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    profile: Profile
    contents: list[str]
    title: str = Field(max_length=200)
    content_lang: str
    licence: str
    licences_used: list[str]
    authors: list[dict[str, Any]] = Field(default_factory=list)
    parent_package_digest: str | None = Field(default=None, pattern=SHA256)
    translation_of_package_uid: str | None = None
    created_with: dict[str, str]
    created_at: str
    required_exercise_types: list[dict[str, Any]] = Field(default_factory=list)
    inventory: Inventory
    extensions: dict[str, Any] = Field(default_factory=dict)
