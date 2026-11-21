"""The `yuo` command: run the server and look after an install.

    yuo serve [--host H] [--port P]   the app and API in one process (one worker)
    yuo desktop [--port P]            this computer only: opens the browser signed in; the launcher runs it
    yuo setup-code                    a new one-time code to enrol a sign-in (also the way back in)
    yuo backup                        a checked backup now (the server makes one a day by itself)
    yuo restore [FILE]                replace the database with a backup, the newest by default (server stopped)
    yuo render-worker                 the render container's loop (no network; compose starts it)
    yuo expose tailscale|caddy|proxy  reach the install from other devices over HTTPS
    yuo expose check --domain NAME    can devices reach ports 80 and 443? What blocks them, and the fix
    yuo fetch-models [DIR]            download the Kokoro voice model, checked by hash
    yuo setup-answers FILE|-          check answers an AI assistant collected and leave them for the wizard

Settings come from the environment: `YUO_DATA_DIR`, `YUO_ORIGIN`, `YUO_HOST`, `YUO_PORT` (see the README).
"""

import argparse
import os
import sys
from pathlib import Path

from yuo import main as m
from yuo.app.auth import Auth
from yuo.app.auth_model import Origin
from yuo.core.errors import YuoError
from yuo.db import backup as bk
from yuo.db.connection import ReadPool, Writer, check_sqlite_version
from yuo.db.migrate import migrate


def _open(root: Path) -> tuple[Writer, ReadPool]:
    db = root / "yuo.db"
    migrate(db, m.VERSION)
    return Writer(db), ReadPool(db)


def serve(host: str, port: int) -> int:
    import uvicorn

    os.environ.setdefault("YUO_PORT", str(port))
    # loopback unless told otherwise; the container sets YUO_HOST=0.0.0.0 behind its proxy
    uvicorn.run("yuo.main:app", host=host, port=port, workers=1, proxy_headers=False, server_header=False)
    return 0


def _free_port(preferred: int) -> int:
    import socket

    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return int(s.getsockname()[1])
    raise YuoError("no free port on this computer")


def _running(root: Path) -> dict[str, str] | None:
    """The desktop server already serving this data folder, from its `desktop.json`."""
    import json

    try:
        info: dict[str, str] = json.loads((root / "desktop.json").read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    return info


def _open_running(info: dict[str, str]) -> int:
    import json
    import urllib.request
    import webbrowser

    if not info["url"].startswith("http://127.0.0.1:"):
        raise YuoError(f"desktop.json names an unexpected address: {info['url']}")
    req = urllib.request.Request(  # noqa: S310 (loopback http only, checked above)
        info["url"] + "/api/desktop/link",
        method="POST",
        headers={"X-Yuo-Request": "1", "X-Yuo-Control": info["control"]},
    )
    with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310
        url = json.loads(r.read())["url"]
    print(f"Yuo is already running at {info['url']}; opening it.", file=sys.stderr)
    if os.environ.get("YUO_NO_BROWSER") != "1":
        webbrowser.open(url)
    return 0


def desktop(port: int) -> int:
    """Loopback only. A second start while one runs asks it for a new link and opens that."""
    import uvicorn

    root = m.data_dir()
    root.mkdir(parents=True, exist_ok=True)
    lock = bk.InstallLock(root)
    try:
        lock.acquire()
    except YuoError:
        info = _running(root)
        if info is None:
            raise
        return _open_running(info)
    lock.release()  # build() takes it again for the server's lifetime
    port = _free_port(port)
    os.environ |= {
        "YUO_MODE": "desktop",
        "YUO_PORT": str(port),
        "YUO_ORIGIN": f"http://127.0.0.1:{port}",
        "YUO_LOG_FORMAT": os.environ.get("YUO_LOG_FORMAT", "console"),
    }
    config = uvicorn.Config(
        "yuo.main:app", host="127.0.0.1", port=port, workers=1, proxy_headers=False, server_header=False,
        log_level="warning",
    )  # fmt: skip
    server = uvicorn.Server(config)
    m._server = server
    server.run()
    return m.EXIT_CODE


def setup_code() -> int:
    root = m.data_dir()
    writer, readers = _open(root)
    try:
        code = Auth(writer, readers, m.origin_from_env()).issue_setup_code()
    finally:
        readers.close()
        writer.close()
    m.announce_setup_code(code, m.origin_from_env())
    return 0


def setup_answers_cmd(source: str) -> int:
    """Checks the answers, says what the wizard will use and what it leaves out, and saves the usable ones."""
    import json

    from yuo.app import setup_answers

    text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8-sig")
    usable, problems = setup_answers.check(text)
    for p in problems:
        print(f"left out: {p}", file=sys.stderr)
    if not usable:
        print("yuo: nothing usable in these answers; nothing saved", file=sys.stderr)
        return 1
    root = m.data_dir()
    root.mkdir(parents=True, exist_ok=True)
    target = root / setup_answers.FILE_NAME
    target.unlink(missing_ok=True)
    # personal answers: readable by Yuo's user only, like the database
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(usable, ensure_ascii=False, indent=2) + "\n")
    parts = " and ".join({"profile": "About you", "first_path": "Your first path"}[k] for k in usable)
    print(f"Saved {target}. The wizard starts {parts} from these answers; the learner checks them there.")
    return 0


