"""Subscription CLIs (Claude Code, Codex): is the program installed, is it signed in, and help with both.

A learner who picks "Claude subscription" or "ChatGPT subscription" needs the vendor's command-line program on
the machine that runs Yuo, signed in to their account. Yuo checks both before it starts any generation, so a
missing sign-in is a clear step in the app and never a failed lesson.

- `status(cli)`: found on this machine? which version? signed in? (asked from the program itself, no model call)
- `Installer`: runs the vendor's own installer where that is possible (a POSIX system with a shell and curl
  or wget; the program lands in the CLI home, `~/.local/bin`). Elsewhere the app shows the command.
- `Login`: the program's sign-in driven from the browser.
  Claude Code prints a sign-in link and waits for a code; Yuo shows the link, the learner signs in at the
  vendor and pastes the code back. Needs a pseudo-terminal (POSIX). On Windows the program opens the browser
  itself and Yuo waits for the sign-in.
  Codex signs in by device code on every system: it prints the vendor's link and a one-time code; Yuo shows
  both, the learner enters the code on the vendor's page, and the program finishes by itself.

The CLI home (`YUO_CLI_HOME`, default the user's home) is where the programs keep their sign-in. In the server
image it is inside the data volume, so a sign-in survives an update of the container.
"""

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import structlog

log = structlog.get_logger(__name__)

Cli = Literal["claude", "codex"]
CLIS: tuple[Cli, ...] = ("claude", "codex")
NAMES = {"claude": "Claude Code", "codex": "Codex"}


@dataclass(frozen=True, slots=True)
class InstallScript:
    """A vendor's own installer: where it is, the shell it is written for, and how it is told not to ask."""

    url: str
    shell: str
    env: tuple[tuple[str, str], ...] = ()
    needs: tuple[tuple[str, ...], ...] = ()  # each group: one of these programs must exist


INSTALLERS: dict[str, InstallScript] = {
    "claude": InstallScript("https://claude.ai/install.sh", "bash"),
    "codex": InstallScript(
        "https://chatgpt.com/codex/install.sh",
        "sh",
        env=(("CODEX_NON_INTERACTIVE", "1"),),
        needs=(("tar",), ("sha256sum", "shasum", "openssl")),
    ),
}
# what the app shows when it cannot do the step itself (the vendors' documented commands)
INSTALL_COMMANDS: dict[str, dict[str, str]] = {
    "claude": {
        "windows": "irm https://claude.ai/install.ps1 | iex",
        "macos": "curl -fsSL https://claude.ai/install.sh | bash",
        "linux": "curl -fsSL https://claude.ai/install.sh | bash",
    },
    "codex": {
        "windows": "irm https://chatgpt.com/codex/install.ps1 | iex",
        "macos": "curl -fsSL https://chatgpt.com/codex/install.sh | sh",
        "linux": "curl -fsSL https://chatgpt.com/codex/install.sh | sh",
    },
}
LOGIN_COMMANDS = {"claude": "claude auth login", "codex": "codex login"}
# with no browser on the machine (a server, a container) Codex signs in by device code
HEADLESS_LOGIN_COMMANDS = {"codex": "codex login --device-auth"}
LOGIN_ARGS = {"claude": ["auth", "login"], "codex": ["login", "--device-auth"]}
# the only hosts a sign-in link may point to
LOGIN_HOSTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "claude": (
        ("claude.com", "claude.ai", "console.anthropic.com", "platform.claude.com"),
        (".claude.com", ".claude.ai", ".anthropic.com"),
    ),
    "codex": (("auth.openai.com", "chatgpt.com", "openai.com"), (".openai.com", ".chatgpt.com")),
}
DOCS = {
    "claude": "https://docs.claude.com/en/docs/claude-code/setup",
    "codex": "https://developers.openai.com/codex/cli",
}
OK_TTL_S = 600.0  # a signed-in answer is trusted this long
BAD_TTL_S = 4.0  # a missing program or sign-in is asked again almost at once ("Check again")
LOGIN_TIMEOUT_S = 900.0
INSTALL_TIMEOUT_S = 600.0
_ANSI = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-_]")
_URL = re.compile(r"https://[^\s\x1b\x07\"'<>]+")
_DEVICE_CODE = re.compile(r"(?<![A-Z0-9-])[A-Z0-9]{4,5}-[A-Z0-9]{4,6}(?![A-Z0-9-])")

