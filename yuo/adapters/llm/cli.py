"""Subscription CLI adapters: Claude Code and Codex.

Every call runs in an empty temporary directory, with a minimal environment (no API keys, so the CLI
uses the learner's own subscription login), with tools and project settings off. Yuo never reads or
writes the CLI's credentials. One call at a time per CLI (a process lock, plus an optional lock file
shared with other programs on the machine). Quota and extra-usage answers become `LLMError(kind="quota")`.

Plan meter: both CLIs report how much of the account's 5-hour window and week is used (Claude Code's
`rate_limit_event` in stream-json; Codex's `rate_limits` in its token-count events). Each reading goes to
`on_meter` as `{"window_pct", "week_pct", "window_resets_at", "week_resets_at", "limited"}`. The meter covers
the whole account, other devices included.
"""

import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from yuo.adapters import cli_access
from yuo.core.llm import Completion, LLMError, Request, Usage

_QUOTA = re.compile(r"usage limit|rate limit|quota|limit reached|extra usage|out of credits", re.IGNORECASE)

type Runner = Callable[[list[str], Path, dict[str, str], float, str], subprocess.CompletedProcess[str]]
type Meter = dict[str, Any]


def _iso(epoch: float | None) -> str | None:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds") if epoch else None


def claude_meter(info: dict[str, Any]) -> Meter | None:
    """Claude Code's `rate_limit_info`: utilization 0..1 per unified window, reset times in epoch seconds."""
    windows = info.get("unifiedWindows") or {}
    five, week = windows.get("five_hour") or {}, windows.get("seven_day") or {}
    if not five and not week:
        return None

    def pct(w: dict[str, Any]) -> float | None:
        u = w.get("utilization")
        return round(float(u) * 100, 1) if u is not None else None

    return {
        "window_pct": pct(five),
        "week_pct": pct(week),
        "window_resets_at": _iso(five.get("resetsAt")),
        "week_resets_at": _iso(week.get("resetsAt")),
        "limited": info.get("status") not in (None, "allowed", "allowed_warning"),
    }


def codex_meter(event: Any) -> Meter | None:
    """Codex's `rate_limits` (primary: the 5-hour window, secondary: the week), wherever it sits in an event.
    The shape comes from tools that read Codex's session files; not verified against a real Codex run here."""
    found: dict[str, Any] | None = None

    def walk(x: Any) -> None:
        nonlocal found
        if isinstance(x, dict):
            if isinstance(x.get("rate_limits"), dict):
                found = x["rate_limits"]
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(event)
    if not found:
        return None
    meter: Meter = {"window_pct": None, "week_pct": None, "window_resets_at": None, "week_resets_at": None,
                    "limited": False}  # fmt: skip
    for w in (found.get("primary"), found.get("secondary")):
        if not isinstance(w, dict):
            continue
        used = w.get("used_percent", w.get("usedPercent"))
        minutes = w.get("window_minutes", w.get("windowMinutes")) or 0
        resets = w.get("resets_at") or (
            time.time() + float(w["resets_in_seconds"]) if w.get("resets_in_seconds") is not None else None
        )
        slot = "window" if minutes and minutes <= 12 * 60 else "week"
        meter[f"{slot}_pct"] = round(float(used), 1) if used is not None else None
        meter[f"{slot}_resets_at"] = _iso(float(resets)) if isinstance(resets, (int, float)) else resets
        meter["limited"] = meter["limited"] or (used is not None and float(used) >= 100)
    return meter


