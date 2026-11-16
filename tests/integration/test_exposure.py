"""Exposure adapters: Tailscale Serve through a fake `tailscale`, the Caddyfile and sslip.io names."""

import json
from pathlib import Path

import pytest

from yuo.adapters.exposure import caddy, tailscale


def fake_tailscale(tmp_path: Path, state: str = "Running") -> str:
    status = {"BackendState": state, "Self": {"DNSName": "box.tail1234.ts.net."}}
    script = tmp_path / "tailscale"
    script.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> {tmp_path}/calls\n'
        f"if [ \"$1\" = status ]; then echo '{json.dumps(status)}'; fi\n"
    )
    script.chmod(0o755)
    return str(script)


def test_tailscale_serve_returns_the_tailnet_origin(tmp_path: Path) -> None:
    binary = fake_tailscale(tmp_path)
    assert tailscale.serve(18765, binary) == "https://box.tail1234.ts.net"
    assert "serve --bg --https=443 http://127.0.0.1:18765" in (tmp_path / "calls").read_text()


def test_tailscale_not_signed_in_says_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(tailscale.TailscaleError, match="tailscale up"):
        tailscale.serve(18765, fake_tailscale(tmp_path, "NeedsLogin"))


def test_sslip_names_and_the_caddyfile() -> None:
    assert caddy.sslip_host("93.90.203.32") == "yuo.93-90-203-32.sslip.io"
    assert caddy.sslip_host("2a01:4f8::1").endswith(".sslip.io")
    for bad in ("10.0.0.5", "127.0.0.1", "192.168.1.2"):
        with pytest.raises(ValueError):
            caddy.sslip_host(bad)
    text = caddy.caddyfile("yuo.93-90-203-32.sslip.io")
    assert "reverse_proxy yuo:18765" in text and "flush_interval -1" in text
    assert "lb_try_duration 30s" in text  # an update restart is waited out, not answered with 502
    with pytest.raises(ValueError):
        caddy.caddyfile("evil.example {\n}\n:80")


# --- can devices reach ports 80 and 443? (0.8.1) ---------------------------------------------------------

from yuo.adapters.exposure import reach  # noqa: E402


def _check(
    *,
    resolved: list[str],
    local: str | None,
    answers: set[tuple[str, int]] | None = None,
    fw: reach.Check | None = None,
    ip: str | None = None,
    system: str = "Linux",
) -> reach.Report:
    open_ = answers or set()
    return reach.check(
        "yuo.example.org",
        ip,
        resolve=lambda _h: resolved,
        source=lambda _t: local,
        connects=lambda a, p: (a, p) in open_,
        firewall=lambda: fw,
        system=system,
    )


def test_a_server_with_its_own_address_and_ufw_closed_gets_the_ufw_command() -> None:
    r = _check(
        resolved=["93.90.203.32"],
        local="93.90.203.32",
        answers={("127.0.0.1", 80), ("127.0.0.1", 443)},
        fw=reach.Check(False, "ufw is on and does not allow 80 and 443"),
    )
    assert r.situation == "direct" and r.problem
    text = r.text()
    assert "sudo ufw allow 80/tcp" in text and "security group" in text and "Port forwarding" not in text
    assert "93.90.203.32 does not answer on port 80 and 443" in text
    assert r.advice[-1].startswith(
        "Check from outside: on a phone with Wi-Fi off, open http://yuo.example.org"
    )


def test_a_server_behind_a_router_is_told_to_forward_the_ports_to_its_address() -> None:
    r = _check(resolved=["93.90.203.32"], local="192.168.1.20")
    assert r.situation == "nat"
    text = r.text()
    assert "forward TCP ports 80 and 443 on the router to 192.168.1.20" in text
    assert "carrier-grade NAT" in text and "yuo expose tailscale" in text


def test_carrier_grade_nat_means_tailscale() -> None:
    r = _check(resolved=["100.72.4.9"], local="100.72.4.9")
    assert r.situation == "cgnat" and r.problem
    assert "yuo expose tailscale" in r.advice[0] and len(r.advice) == 2


def test_a_name_that_points_elsewhere_or_nowhere_comes_first() -> None:
    r = _check(resolved=["203.0.113.9"], local="93.90.203.32", ip="93.90.203.32")
    assert "points at 203.0.113.9, not at 93.90.203.32" in r.checks[0].text and r.checks[0].ok is False
    assert r.advice[0].startswith("Point yuo.example.org at the server")
    r = _check(resolved=[], local=None)
    assert "does not resolve" in r.checks[0].text and r.advice[0].startswith("Point")


def test_windows_and_macos_get_their_own_firewall_steps() -> None:
    win = _check(resolved=["93.90.203.32"], local="93.90.203.32", system="Windows")
    assert "New-NetFirewallRule" in win.text() and "Windows firewall is not checked" in win.text()
    mac = _check(resolved=["93.90.203.32"], local="10.0.0.4", system="Darwin")
    assert "System Settings > Network > Firewall" in mac.text()


def test_reading_ufw_and_firewalld() -> None:
    def ufw(out: str, code: int = 0) -> reach.Check | None:
        return reach.host_firewall(lambda *a: (code, out) if a[0] == "ufw" else None, "Linux")

    assert ufw("Status: inactive") == reach.Check(True, "ufw is installed and off")
    on = (
        "Status: active\n\nTo Action From\n-- ------ ----\n22/tcp ALLOW Anywhere\n80,443/tcp ALLOW Anywhere\n"
    )
    assert ufw(on) == reach.Check(True, "ufw allows ports 80 and 443")
    assert ufw("Status: active\n22/tcp ALLOW Anywhere\n").ok is False  # type: ignore[union-attr]
    assert ufw("ERROR: You need to be root to run this script", 1).ok is None  # type: ignore[union-attr]

    def firewalld(listed: str) -> reach.Check | None:
        answers = {"--state": (0, "running"), "--list-all": (0, listed)}
        return reach.host_firewall(lambda *a: answers[a[1]] if a[0] == "firewall-cmd" else None, "Linux")

    assert firewalld("services: ssh http https").ok is True  # type: ignore[union-attr]
    assert firewalld("services: ssh").ok is False  # type: ignore[union-attr]
    assert reach.host_firewall(lambda *a: None, "Linux") is None


def test_a_firewall_found_open_is_not_sent_to_be_opened() -> None:
    r = _check(
        resolved=["93.90.203.32"], local="93.90.203.32", fw=reach.Check(True, "ufw allows ports 80 and 443")
    )
    assert "sudo ufw allow" not in r.text() and "security group" in r.text()


def test_nothing_in_the_way_reads_as_such() -> None:
    r = _check(
        resolved=["93.90.203.32"],
        local="93.90.203.32",
        answers={("127.0.0.1", 80), ("127.0.0.1", 443), ("93.90.203.32", 80), ("93.90.203.32", 443)},
        fw=reach.Check(True, "ufw allows ports 80 and 443"),
    )
    assert not r.problem and "Nothing found in the way. If a device still cannot connect:" in r.text()
