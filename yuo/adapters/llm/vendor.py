"""Direct vendor keys: the port for a vendor in `yuo/setup/providers.py`, and the free key check.

The check lists the vendor's models with the key (no model call, nothing billed) and returns their ids, which
the learner picks from.
"""

from collections.abc import Callable
from typing import Any

import httpx

from yuo.adapters.llm.anthropic_api import AnthropicAdapter
from yuo.adapters.llm.openai_compat import OpenAICompatAdapter
from yuo.core.llm import LLMError, LLMPort
from yuo.setup.providers import Provider

type Price = Callable[[str], tuple[float, float] | None]

ANTHROPIC_VERSION = "2023-06-01"


def vendor_port(provider: Provider, key: str, price: Price | None = None) -> LLMPort:
    if provider.kind == "anthropic":
        return AnthropicAdapter(key, name=provider.adapter, price=price)
    return OpenAICompatAdapter(provider.adapter, provider.base_url, key, price=price)


def vendor_models(provider: Provider, key: str, *, client: Any = None) -> list[str]:
    """The model ids this key may use; LLMError(kind="auth") when the vendor refuses the key."""
    http = client or httpx.Client(timeout=15)
    if provider.kind == "anthropic":
        url = provider.base_url + "/v1/models?limit=1000"
        headers = {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}
    else:
        url = provider.base_url + "/models"
        headers = {"Authorization": f"Bearer {key}"}
    try:
        r = http.get(url, headers=headers)
    except httpx.HTTPError as e:
        raise LLMError(
            f"{provider.id}: cannot reach {provider.label} ({type(e).__name__})", kind="transport"
        ) from e
    if r.status_code in (400, 401, 403):  # Google answers 400 for an invalid key
        raise LLMError(f"{provider.id}: the key was refused", kind="auth")
    if r.status_code >= 400:
        raise LLMError(f"{provider.id}: listing models answered {r.status_code}", kind="error")
    ids = {str(m.get("id", "")).removeprefix("models/") for m in r.json().get("data", [])}
    return sorted(i for i in ids if i)
