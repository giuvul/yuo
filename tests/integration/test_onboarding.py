"""The environment wizard, AI access, learner onboarding, updates and the desktop sign-in over HTTP."""

import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests import fakes
from tests.integration.test_slice import NoPrices
from yuo import main
from yuo.api.app import create_app
from yuo.app.access import Access
from yuo.app.auth import Auth
from yuo.app.auth_model import Origin
from yuo.app.plan_meter import PlanMeter
from yuo.app.updates import EXIT_FOR_UPDATE, Updates
from yuo.core.llm import LLMError
from yuo.main import Runtime, start
from yuo.setup.probe import Bench, Gpu, Probe
from yuo.setup.providers import Provider

CSRF = {"X-Yuo-Request": "1"}
DESKTOP = "http://127.0.0.1:18765"


class Secrets:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


def check_key(key: str) -> dict[str, Any]:
    if key != "sk-or-v1-good":
        raise LLMError("openrouter: the key was refused", kind="auth")
    return {"limit_remaining": 4.5, "free_tier": False}


def vendor_models(provider: Provider, key: str) -> list[str]:
    if key != "sk-ant-api03-good":
        raise LLMError(f"{provider.id}: the key was refused", kind="auth")
    return ["claude-haiku-5-5", "claude-opus-5-5", "claude-sonnet-5-5"]


class FakeDesktop:
    def __init__(self, auth: Auth) -> None:
        self.auth = auth
        self.control_token = "control-token"
        self.quits = 0

    def link(self) -> str:
        return f"{DESKTOP}/#launch={self.auth.issue_launch_code()}"

    def quit(self) -> None:
        self.quits += 1


@pytest.fixture
def desk(db_path: Path, tmp_path: Path) -> Iterator[tuple[Runtime, TestClient, dict[str, Any]]]:
    llm = fakes.FakeLLM()
    rt = start(db_path, {"claude-cli": llm}, NoPrices(), worker=False)
    svc = rt.service
    svc.ensure_learner()
    state: dict[str, Any] = {"exits": [], "feed": None, "downloads": 0, "llm": llm}
    secrets = Secrets()
    svc.prober = lambda: Probe("linux", "6", "x64", "cpu", 8, 32.0, [Gpu("RTX 3090", 24.0, "nvidia")], 50.0,
                               {}, [], Bench(100.0, 1.5))  # fmt: skip
    svc.access = Access(
        rt.writer, rt.readers, secrets, svc.runner.ports,
        openrouter=lambda key: fakes.FakeLLM(), local=lambda url: fakes.FakeLLM(), check_key=check_key,
        list_models=lambda url: ["qwen3.8:27b"], vendor=lambda provider, key: fakes.FakeLLM(),
        vendor_models=vendor_models,
    )  # fmt: skip

    def download(url: str, target: Path, sha: str, size: int) -> Path:
        state["downloads"] += 1
        target.write_bytes(b"x" * size)
        return target

    svc.updates = Updates(
        tmp_path / "data", "1.0.0", "https://releases.example/feed.json",
        fetch=lambda url: state["feed"], download=download, enabled=lambda: True, desktop=True,
        exit_process=state["exits"].append,
    )  # fmt: skip
    auth = Auth(rt.writer, rt.readers, Origin.parse(DESKTOP), desktop=True)
    desktop = FakeDesktop(auth)
    state["secrets"], state["desktop"], state["auth"] = secrets, desktop, auth
    app = create_app(version="test", health=dict, service=svc, auth=auth, desktop=desktop,
                     waitlist_url="https://waitlist.example/yuo")  # fmt: skip
    with TestClient(app, base_url=DESKTOP, headers=CSRF) as c:
        yield rt, c, state
    rt.close()


def sign_in(c: TestClient, auth: Auth) -> None:
    assert c.post("/api/auth/launch", json={"code": auth.issue_launch_code()}).status_code == 200


def test_the_launch_link_signs_in_once(desk: tuple[Runtime, TestClient, dict[str, Any]]) -> None:
    _, c, state = desk
    auth: Auth = state["auth"]
    assert c.get("/api/auth/state").json()["desktop"] is True
    assert c.get("/api/setup").status_code == 401
    code = auth.issue_launch_code()
    first = c.post("/api/auth/launch", json={"code": code})
    assert first.status_code == 200
    assert c.post("/api/auth/launch", json={"code": code}).status_code == 400  # once only
    setup = c.get("/api/setup").json()
    assert setup["desktop"] is True and setup["waitlist_url"] == "https://waitlist.example/yuo"
    again = TestClient(c.app, base_url=DESKTOP, headers=CSRF)  # a later start: the same device, a new session
    sign_in(again, auth)
    assert again.get("/api/auth/state").json()["device_id"] == first.json()["device_id"]