def _run(
    cmd: list[str], cwd: Path, env: dict[str, str], timeout: float, stdin: str
) -> subprocess.CompletedProcess[str]:
    # argument list, no shell; the prompt goes on stdin (one argv element is capped at 128 KB on Linux, and a
    # video repair prompt with the lesson and the module ran past it)
    return subprocess.run(  # noqa: S603
        cmd,
        cwd=cwd,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def clean_env() -> dict[str, str]:
    """The environment a subscription CLI runs in (never Yuo's secrets), with the CLI home as HOME."""
    return cli_access.cli_env()


@contextlib.contextmanager
def _file_lock(path: str | None) -> Iterator[None]:
    if not path or sys.platform == "win32":
        yield
        return
    import fcntl

    with Path(path).open("a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _prompt(request: Request) -> str:
    return "\n\n".join(m.content for m in request.messages)


def _images(request: Request) -> dict[str, bytes]:
    """The images of a request as files in the CLI's empty working directory (the CLI takes no image argument)."""
    paths = [p for m in request.messages for p in m.images]
    return {
        f"img_{i:02d}{Path(p).suffix.lower() or '.jpg'}": Path(p).read_bytes() for i, p in enumerate(paths)
    }


class _CLIAdapter:
    executable: str
    version = "1"
    remote = True

    def __init__(
        self, *, runner: Runner = _run, lock_file: str | None = None, binary: str | None = None
    ) -> None:
        self._runner = runner
        self._lock = threading.Lock()
        self._lock_file = lock_file or os.environ.get("YUO_CLI_LOCK")
        self._binary = binary
        self.on_meter: Callable[[Meter], None] | None = None

    def _report(self, meter: Meter | None) -> None:
        if meter is not None and self.on_meter is not None:
            with contextlib.suppress(Exception):  # the meter is a courtesy: never fail a lesson over it
                self.on_meter(meter)

    @property
    def binary(self) -> str:
        """The program to run: found again on every call, so one installed while Yuo runs is picked up."""
        return self._binary or cli_access.find(self.executable) or self.executable

    def available(self) -> bool:
        return self._binary is not None or cli_access.find(self.executable) is not None

    def _call(
        self, cmd: list[str], prompt: str, timeout: float, files: dict[str, str | bytes] | None = None
    ) -> tuple[str, dict[str, str]]:
        with self._lock, _file_lock(self._lock_file), tempfile.TemporaryDirectory(prefix="yuo-cli-") as d:
            cwd = Path(d)
            for name, body in (files or {}).items():
                if isinstance(body, bytes):
                    (cwd / name).write_bytes(body)
                else:
                    (cwd / name).write_text(body, encoding="utf-8")
            try:
                p = self._runner(cmd, cwd, clean_env(), timeout, prompt)
            except subprocess.TimeoutExpired as e:
                raise LLMError(
                    f"{self.name}: timed out after {timeout:.0f}s", retryable=True, kind="timeout"
                ) from e
            except FileNotFoundError as e:
                raise LLMError(f"{self.name}: `{self.executable}` is not installed", kind="auth") from e
            out = p.stdout
            extra = {
                name: (cwd / name).read_text(encoding="utf-8")
                for name in ("last.txt",)
                if (cwd / name).exists()
            }
        if p.returncode != 0 and not out.strip():
            tail = (p.stderr or "")[-400:]
            kind = "quota" if _QUOTA.search(tail) else "transport"
            raise LLMError(
                f"{self.name}: exit {p.returncode}: {tail}", retryable=kind == "transport", kind=kind
            )
        return out, extra

    name: str


class ClaudeCLIAdapter(_CLIAdapter):
    """`claude -p` with isolation flags. Never `--bare` (it ignores the subscription login)."""

    name = "claude-cli"
    executable = "claude"

    def generate(self, request: Request) -> Completion:
        images = _images(request)
        prompt = _prompt(request)
        tools = [""]
        if images:
            # only the Read tool, and only for the copied images (a path rule, not Read everywhere)
            prompt = (
                "First look at these image files in the current directory with the Read tool, in order: "
                + ", ".join(images)
                + ".\n\n"
                + prompt
            )
            tools = ["Read", "--allowedTools", "Read(./img_*)"]
        cmd = [
            self.binary,
            "-p",  # the prompt is read from stdin
            "--model",
            request.model,
            "--output-format",
            "stream-json",
            "--verbose",  # stream-json in print mode needs it; the events carry the plan meter
            "--no-session-persistence",
            "--setting-sources",
            "",
            "--strict-mcp-config",
            "--tools",
            *tools,
        ]
        if request.json_schema is not None:
            cmd += ["--json-schema", json.dumps(request.json_schema)]
        start = time.monotonic()
        out, _ = self._call(cmd, prompt, request.timeout_s, dict(images))
        events = []
        for line in out.splitlines():
            if line.strip().startswith("{"):
                with contextlib.suppress(json.JSONDecodeError):
                    events.append(json.loads(line))
        results = [e for e in events if e.get("type", "result") == "result"]
        if not results:
            raise LLMError(f"claude-cli: no result: {out[-300:]}", retryable=True, kind="transport")
        raw: dict[str, Any] = results[-1]
        for ev in events:
            if ev.get("type") == "rate_limit_event":
                self._report(claude_meter(ev.get("rate_limit_info") or {}))
        result = str(raw.get("result") or "")
        if raw.get("is_error"):
            kind = "quota" if _QUOTA.search(result) else "error"
            raise LLMError(f"claude-cli: {result[:300]}", retryable=False, kind=kind)
        u = raw.get("usage") or {}
        tokens_in = sum(
            int(u.get(k) or 0)
            for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        )
        notional = round(float(raw.get("total_cost_usd") or 0.0) * 1_000_000)
        parsed = raw.get("structured_output")
        text = json.dumps(parsed) if parsed is not None else result
        models = list((raw.get("modelUsage") or {}).keys())
        return Completion(
            text=text,
            raw=raw,
            usage=Usage(tokens_in, int(u.get("output_tokens") or 0), 0, notional, notional=True),
            model_resolved=models[0] if models else request.model,
            provider="anthropic-subscription",
            finish=str(raw.get("subtype") or ""),
            parsed=parsed,
            latency_s=time.monotonic() - start,
        )


class CodexCLIAdapter(_CLIAdapter):
    """`codex exec`, read-only sandbox, no git checks; the final message is written to a file.

    Verified on Windows with a real ChatGPT account.
    """

    name = "codex-cli"
    executable = "codex"

    def generate(self, request: Request) -> Completion:
        cmd = [
            self.binary,
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--json",
            "--output-last-message",
            "last.txt",
            "-m",
            request.model,
        ]
        files: dict[str, str | bytes] = {}
        if request.json_schema is not None:
            files["schema.json"] = json.dumps(request.json_schema)
            cmd += ["--output-schema", "schema.json"]
        cmd.append("-")  # the prompt is read from stdin
        start = time.monotonic()
        out, extra = self._call(cmd, _prompt(request), request.timeout_s, files)
        events = [json.loads(line) for line in out.splitlines() if line.strip().startswith("{")]
        text = extra.get("last.txt", "")
        tokens_in = tokens_out = reasoning = 0
        meter = None
        for ev in events:
            meter = codex_meter(ev) or meter
            usage = ev.get("usage") or (ev.get("msg") or {}).get("info", {}).get("total_token_usage") or {}
            if usage:
                tokens_in = int(usage.get("input_tokens") or tokens_in)
                tokens_out = int(usage.get("output_tokens") or tokens_out)
                reasoning = int(usage.get("reasoning_output_tokens") or reasoning)
            if ev.get("type") == "error" or (ev.get("msg") or {}).get("type") == "error":
                msg = json.dumps(ev)[:300]
                raise LLMError(f"codex-cli: {msg}", kind="quota" if _QUOTA.search(msg) else "error")
        self._report(meter)
        if not text:
            raise LLMError("codex-cli: no final message", retryable=True, kind="transport")
        return Completion(
            text=text,
            raw={"events": events, "last": text},
            usage=Usage(tokens_in, tokens_out, reasoning, 0, notional=True),
            model_resolved=request.model,
            provider="openai-subscription",
            finish="stop",
            latency_s=time.monotonic() - start,
        )
