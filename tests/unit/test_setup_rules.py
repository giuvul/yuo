"""The environment wizard's rules: reading the machine and the recommendation."""

from pathlib import Path
from typing import Any

import httpx
import pytest

from yuo.adapters import machine, release_feed
from yuo.app.updates import newer
from yuo.setup.probe import Bench, Gpu, LocalServer, Probe
from yuo.setup.recommend import LOCAL_MODEL, recommend


def make(**kw: Any) -> Probe:
    base: dict[str, Any] = dict(os="windows", os_version="11", arch="x64", cpu="CPU", cores=8, memory_gb=16.0,
                                gpus=[], disk_free_gb=100.0, clis={}, servers=[])  # fmt: skip
    return Probe(**(base | kw))


def test_a_subscription_cli_wins_and_needs_consent() -> None:
    r = recommend(make(clis={"claude": "2.1", "codex": None}))
    assert (r.preset, r.needs, r.alternatives) == ("claude", ["consent"], ["codex", "open"])
    r = recommend(make(clis={"codex": None}))
    assert r.preset == "codex" and [x.code for x in r.reasons] == ["cli_found"]


@pytest.mark.parametrize(
    ("kw", "local"),
    [
        ({"gpus": [Gpu("RTX 4090", 24.0, "nvidia")]}, True),
        ({"gpus": [Gpu("RTX 4070", 12.0, "nvidia")]}, False),
        (
            {
                "os": "macos",
                "arch": "arm64",
                "memory_gb": 32.0,
                "gpus": [Gpu("Apple silicon", 32.0, "apple")],
            },
            True,
        ),
        (
            {
                "os": "macos",
                "arch": "arm64",
                "memory_gb": 24.0,
                "gpus": [Gpu("Apple silicon", 24.0, "apple")],
            },
            False,
        ),
        (
            {"os": "macos", "arch": "x64", "memory_gb": 64.0},
            False,
        ),  # an Intel Mac shares no memory with a GPU
        ({"gpus": [Gpu("card0", None, "amd")]}, False),  # unknown size is not enough
    ],
)
def test_qwen_runs_locally_only_with_enough_gpu_memory(kw: dict[str, Any], local: bool) -> None:
    r = recommend(make(**kw))
    assert r.preset == ("local" if local else "open")
    assert ("open" in r.alternatives) is local  # the API route stays available as the alternative


def test_what_is_left_to_do() -> None:
    gpu = [Gpu("RTX 3090", 24.0, "nvidia")]
    assert recommend(make(gpus=gpu)).needs == ["local_server", "local_model"]
    ollama = LocalServer("ollama", "http://127.0.0.1:11434/v1", ["llama3:8b"])
    assert recommend(make(gpus=gpu, servers=[ollama])).needs == ["local_model"]
    ollama.models.append(LOCAL_MODEL)
    assert recommend(make(gpus=gpu, servers=[ollama])).needs == []
    assert recommend(make()).needs == ["openrouter_key"]
    assert recommend(make(), has_openrouter_key=True).needs == []
    assert [x.code for x in recommend(make()).reasons] == ["no_subscription", "no_gpu", "api_billed"]


def test_probe_round_trips_through_json() -> None:
    p = make(
        gpus=[Gpu("x", 8.0, "nvidia")], servers=[LocalServer("ollama", "u", ["m"])], bench=Bench(10.0, 1.0)
    )
    assert Probe.from_json(p.as_json()) == p


def test_machine_readings_from_tool_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("yuo.adapters.machine.shutil.which", lambda name: f"/usr/bin/{name}")
    outputs = {
        "nvidia-smi": "NVIDIA GeForce RTX 4090, 24564\nNVIDIA T4, 15360\n",
        "claude": "2.1.3 (Claude Code)\n",
    }

    def run(cmd: list[str]) -> str | None:
        return next((v for k, v in outputs.items() if cmd[0].endswith(k)), None)

    found = machine.gpus("windows", "x64", None, run)
    assert [(g.name, g.memory_gb) for g in found] == [("NVIDIA GeForce RTX 4090", 24.0), ("NVIDIA T4", 15.0)]
    assert machine.clis(run) == {"claude": "2.1.3 (Claude Code)", "codex": None}
    assert machine.gpus("macos", "arm64", 34359738368, lambda _: None)[-1].memory_gb == 32.0


def test_local_servers_are_found_on_loopback_only() -> None:
    seen: list[str] = []

    def get(url: str) -> Any:
        seen.append(url)
        if url.startswith("http://127.0.0.1:11434"):
            return {"models": [{"name": "qwen3.8:27b"}]}
        raise httpx.ConnectError("refused")

    found = machine.servers(get)
    assert [(s.name, s.url, s.models) for s in found] == [
        ("ollama", "http://127.0.0.1:11434/v1", ["qwen3.8:27b"])
    ]
    assert all(u.startswith("http://127.0.0.1:") for u in seen)


def test_cpu_benchmark_is_short() -> None:
    b = machine.cpu_benchmark(0.2)
    assert b.cpu_gflops and b.cpu_gflops > 0 and b.seconds < 1


