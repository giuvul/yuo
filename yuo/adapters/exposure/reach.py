"""Can other devices reach this server on ports 80 and 443? What Yuo can see from the server itself, and what to
do about each way it can fail (a closed port or a firewall must be found and explained on
the first setup, on any system).

A public name with Caddy needs both ports open from the internet: Let's Encrypt connects to them to issue the
certificate, and the devices use 443. Four things can stand in the way, and the server sees only some of them:

- the name does not point at the server (DNS): checked;
- a firewall on the server (ufw, firewalld, Windows Defender Firewall, the macOS firewall): looked up where the
  tool says so;
- a firewall in front of the server (a cloud provider's security group or firewall): invisible from inside;
- a router in front of the server: seen when the server's own address is private; ports must be forwarded, and
  behind carrier-grade NAT (CGNAT) forwarding cannot work, so Tailscale is the way.

No outside service is asked. A connection from the server to its own public address proves little (a router
may loop it back, a cloud firewall does not filter it), so the last step is always a check from outside: a
phone with Wi-Fi off.
"""

import ipaddress
import platform
import shutil
import socket
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

PORTS = (80, 443)
CGNAT = ipaddress.ip_network("100.64.0.0/10")

Situation = Literal["direct", "nat", "cgnat", "unknown"]


@dataclass
class Check:
    ok: bool | None  # None: could not tell
    text: str


@dataclass
class Report:
    host: str
    public: list[str]
    local: str | None
    situation: Situation
    checks: list[Check] = field(default_factory=list)
    advice: list[str] = field(default_factory=list)

    @property
    def problem(self) -> bool:
        return any(c.ok is False for c in self.checks)

    def text(self) -> str:
        mark = {True: "ok ", False: "NO ", None: " ? "}
        lines = [f"Reaching https://{self.host} from other devices", ""]
        lines += [f"  [{mark[c.ok]}] {c.text}" for c in self.checks]
        if self.advice:
            lines += [
                "",
                "What to do:"
                if self.problem
                else "Nothing found in the way. If a device still cannot connect:",
            ]
            lines += [f"  {n}. {a}" for n, a in enumerate(self.advice, start=1)]
        return "\n".join(lines)


