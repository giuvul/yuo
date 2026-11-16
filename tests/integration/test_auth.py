"""Sign-in and the request guards over HTTP, with a software passkey."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests import fakes
from tests.integration.test_slice import NoPrices, lessons_of
from tests.softkey import SoftKey
from yuo.api.app import create_app
from yuo.app.auth import GUESSES, Auth
from yuo.app.auth_model import Origin
from yuo.app.forms import PathForm
from yuo.core import clock
from yuo.core.ids import new_id
from yuo.main import Runtime, start

ORIGIN = "https://yuo.example"
CSRF = {"X-Yuo-Request": "1"}


@pytest.fixture
def env(db_path: Path) -> Iterator[tuple[Runtime, Auth, TestClient]]:
    rt = start(db_path, {"openrouter": fakes.FakeLLM()}, NoPrices(), worker=False)
    rt.service.ensure_learner()
    auth = Auth(rt.writer, rt.readers, Origin.parse(ORIGIN))
    app = create_app(version="test", health=dict, service=rt.service, auth=auth)
    with TestClient(app, base_url=ORIGIN, headers=CSRF) as c:
        yield rt, auth, c
    rt.close()


def other(c: TestClient) -> TestClient:
    """A second device: same app, its own cookie jar."""
    return TestClient(c.app, base_url=ORIGIN, headers=CSRF)


def enrol(auth: Auth, c: TestClient) -> None:
    code = auth.setup_code_on_start()
    assert code is not None
    assert c.post("/api/auth/setup", json={"code": code.lower().replace("-", " ")}).status_code == 200


def test_everything_but_health_and_sign_in_needs_a_session(env: tuple[Runtime, Auth, TestClient]) -> None:
    _, _, c = env
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/auth/state").json() == {
        "signed_in": False, "desktop": False, "enrolled": False, "methods": [], "device_id": None,
        "recovery_codes_left": None,
    }  # fmt: skip
    for method, url in (("GET", "/api/paths"), ("GET", "/api/stream"), ("POST", "/api/devices")):
        assert c.request(method, url, json={}).status_code == 401, url
    routes = {getattr(r, "path", "") for r in c.app.routes}  # type: ignore[attr-defined]
    open_ = {"/api/health", "/api/auth/state", "/api/auth/setup"}
    assert {
        r for r in routes if r.startswith("/api/auth/sign-in/")
    } | open_ >= open_  # the public set is small


def test_host_allowlist_and_csrf(env: tuple[Runtime, Auth, TestClient]) -> None:
    _, _, c = env
    assert c.get("/api/health", headers={"Host": "evil.example"}).status_code == 421  # DNS rebinding
    assert (
        c.get("/api/health", headers={"Host": "localhost:18765"}).status_code == 200
    )  # the container's probe
    bare = TestClient(c.app, base_url=ORIGIN)
    assert bare.post("/api/auth/setup", json={"code": "x" * 8}).status_code == 403  # no custom header
    assert (
        c.post(
            "/api/auth/setup", json={"code": "x" * 8}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert c.post("/api/auth/setup", json={"code": "x" * 8}, headers={"Origin": ORIGIN}).status_code == 400


def test_setup_code_works_once_then_a_passkey_signs_in(env: tuple[Runtime, Auth, TestClient]) -> None:
    _, auth, c = env
    code = auth.setup_code_on_start()
    assert code is not None
    assert c.post("/api/auth/setup", json={"code": "WRONG-CODE"}).status_code == 400
    r = c.post("/api/auth/setup", json={"code": code, "device_label": "laptop"})
    assert r.status_code == 200 and r.cookies.get("__Host-yuo_session")
    assert "HttpOnly" in r.headers["set-cookie"] and "SameSite=strict" in r.headers["set-cookie"]
    assert other(c).post("/api/auth/setup", json={"code": code}).status_code == 400  # used

    key = SoftKey(ORIGIN)
    opts = c.post("/api/auth/passkeys/options").json()
    assert opts["options"]["rp"]["id"] == "yuo.example"
    made = c.post(
        "/api/auth/passkeys",
        json={
            "challenge_id": opts["challenge_id"],
            "credential": key.create(opts["options"]),
            "label": "Phone",
        },
    )
    assert made.status_code == 201 and made.json()["kind"] == "passkey"
    assert auth.setup_code_on_start() is None  # enrolled: no more codes at startup

    phone = other(c)
    assert phone.get("/api/paths").status_code == 401
    opts = phone.post("/api/auth/sign-in/passkey/options").json()
    bad = key.get(opts["options"], origin="https://evil.example")
    refused = phone.post(
        "/api/auth/sign-in/passkey", json={"challenge_id": opts["challenge_id"], "credential": bad}
    )
    assert refused.status_code == 400
    opts = phone.post("/api/auth/sign-in/passkey/options").json()
    ok = phone.post(
        "/api/auth/sign-in/passkey",
        json={
            "challenge_id": opts["challenge_id"],
            "credential": key.get(opts["options"]),
            "device_label": "phone",
        },
    )
    assert ok.status_code == 200 and phone.get("/api/paths").status_code == 200
    replay = phone.post(
        "/api/auth/sign-in/passkey",
        json={"challenge_id": opts["challenge_id"], "credential": key.get(opts["options"])},
    )
    assert replay.status_code == 400  # a challenge is used once
    state = phone.get("/api/auth/state").json()
    assert (
        state["signed_in"]
        and state["methods"] == ["passkey"]
        and state["device_id"] == ok.json()["device_id"]
    )


def test_password_guesses_are_throttled_but_a_passkey_still_works(
    env: tuple[Runtime, Auth, TestClient],
) -> None:
    _, auth, c = env
    enrol(auth, c)
    assert c.put("/api/auth/password", json={"password": "short"}).status_code == 400
    assert c.put("/api/auth/password", json={"password": "correct horse battery"}).status_code == 204
    key = SoftKey(ORIGIN)
    opts = c.post("/api/auth/passkeys/options").json()
    c.post(
        "/api/auth/passkeys",
        json={"challenge_id": opts["challenge_id"], "credential": key.create(opts["options"])},
    )

    d = other(c)
    assert d.post("/api/auth/sign-in/password", json={"password": "correct horse battery"}).status_code == 200
    e = other(c)
    for _ in range(GUESSES):
        assert e.post("/api/auth/sign-in/password", json={"password": "guess"}).status_code == 400
    r = e.post("/api/auth/sign-in/password", json={"password": "correct horse battery"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    opts = e.post("/api/auth/sign-in/passkey/options").json()
    passkey = e.post(
        "/api/auth/sign-in/passkey",
        json={"challenge_id": opts["challenge_id"], "credential": key.get(opts["options"])},
    )
    assert passkey.status_code == 200


def test_recovery_codes_work_once(env: tuple[Runtime, Auth, TestClient]) -> None:
    _, auth, c = env
    enrol(auth, c)
    old = c.post("/api/auth/recovery-codes").json()["codes"]
    codes = c.post("/api/auth/recovery-codes").json()["codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    d = other(c)
    assert d.post("/api/auth/sign-in/recovery", json={"code": old[0]}).status_code == 400  # replaced
    assert d.post("/api/auth/sign-in/recovery", json={"code": codes[0].lower()}).status_code == 200
    assert other(c).post("/api/auth/sign-in/recovery", json={"code": codes[0]}).status_code == 400
    assert d.get("/api/auth/state").json()["recovery_codes_left"] == 9


def test_devices_are_listed_and_revoked(env: tuple[Runtime, Auth, TestClient]) -> None:
    rt, auth, c = env
    rt.service.bind("generator", "openrouter", "deepseek/deepseek-v4-pro")
    for role in ("reviewer", "grader", "utility"):
        rt.service.bind(role, "openrouter", "qwen/qwen3.8-27b")
    path_id, _ = rt.service.create_path(PathForm(title="SQL", subject="SQL", goal="joins"))
    while rt.worker.run_once():
        pass
    version = rt.service.lesson_view(lessons_of(rt, path_id)[0]["id"])["version_id"]
    enrol(auth, c)
    c.put("/api/auth/password", json={"password": "correct horse battery"})
    phone = other(c)
    phone_id = phone.post(
        "/api/auth/sign-in/password", json={"password": "correct horse battery", "device_label": "phone"}
    ).json()["device_id"]

    assert phone.post("/api/devices", json={"label": "ignored"}).json()["device_id"] == phone_id
    payload = {"lesson_version_id": version, "seconds": 30}
    event = {
        "id": new_id(),
        "type": "lesson.started",
        "device_at": clock.now(),
        "tz": "UTC",
        "payload": payload,
    }
    assert phone.post("/api/events", json={"device_id": "not-mine", "events": [event]}).json()[
        "accepted"
    ] == [event["id"]]
    with rt.readers.connection() as conn:
        row = conn.execute("SELECT device_id FROM learning_event WHERE id = ?", (event["id"],)).fetchone()
    assert row[0] == phone_id  # the session's device, never the body's

    devices = c.get("/api/auth/devices").json()
    assert {d["label"] for d in devices} == {"browser", "phone"}
    assert [d["current"] for d in devices if d["label"] == "browser"] == [True]
    assert c.delete(f"/api/auth/devices/{phone_id}").status_code == 204
    assert phone.get("/api/paths").status_code == 401
    assert c.get("/api/paths").status_code == 200

    (only,) = c.get("/api/auth/credentials").json()
    assert c.delete(f"/api/auth/credentials/{only['id']}").status_code == 400  # the last way in stays
    assert c.post("/api/auth/sign-out").status_code == 204
    assert c.get("/api/paths").status_code == 401


def test_origin_must_be_https_unless_local() -> None:
    assert Origin.parse("http://localhost:18765").secure is False
    assert Origin.parse("https://yuo.1-2-3-4.sslip.io/").url == "https://yuo.1-2-3-4.sslip.io"
    for bad in ("http://yuo.example", "https://yuo.example/app", "ftp://x"):
        with pytest.raises(ValueError):
            Origin.parse(bad)