def backup() -> int:
    root = m.data_dir()
    writer, readers = _open(root)
    try:
        path = bk.backup(root / "yuo.db", writer, root / "backups")
    finally:
        readers.close()
        writer.close()
    print(path)
    return 0


def restore(source: str | None) -> int:
    root = m.data_dir()
    path = Path(source) if source else bk.latest(root / "backups")
    if path is None:
        print("no backup found in", root / "backups", file=sys.stderr)
        return 1
    with bk.InstallLock(root):
        kept = bk.restore(root / "yuo.db", path, m.VERSION)
    print(f"restored {path.name}; the previous database is kept as {kept.name}")
    return 0


def render_worker() -> int:
    from yuo.adapters.renderer import spool

    root = m.data_dir()
    renderer = m.media_from_env(root).renderer
    spool.serve(renderer.work_root, renderer.package, renderer.env(), node=renderer.node)
    return 0


def expose(how: str, ip: str | None, domain: str | None, origin: str | None, out: str | None) -> int:
    from yuo.adapters.exposure import caddy, reach, tailscale

    if how == "check":
        if not (ip or domain):
            print("give --domain NAME or --ip PUBLIC_ADDRESS (the one devices will use)", file=sys.stderr)
            return 2
        report = reach.check(domain or caddy.sslip_host(ip or ""), ip)
        print(report.text())
        return 1 if report.problem else 0

    port = int(os.environ.get("YUO_PORT", "18765"))
    if how == "tailscale":
        url = tailscale.serve(port)
    elif how == "caddy":
        if not (ip or domain):
            print(
                "give --domain NAME (pointing at this server) or --ip PUBLIC_ADDRESS for sslip.io",
                file=sys.stderr,
            )
            return 2
        host = domain or caddy.sslip_host(ip or "")
        text = caddy.caddyfile(host, os.environ.get("YUO_UPSTREAM", f"127.0.0.1:{port}"))
        if out:
            Path(out).write_text(text, encoding="utf-8")
            print(f"wrote {out}")
        else:
            print(text)
        url = f"https://{host}"
        # the certificate and every device need ports 80 and 443 open from the internet: say now if they are not
        print()
        print(reach.check(host, ip).text())
    else:
        if not origin:
            print("give --origin https://NAME (the URL your proxy serves)", file=sys.stderr)
            return 2
        url = Origin.parse(origin).url
        print(
            f"Proxy to http://127.0.0.1:{port}, keep the Host header, do not buffer text/event-stream, "
            "and serve only over HTTPS."
        )
    print(f"\nSet YUO_ORIGIN={url} and restart Yuo; then open {url} on each device.")
    return 0


def fetch_models(directory: str | None) -> int:
    from yuo.adapters.tts.kokoro_models import fetch_models as fetch

    target = Path(directory or os.environ.get("YUO_KOKORO_DIR") or m.data_dir() / "models" / "kokoro")
    got = fetch(target)
    print(f"{target}: {', '.join(got) if got else 'already there'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="yuo", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--version", action="version", version=f"yuo {m.VERSION}")
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default=os.environ.get("YUO_HOST", "127.0.0.1"))
    s.add_argument("--port", type=int, default=int(os.environ.get("YUO_PORT", "18765")))
    d = sub.add_parser("desktop")
    d.add_argument("--port", type=int, default=int(os.environ.get("YUO_PORT", "18765")))
    sub.add_parser("setup-code")
    sub.add_parser("backup")
    r = sub.add_parser("restore")
    r.add_argument("file", nargs="?")
    sub.add_parser("render-worker")
    e = sub.add_parser("expose")
    e.add_argument("how", choices=["tailscale", "caddy", "proxy", "check"])
    e.add_argument("--ip")
    e.add_argument("--domain")
    e.add_argument("--origin")
    e.add_argument("--out", help="write the Caddyfile here")
    f = sub.add_parser("fetch-models")
    f.add_argument("dir", nargs="?")
    sa = sub.add_parser("setup-answers")
    sa.add_argument("file", help="a JSON file, or - to read it from standard input")
    a = ap.parse_args(argv)
    try:
        check_sqlite_version()
        match a.command:
            case "serve":
                return serve(a.host, a.port)
            case "desktop":
                return desktop(a.port)
            case "setup-code":
                return setup_code()
            case "backup":
                return backup()
            case "restore":
                return restore(a.file)
            case "render-worker":
                return render_worker()
            case "expose":
                return expose(a.how, a.ip, a.domain, a.origin, a.out)
            case "fetch-models":
                return fetch_models(a.dir)
            case "setup-answers":
                return setup_answers_cmd(a.file)
    except YuoError as e:
        print(f"yuo: {e}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
