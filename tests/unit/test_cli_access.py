"""Subscription CLIs: found, signed in, and the readiness gate before generation (0.7.6)."""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from yuo.adapters import cli_access as ca


def _run_with(outputs: dict[str, tuple[int, str]]) -> ca.Run:
    def run(cmd: list[str], env: dict[str, str], timeout: float) -> subprocess.CompletedProcess[str]:
        code, out = outputs[" ".join(cmd[1:])]
        return subprocess.CompletedProcess(cmd, code, out, "")

    return run


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("YUO_CLI_HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path / "nothing"))
    return tmp_path


def _program(home: Path, name: str) -> None:
    folder = home / ".local" / "bin"
    folder.mkdir(parents=True)
    (folder / name).write_text("#!/bin/sh\n")
    (folder / name).chmod(0o755)


def test_a_missing_program_is_not_installed(home: Path) -> None:
    s = ca.status("claude")
    assert (s.installed, s.ready, s.reason) == (False, False, "not_installed")


def test_claude_says_whether_it_is_signed_in(home: Path) -> None:
    _program(home, "claude")  # found under the CLI home, where the vendor's installer puts it
    out = {"--version": (0, "2.1.319 (Claude Code)\n")}
    signed_out = ca.status(
        "claude", _run_with(out | {"auth status": (1, '{"loggedIn": false, "authMethod": "none"}')})
    )
    assert (signed_out.installed, signed_out.logged_in, signed_out.reason) == (True, False, "not_logged_in")
    assert signed_out.version == "2.1.319 (Claude Code)"
    signed_in = ca.status(
        "claude",
        _run_with(
            out
            | {"auth status": (0, '{"loggedIn": true, "subscriptionType": "max", "email": "a@b.example"}')}
        ),
    )
    assert signed_in.ready and signed_in.account == "max"  # the plan, never the address
    unclear = ca.status("claude", _run_with(out | {"auth status": (2, "unknown command")}))
    assert unclear.logged_in is None and unclear.ready  # an old program that cannot say is not blocked


def test_codex_login_status(home: Path) -> None:
    _program(home, "codex")
    out = {"--version": (0, "codex 0.50\n")}
    signed_in = ca.status("codex", _run_with(out | {"login status": (0, "Logged in using ChatGPT")}))
    assert signed_in.ready and signed_in.account == "ChatGPT"
    assert (
        ca.status("codex", _run_with(out | {"login status": (1, "Not logged in")})).reason == "not_logged_in"
    )


def test_the_cli_runs_in_the_cli_home_without_yuo_secrets(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YUO_SECRET_OPENROUTER_FILE", "/secret")
    env = ca.cli_env()
    assert env["HOME"] == str(home) and "YUO_SECRET_OPENROUTER_FILE" not in env
    assert env["PATH"].startswith(str(home / ".local" / "bin"))


def test_the_sign_in_link_is_read_from_terminal_output() -> None:
    raw = (
        b"Opening browser to sign in\xe2\x80\xa6\r\nIf the browser didn't open, visit: "
        b"\x1b]8;;https://claude.com/cai/oauth/authorize?code=true&state=abc\x07https://claude.com/cai/oauth/"
        b"authorize?code=true&state=abc\x1b]8;;\x07\r\n\x1b[1mPaste code here if prompted >\x1b[0m "
    )
    text = ca.clean_terminal(raw)
    assert "\x1b" not in text and "Paste code here" in text
    assert ca.sign_in_link(text) == "https://claude.com/cai/oauth/authorize?code=true&state=abc"
    assert (
        ca.sign_in_link("visit https://evil.example/claude.com/login now") is None
    )  # the vendor's pages only


def test_a_good_answer_is_cached_and_a_bad_one_asked_again(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = [ca.Status("claude", True, logged_in=False), ca.Status("claude", True, logged_in=True)]
    asked: list[str] = []

    def ask(cli: str) -> ca.Status:
        asked.append(cli)
        return answers[min(len(asked), 2) - 1]

    cache = ca.StatusCache(ask)
    monkeypatch.setattr(ca, "BAD_TTL_S", 0.0)
    assert cache.get("claude").ready is False
    assert cache.get("claude").ready is True  # not signed in: asked again
    assert cache.get("claude").ready is True and len(asked) == 2  # signed in: kept
    assert cache.get("claude", fresh=True).ready and len(asked) == 3


def test_an_install_runs_the_vendors_script_in_the_cli_home(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ca, "can_install", lambda cli: True)
    seen: dict[str, Any] = {}

    def run(cmd: list[str], env: dict[str, str], timeout: float) -> subprocess.CompletedProcess[str]:
        seen["cmd"], seen["home"], seen["script"] = cmd[0], env["HOME"], Path(cmd[1]).read_text()
        _program(home, "claude")  # what the installer does
        return subprocess.CompletedProcess(cmd, 0, "", "")

    done: list[bool] = []
    installer = ca.Installer(fetch=lambda url: "#!/bin/bash\necho hi\n", run=run)
    installer._work(lambda: done.append(True))
    assert installer.task.state == "done" and done == [True]
    assert seen == {"cmd": "bash", "home": str(home), "script": "#!/bin/bash\necho hi\n"}
    failing = ca.Installer(
        fetch=lambda url: "#!/bin/bash\n",
        run=lambda c, e, t: subprocess.CompletedProcess(c, 1, "", "no network"),
    )
    (home / ".local" / "bin" / "claude").unlink()
    failing._work(None)
    assert failing.task.state == "failed" and failing.task.error == "no network"


def test_codex_installs_with_its_own_script_and_without_questions(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ca, "can_install", lambda cli: True)
    seen: dict[str, Any] = {}

    def fetch(url: str) -> str:
        seen["url"] = url
        return "#!/bin/sh\n"

    def run(cmd: list[str], env: dict[str, str], timeout: float) -> subprocess.CompletedProcess[str]:
        seen["shell"], seen["quiet"], seen["home"] = cmd[0], env.get("CODEX_NON_INTERACTIVE"), env["HOME"]
        _program(home, "codex")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    installer = ca.Installer("codex", fetch=fetch, run=run)
    installer._work(None)
    assert installer.task.state == "done"
    assert seen == {
        "url": "https://chatgpt.com/codex/install.sh",
        "shell": "sh",
        "quiet": "1",
        "home": str(home),
    }


DEVICE_OUTPUT = """
Welcome to Codex [v\x1b[90m0.169.0\x1b[0m]

Follow these steps to sign in with ChatGPT using device code authorization:

1. Open this link in your browser and sign in to your account
   \x1b[94mhttps://auth.openai.com/codex/device\x1b[0m

2. Enter this one-time code \x1b[90m(expires in 15 minutes)\x1b[0m
   \x1b[94mFQ9C-SNGC4\x1b[0m
"""


def test_the_device_code_and_link_are_read_from_codex() -> None:
    text = ca.clean_terminal(DEVICE_OUTPUT.encode())
    assert ca.sign_in_link(text, "codex") == "https://auth.openai.com/codex/device"
    assert ca.device_code(text) == "FQ9C-SNGC4"
    assert ca.sign_in_link("open https://auth.openai.com.evil.example/device", "codex") is None
    assert ca.sign_in_link(text, "claude") is None  # each program's own vendor only
    assert ca.device_code("Welcome to Codex, version 0.169.0") is None


@pytest.mark.skipif(not hasattr(__import__("os"), "fork"), reason="needs a POSIX shell")
def test_a_codex_sign_in_shows_the_code_and_ends_by_itself(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a stand-in program: prints what Codex prints, waits for the "sign-in", then says it is signed in
    folder = home / ".local" / "bin"
    folder.mkdir(parents=True)
    gate, marker = home / "gate", home / "signed-in"
    (folder / "codex").write_text(
        "#!/bin/sh\n"
        f'if [ "$1 $2" = "login status" ]; then [ -f {marker} ] && echo "Logged in using ChatGPT" && exit 0; '
        'echo "Not logged in"; exit 1; fi\n'
        'echo "1. Open this link"; echo "   https://auth.openai.com/codex/device"\n'
        'echo "2. Enter this one-time code"; echo "   ABCD-12345"\n'
        f"while [ ! -f {gate} ]; do sleep 0.05; done\n"
        f"touch {marker}\n"
    )
    (folder / "codex").chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}:/usr/bin:/bin")
    changed: list[bool] = []
    login = ca.Login("codex", on_change=lambda: changed.append(True))
    login.start()
    _wait(lambda: login.task.state == "waiting_device")
    assert (login.task.url, login.task.code) == ("https://auth.openai.com/codex/device", "ABCD-12345")
    assert login.submit("anything").state == "waiting_device"  # no code is typed into Codex
    gate.touch()  # the learner entered the code on the vendor's page
    _wait(lambda: login.task.state == "done")
    assert changed == [True]


def _wait(done: Any, seconds: float = 10.0) -> None:
    import time

    end = time.monotonic() + seconds
    while not done():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.02)


def test_the_manual_codex_sign_in_fits_the_machine(home: Path) -> None:
    assert ca.CliAccess(container=True).view("codex")["login_command"] == "codex login --device-auth"
    assert ca.CliAccess(container=False).view("codex")["login_command"] == "codex login"
    assert ca.CliAccess(container=True).view("claude")["login_command"] == "claude auth login"
