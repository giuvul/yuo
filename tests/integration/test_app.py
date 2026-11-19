import json
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from yuo import main

LOCAL = "http://localhost:18765"


def test_health_reports_the_migrated_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YUO_DATA_DIR", str(tmp_path))
    with TestClient(main.build(), base_url=LOCAL) as client:
        body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["schema_version"] == 7
    assert (tmp_path / "yuo.db").exists()


def test_the_built_app_needs_a_session_on_every_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No unauthenticated endpoint but health and the sign-in flow, on loopback too."""
    monkeypatch.setenv("YUO_DATA_DIR", str(tmp_path))
    app = main.build()
    err = capsys.readouterr().err
    assert "one-time code" in err  # the setup code goes to the console of whoever runs the server
    public = {"/api/health", "/api/auth/state", "/api/auth/setup", "/api/auth/launch"}
    with TestClient(app, base_url=LOCAL, headers={"X-Yuo-Request": "1"}) as client:
        for route in app.routes:
            if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
                continue
            if route.path in public or route.path.startswith("/api/auth/sign-in/"):
                continue
            url = route.path.replace("{", "").replace("}", "")
            for method in (route.methods or set()) - {"HEAD"}:
                assert client.request(method, url).status_code == 401, (method, route.path)
        assert client.get("/api/health", headers={"Host": "attacker.example"}).status_code == 421


def test_the_desktop_app_is_loopback_only_and_signs_in_by_launch_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No setup code on the console, the launch link and the control route are the only additions."""
    monkeypatch.setenv("YUO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("YUO_MODE", "desktop")
    monkeypatch.setenv("YUO_NO_BROWSER", "1")
    monkeypatch.setenv("YUO_SECRETS_KEY_FILE", str(tmp_path / "k"))  # no OS keychain in tests
    (tmp_path / "k").write_text("a" * 64)
    app = main.build()
    assert "one-time code" not in capsys.readouterr().err
    public = {
        "/api/health", "/api/auth/state", "/api/auth/setup", "/api/auth/launch", "/api/desktop/link", "/api/desktop/open",
    }  # fmt: skip
    with TestClient(app, base_url=LOCAL, headers={"X-Yuo-Request": "1"}) as client:
        assert client.get("/api/auth/state").json()["desktop"] is True
        assert client.post("/api/desktop/link").status_code == 403  # no control token
        assert client.post("/api/desktop/open", json={"auto": True}).status_code == 429  # no browser here
        assert json.loads((tmp_path / "desktop.json").read_text())["launch"] == ""
        info = json.loads((tmp_path / "desktop.json").read_text())
        url = client.post("/api/desktop/link", headers={"X-Yuo-Control": info["control"]}).json()["url"]
        for route in app.routes:
            if isinstance(route, APIRoute) and route.path.startswith("/api/") and route.path not in public:
                if route.path.startswith("/api/auth/sign-in/"):
                    continue
                for method in (route.methods or set()) - {"HEAD"}:
                    url_ = route.path.replace("{", "").replace("}", "")
                    assert client.request(method, url_).status_code == 401, (method, route.path)
        assert client.post("/api/auth/launch", json={"code": url.split("=", 1)[1]}).status_code == 200
        assert client.get("/api/setup").json()["desktop"] is True
    assert not (tmp_path / "desktop.json").exists()  # removed on stop
