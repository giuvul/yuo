"""OpenAI-compatible chat adapter: OpenRouter, Ollama, llama.cpp server, vLLM.

OpenRouter specifics: a provider allowlist with fallbacks off when the capability file names
providers; Darkbloom always ignored; `usage.include` for the billed cost; reasoning effort passed through.
"""

import base64
import dataclasses
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import openai

from yuo.core.llm import Completion, LLMError, Message, Request, Usage

OPENROUTER = "https://openrouter.ai/api/v1"
IGNORED_PROVIDERS = ("Darkbloom",)  # empty or endless output on most calls in testing


class OpenAICompatAdapter:
    version = "1"

    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str | None,
        *,
        client: Any = None,
        app_title: str = "Yuo",
        price: Callable[[str], tuple[float, float] | None] | None = None,
    ) -> None:
        self.name = name
        self._price = price  # USD per token (in, out) for vendors that do not report a cost (direct keys)
        self.base_url = base_url.rstrip("/")
        self.is_openrouter = self.base_url.startswith(OPENROUTER)
        host = urlparse(self.base_url).hostname or ""
        self.remote = host not in ("localhost", "127.0.0.1", "::1")  # local runtimes send nothing out
        self._client = client or openai.OpenAI(
            base_url=self.base_url,
            api_key=api_key or "not-needed",
            max_retries=0,
            default_headers={"X-Title": app_title} if self.is_openrouter else None,
        )

    def _body(self, req: Request) -> tuple[dict[str, Any], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "model": req.model,
            "messages": [_message(m) for m in req.messages],
            "max_tokens": req.max_tokens,
        }
        if req.temperature is not None:
            kwargs["temperature"] = req.temperature
        extra: dict[str, Any] = {}
        if req.json_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": req.schema_name, "strict": True, "schema": req.json_schema},
            }
        if self.is_openrouter:
            provider: dict[str, Any] = {"ignore": [*IGNORED_PROVIDERS, *req.avoid]}
            if req.providers:
                provider |= {"order": list(req.providers), "allow_fallbacks": False}
            if req.json_schema is not None:
                provider["require_parameters"] = True
            extra["provider"] = provider
            extra["usage"] = {"include": True}
            if req.effort and req.effort != "none":
                extra["reasoning"] = {"effort": req.effort}
        elif req.effort:
            kwargs["reasoning_effort"] = req.effort
        return kwargs, extra

    @contextmanager
    def _errors(self) -> Iterator[None]:
        try:
            yield
        except openai.RateLimitError as e:
            raise LLMError(f"{self.name}: rate limited", retryable=True, kind="quota") from e
        except openai.AuthenticationError as e:
            raise LLMError(f"{self.name}: authentication failed", kind="auth") from e
        except openai.APIStatusError as e:
            kind = "quota" if e.status_code == 402 else "transport"
            raise LLMError(
                f"{self.name}: HTTP {e.status_code}", retryable=e.status_code >= 500, kind=kind
            ) from e
        except (openai.APITimeoutError, openai.APIConnectionError) as e:
            raise LLMError(f"{self.name}: {type(e).__name__}", retryable=True, kind="timeout") from e

    def generate(self, request: Request) -> Completion:
        kwargs, extra = self._body(request)
        start = time.monotonic()
        with self._errors():
            resp = self._client.chat.completions.create(
                **kwargs, extra_body=extra or None, timeout=request.timeout_s
            )
        raw = resp.model_dump()
        return self._priced(parse_response(raw, latency_s=time.monotonic() - start), request.model)

    def _priced(self, done: Completion, model: str) -> Completion:
        """A direct vendor key reports tokens but no cost: price them for the budget ledger."""
        if done.usage.cost_micros or self._price is None or (price := self._price(model)) is None:
            return done
        cost = round((done.usage.in_tokens * price[0] + done.usage.out_tokens * price[1]) * 1_000_000)
        return dataclasses.replace(done, usage=dataclasses.replace(done.usage, cost_micros=cost))

    def stream(self, request: Request, on_text: Callable[[str], None]) -> Completion:
        """Stream the reply; the last chunk carries the usage (and on OpenRouter the billed cost)."""
        kwargs, extra = self._body(request)
        start = time.monotonic()
        parts: list[str] = []
        last: dict[str, Any] = {}
        usage: dict[str, Any] | None = None
        finish = None
        with self._errors():
            chunks = self._client.chat.completions.create(
                **kwargs,
                stream=True,
                stream_options={"include_usage": True},
                extra_body=extra or None,
                timeout=request.timeout_s,
            )
            for chunk in chunks:
                raw = chunk.model_dump()
                if raw.get("error"):
                    raise LLMError(
                        f"provider error: {str(raw['error'])[:200]}", retryable=True, kind="transport"
                    )
                last = raw
                usage = raw.get("usage") or usage
                for choice in raw.get("choices") or []:
                    text = (choice.get("delta") or {}).get("content")
                    if text:
                        parts.append(text)
                        on_text(text)
                    finish = choice.get("finish_reason") or finish
        text = "".join(parts)
        merged = {
            "model": last.get("model"),
            "provider": last.get("provider"),
            "streamed": True,
            "choices": [{"message": {"content": text}, "finish_reason": finish}],
            "usage": usage or {},
        }
        return self._priced(parse_response(merged, latency_s=time.monotonic() - start), request.model)