# what a CLI may inherit from Yuo's own environment (never Yuo's secrets)
PASS_ENV = (
    "HOME",
    "PATH",
    "LANG",
    "LC_ALL",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "XDG_CONFIG_HOME",
)

Run = Callable[[list[str], dict[str, str], float], "subprocess.CompletedProcess[str]"]


def cli_home() -> Path:
    return Path(os.environ.get("YUO_CLI_HOME") or Path.home())


def cli_env() -> dict[str, str]:
    """The environment a subscription CLI runs in: the usual variables, with the CLI home as HOME."""
    env = {k: v for k, v in os.environ.items() if k in PASS_ENV}
    if os.environ.get("YUO_CLI_HOME"):
        home = cli_home()
        home.mkdir(parents=True, exist_ok=True)
        env["HOME"] = str(home)
        if sys.platform == "win32":
            env["USERPROFILE"] = str(home)
    env["PATH"] = os.pathsep.join([str(cli_home() / ".local" / "bin"), env.get("PATH", os.defpath)])
    return env


def find(cli: str) -> str | None:
    """The program's path: on PATH, or where the vendors' installers put it under the CLI home."""
    if path := shutil.which(cli):
        return path
    names = [f"{cli}.exe", f"{cli}.cmd", cli] if sys.platform == "win32" else [cli]
    for folder in (
        cli_home() / ".local" / "bin",
        cli_home() / ".claude" / "local",
        cli_home() / ".npm-global" / "bin",
    ):
        for name in names:
            if (folder / name).is_file():
                return str(folder / name)
    return None


