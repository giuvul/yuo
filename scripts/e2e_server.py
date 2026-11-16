"""The real backend on a scripted model, for the browser tests: `uv run scripts/e2e_server.py --port 18775`.

A fresh database under `.dev/e2e/`, lessons with videos (a real test-pattern MP4 from a fake renderer), the test suite's FakeLLM bound to every role (no network, no
cost), sign-in on as in the shipped app (the origin is the web preview's, `--origin`), and two extra
routes for the tests only: `GET /api/_e2e/key/{item_version_id}` (signed in) returns the right answer of an
item as its view shows it, so a test can play a learner who knows the material; `GET /e2e/setup-code`
(outside `/api`, so public, and only reachable on the backend port: the preview proxies `/api` alone) issues
a fresh one-time setup code, which the server would otherwise print to its console.

The environment wizard runs on fakes: a fixed machine probe (no GPU, no subscription apps, so the
recommendation is Qwen through OpenRouter), AI access whose OpenRouter key check accepts only `sk-or-v1-e2e`
and keeps its own port table (the scripted model stays bound for the other tests), and an update feed with a
fixed newer version. A direct vendor key for Anthropic: `sk-ant-e2e` is accepted and lists three Claude models,
any other key is refused; the runner has an `api:anthropic` port on the scripted model, so a path still
generates after the wizard bound the vendor's models. The plan meter has a Claude reading. Onboarding counts as finished at start (the other tests expect the app, not the
wizard); `POST /e2e/onboarding/reset` undoes the wizard's milestones and the OpenRouter and vendor keys, and
`POST /e2e/models/reset` binds the scripted model again after a test chose a preset.
Started by `web/playwright.config.ts`; never part of the shipped app.
"""

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests import fakes  # noqa: E402
from tests.fakes_media import FakeFFmpeg, FakeRenderer, FakeVoice  # noqa: E402
from yuo.api.app import create_app  # noqa: E402
from yuo.app.access import Access  # noqa: E402
from yuo.app.auth import Auth  # noqa: E402
from yuo.app.auth_model import Origin  # noqa: E402
from yuo.app.plan_meter import PlanMeter  # noqa: E402
from yuo.app.updates import Updates  # noqa: E402
from yuo.assessment import types as xt  # noqa: E402
from yuo.core import logs  # noqa: E402
from yuo.core.llm import LLMError, LLMPort, Role  # noqa: E402
from yuo.db.blobs import BlobStore  # noqa: E402
from yuo.db.migrate import migrate  # noqa: E402
from yuo.main import Media, start  # noqa: E402
from yuo.setup.probe import Bench, Probe  # noqa: E402
from yuo.setup.providers import Provider  # noqa: E402

ROLES: tuple[Role, ...] = ("generator", "reviewer", "grader", "utility", "tutor")


E2E_KEY = "sk-or-v1-e2e"
E2E_VENDOR_KEY = "sk-ant-e2e"
E2E_VENDOR_MODELS = ["claude-haiku-5-5", "claude-opus-5-5", "claude-sonnet-5-5"]


