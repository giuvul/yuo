"""Current prices for the estimator: OpenRouter's public models list, cached for a day.

Fetching the list costs nothing. Subscription CLIs and local runtimes have no per-token price (None). A direct
vendor key (`api:<vendor>`) is priced at that vendor's model in the list, matched by its spelling-free id
(`claude-sonnet-5-5` is `anthropic/claude-sonnet-5.5` there).
"""

import json
import time
from pathlib import Path
from typing import Any

import httpx

from yuo.core.llm import LLMError
from yuo.setup.providers import model_key, provider_of

MODELS_URL = "https://openrouter.ai/api/v1/models"
TTL_S = 24 * 3600


class OpenRouterPrices:
    def __init__(self, cache_file: Path, *, client: httpx.Client | None = None) -> None:
        self.cache_file = cache_file
        self._client = client
        self._prices: dict[str, tuple[float, float]] | None = None
        self._catalog: list[dict[str, Any]] = []
        self.fetched_at: float | None = None

    def _load(self) -> dict[str, tuple[float, float]]:
        if self._prices is not None:
            return self._prices
        data: dict[str, Any] | None = None
        if self.cache_file.exists():
            cached = json.loads(self.cache_file.read_text(encoding="utf-8"))
            # a cache from before 0.8.1 has no catalog: fetched again
            if time.time() - cached["fetched_at"] < TTL_S and "catalog" in cached:
                data = cached
        if data is None:
            client = self._client or httpx.Client(timeout=30)
            resp = client.get(MODELS_URL)
            resp.raise_for_status()
            listed = resp.json()["data"]
            data = {
                "fetched_at": time.time(),
                "models": {
                    m["id"]: [float(m["pricing"]["prompt"]), float(m["pricing"]["completion"])]
                    for m in listed
                    if m.get("pricing")
                },
                "catalog": [_entry(m) for m in listed if _writes_text(m)],
            }
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(data), encoding="utf-8")
        self.fetched_at = data["fetched_at"]
        self._prices = {k: (v[0], v[1]) for k, v in data["models"].items()}
        self._catalog = data["catalog"]
        return self._prices

    def catalog(self) -> list[dict[str, Any]]:
        """Every text model on OpenRouter with its name, prices per million tokens and context length, for the
        model picker in Settings. The list endpoint has no search: the page filters it.
        LLMError when OpenRouter cannot be reached and no fresh copy is cached."""
        try:
            self._load()
        except httpx.HTTPError as e:
            raise LLMError(f"openrouter models list: {e}", retryable=True, kind="transport") from e
        return list(self._catalog)

    def per_token(self, adapter: str, model: str) -> tuple[float, float] | None:
        if adapter == "openrouter":
            return self._load().get(model)
        if (vendor := provider_of(adapter)) is None:
            return None
        want = model_key(model)
        for listed, price in self._load().items():
            if listed.startswith(vendor.price_prefix) and model_key(listed) == want:
                return price
        return None


def _writes_text(m: dict[str, Any]) -> bool:
    arch = m.get("architecture") or {}
    return "text" in (arch.get("output_modalities") or ["text"]) and "text" in (
        arch.get("input_modalities") or ["text"]
    )


def _entry(m: dict[str, Any]) -> dict[str, Any]:
    price = m.get("pricing") or {}

    def per_m(v: Any) -> float | None:
        try:
            return round(float(v) * 1_000_000, 4)
        except TypeError, ValueError:
            return None

    return {
        "id": m["id"],
        "name": str(m.get("name") or m["id"]),
        "in_usd_per_m": per_m(price.get("prompt")),
        "out_usd_per_m": per_m(price.get("completion")),
        "context": int(m.get("context_length") or 0) or None,
    }
