"""Tailscale Serve: `https://<machine>.<tailnet>.ts.net` in front of the app, inside the tailnet only."""

import json
import shutil
import subprocess

from yuo.core.errors import YuoError


class TailscaleError(YuoError):
    pass


def _run(binary: str, *args: str) -> str:
    try:
        p = subprocess.run(  # noqa: S603 (fixed args)
            [binary, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise TailscaleError(f"could not run tailscale: {e}") from e
    if p.returncode != 0:
        raise TailscaleError((p.stderr or p.stdout).strip()[-500:] or f"tailscale exited with {p.returncode}")
    return p.stdout


def origin(binary: str = "tailscale") -> str:
    """The machine's tailnet HTTPS name, from `tailscale status --json`."""
    status = json.loads(_run(binary, "status", "--json"))
    if status.get("BackendState") != "Running":
        raise TailscaleError("tailscale is not connected: run `tailscale up` and sign in first")
    name = str(status.get("Self", {}).get("DNSName", "")).rstrip(".")
    if not name:
        raise TailscaleError("tailscale has no DNS name for this machine (MagicDNS and HTTPS must be on)")
    return f"https://{name}"


def serve(port: int, binary: str = "tailscale") -> str:
    """Serve the app on the tailnet in the background (kept across restarts by tailscaled). Returns the origin."""
    if shutil.which(binary) is None:
        raise TailscaleError("tailscale is not installed (https://tailscale.com/download)")
    url = origin(binary)
    _run(binary, "serve", "--bg", "--https=443", f"http://127.0.0.1:{port}")
    return url