def test_a_second_start_gets_a_link_with_the_control_token(
    desk: tuple[Runtime, TestClient, dict[str, Any]],
) -> None:
    _, c, _ = desk
    assert c.post("/api/desktop/link", headers={"X-Yuo-Control": "wrong"}).status_code == 403
    url = c.post("/api/desktop/link", headers={"X-Yuo-Control": "control-token"}).json()["url"]
    assert url.startswith(f"{DESKTOP}/#launch=")
    assert c.post("/api/auth/launch", json={"code": url.split("=", 1)[1]}).status_code == 200


def test_desktop_sign_in_needs_a_loopback_origin(desk: tuple[Runtime, TestClient, dict[str, Any]]) -> None:
    rt, _, _ = desk
    with pytest.raises(ValueError, match="loopback"):
        Auth(rt.writer, rt.readers, Origin.parse("https://yuo.example"), desktop=True)
    server = Auth(rt.writer, rt.readers, Origin.parse("https://yuo.example"))
    app = create_app(version="test", health=dict, service=rt.service, auth=server)
    with TestClient(app, base_url="https://yuo.example", headers=CSRF) as c:
        assert c.post("/api/auth/launch", json={"code": "x" * 20}).status_code == 404
        assert c.post("/api/desktop/link", headers={"X-Yuo-Control": "control-token"}).status_code == 404


def test_the_wizard_from_probe_to_first_path(desk: tuple[Runtime, TestClient, dict[str, Any]]) -> None:
    rt, c, state = desk
    sign_in(c, state["auth"])
    assert c.get("/api/onboarding").json() == {
        "probed": False, "models_chosen": False, "profile_done": False, "has_path": False, "done": False,
    }  # fmt: skip
    probe = c.post("/api/setup/probe").json()
    assert probe["gpus"][0]["memory_gb"] == 24.0
    rec = c.get("/api/setup/recommendation").json()
    assert rec["preset"] == "local" and rec["needs"] == ["local_server", "local_model"]
    assert [o["preset"] for o in rec["options"]] == [
        "local",
        "open",
        "claude",
        "codex",
    ]  # subscriptions last: not installed
    local, api = (o["estimate"] for o in rec["options"][:2])
    assert (
        local["high_usd"] == 0
        and local["missing"] == []
        and {x["source"] for x in local["lines"]} == {"local"}
    )
    assert api["lessons"] == 20

    # AI access: a wrong key is refused and nothing is stored; a good one connects at once
    assert c.put("/api/setup/access/openrouter", json={"key": "not-a-key"}).status_code == 422
    bad = c.put("/api/setup/access/openrouter", json={"key": "sk-or-v1-bad"})
    assert bad.status_code == 400 and bad.json()["kind"] == "auth" and state["secrets"].values == {}
    assert (
        c.put("/api/setup/access/openrouter", json={"key": "sk-or-v1-good"}).json()["limit_remaining"] == 4.5
    )
    assert (
        state["secrets"].values == {"openrouter": "sk-or-v1-good"} and "openrouter" in rt.service.runner.ports
    )
    access = c.get("/api/setup/access").json()
    assert access["openrouter"] is True and "sk-or" not in json.dumps(access)  # the key never comes back
    assert c.put("/api/setup/access/local", json={"url": "http://192.168.1.5:11434/v1"}).status_code == 422
    assert c.put("/api/setup/access/local", json={"url": "http://127.0.0.1:11434/v1"}).json()["models"] == [
        "qwen3.8:27b"
    ]
    assert c.post("/api/setup/preset", json={"preset": "local"}).json()["bindings"]["generator"] == {
        "adapter": "local", "model": "qwen3.8:27b",
    }  # fmt: skip

    # subscription consent: asked once, recorded with the text's hash
    assert "extra usage" in c.get("/api/setup/consent/claude").json()["text"]
    assert c.post("/api/setup/preset", json={"preset": "claude"}).status_code == 409
    assert c.post("/api/setup/preset", json={"preset": "claude", "consent": True}).status_code == 200
    assert c.post("/api/setup/preset", json={"preset": "claude"}).status_code == 200
    assert c.get("/api/setup/access").json()["consent"] == {"claude": True}

    me = c.patch("/api/me", json={"display_name": "Ada", "tz": "Europe/Rome", "theme": "dark", "session_minutes": 30,
                                  "interests": "football and logistics"}).json()  # fmt: skip
    assert (me["display_name"], me["theme"], me["session_minutes"]) == ("Ada", "dark", 30)
    assert c.patch("/api/me", json={"tz": "Mars/Base"}).status_code == 422
    assert c.patch("/api/me", json={"session_minutes": 500}).status_code == 422
    assert c.post("/api/paths", json={"title": "SQL", "subject": "SQL", "goal": "joins"}).status_code == 201
    while rt.worker.run_once():
        pass
    prompts = [m.content for _, r in state["llm"].calls for m in r.messages]
    assert any("<learner_input>" in p and "football and logistics" in p for p in prompts)  # as learner data
    assert c.post("/api/onboarding/done").json() == {
        "probed": True, "models_chosen": True, "profile_done": True, "has_path": True, "done": True,
    }  # fmt: skip


