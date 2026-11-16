"""The LLM port: what every model adapter offers, independent of vendor SDKs.

Adapters live in `yuo/adapters/llm`. Structured generation (validate + one repair round) is built
on top of `generate` in `yuo/generation/structured.py`, so every adapter gets the same policy.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

from yuo.core.errors import YuoError

Role = Literal["generator", "reviewer", "tutor", "grader", "utility"]
Effort = Literal["none", "low", "medium", "high"]


class StructuredMode(StrEnum):
    NATIVE = "native"  # provider-side constrained decoding (json_schema strict, --json-schema)
    PROMPT = "prompt"  # schema in the prompt, validated by us


@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str
    images: tuple[str, ...] = ()  # JPEG/PNG file paths shown with this message (multimodal critics)


@dataclass(frozen=True, slots=True)
class Request:
    messages: tuple[Message, ...]
    model: str
    max_tokens: int = 8000
    temperature: float | None = 0.7
    effort: Effort | None = None
    json_schema: dict[str, Any] | None = None  # set only in native structured mode
    schema_name: str = "output"
    providers: tuple[str, ...] = ()  # allowlist (OpenRouter `provider.order`, no fallbacks)
    avoid: tuple[str, ...] = ()  # providers measured bad for this model (OpenRouter `provider.ignore`)
    timeout_s: float = 600


@dataclass(frozen=True, slots=True)
class Usage:
    in_tokens: int = 0
    out_tokens: int = 0
    reasoning_tokens: int = 0
    cost_micros: int = 0  # billed cost reported by the provider, USD micro-units
    notional: bool = False  # subscription CLI: the cost is what the API would charge, not billed


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    raw: dict[str, Any]  # the full provider response, stored as stage_output.raw
    usage: Usage
    model_resolved: str | None = None
    provider: str | None = None
    finish: str | None = None
    parsed: Any = None  # native structured output when the transport returns it separately
    latency_s: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


class LLMError(YuoError):
    """A call failed. `retryable` errors may be retried by the stage runner later, never in a tight loop."""

    def __init__(self, message: str, *, retryable: bool = False, kind: str = "error") -> None:
        super().__init__(message)
        self.retryable = retryable
        self.kind = kind  # error, quota, auth, timeout, transport


class LLMPort(Protocol):
    """Implemented by every model adapter."""

    name: str  # adapter id, e.g. "openrouter", "claude-cli"
    version: str  # adapter code version, part of the stage manifest
    remote: bool  # data leaves the machine (egress_record)

    def generate(self, request: Request) -> Completion: ...


@runtime_checkable
class StreamingPort(LLMPort, Protocol):
    """An adapter that can stream text as it is written. Adapters without it are called
    with `generate` and the UI shows staged progress instead: streaming is never faked."""

    def stream(self, request: Request, on_text: Callable[[str], None]) -> Completion: ...


@dataclass(frozen=True, slots=True)
class Binding:
    """A resolved model binding for one role (adapter_binding row + capability file)."""

    adapter: str
    model: str
    mode: StructuredMode = StructuredMode.PROMPT
    providers: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    effort: Effort | None = None
    max_tokens: int = 8000
    temperature: float | None = 0.7
    role: Role = "generator"
