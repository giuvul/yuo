"""Answers an AI assistant collected before Yuo started (SETUP.md): checked, pre-filled once, then deleted."""

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from tests import fakes
from tests.integration.test_slice import NoPrices
from yuo import cli
from yuo.api.app import create_app
from yuo.app import setup_answers
from yuo.main import Runtime, start

ANSWERS = {
    "version": 1,
    "profile": {
        "display_name": "Sam",
        "ui_lang": "en",
        "content_lang": "it",
        "tz": "Europe/Rome",
        "session_minutes": 20,
        "interests": "cycling, cooking",
    },
    "first_path": {
        "title": "Statistics for A/B tests",
        "goal": "Read and design A/B tests at work",
        "goal_type": "practical",
        "custom_instructions": "I know basic SQL and Python.",
    },
}


def test_every_part_is_kept_when_it_fits(tmp_path: Path) -> None:
    f = tmp_path / setup_answers.FILE_NAME
    f.write_text(json.dumps(ANSWERS), encoding="utf-8")
    got = setup_answers.read(f)
    assert got["profile"]["display_name"] == "Sam" and got["first_path"]["goal_type"] == "practical"


def test_a_field_that_does_not_fit_is_left_out_on_its_own(tmp_path: Path) -> None:
    raw = {
        "profile": {"display_name": "Sam", "tz": "Mars/Olympus", "session_minutes": 500},
        "first_path": {"title": "Chess", "goal": "Beat my brother", "goal_type": "fame"},
        "api_key": "never",
    }
    usable, problems = setup_answers.parse(raw)
    assert usable == {
        "profile": {"display_name": "Sam"},
        "first_path": {"title": "Chess", "goal": "Beat my brother", "goal_type": "understanding",
                       "custom_instructions": ""},
    }  # fmt: skip
    assert any("api_key" in p for p in problems) and any("profile.tz" in p for p in problems)


def test_a_first_path_without_a_goal_is_left_out(tmp_path: Path) -> None:
    usable, problems = setup_answers.parse({"first_path": {"title": "Chess"}})
    assert usable == {} and any("first_path.goal" in p for p in problems)


def test_a_windows_file_with_a_byte_order_mark_reads(tmp_path: Path) -> None:
    f = tmp_path / setup_answers.FILE_NAME
    f.write_text(json.dumps(ANSWERS), encoding="utf-8-sig")
    assert setup_answers.read(f)["profile"]["tz"] == "Europe/Rome"


def test_a_broken_file_is_ignored(tmp_path: Path) -> None:
    f = tmp_path / setup_answers.FILE_NAME
    f.write_text("{not json", encoding="utf-8")
    assert setup_answers.read(f) == {}
    assert setup_answers.read(tmp_path / "missing.json") == {}


@pytest.fixture
def client(db_path: Path) -> Iterator[tuple[TestClient, Runtime, Path]]:
    rt = start(db_path, {"openrouter": fakes.FakeLLM()}, NoPrices(), worker=False)
    answers = db_path.parent / setup_answers.FILE_NAME
    rt.service.answers_file = answers
    app = create_app(version="test", health=dict, service=rt.service)
    with TestClient(app) as c:
        yield c, rt, answers
    rt.close()


def test_the_wizard_reads_them_until_it_is_done(client: tuple[TestClient, Runtime, Path]) -> None:
    http, _, answers = client
    assert http.get("/api/setup/answers").json() == {"profile": None, "first_path": None}
    answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
    got = http.get("/api/setup/answers").json()
    assert got["profile"]["content_lang"] == "it" and got["profile"]["tz"] == "Europe/Rome"
    assert got["first_path"]["title"] == "Statistics for A/B tests"
    assert http.post("/api/onboarding/done").status_code == 200
    assert not answers.exists()  # used once
    answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
    assert http.get("/api/setup/answers").json()["profile"] is None  # too late: the wizard is done


def test_the_learner_can_throw_them_away(client: tuple[TestClient, Runtime, Path]) -> None:
    http, _, answers = client
    answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
    assert http.delete("/api/setup/answers").status_code == 204
    assert not answers.exists()
    assert http.delete("/api/setup/answers").status_code == 204  # nothing left: still fine


def test_the_command_checks_and_saves_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "data"
    monkeypatch.setenv("YUO_DATA_DIR", str(data))
    given = tmp_path / "answers.json"
    given.write_text(
        json.dumps(ANSWERS | {"profile": cast(dict[str, Any], ANSWERS["profile"]) | {"tz": "Nowhere/Land"}})
    )
    assert cli.main(["setup-answers", str(given)]) == 0
    out = capsys.readouterr()
    assert "profile.tz" in out.err and "About you and Your first path" in out.out
    saved = json.loads((data / setup_answers.FILE_NAME).read_text(encoding="utf-8"))
    assert "tz" not in saved["profile"] and saved["profile"]["display_name"] == "Sam"
    if os.name == "posix":  # personal answers: owner only
        assert (data / setup_answers.FILE_NAME).stat().st_mode & 0o777 == 0o600
    assert cli.main(["setup-answers", str(given)]) == 0  # a second run replaces the file
    given.write_text("[]")
    assert cli.main(["setup-answers", str(given)]) == 1