def test_an_update_is_fetched_checked_and_handed_to_the_launcher(
    desk: tuple[Runtime, TestClient, dict[str, Any]],
) -> None:
    _, c, state = desk
    sign_in(c, state["auth"])
    assert c.get("/api/update").json()["available"] is False
    state["feed"] = {"version": "1.0.0", "desktop": None}
    assert c.post("/api/update/check").json()["available"] is False
    assert c.post("/api/update/download").status_code == 422  # nothing newer
    state["feed"] = {
        "version": "1.1.0", "published_at": "2026-11-20T10:00:00Z", "notes_url": "javascript:alert(1)",
        "desktop": {"url": "https://releases.example/yuo-1.1.0-desktop.zip", "sha256": "a" * 64, "bytes": 10},
    }  # fmt: skip
    status = c.post("/api/update/check").json()
    assert status["available"] and status["latest"] == "1.1.0" and status["notes_url"] is None
    assert c.post("/api/update/restart").status_code == 422  # nothing staged yet
    assert c.post("/api/update/download").json()["staged"] == "1.1.0"
    c.post("/api/update/download")
    assert state["downloads"] == 1  # already there: not fetched again
    assert c.post("/api/update/restart").status_code == 202 and state["exits"] == [EXIT_FOR_UPDATE]
    assert c.post("/api/desktop/quit").status_code == 202 and state["desktop"].quits == 1


def test_every_start_looks_for_a_new_release_even_with_a_fresh_answer_from_yesterday(tmp_path: Path) -> None:
    """A computer that is off at night may never run for a whole day: the look happens after each start."""
    import time

    fetched: list[str] = []
    on = [True]

    def fetch(url: str) -> dict[str, Any]:
        fetched.append(url)
        if len(fetched) == 1:
            raise OSError("offline")  # the first look fails: tried again at the next wake
        return {"version": "1.1.0", "desktop": None}

    cache = tmp_path / "cache" / "update-check.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"version": "1.0.0", "checked_at": time.time()}), encoding="utf-8")

    def updates(feed: str | None) -> Updates:
        return Updates(tmp_path, "1.0.0", feed, fetch=fetch, download=lambda *a: tmp_path, enabled=lambda: on[0],
                       desktop=False, exit_process=lambda code: None, first_check_s=0, poll_s=0.01)  # fmt: skip

    u = updates("https://releases.example/feed.json")
    u.start()
    deadline = time.time() + 5
    while len(fetched) < 2 and time.time() < deadline:
        time.sleep(0.01)
    time.sleep(0.1)  # more wakes: the answer is fresh now, nothing more is fetched
    u.stop()
    assert len(fetched) == 2 and u.status()["latest"] == "1.1.0" and u.status()["available"] is True

    fetched.clear()
    on[0] = False  # "updates.check" off: no look at all
    u = updates("https://releases.example/feed.json")
    u.start()
    time.sleep(0.1)
    u.stop()
    no_feed = updates(None)  # a build without a feed never starts the look
    no_feed.start()
    assert fetched == [] and no_feed._thread is None


