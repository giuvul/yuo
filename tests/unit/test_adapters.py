"""Contract tests for the LLM port adapters, on recorded or fake transports (no network)."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from yuo.adapters.llm import anthropic_api, openai_compat
from yuo.adapters.llm.cli import ClaudeCLIAdapter, CodexCLIAdapter
from yuo.core.llm import LLMError, Message, Request

REQ = Request(
    messages=(Message("system", "sys"), Message("user", "hello")), model="m", max_tokens=100, effort="low"
)

OPENROUTER_RAW = {
    "id": "gen-1",
    "model": "deepseek/deepseek-v4-pro",
    "provider": "AtlasCloud",
    "choices": [{"message": {"role": "assistant", "content": '{"a": 1}'}, "finish_reason": "stop"}],
    "usage": {
        "prompt_tokens": 120,
        "completion_tokens": 300,
        "completion_tokens_details": {"reasoning_tokens": 200},
        "cost": 0.000412,
    },
}


class FakeCompletions:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return SimpleNamespace(model_dump=lambda: OPENROUTER_RAW)


def openrouter() -> tuple[openai_compat.OpenAICompatAdapter, FakeCompletions]:
    fake = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    return openai_compat.OpenAICompatAdapter("openrouter", openai_compat.OPENROUTER, "k", client=client), fake


def test_openrouter_request_pins_providers_and_reports_cost() -> None:
    adapter, fake = openrouter()
    req = Request(
        messages=REQ.messages,
        model="qwen/qwen3.8-27b",
        providers=("Alibaba",),
        effort="low",
        json_schema={"type": "object"},
    )
    out = adapter.generate(req)
    extra = fake.kwargs["extra_body"]
    assert extra["provider"]["order"] == ["Alibaba"] and extra["provider"]["allow_fallbacks"] is False
    assert "Darkbloom" in extra["provider"]["ignore"] and extra["provider"]["require_parameters"] is True
    assert extra["reasoning"] == {"effort": "low"} and extra["usage"] == {"include": True}
    assert fake.kwargs["response_format"]["json_schema"]["strict"] is True
    assert out.usage.cost_micros == 412 and out.usage.reasoning_tokens == 200 and out.provider == "AtlasCloud"
    assert out.text == '{"a": 1}' and not out.usage.notional


def test_local_runtimes_are_not_remote_and_get_no_openrouter_fields() -> None:
    fake = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    local = openai_compat.OpenAICompatAdapter("local", "http://localhost:11434/v1", None, client=client)
    local.generate(REQ)
    assert local.remote is False and fake.kwargs["extra_body"] is None
    assert fake.kwargs["reasoning_effort"] == "low"


def test_provider_errors_in_the_body_are_errors() -> None:
    with pytest.raises(LLMError):
        openai_compat.parse_response({"error": {"message": "upstream"}})


def test_anthropic_response_parsing() -> None:
    raw = {
        "model": "claude-x",
        "content": [{"type": "text", "text": "hi"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 2},
    }
    out = anthropic_api.parse_response(raw)
    assert out.text == "hi" and out.usage.in_tokens == 12 and out.provider == "anthropic"


class Recorder:
    def __init__(
        self, stdout: str, code: int = 0, stderr: str = "", files: dict[str, str] | None = None
    ) -> None:
        self.stdout, self.code, self.stderr, self.files = stdout, code, stderr, files or {}
        self.cmd: list[str] = []
        self.cwd: Path | None = None
        self.env: dict[str, str] = {}
        self.stdin = ""

    def __call__(
        self, cmd: list[str], cwd: Path, env: dict[str, str], timeout: float, stdin: str
    ) -> subprocess.CompletedProcess[str]:
        self.cmd, self.cwd, self.env, self.stdin = cmd, cwd, env, stdin
        self.cwd_listing = sorted(p.name for p in cwd.iterdir())
        for name, text in self.files.items():
            (cwd / name).write_text(text)
        return subprocess.CompletedProcess(cmd, self.code, self.stdout, self.stderr)


CLAUDE_OK = json.dumps(
    {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "",
        "total_cost_usd": 0.0123,
        "structured_output": {"a": 1},
        "usage": {"input_tokens": 50, "cache_read_input_tokens": 3000, "output_tokens": 40},
        "modelUsage": {"claude-sonnet-5-5": {}},
    }
)


def test_claude_cli_runs_isolated_and_reports_notional_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    monkeypatch.setenv("OPENROUTER_API_KEY", "nope")
    rec = Recorder(CLAUDE_OK)
    out = ClaudeCLIAdapter(runner=rec).generate(
        Request(messages=REQ.messages, model="sonnet", json_schema={"type": "object"})
    )
    for flag in ("--no-session-persistence", "--strict-mcp-config"):
        assert flag in rec.cmd
    assert (
        rec.cmd[rec.cmd.index("--setting-sources") + 1] == "" and rec.cmd[rec.cmd.index("--tools") + 1] == ""
    )
    assert "--bare" not in rec.cmd  # --bare ignores the subscription login
    assert rec.stdin.endswith(REQ.messages[-1].content) and REQ.messages[-1].content not in rec.cmd  # stdin
    assert "ANTHROPIC_API_KEY" not in rec.env and "OPENROUTER_API_KEY" not in rec.env
    assert (
        rec.cwd_listing == [] and rec.cwd is not None and not rec.cwd.exists()
    )  # empty temp dir, removed after
    assert out.parsed == {"a": 1} and out.usage.notional and out.usage.cost_micros == 12300
    assert out.usage.in_tokens == 3050 and out.model_resolved == "claude-sonnet-5-5"


def test_claude_cli_quota_answers_are_quota_errors() -> None:
    rec = Recorder(
        json.dumps({"is_error": True, "result": "Claude usage limit reached. Your limit resets at 5pm"})
    )
    with pytest.raises(LLMError) as e:
        ClaudeCLIAdapter(runner=rec).generate(REQ)
    assert e.value.kind == "quota" and not e.value.retryable


def test_codex_cli_reads_the_last_message_file() -> None:
    events = "\n".join(
        json.dumps(x)
        for x in [
            {"type": "turn.started"},
            {"type": "turn.completed", "usage": {"input_tokens": 900, "output_tokens": 50}},
        ]
    )
    rec = Recorder(events, files={"last.txt": '{"a": 2}'})
    out = CodexCLIAdapter(runner=rec).generate(
        Request(messages=REQ.messages, model="gpt-5.5", json_schema={"type": "object"})
    )
    assert rec.cmd[:2] == ["codex", "exec"] and "--output-schema" in rec.cmd and "read-only" in rec.cmd
    assert out.text == '{"a": 2}' and out.usage.in_tokens == 900 and out.usage.notional


def test_cli_missing_binary_is_reported() -> None:
    def runner(*_: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("claude")

    with pytest.raises(LLMError, match="not installed"):
        ClaudeCLIAdapter(runner=runner).generate(REQ)


CLAUDE_STREAM = "\n".join(
    json.dumps(x)
    for x in [
        {"type": "system", "subtype": "init"},
        {"type": "rate_limit_event", "rate_limit_info": {
            "status": "allowed", "unifiedWindows": {
                "five_hour": {"utilization": 0.06, "resetsAt": 1793376600, "status": "allowed"},
                "seven_day": {"utilization": 0.47, "resetsAt": 1793674800, "status": "allowed"}}}},
        json.loads(CLAUDE_OK),
    ]
)  # fmt: skip


def test_claude_cli_reports_the_plan_meter_from_its_stream() -> None:
    adapter = ClaudeCLIAdapter(runner=Recorder(CLAUDE_STREAM))
    seen: list[dict[str, Any]] = []
    adapter.on_meter = seen.append
    out = adapter.generate(REQ)
    assert out.parsed == {"a": 1}
    assert seen == [{"window_pct": 6.0, "week_pct": 47.0, "window_resets_at": "2026-10-30T16:10:00+00:00",
                     "week_resets_at": "2026-11-03T03:00:00+00:00", "limited": False}]  # fmt: skip


def test_codex_cli_reports_the_plan_meter_from_token_count_events() -> None:
    events = "\n".join(
        json.dumps(x)
        for x in [
            {"id": "1", "msg": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 9}},
             "rate_limits": {"primary": {"used_percent": 12.0, "window_minutes": 299, "resets_at": 1793376600},
                             "secondary": {"used_percent": 101.0, "window_minutes": 10079, "resets_at": 1793674800}}}},
        ]
    )  # fmt: skip
    adapter = CodexCLIAdapter(runner=Recorder(events, files={"last.txt": "ok"}))
    seen: list[dict[str, Any]] = []
    adapter.on_meter = seen.append
    adapter.generate(REQ)
    assert seen[0]["window_pct"] == 12.0 and seen[0]["week_pct"] == 101.0 and seen[0]["limited"] is True


def test_a_direct_key_reply_is_priced_for_the_ledger() -> None:
    from yuo.adapters.llm.anthropic_api import parse_response

    raw = {"content": [{"type": "text", "text": "hi"}], "model": "claude-sonnet-5-5",
           "usage": {"input_tokens": 1000, "output_tokens": 100}}  # fmt: skip
    assert parse_response(raw, price=(2e-6, 1e-5)).usage.cost_micros == 3000
    assert parse_response(raw).usage.cost_micros == 0