def _resolve(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    return sorted({str(i[4][0]) for i in infos})


def _source_address(target: str) -> str | None:
    """The address this machine sends from towards `target` (a UDP connect sends nothing)."""
    family = socket.AF_INET6 if ":" in target else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as s:
            s.connect((target, 9))
            return str(s.getsockname()[0])
    except OSError:
        return None


def _connects(address: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((address, port), timeout=timeout):
            return True
    except OSError:
        return False


def _run(*args: str) -> tuple[int, str] | None:
    if shutil.which(args[0]) is None:
        return None
    try:
        p = subprocess.run(  # noqa: S603 (fixed args)
            list(args), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    return p.returncode, (p.stdout + p.stderr)


def host_firewall(
    run: Callable[..., tuple[int, str] | None] = _run, system: str | None = None
) -> Check | None:
    """The server's own firewall, where its tool answers. None when no known tool is there."""
    system = system or platform.system()
    if system != "Linux":
        return None
    if (ufw := run("ufw", "status")) is not None:
        code, out = ufw
        if code != 0 or "need to be root" in out.lower() or "permission" in out.lower():
            return Check(
                None, "ufw is installed, but its rules can only be read as root (sudo yuo expose check)"
            )
        if "status: inactive" in out.lower():
            return Check(True, "ufw is installed and off")
        allowed = [p for p in PORTS if _ufw_allows(out, p)]
        if len(allowed) == len(PORTS):
            return Check(True, "ufw allows ports 80 and 443")
        return Check(
            False, "ufw is on and does not allow " + " and ".join(str(p) for p in PORTS if p not in allowed)
        )
    if (state := run("firewall-cmd", "--state")) is not None:
        code, out = state
        if code != 0 or "not running" in out:
            return Check(True, "firewalld is installed and not running")
        listed = run("firewall-cmd", "--list-all")
        if listed is None or listed[0] != 0:
            return Check(
                None, "firewalld is running, but its rules can only be read as root (sudo yuo expose check)"
            )
        text = listed[1]
        ok = all(svc in text or f"{p}/tcp" in text for svc, p in (("http", 80), ("https", 443)))
        return Check(
            ok, "firewalld allows ports 80 and 443" if ok else "firewalld is on and does not allow 80 and 443"
        )
    return None


def _ufw_allows(status: str, port: int) -> bool:
    names = {80: ("80", "80/tcp", "http", "www", "caddy", "nginx full", "apache full"), 443: ("443", "443/tcp", "https", "www secure", "caddy", "nginx full", "apache full")}[port]  # fmt: skip
    for line in status.lower().splitlines():
        if "allow" in line and "(v6)" not in line:
            target = line.split("allow", 1)[0].strip()
            if target in names or any(target.startswith(f"{n} ") for n in names) or _in_range(target, port):
                return True
    return False


def _in_range(target: str, port: int) -> bool:
    spec = target.split("/", 1)[0]
    for part in spec.split(","):
        lo, _, hi = part.partition(":")
        if lo.isdigit() and int(lo) <= port <= int(hi or lo):
            return True
    return False


def check(
    host: str,
    ip: str | None = None,
    *,
    resolve: Callable[[str], list[str]] = _resolve,
    source: Callable[[str], str | None] = _source_address,
    connects: Callable[[str, int], bool] = _connects,
    firewall: Callable[[], Check | None] = host_firewall,
    system: str | None = None,
) -> Report:
    system = system or platform.system()
    checks: list[Check] = []
    try:
        resolved = resolve(host)
    except OSError:
        resolved = []
    if resolved:
        if ip and ip not in resolved:
            checks.append(Check(False, f"{host} points at {', '.join(resolved)}, not at {ip}"))
        else:
            checks.append(Check(True, f"{host} points at {', '.join(resolved)}"))
    else:
        checks.append(
            Check(False, f"{host} does not resolve (no DNS record yet, or this server has no internet)")
        )
    public = [ip] if ip else resolved
    target = public[0] if public else None
    local = source(target) if target else None

    situation: Situation = "unknown"
    if target and ipaddress.ip_address(target) in CGNAT:
        situation = "cgnat"
        checks.append(Check(False, f"{target} is a carrier-grade NAT address: no port can be opened to it"))
    elif target and not ipaddress.ip_address(target).is_global:
        checks.append(Check(False, f"{target} is not a public address"))
    elif local and target:
        situation = "direct" if local == target else "nat"
        if situation == "direct":
            checks.append(Check(True, f"this server holds the public address {target} itself"))
        else:
            checks.append(
                Check(
                    None, f"this server is at {local} behind a router or a cloud network that holds {target}"
                )
            )
    if local and ipaddress.ip_address(local) in CGNAT:
        situation = "cgnat"

    if (fw := firewall()) is not None:
        checks.append(fw)
    elif system == "Linux":
        checks.append(
            Check(None, "no ufw or firewalld found; another firewall (nftables, iptables) is not checked")
        )
    else:
        checks.append(Check(None, f"the {_system_name(system)} firewall is not checked by Yuo"))

    listening = [p for p in PORTS if connects("127.0.0.1", p)]
    if len(listening) == len(PORTS):
        checks.append(Check(True, "something answers on ports 80 and 443 here (Caddy, once it runs)"))
    else:
        missing = " and ".join(str(p) for p in PORTS if p not in listening)
        checks.append(
            Check(None, f"nothing answers on port {missing} here yet: start Caddy, then check again")
        )
    if target and situation != "cgnat":
        reached = [p for p in PORTS if connects(target, p)]
        if len(reached) == len(PORTS):
            checks.append(
                Check(
                    None,
                    f"from this server, {target} answers on 80 and 443; a firewall in front of the server "
                    "is not seen from here",
                )
            )
        else:
            gone = " and ".join(str(p) for p in PORTS if p not in reached)
            checks.append(Check(False, f"from this server, {target} does not answer on port {gone}"))

    report = Report(host, public, local, situation, checks)
    report.advice = advice(report, system, fw)
    return report


def _system_name(system: str) -> str:
    return {"Darwin": "macOS", "Windows": "Windows"}.get(system, system)


def advice(report: Report, system: str, fw: Check | None) -> list[str]:
    """Every step that can apply, the likely ones first; the outside check always last."""
    host = report.host
    steps: list[str] = []
    if report.situation == "cgnat":
        return [
            "Your internet provider shares one public address among many customers (carrier-grade NAT), so no "
            "port can be opened to this server. Use Tailscale instead: install it on the server and on each "
            "device, sign in, then run `yuo expose tailscale` (https://tailscale.com/download). It needs no open "
            "port and stays private to your devices.",
            "Or ask your provider for a public IPv4 address (some give one on request), then run this check again.",
        ]
    private = bool(report.public) and not ipaddress.ip_address(report.public[0]).is_global
    if not report.checks or report.checks[0].ok is False or private:  # the first check is always the name
        steps.append(
            f"Point {host} at the server: at your domain's DNS provider, add an A record (an AAAA record for IPv6) "
            "with the server's public address. Changes can take a few minutes to an hour to arrive."
        )
    firewall_steps = {
        "Linux": "On the server, open the ports in its firewall: with ufw, `sudo ufw allow 80/tcp && sudo ufw "
        "allow 443/tcp`; with firewalld, `sudo firewall-cmd --permanent --add-service=http --add-service=https "
        "&& sudo firewall-cmd --reload`.",
        "Windows": "On the server, open the ports in Windows Defender Firewall: in PowerShell as administrator, "
        '`New-NetFirewallRule -DisplayName "Yuo web" -Direction Inbound -Protocol TCP -LocalPort 80,443 '
        "-Action Allow`.",
        "Darwin": "On the server, in System Settings > Network > Firewall > Options, allow incoming connections "
        "for Caddy (or Docker).",
    }
    fw_step = firewall_steps.get(system, firewall_steps["Linux"])
    cloud = (
        "If the server is rented (a cloud server or VPS), open the ports in the provider's panel too: allow "
        "inbound TCP 80 and 443 from anywhere in its firewall or security group (for example an AWS security "
        "group, a Google Cloud VPC firewall rule, an Azure network security group, or the cloud firewall of "
        "Hetzner, DigitalOcean, IONOS or OVH). It sits in front of the server, so this check cannot see it."
    )
    router = (
        f"If the server is at home or in an office, forward TCP ports 80 and 443 on the router to "
        f"{report.local or 'the server'} (look for Port forwarding, Virtual server or NAT in the router's "
        "settings), and give the server a fixed address on that network."
    )
    cgnat_hint = (
        "If forwarding is set and the ports still do not answer from outside, the provider may use carrier-grade "
        "NAT (the router's WAN address starts with 100.64 to 100.127, or differs from the address websites show "
        "for you). Then use Tailscale: `yuo expose tailscale`."
    )
    # the server's own firewall: left out only when its tool said the ports are open
    if fw is None or fw.ok is not True:
        steps.append(fw_step)
    if report.situation == "direct":
        steps.append(cloud)
    else:
        steps += [cloud, router, cgnat_hint]
    steps.append(
        f"Check from outside: on a phone with Wi-Fi off, open http://{host}. A page or a redirect means the ports "
        "are open; a long wait and a timeout mean something above still blocks them."
    )
    return steps
