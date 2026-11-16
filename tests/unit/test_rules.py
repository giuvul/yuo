"""Deterministic gate rules, structured generation and settings (no model calls)."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from tests import fakes
from yuo.adapters.secrets import ChainStore, EncryptedFileStore, EnvFileStore
from yuo.content.lesson_body import LessonDraft, inlines, lesson_rules, plain_text, to_body
from yuo.core.llm import Binding, StructuredMode
from yuo.curriculum.tree import TreeDraft, tree_rules
from yuo.generation.structured import StructuredFailure, generate_structured, strict_schema
from yuo.learning.events import learning_day
from yuo.setup import settings


def test_tree_rules_catch_cycles_unknown_refs_and_duplicates() -> None:
    t = fakes.tree()
    assert tree_rules(TreeDraft.model_validate(t)) == []
    skills = t["branches"][0]["skills"]
    skills[0]["requires"] = ["sql.b1.s1", "sql.nope"]
    skills[1]["code"] = "sql.b0.s0"
    problems = " | ".join(tree_rules(TreeDraft.model_validate(t)))
    assert "cycle" in problems and "unknown skill 'sql.nope'" in problems and "used twice" in problems


def test_lesson_rules() -> None:
    assert lesson_rules(LessonDraft.model_validate(fakes.lesson(1000))) == []
    bad = fakes.lesson(1000)
    bad["blocks"][1]["text"] += " <script>x</script> see https://example.com"
    bad["blocks"] = bad["blocks"][1:]
    problems = " | ".join(lesson_rules(LessonDraft.model_validate(bad)))
    assert "first block must be a heading" in problems and "HTML" in problems and "URL" in problems
    assert "words" in " ".join(lesson_rules(LessonDraft.model_validate(fakes.lesson(200))))


def test_stored_body_has_block_ids_and_marks() -> None:
    body = to_body(LessonDraft.model_validate(fakes.lesson(1000)))
    assert [b["bid"] for b in body] == [f"b{i}" for i in range(1, len(body) + 1)]
    assert inlines("use **bold** and `code`") == [
        {"text": "use "},
        {"text": "bold", "marks": ["bold"]},
        {"text": " and "},
        {"text": "code", "marks": ["code"]},
    ]
    assert "SELECT" in plain_text(body)


class Out(BaseModel):
    title: str
    n: int
    tags: list[str] | None = None


def test_strict_schema_closes_objects_and_keeps_a_title_property() -> None:
    s = strict_schema(Out)
    assert s["additionalProperties"] is False and s["required"] == ["title", "n", "tags"]
    assert "title" in s["properties"] and "title" not in s


class Scripted:
    name, version, remote = "openrouter", "t", True

    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.requests: list[Any] = []

    def generate(self, request: Any) -> Any:
        self.requests.append(request)
        return _completion(self.texts.pop(0))


def _completion(text: str) -> Any:
    from yuo.core.llm import Completion, Usage

    return Completion(text=text, raw={}, usage=Usage())


def test_prompt_mode_validates_and_repairs_once() -> None:
    port = Scripted('```json\n{"title": "x"}\n```', '{"title": "x", "n": 2, "tags": null}')
    out = generate_structured(port, Binding("openrouter", "m"), Out, [fakes_msg()])
    assert out.value.n == 2 and out.repaired and len(port.requests) == 2
    assert "JSON Schema" in port.requests[0].messages[0].content and port.requests[0].json_schema is None
    assert "n: Field required" in port.requests[1].messages[-1].content


def test_native_mode_sends_the_schema_and_fails_after_one_repair() -> None:
    port = Scripted("nope", "still nope")
    with pytest.raises(StructuredFailure) as e:
        generate_structured(port, Binding("openrouter", "m", mode=StructuredMode.NATIVE), Out, [fakes_msg()])
    assert port.requests[0].json_schema["required"] == ["title", "n", "tags"]
    assert len(e.value.completions) == 2


def fakes_msg() -> Any:
    from yuo.core.llm import Message

    return Message("user", "go")


def test_every_setting_explains_itself() -> None:
    """Suggestion, explanation, example and impact tags on every setting."""
    for key, d in settings.REGISTRY.items():
        assert d.cfg.startswith("CFG-"), key
        assert d.explanation and d.example and d.suggestion and d.impact, key
        settings.validate(key, d.default)


def test_learning_day_respects_the_boundary() -> None:
    late = datetime(2026, 10, 27, 1, 30, tzinfo=UTC)  # 02:30 in Rome, before the 04:00 boundary
    assert learning_day(late, "Europe/Rome", "04:00") == "2026-10-26"
    assert learning_day(late, "Europe/Rome", "00:00") == "2026-10-27"


def test_encrypted_secret_store_round_trip(tmp_path: Path) -> None:
    store = EncryptedFileStore(tmp_path / "s.bin", b"k" * 32)
    store.set("openrouter", "sk-or-secret")
    assert store.get("openrouter") == "sk-or-secret"
    assert b"sk-or-secret" not in (tmp_path / "s.bin").read_bytes()
    store.delete("openrouter")
    assert store.get("openrouter") is None


def test_env_file_secrets_are_read_on_demand(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "key").write_text("sk-file\n")
    monkeypatch.setenv("YUO_SECRET_OPENROUTER_FILE", str(tmp_path / "key"))
    chain = ChainStore(EnvFileStore(), EncryptedFileStore(tmp_path / "s.bin", b"k" * 32))
    assert chain.get("openrouter") == "sk-file"
    chain.set("other", "v")
    assert chain.get("other") == "v"