def test_versions_compare_numerically() -> None:
    assert newer("1.0.10", "1.0.9") and not newer("1.0.0", "1.0.0") and not newer("1.0", "0.9.0")
    assert newer("0.1.0", "dev")  # a source checkout is older than any release


def _client(body: bytes, *, status: int = 200) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status, content=body)))


def test_downloads_are_checked_against_the_feed(tmp_path: Path) -> None:
    import hashlib

    body = b"zip bytes" * 100
    sha = hashlib.sha256(body).hexdigest()
    target = tmp_path / "yuo.zip"
    url = "https://example.org/yuo.zip"
    with pytest.raises(release_feed.FeedError, match="does not match"):
        release_feed.download(url, target, "0" * 64, len(body), client=_client(body))
    with pytest.raises(release_feed.FeedError, match="larger"):
        release_feed.download(url, target, sha, 10, client=_client(body))
    assert not target.exists() and not list(tmp_path.iterdir())  # nothing left behind
    with pytest.raises(release_feed.FeedError, match="https"):
        release_feed.download("http://example.org/yuo.zip", target, sha, len(body), client=_client(body))
    assert release_feed.download(url, target, sha, len(body), client=_client(body)).read_bytes() == body


def test_a_subscription_path_is_shown_as_a_share_of_each_plan() -> None:
    """The learner on a subscription sees the plan's limits, not an API price; a limit a plan does not have
    (ChatGPT Pro's 5-hour window) or that is not published (every Codex week) is null."""
    from yuo.generation.estimate import plan_usage

    rows = {r["plan"]: r for r in plan_usage({"claude-cli": 5.5}, 20)}
    assert set(rows) == {"pro", "max5x", "max20x"}
    assert rows["pro"]["window_pct"] == 50.0 and rows["pro"]["lessons_per_window"] == 40
    assert rows["max20x"]["week_pct"] < rows["max5x"]["week_pct"] < rows["pro"]["week_pct"]
    codex = {r["plan"]: r for r in plan_usage({"codex-cli": 5.5}, 20)}
    assert codex["plus"]["window_pct"] == 100.0 and codex["plus"]["lessons_per_window"] == 20
    assert codex["plus"]["week_pct"] is None and codex["plus"]["lessons_per_week"] is None
    assert codex["pro"]["window_pct"] is None and codex["pro"]["lessons_per_window"] is None


def test_the_api_names_every_vendor_in_the_provider_table() -> None:
    from typing import get_args

    from yuo.api.onboarding import ProviderId
    from yuo.setup.providers import PROVIDERS

    assert set(get_args(ProviderId)) == set(PROVIDERS)


def test_a_direct_key_model_is_priced_at_the_vendors_model_in_the_list(tmp_path: Path) -> None:
    import json
    import time

    from yuo.adapters.llm.prices import OpenRouterPrices

    cache = tmp_path / "prices.json"
    cache.write_text(json.dumps({"fetched_at": time.time(), "models": {
        "anthropic/claude-sonnet-5.5": [2e-6, 1e-5], "openai/gpt-6.1-sol": [5e-6, 3e-5],
        "openai/gpt-6.1-sol:batch": [2.5e-6, 1.5e-5]}, "catalog": []}))  # fmt: skip
    prices = OpenRouterPrices(cache)
    assert prices.per_token("api:anthropic", "claude-sonnet-5-5") == (2e-6, 1e-5)
    assert prices.per_token("api:openai", "gpt-6.1-sol") == (5e-6, 3e-5)
    assert prices.per_token("api:gemini", "gpt-6.1-sol") is None  # another vendor's prefix
    assert prices.per_token("claude-cli", "sonnet") is None


def test_the_openrouter_catalog_lists_text_models_with_prices_per_million(tmp_path: Path) -> None:
    import httpx

    from yuo.adapters.llm.prices import OpenRouterPrices

    listed = [
        {"id": "qwen/qwen3.8-27b", "name": "Qwen: Qwen3.8 27B", "context_length": 131072,
         "pricing": {"prompt": "0.0000003", "completion": "0.0000012"},
         "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}},
        {"id": "maker/image-1", "name": "Image", "pricing": {"prompt": "0", "completion": "0"},
         "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]}},
    ]  # fmt: skip
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, json={"data": listed})

    cache = tmp_path / "prices.json"
    cache.write_text(
        '{"fetched_at": 9e12, "models": {}}'
    )  # an older cache without the catalog: fetched again
    prices = OpenRouterPrices(cache, client=httpx.Client(transport=httpx.MockTransport(answer)))
    assert prices.catalog() == [
        {"id": "qwen/qwen3.8-27b", "name": "Qwen: Qwen3.8 27B", "in_usd_per_m": 0.3, "out_usd_per_m": 1.2,
         "context": 131072}
    ]  # fmt: skip
    assert prices.per_token("openrouter", "qwen/qwen3.8-27b") == (3e-7, 1.2e-6)
    assert OpenRouterPrices(cache).catalog()[0]["id"] == "qwen/qwen3.8-27b"  # from the cache now
    assert len(asked) == 1