def _message(m: Message) -> dict[str, Any]:
    if not m.images:
        return {"role": m.role, "content": m.content}
    parts: list[dict[str, Any]] = [{"type": "text", "text": m.content}]
    for path in m.images:
        kind = "png" if path.lower().endswith(".png") else "jpeg"
        data = base64.b64encode(Path(path).read_bytes()).decode()
        parts.append({"type": "image_url", "image_url": {"url": f"data:image/{kind};base64,{data}"}})
    return {"role": m.role, "content": parts}


def parse_response(raw: dict[str, Any], *, latency_s: float = 0.0) -> Completion:
    if raw.get("error"):
        raise LLMError(f"provider error: {str(raw['error'])[:200]}", retryable=True, kind="transport")
    choice = (raw.get("choices") or [{}])[0]
    text = ((choice.get("message") or {}).get("content")) or ""
    u = raw.get("usage") or {}
    details = u.get("completion_tokens_details") or {}
    cost = u.get("cost") or 0.0
    usage = Usage(
        in_tokens=int(u.get("prompt_tokens") or 0),
        out_tokens=int(u.get("completion_tokens") or 0),
        reasoning_tokens=int(details.get("reasoning_tokens") or 0),
        cost_micros=round(float(cost) * 1_000_000),
    )
    return Completion(
        text=text,
        raw=raw,
        usage=usage,
        model_resolved=raw.get("model"),
        provider=raw.get("provider"),
        finish=choice.get("finish_reason"),
        latency_s=latency_s,
    )


def check_openrouter_key(key: str, *, client: Any = None) -> dict[str, Any]:
    """OpenRouter's key endpoint (free, no model call): raises LLMError(kind="auth") for a bad key.
    Returns the credit left (`None` when the key has no limit) and whether it is a free-tier key."""
    import httpx

    http = client or httpx.Client(timeout=15)
    try:
        r = http.get(f"{OPENROUTER}/key", headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError as e:
        raise LLMError(f"openrouter: cannot reach OpenRouter ({type(e).__name__})", kind="transport") from e
    if r.status_code in (401, 403):
        raise LLMError("openrouter: the key was refused", kind="auth")
    if r.status_code >= 400:
        raise LLMError(f"openrouter: key check answered {r.status_code}", kind="error")
    data = r.json().get("data", {})
    return {"limit_remaining": data.get("limit_remaining"), "free_tier": bool(data.get("is_free_tier"))}


def list_models(base_url: str, *, client: Any = None) -> list[str]:
    """The models a local OpenAI-compatible server offers (Ollama, LM Studio, llama.cpp); raises LLMError."""
    import httpx

    http = client or httpx.Client(timeout=3)
    try:
        r = http.get(base_url.rstrip("/") + "/models")
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise LLMError(f"local: nothing answers at {base_url}", kind="transport") from e
    return sorted(m["id"] for m in r.json().get("data", []))
