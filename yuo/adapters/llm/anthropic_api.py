"""Anthropic Messages API adapter. Structured stages use prompt mode plus validation.

No sampling parameters: current Claude models reject `temperature` (400), so the request leaves it out.
"""

import base64
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anthropic

from yuo.core.llm import Completion, LLMError, Message, Request, Usage


class AnthropicAdapter:
    remote = True
    version = "1"

    def __init__(
        self,
        api_key: str | None,
        *,
        client: Any = None,
        name: str = "anthropic",
        price: Callable[[str], tuple[float, float] | None] | None = None,
    ) -> None:
        self.name = name
        self._client = client or anthropic.Anthropic(api_key=api_key, max_retries=0)
        self._price = price  # USD per token (in, out), from the price list; None: not priced

    def generate(self, request: Request) -> Completion:
        system = "\n\n".join(m.content for m in request.messages if m.role == "system")
        messages = [_message(m) for m in request.messages if m.role != "system"]
        kwargs: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        start = time.monotonic()
        try:
            resp = self._client.messages.create(**kwargs, timeout=request.timeout_s)
        except anthropic.RateLimitError as e:
            raise LLMError("anthropic: rate limited", retryable=True, kind="quota") from e
        except anthropic.AuthenticationError as e:
            raise LLMError("anthropic: authentication failed", kind="auth") from e
        except anthropic.APIStatusError as e:
            raise LLMError(
                f"anthropic: HTTP {e.status_code}", retryable=e.status_code >= 500, kind="transport"
            ) from e
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as e:
            raise LLMError(f"anthropic: {type(e).__name__}", retryable=True, kind="timeout") from e
        price = self._price(request.model) if self._price else None
        return parse_response(resp.model_dump(), latency_s=time.monotonic() - start, price=price)


def parse_response(
    raw: dict[str, Any], *, latency_s: float = 0.0, price: tuple[float, float] | None = None
) -> Completion:
    text = "".join(b.get("text", "") for b in raw.get("content") or [] if b.get("type") == "text")
    u = raw.get("usage") or {}
    tokens_in = (
        int(u.get("input_tokens") or 0)
        + int(u.get("cache_read_input_tokens") or 0)
        + int(u.get("cache_creation_input_tokens") or 0)
    )
    tokens_out = int(u.get("output_tokens") or 0)
    price_in, price_out = price or (0.0, 0.0)  # cache reads priced as input: an upper bound
    cost = round((tokens_in * price_in + tokens_out * price_out) * 1_000_000)
    return Completion(
        text=text,
        raw=raw,
        usage=Usage(tokens_in, tokens_out, 0, cost),
        model_resolved=raw.get("model"),
        provider="anthropic",
        finish=raw.get("stop_reason"),
        latency_s=latency_s,
    )


def _message(m: Message) -> dict[str, Any]:
    if not m.images:
        return {"role": m.role, "content": m.content}
    blocks: list[dict[str, Any]] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png" if p.lower().endswith(".png") else "image/jpeg",
                "data": base64.b64encode(Path(p).read_bytes()).decode(),
            },
        }
        for p in m.images
    ]
    return {"role": m.role, "content": [*blocks, {"type": "text", "text": m.content}]}