class Secrets:
    """The secret store, in memory."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


def check_key(key: str) -> dict[str, Any]:
    if key != E2E_KEY:
        raise LLMError("openrouter: the key was refused", kind="auth")
    return {"limit_remaining": 4.5, "free_tier": False}


def vendor_models(provider: Provider, key: str) -> list[str]:
    if provider.id != "anthropic" or key != E2E_VENDOR_KEY:
        raise LLMError(f"{provider.id}: the key was refused", kind="auth")
    return list(E2E_VENDOR_MODELS)


def probe() -> Probe:
    return Probe("windows", "11", "x64", "e2e CPU", 8, 16.0, [], 120.0, {}, [], Bench(351.0, 1.5))


def bind_scripted(service: Any) -> None:
    for role in ROLES:
        service.bind(role, "openrouter", "deepseek/deepseek-v4-pro")


class FlatPrices:
    def per_token(self, adapter: str, model: str) -> tuple[float, float] | None:
        return (1e-6, 2e-6)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18775)
    ap.add_argument("--origin", default="http://localhost:4173", help="where the browser opens the app")
    ap.add_argument(
        "--realistic",
        action="store_true",
        help="a real SQL tree, lesson text and review questions (tests/realistic.py), for design screenshots",
    )
    a = ap.parse_args()
    logs.configure("WARNING", json=False)
    work = ROOT / ".dev" / "e2e"  # wiped at start: Playwright may kill the server before it can clean up
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    db = work / "yuo.db"
    migrate(db, "e2e")
    # videos: the scripted author, a voice of silence and a real test-pattern MP4 (playable in the browser)
    media = Media(
        FakeRenderer(playable=True),
        {"kokoro": FakeVoice()},
        FakeFFmpeg(),
        BlobStore(work / "blobs"),
        work / "media",
    )
    # "api:anthropic": the scripted model, for a path after the wizard bound the vendor's models
    ports: dict[str, LLMPort] = {
        "openrouter": fakes.FakeLLM(),
        "api:anthropic": fakes.FakeLLM(name="api:anthropic"),
    }
    rt = start(db, ports, FlatPrices(), media=media)
    bind_scripted(rt.service)
    if a.realistic:
        from tests import realistic

        realistic.install(ports["openrouter"])
    rt.service.put_setting("video.length", "short", "installation")
    rt.service.ensure_learner()
    rt.service.finish_onboarding()
    rt.service.prober = probe
    access_ports: dict[str, Any] = {}  # not the runner's: the scripted model stays the "openrouter" port
    secrets = Secrets()
    rt.service.access = Access(
        rt.writer, rt.readers, secrets, access_ports,
        openrouter=lambda key: fakes.FakeLLM(), local=lambda url: fakes.FakeLLM(), check_key=check_key,
        list_models=lambda url: ["qwen3.8:27b"],
        vendor=lambda provider, key: fakes.FakeLLM(name=provider.adapter), vendor_models=vendor_models,
    )  # fmt: skip
    meter = PlanMeter(work / "cache" / "plan-meter.json")
    rt.service.plan_meter = meter
    meter.reporter("claude")({
        "window_pct": 6.0, "week_pct": 47.0, "window_resets_at": "2026-10-30T16:10:00Z",
        "week_resets_at": "2026-11-03T03:00:00Z", "limited": False,
    })  # fmt: skip
    feed = {
        "version": "9.0.0",
        "published_at": "2026-10-30T00:00:00Z",
        "notes_url": "https://releases.example/9.0.0",
    }
    rt.service.updates = Updates(
        work / "data", "1.0.0", "https://releases.example/feed.json",
        fetch=lambda url: feed, download=lambda url, target, sha, size: target, enabled=lambda: False,
        desktop=False, exit_process=lambda code: None,
    )  # fmt: skip
    auth = Auth(rt.writer, rt.readers, Origin.parse(a.origin))
    app = create_app(version="e2e", health=lambda: {"e2e": True}, service=rt.service, auth=auth)

    @app.get("/e2e/setup-code")
    def setup_code() -> dict[str, str]:
        return {"code": auth.issue_setup_code()}

    @app.post("/e2e/onboarding/reset")
    def reset_onboarding() -> dict[str, bool]:
        with sqlite3.connect(db) as c:
            c.execute(
                "UPDATE installation SET env_profile = json_remove(env_profile, '$.probe', '$.probed_at', "
                "'$.profile_at', '$.onboarded_at')"
            )
        access_ports.clear()
        secrets.values.clear()
        return {"ok": True}

    @app.post("/e2e/models/reset")
    def reset_models() -> dict[str, bool]:
        bind_scripted(rt.service)
        return {"ok": True}

    @app.get("/api/_e2e/key/{item_version_id}")
    def key(item_version_id: str) -> dict[str, Any]:
        with sqlite3.connect(db) as c:
            row = c.execute(
                "SELECT i.type_key, v.payload FROM item_version v JOIN item i ON i.id = v.item_id WHERE v.id = ?",
                (item_version_id,),
            ).fetchone()
        t = xt.get(row[0])
        return {"type": t.key, "answer": t.correct(json.loads(row[1]))}

    try:
        uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")
    finally:
        rt.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
