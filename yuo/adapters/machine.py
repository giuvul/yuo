"""Machine probe and benchmark: fills `yuo.setup.probe.Probe`.

Everything runs locally and sends nothing out: the OS, CPU, memory, GPU memory, free disk, the
subscription CLIs on PATH, model servers listening on loopback, and a short CPU timing.
"""

import ctypes
import os
import platform
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from yuo.adapters import cli_access
from yuo.setup.probe import Bench, Gpu, LocalServer, Probe

Run = Callable[[list[str]], str | None]

# Model servers that speak the OpenAI chat API on this machine. Loopback only: the probe never
# scans the network.
LOCAL_SERVERS: tuple[tuple[str, str, str], ...] = (
    ("ollama", "http://127.0.0.1:11434", "/api/tags"),
    ("lm-studio", "http://127.0.0.1:1234", "/v1/models"),
    ("llama.cpp", "http://127.0.0.1:8080", "/v1/models"),
)


def _run(cmd: list[str]) -> str | None:
    try:
        p = subprocess.run(  # noqa: S603 (fixed tools)
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, check=False
        )
    except OSError, subprocess.SubprocessError:
        return None
    return p.stdout if p.returncode == 0 else None


def _os() -> str:
    return {"Windows": "windows", "Darwin": "macos"}.get(platform.system(), "linux")


def _arch() -> str:
    m = platform.machine().lower()
    return {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(m, m)


def _gb(n: float) -> float:
    return round(n / 1024**3, 1)


def memory_bytes(os_name: str, run: Run = _run) -> int | None:
    if os_name == "linux":
        try:
            text = Path("/proc/meminfo").read_text(encoding="utf-8")
        except OSError:
            return None
        m = re.search(r"^MemTotal:\s+(\d+) kB", text, re.M)
        return int(m[1]) * 1024 if m else None
    if os_name == "macos":
        out = run(["sysctl", "-n", "hw.memsize"])
        return int(out) if out and out.strip().isdigit() else None
    if os_name == "windows":

        class Status(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        s = Status()
        s.dwLength = ctypes.sizeof(Status)
        windll = getattr(ctypes, "windll", None)
        if windll and windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):
            return int(s.ullTotalPhys)
    return None


def cpu_name(os_name: str, run: Run = _run) -> str | None:
    if os_name == "linux":
        try:
            m = re.search(r"^model name\s*:\s*(.+)$", Path("/proc/cpuinfo").read_text(encoding="utf-8"), re.M)
        except OSError:
            return None
        return m[1].strip() if m else None
    if os_name == "macos":
        out = run(["sysctl", "-n", "machdep.cpu.brand_string"])
        return out.strip() if out else None
    return platform.processor() or None


def gpus(os_name: str, arch: str, memory: int | None, run: Run = _run) -> list[Gpu]:
    found: list[Gpu] = []
    if shutil.which("nvidia-smi"):
        out = run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
        for line in (out or "").splitlines():
            name, _, mib = line.rpartition(",")
            if name.strip():
                mem = float(mib) / 1024 if mib.strip().replace(".", "").isdigit() else None
                found.append(Gpu(name.strip(), round(mem, 1) if mem else None, "nvidia"))
    if os_name == "linux":  # AMD reports its VRAM in sysfs
        for card in sorted(Path("/sys/class/drm").glob("card[0-9]*/device/mem_info_vram_total")):
            try:
                found.append(Gpu(card.parent.parent.name, _gb(int(card.read_text())), "amd"))
            except OSError, ValueError:
                continue
    if os_name == "macos" and arch == "arm64":
        found.append(Gpu("Apple silicon", _gb(memory) if memory else None, "apple"))
    return found


def clis(run: Run = _run) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name in ("claude", "codex"):
        if path := cli_access.find(name):
            version = run([path, "--version"])
            out[name] = version.strip().splitlines()[0][:80] if version else None
    return out


def servers(get: Callable[[str], Any] | None = None) -> list[LocalServer]:
    def fetch(url: str) -> Any:
        r = httpx.get(url, timeout=0.5)
        r.raise_for_status()
        return r.json()

    get = get or fetch
    found: list[LocalServer] = []
    for name, base, listing in LOCAL_SERVERS:
        try:
            data = get(base + listing)
        except Exception:  # noqa: S112 (nothing listening, or not this server)
            continue
        models = (
            [m["name"] for m in data.get("models", [])]
            if name == "ollama"
            else [m["id"] for m in data.get("data", [])]
        )
        found.append(LocalServer(name, base + "/v1", sorted(models)))
    return found


def cpu_benchmark(seconds: float = 1.5) -> Bench:
    """Float32 matrix multiplies for about `seconds`: the work voice synthesis does (ONNX on the CPU)."""
    import numpy as np

    n = 512
    a = np.random.default_rng(0).random((n, n), dtype=np.float32)
    flops, start = 0.0, time.perf_counter()
    while (elapsed := time.perf_counter() - start) < seconds:
        a @ a
        flops += 2 * n**3
    return Bench(round(flops / elapsed / 1e9, 1), round(elapsed, 2))


def probe(
    data_dir: Path, *, run: Run = _run, bench: bool = True, http: Callable[[str], Any] | None = None
) -> Probe:
    os_name, arch = _os(), _arch()
    mem = memory_bytes(os_name, run)
    try:
        free = _gb(shutil.disk_usage(data_dir if data_dir.exists() else data_dir.anchor or "/").free)
    except OSError:
        free = None
    return Probe(
        os=os_name,
        os_version=platform.release(),
        arch=arch,
        cpu=cpu_name(os_name, run),
        cores=os.cpu_count(),
        memory_gb=_gb(mem) if mem else None,
        gpus=gpus(os_name, arch, mem, run),
        disk_free_gb=free,
        clis=clis(run),
        servers=servers(http),
        bench=cpu_benchmark() if bench else Bench(),
    )