def _run(cmd: list[str], env: dict[str, str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  (argument list, no shell)
        cmd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        stdin=subprocess.DEVNULL,
    )


@dataclass(frozen=True, slots=True)
class Status:
    cli: str
    installed: bool
    version: str | None = None
    logged_in: bool | None = None  # None: installed, but the program did not say
    account: str | None = None  # the plan or sign-in method, never an address
    detail: str | None = None

    @property
    def ready(self) -> bool:
        return self.installed and self.logged_in is not False

    @property
    def reason(self) -> str | None:
        if not self.installed:
            return "not_installed"
        return "not_logged_in" if self.logged_in is False else None


def status(cli: str, run: Run = _run) -> Status:
    path = find(cli)
    if path is None:
        return Status(cli, installed=False)
    env = cli_env()
    version = None
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        out = run([path, "--version"], env, 20).stdout.strip().splitlines()
        version = out[0][:80] if out else None
    try:
        if cli == "claude":
            p = run([path, "auth", "status"], env, 30)
            data = json.loads(p.stdout[p.stdout.index("{") :]) if "{" in p.stdout else {}
            if "loggedIn" not in data:
                return Status(cli, True, version, None, detail=(p.stderr or p.stdout).strip()[-200:] or None)
            account = data.get("subscriptionType") or data.get("authMethod")
            return Status(cli, True, version, bool(data["loggedIn"]), str(account) if account else None)
        p = run([path, "login", "status"], env, 30)
        text = (p.stdout + p.stderr).strip()
        logged_in = p.returncode == 0 and "not logged in" not in text.lower()
        how = re.search(r"logged in (?:using|with) (an? )?([A-Za-z ]{2,30})", text, re.IGNORECASE)
        account = how.group(2).strip() if logged_in and how else None
        return Status(cli, True, version, logged_in, account, None if logged_in else text[-200:] or None)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return Status(cli, True, version, None, detail=str(e)[-200:])


class StatusCache:
    """Asking a CLI costs a second and a process: a good answer is kept for a while, a bad one briefly."""

    def __init__(self, ask: Callable[[str], Status] = status) -> None:
        self._ask = ask
        self._lock = threading.Lock()
        self._seen: dict[str, tuple[float, Status]] = {}

    def get(self, cli: str, *, fresh: bool = False) -> Status:
        with self._lock:
            hit = self._seen.get(cli)
            # only a confirmed sign-in is kept long: an unclear answer (a first run right after installing can
            # be slow) is asked again soon, so the card moves on to the sign-in by itself
            if (
                hit
                and not fresh
                and time.monotonic() - hit[0] < (OK_TTL_S if hit[1].logged_in is True else BAD_TTL_S)
            ):
                return hit[1]
        s = self._ask(cli)
        with self._lock:
            self._seen[cli] = (time.monotonic(), s)
        return s

    def forget(self, cli: str) -> None:
        with self._lock:
            self._seen.pop(cli, None)


# --- installing a CLI --------------------------------------------------------------------------------


def can_install(cli: str) -> bool:
    """Yuo can run the vendor's installer itself: a POSIX system with the script's shell and a downloader."""
    script = INSTALLERS.get(cli)
    return (
        script is not None
        and sys.platform != "win32"
        and shutil.which(script.shell) is not None
        and (shutil.which("curl") is not None or shutil.which("wget") is not None)
        and all(any(shutil.which(tool) for tool in group) for group in script.needs)
    )


def _fetch_installer(url: str) -> str:
    import httpx

    r = httpx.get(url, timeout=30, follow_redirects=True)
    r.raise_for_status()
    if not r.text.lstrip().startswith("#!"):
        raise RuntimeError("the installer did not download as a script")
    return r.text


@dataclass
class Task:
    """A step Yuo runs for the learner, polled by the app."""

    state: str = "idle"  # idle | running | waiting_code | waiting_browser | waiting_device | done | failed
    url: str | None = None
    code: str | None = None  # waiting_device: the one-time code the learner enters on the vendor's page
    error: str | None = None
    started: float = field(default_factory=time.monotonic)

    def view(self) -> dict[str, Any]:
        d = asdict(self)
        del d["started"]
        return d


class Installer:
    def __init__(
        self, cli: str = "claude", fetch: Callable[[str], str] = _fetch_installer, run: Run = _run
    ) -> None:
        self.cli = cli
        self._fetch, self._run = fetch, run
        self._lock = threading.Lock()
        self.task = Task()

    def start(self, done: Callable[[], None] | None = None) -> Task:
        with self._lock:
            if self.task.state == "running":
                return self.task
            if not can_install(self.cli):
                self.task = Task(
                    "failed", error="this system cannot run the installer; use the command shown"
                )
                return self.task
            self.task = Task("running")
        threading.Thread(target=self._work, args=(done,), name="yuo-cli-install", daemon=True).start()
        return self.task

    def _work(self, done: Callable[[], None] | None) -> None:
        try:
            spec = INSTALLERS[self.cli]
            script = self._fetch(spec.url)
            with tempfile.TemporaryDirectory(prefix="yuo-cli-install-") as d:
                path = Path(d) / "install.sh"
                path.write_text(script, encoding="utf-8")
                p = self._run([spec.shell, str(path)], cli_env() | dict(spec.env), INSTALL_TIMEOUT_S)
            if p.returncode != 0 or find(self.cli) is None:
                tail = (p.stderr or p.stdout).strip()[-300:]
                self.task = Task("failed", error=tail or f"the installer ended with code {p.returncode}")
            else:
                self.task = Task("done")
        except Exception as e:  # shown to the learner, with the manual command beside it
            log.warning("cli.install_failed", error=str(e)[:300], exc_info=True)
            self.task = Task("failed", error=str(e)[-300:])
        if done:
            done()


# --- signing in from the browser ---------------------------------------------------------------------


def clean_terminal(raw: bytes) -> str:
    """Terminal output as plain text (colour codes and hyperlink wrappers removed)."""
    return _ANSI.sub("", raw.decode("utf-8", "replace")).replace("\r", "\n")


def sign_in_link(text: str, cli: str = "claude") -> str | None:
    """The sign-in address a CLI printed: the vendor's own, never anything else."""
    exact, suffixes = LOGIN_HOSTS[cli]
    for url in _URL.findall(text):
        host = url.split("/", 3)[2].lower()
        if host in exact or host.endswith(suffixes):
            return str(url).rstrip(".,)")
    return None


def device_code(text: str) -> str | None:
    """The one-time code of a device sign-in: the first code-shaped word after the sign-in link."""
    link = _URL.search(text)
    found = _DEVICE_CODE.search(text, link.end() if link else 0)
    return found.group(0) if found else None


class Login:
    """One sign-in to a CLI at a time.

    Claude Code: `start()` runs `claude auth login`; with a pseudo-terminal the link it prints is shown in
    the app and `submit(code)` types the code the vendor's page gives.
    Codex: `start()` runs `codex login --device-auth`; the link and the one-time code it prints are shown in
    the app, and the program ends by itself once the learner has entered the code on the vendor's page."""

    def __init__(self, cli: str = "claude", on_change: Callable[[], None] | None = None) -> None:
        self.cli = cli
        self._lock = threading.Lock()
        self._on_change = on_change
        self.task = Task()
        self._fd: int | None = None
        self._proc: Any = None
        self._pid: int | None = None

    def start(self) -> Task:
        with self._lock:
            if self.task.state in ("running", "waiting_code", "waiting_browser", "waiting_device"):
                if time.monotonic() - self.task.started < LOGIN_TIMEOUT_S:
                    return self.task
                self._stop()
            path = find(self.cli)
            if path is None:
                self.task = Task("failed", error=f"{NAMES[self.cli]} is not installed")
                return self.task
            self.task = Task("running")
            if self.cli == "codex":
                target = self._device
            else:
                target = self._windows if sys.platform == "win32" else self._posix
            threading.Thread(target=target, args=(path, self.task), name="yuo-cli-login", daemon=True).start()
            return self.task

    def _finish(self, task: Task, ok: bool, text: str) -> None:
        if self.task is not task:  # cancelled or replaced
            return
        if status(self.cli).logged_in is True:
            self.task = Task("done")
        else:
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            self.task = Task("failed", error=lines[-1][:300] if lines else "the sign-in did not finish")
        if self._on_change:
            self._on_change()

    def _posix(self, path: str, task: Task) -> None:
        import pty
        import select

        pid, fd = pty.fork()
        if pid == 0:  # the child: the CLI on its own terminal
            os.execve(path, [path, *LOGIN_ARGS[self.cli]], cli_env() | {"TERM": "dumb", "NO_COLOR": "1"})  # noqa: S606
        self._fd, self._pid = fd, pid
        raw = b""
        code = None
        try:
            while self.task is task and time.monotonic() - task.started < LOGIN_TIMEOUT_S:
                ready, _, _ = select.select([fd], [], [], 0.5)
                if ready:
                    try:
                        chunk = os.read(fd, 4096)
                    except OSError:
                        chunk = b""
                    if not chunk:
                        break
                    raw += chunk
                    if task.url is None and (url := sign_in_link(clean_terminal(raw))):
                        task.url, task.state = url, "waiting_code"
                done, code = os.waitpid(pid, os.WNOHANG)
                if done:
                    break
        finally:
            with contextlib.suppress(OSError):
                os.close(fd)
            self._fd = None
            if code is None:
                with contextlib.suppress(OSError, ChildProcessError):
                    os.kill(pid, 15)
                    os.waitpid(pid, 0)
            self._pid = None
        self._finish(task, code == 0, clean_terminal(raw))

    def _device(self, path: str, task: Task) -> None:
        # a device sign-in needs no terminal: the program prints a link and a code, then waits by itself
        try:
            proc = subprocess.Popen(  # noqa: S603
                [path, *LOGIN_ARGS[self.cli]],
                env=cli_env() | {"TERM": "dumb", "NO_COLOR": "1"},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except OSError as e:
            self.task = Task("failed", error=str(e)[:300])
            return
        self._proc = proc
        raw = bytearray()

        def read() -> None:
            out = proc.stdout
            while out is not None and (chunk := out.read1(4096)):  # type: ignore[attr-defined]
                raw.extend(chunk)
                text = clean_terminal(bytes(raw))
                if (
                    task.code is None
                    and (url := sign_in_link(text, self.cli))
                    and (code := device_code(text))
                ):
                    task.url, task.code, task.state = url, code, "waiting_device"

        reader = threading.Thread(target=read, name="yuo-cli-login-read", daemon=True)
        reader.start()
        try:
            proc.wait(timeout=LOGIN_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
        reader.join(timeout=5)
        self._proc = None
        self._finish(task, proc.returncode == 0, clean_terminal(bytes(raw)))

    def _windows(self, path: str, task: Task) -> None:
        # no pseudo-terminal here: the CLI opens the browser on this computer and finishes by itself
        try:
            proc = subprocess.Popen(  # noqa: S603
                [path, *LOGIN_ARGS[self.cli]],
                env=cli_env(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as e:
            self.task = Task("failed", error=str(e)[:300])
            return
        self._proc = proc
        task.state = "waiting_browser"
        try:
            out, _ = proc.communicate(timeout=LOGIN_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            out = ""
        self._proc = None
        self._finish(task, proc.returncode == 0, out or "")

    def submit(self, code: str) -> Task:
        code = code.strip()
        with self._lock:
            if self.task.state != "waiting_code" or self._fd is None:
                return self.task
            if not code or len(code) > 2000 or any(ch in code for ch in "\r\n\x1b\x03\x04"):
                self.task.error = "that does not look like a sign-in code"
                return self.task
            os.write(self._fd, code.encode() + b"\r")
            self.task.state, self.task.error = "running", None
            return self.task

    def _stop(self) -> None:
        if self._pid is not None:
            with contextlib.suppress(OSError):
                os.kill(self._pid, 15)
        if self._proc is not None:
            with contextlib.suppress(OSError):
                self._proc.kill()

    def cancel(self) -> Task:
        with self._lock:
            self._stop()
            self.task = Task()
            return self.task


# --- one object for the app ---------------------------------------------------------------------------


def os_name() -> str:
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


class CliAccess:
    """What the service needs: the state of each CLI, and the two helpers."""

    def __init__(self, *, container: bool | None = None) -> None:
        self.cache = StatusCache()
        self.installers: dict[str, Installer] = {cli: Installer(cli) for cli in CLIS}
        self.logins: dict[str, Login] = {cli: self._login(cli) for cli in CLIS}
        self.container = Path("/.dockerenv").exists() if container is None else container

    def _login(self, cli: str) -> Login:
        return Login(cli, on_change=lambda: self.cache.forget(cli))

    def found(self, cli: str) -> bool:
        return find(cli) is not None

    def status(self, cli: str, *, fresh: bool = False) -> Status:
        return self.cache.get(cli, fresh=fresh)

    def view(self, cli: str, *, fresh: bool = False) -> dict[str, Any]:
        s = self.status(cli, fresh=fresh)
        install = self.installers[cli].task.view()
        login = self.logins[cli].task.view()
        return {
            "cli": cli,
            "name": NAMES[cli],
            "installed": s.installed,
            "version": s.version,
            "logged_in": s.logged_in,
            "account": s.account,
            "ready": s.ready,
            "reason": s.reason,
            "detail": s.detail,
            "os": os_name(),
            "container": self.container,
            "can_install": can_install(cli),
            "can_login": True,
            "code_login": cli == "claude" and sys.platform != "win32",
            "install_command": INSTALL_COMMANDS[cli][os_name()],
            "login_command": (HEADLESS_LOGIN_COMMANDS if self.container else {}).get(
                cli, LOGIN_COMMANDS[cli]
            ),
            "docs_url": DOCS[cli],
            "install": install,
            "login": login,
        }

    def start_install(self, cli: str) -> None:
        self.installers[cli].start(done=lambda: self.cache.forget(cli))

    def start_login(self, cli: str) -> None:
        self.logins[cli].start()

    def submit_code(self, cli: str, code: str) -> None:
        self.logins[cli].submit(code)

    def cancel_login(self, cli: str) -> None:
        self.logins[cli].cancel()