def test_a_signed_out_tab_gets_a_signed_in_one_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first link can get lost (a browser's first-run screens): a signed-out tab asks the server to open a
    fresh one on this computer, once on its own and then from a button, never more than every 5 s."""
    opened: list[str] = []
    monkeypatch.delenv("YUO_NO_BROWSER", raising=False)
    monkeypatch.setattr("webbrowser.open", opened.append)
    clock = [100.0]
    monkeypatch.setattr("time.monotonic", lambda: clock[0])
    desktop = main.Desktop(tmp_path, Origin.parse(DESKTOP))
    desktop.auth = SimpleNamespace(issue_launch_code=lambda: f"code{len(opened)}")
    desktop.open_browser()
    assert opened == [f"{DESKTOP}/#launch=code0"]
    assert desktop.reopen(auto=True) is False  # just opened
    clock[0] += 6
    assert desktop.reopen(auto=True) is True
    clock[0] += 6
    assert desktop.reopen(auto=True) is False  # once on its own
    assert desktop.reopen(auto=False) is True  # the button
    assert desktop.reopen(auto=False) is False
    assert len(opened) == 3


def test_a_direct_vendor_key_is_checked_kept_and_its_models_bound(
    desk: tuple[Runtime, TestClient, dict[str, Any]],
) -> None:
    rt, c, state = desk
    sign_in(c, state["auth"])
    anthropic = next(p for p in c.get("/api/setup/providers").json() if p["id"] == "anthropic")
    assert anthropic["suggested_main"] == "claude-sonnet-5-5" and anthropic["connected"] is False
    assert (
        c.put("/api/setup/access/vendor/anthropic", json={"key": "sk-proj-not-anthropic"}).status_code == 422
    )
    refused = c.put("/api/setup/access/vendor/anthropic", json={"key": "sk-ant-api03-bad"})
    assert refused.status_code == 400 and "vendor:anthropic" not in state["secrets"].values
    assert c.put("/api/setup/access/vendor/nobody", json={"key": "sk-ant-api03-good"}).status_code == 422
    ok = c.put("/api/setup/access/vendor/anthropic", json={"key": "sk-ant-api03-good"})
    assert ok.json()["models"] == ["claude-haiku-5-5", "claude-opus-5-5", "claude-sonnet-5-5"]
    assert state["secrets"].values["vendor:anthropic"] == "sk-ant-api03-good"
    assert "api:anthropic" in rt.service.runner.ports and c.get("/api/setup/access").json()["vendors"] == [
        "anthropic"
    ]
    assert "sk-ant" not in c.get("/api/setup/access").text  # the key never comes back

    estimate = c.get(
        "/api/setup/estimate-vendor",
        params={"provider": "anthropic", "main": "claude-sonnet-5-5", "reviewer": "claude-opus-5-5"},
    ).json()
    assert {line["adapter"] for line in estimate["lines"]} == {"api:anthropic"} and estimate[
        "plan_usage"
    ] == []

    body = {"provider": "anthropic", "main": "claude-sonnet-5-5", "reviewer": "claude-gone-1"}
    assert c.post("/api/setup/vendor-models", json=body).status_code == 422  # not a model the key can use
    setup = c.post("/api/setup/vendor-models", json=body | {"reviewer": "claude-opus-5-5"}).json()
    assert setup["bindings"]["generator"] == {"adapter": "api:anthropic", "model": "claude-sonnet-5-5"}
    assert setup["bindings"]["reviewer"] == {"adapter": "api:anthropic", "model": "claude-opus-5-5"}
    assert any("has not been tested with Yuo" in w for w in setup["warnings"])

    assert c.delete("/api/setup/access/vendor/anthropic").status_code == 204
    assert (
        "api:anthropic" not in rt.service.runner.ports and "vendor:anthropic" not in state["secrets"].values
    )


def test_the_plan_meter_shows_the_last_reading_per_subscription(
    desk: tuple[Runtime, TestClient, dict[str, Any]], tmp_path: Path
) -> None:
    rt, c, state = desk
    sign_in(c, state["auth"])
    assert c.get("/api/setup/plan-meter").json() == {"claude": None, "codex": None}
    meter = PlanMeter(tmp_path / "plan-meter.json")
    rt.service.plan_meter = meter
    reading = {"window_pct": 6.0, "week_pct": 47.0, "window_resets_at": "2026-10-30T15:30:00+00:00",
               "week_resets_at": "2026-11-03T03:00:00+00:00", "limited": False}  # fmt: skip
    meter.reporter("claude")(reading)
    got = c.get("/api/setup/plan-meter").json()
    assert got["codex"] is None and got["claude"]["week_pct"] == 47.0 and got["claude"]["observed_at"]
    kept = PlanMeter(tmp_path / "plan-meter.json").snapshot()["claude"]  # kept on disk
    assert kept is not None and kept["window_pct"] == 6.0


def test_generation_waits_for_the_subscription_program(
    desk: tuple[Runtime, TestClient, dict[str, Any]],
) -> None:
    """0.7.6: a chosen subscription whose program is missing or signed out stops a new path with a clear
    step, before any job is queued (a level check used to fail with "Not logged in")."""
    from yuo.adapters import cli_access as ca

    rt, c, state = desk
    sign_in(c, state["auth"])
    answers = {"claude": ca.Status("claude", installed=False)}
    cli = ca.CliAccess(container=False)
    cli.cache = ca.StatusCache(lambda name: answers[name])
    rt.service.cli = cli
    assert c.get("/api/setup/ai-ready").json() == {"ready": True, "clis": []}  # the scripted model needs none
    rt.service.bind("generator", "claude-cli", "sonnet")
    ready = c.get("/api/setup/ai-ready").json()
    assert ready["ready"] is False and ready["clis"][0]["reason"] == "not_installed"
    assert ready["clis"][0]["install_command"] and ready["clis"][0]["needed"] is True
    refused = c.post("/api/paths", json={"title": "SQL", "goal": "joins"}, headers=CSRF)
    assert refused.status_code == 409
    assert refused.json() | {"detail": ""} == {
        "detail": "",
        "code": "ai_not_ready",
        "cli": "claude",
        "reason": "not_installed",
    }
    with rt.readers.connection() as conn:
        assert conn.execute("SELECT count(*) FROM path").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM generation_job").fetchone()[0] == 0
    answers["claude"] = ca.Status("claude", installed=True, logged_in=False)
    assert c.get("/api/setup/cli/claude?fresh=true").json()["reason"] == "not_logged_in"
    answers["claude"] = ca.Status("claude", installed=True, logged_in=True, account="max")
    assert c.get("/api/setup/ai-ready?fresh=true").json()["ready"] is True
    assert c.post("/api/paths", json={"title": "SQL", "goal": "joins"}, headers=CSRF).status_code == 201


def test_openrouter_models_are_chosen_from_its_list(desk: tuple[Runtime, TestClient, dict[str, Any]]) -> None:
    """Settings > Your own API keys > OpenRouter: any model in OpenRouter's list, main and reviewer (0.8.1)."""
    rt, c, state = desk
    sign_in(c, state["auth"])
    assert c.get("/api/setup/access/openrouter/models").json() == {"models": []}  # no price list here
    catalog = [
        {"id": "deepseek/deepseek-v4-pro", "name": "DeepSeek V4 Pro", "in_usd_per_m": 0.5, "out_usd_per_m": 2.0,
         "context": 128000},
        {"id": "qwen/qwen3.8-27b", "name": "Qwen3.8 27B", "in_usd_per_m": 0.3, "out_usd_per_m": 1.2, "context": None},
    ]  # fmt: skip
    rt.service.prices.catalog = lambda: catalog  # type: ignore[attr-defined]
    assert [m["id"] for m in c.get("/api/setup/access/openrouter/models").json()["models"]] == [
        "deepseek/deepseek-v4-pro",
        "qwen/qwen3.8-27b",
    ]
    estimate = c.get(
        "/api/setup/estimate-vendor",
        params={"provider": "openrouter", "main": "deepseek/deepseek-v4-pro", "reviewer": "qwen/qwen3.8-27b"},
    ).json()
    assert {line["adapter"] for line in estimate["lines"]} == {"openrouter"} and estimate["high_usd"] > 0
    body = {"provider": "openrouter", "main": "deepseek/deepseek-v4-pro", "reviewer": "nobody/model"}
    assert c.post("/api/setup/vendor-models", json=body).status_code == 422
    setup = c.post("/api/setup/vendor-models", json=body | {"reviewer": "qwen/qwen3.8-27b"}).json()
    assert setup["bindings"]["tutor"] == {"adapter": "openrouter", "model": "deepseek/deepseek-v4-pro"}
    assert setup["bindings"]["reviewer"] == {"adapter": "openrouter", "model": "qwen/qwen3.8-27b"}
