"""Caddy in front of the app: a public HTTPS name with automatic certificates.

Without a domain, sslip.io turns the server's IP address into a name (`yuo.203-0-113-7.sslip.io`), which is
enough for a certificate and for passkeys. The generated Caddyfile keeps the Host header (the app checks it),
does not buffer the event stream, holds requests for up to 30 s while the app restarts (an update) instead of
answering 502, and hides the server banner.
"""

import ipaddress


def sslip_host(ip: str, prefix: str = "yuo") -> str:
    addr = ipaddress.ip_address(ip)
    if addr.is_private or addr.is_loopback or addr.is_link_local:
        raise ValueError(f"{ip} is not a public address: certificates need one reachable from the internet")
    dashed = addr.exploded.replace(":", "-") if addr.version == 6 else str(addr).replace(".", "-")
    return f"{prefix}.{dashed}.sslip.io"


def caddyfile(host: str, upstream: str = "yuo:18765") -> str:
    if not host or any(c in host for c in " {}\n/"):
        raise ValueError(f"not a host name: {host!r}")
    return f"""{host} {{
	encode zstd gzip
	reverse_proxy {upstream} {{
		flush_interval -1
		lb_try_duration 30s
		lb_try_interval 250ms
	}}
	header -Server
}}
"""
