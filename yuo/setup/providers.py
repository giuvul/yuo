"""Model vendors reachable with the learner's own API key: one table, two kinds of adapter.

Most vendors offer an OpenAI-compatible chat endpoint, so one adapter configured with a base URL and a key
covers them. Anthropic gets its native Messages API (its OpenAI-compatible layer is meant for testing). A key is
checked by listing the vendor's models, which costs nothing. Prices for the estimate come from OpenRouter's public
models list, under the vendor's prefix there (`price_prefix`).

Models are chosen from what the vendor lists for the key. Suggestions exist only where the model ids are known;
none of these models are measured with Yuo yet, so a binding to one carries the untested warning.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from yuo.core.errors import InvalidInput

Kind = Literal["openai", "anthropic"]
ADAPTER_PREFIX = "api:"


@dataclass(frozen=True, slots=True)
class Provider:
    id: str
    label: str
    kind: Kind
    base_url: str
    keys_url: str  # where the learner creates a key
    price_prefix: str  # the vendor's prefix in OpenRouter's models list
    key_prefix: str = ""  # a format hint, checked before the vendor is asked
    suggested: dict[str, str] = field(default_factory=dict)  # "main" / "reviewer" -> model id

    @property
    def adapter(self) -> str:
        return ADAPTER_PREFIX + self.id


PROVIDERS: dict[str, Provider] = {
    p.id: p
    for p in (
        Provider(
            "anthropic", "Anthropic (Claude)", "anthropic", "https://api.anthropic.com",
            "https://console.anthropic.com/settings/keys", "anthropic/", "sk-ant-",
            {"main": "claude-sonnet-5-5", "reviewer": "claude-opus-5-5"},
        ),
        Provider(
            "openai", "OpenAI", "openai", "https://api.openai.com/v1",
            "https://platform.openai.com/api-keys", "openai/", "sk-",
        ),
        Provider(
            "gemini", "Google Gemini", "openai", "https://generativelanguage.googleapis.com/v1beta/openai",
            "https://aistudio.google.com/apikey", "google/",
        ),
        Provider(
            "mistral", "Mistral", "openai", "https://api.mistral.ai/v1",
            "https://console.mistral.ai/api-keys", "mistralai/",
        ),
        Provider(
            "deepseek", "DeepSeek", "openai", "https://api.deepseek.com/v1",
            "https://platform.deepseek.com/api_keys", "deepseek/", "sk-",
        ),
        Provider(
            "xai", "xAI (Grok)", "openai", "https://api.x.ai/v1",
            "https://console.x.ai", "x-ai/", "xai-",
        ),
        Provider(
            "qwen", "Qwen (Alibaba Cloud Model Studio)", "openai",
            "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            "https://modelstudio.console.alibabacloud.com/", "qwen/", "sk-",
        ),
    )
}  # fmt: skip


def provider_of(adapter: str) -> Provider | None:
    """The vendor behind an `api:<id>` adapter name, or None for any other adapter."""
    if not adapter.startswith(ADAPTER_PREFIX):
        return None
    return PROVIDERS.get(adapter.removeprefix(ADAPTER_PREFIX))


def check_key_format(provider: Provider, key: str) -> str:
    """The trimmed key; ValueError when it cannot be one (blank, spaces, too long, wrong prefix)."""
    key = key.strip()
    if not key or len(key) > 400 or any(ch.isspace() for ch in key):
        raise InvalidInput(f"that does not look like a {provider.label} key")
    if provider.key_prefix and not key.startswith(provider.key_prefix):
        raise InvalidInput(
            f"that does not look like a {provider.label} key (it starts with {provider.key_prefix})"
        )
    return key


def model_key(model: str) -> str:
    """A model id reduced for matching across vendors' spellings: `models/gemini-x`, `claude-sonnet-5-5` and
    `anthropic/claude-sonnet-5.5` meet as `geminix`, `claudesonnet55`."""
    return re.sub(r"[^a-z0-9]", "", model.lower().rsplit("/", 1)[-1])
