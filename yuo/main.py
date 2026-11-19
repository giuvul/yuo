"""Composition root: settings, database, adapters, services and the API wired together for one process.
Run with `uvicorn yuo.main:app` and exactly one worker: more workers, more writers.
"""

import os
import sqlite3
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib.metadata import version as dist_version
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI

from yuo.adapters.llm.cli import ClaudeCLIAdapter, CodexCLIAdapter
from yuo.adapters.llm.openai_compat import OPENROUTER, OpenAICompatAdapter
from yuo.adapters.llm.prices import OpenRouterPrices
from yuo.adapters.secrets import ChainStore, EncryptedFileStore, EnvFileStore, KeyringStore, SecretStore
from yuo.api import web
from yuo.api.app import create_app
from yuo.app.auth import Auth
from yuo.app.auth_model import Origin
from yuo.app.maintenance import Maintenance
from yuo.app.plan_meter import PlanMeter
from yuo.app.service import Service
from yuo.app.tutor import TutorWorker
from yuo.assessment import types as xt
from yuo.core import logs
from yuo.core.errors import StartupError
from yuo.core.llm import LLMPort
from yuo.db.backup import InstallLock
from yuo.db.connection import ReadPool, Writer, check_sqlite_version
from yuo.db.migrate import migrate
from yuo.generation.jobs import JobWorker
from yuo.generation.lanes import with_lanes
from yuo.generation.runner import BudgetGuard, StageRunner
from yuo.setup import settings

VERSION = dist_version("yuo")
log = structlog.get_logger(__name__)


def data_dir() -> Path:
    return Path(os.environ.get("YUO_DATA_DIR", Path.home() / ".local" / "share" / "yuo"))


def origin_from_env() -> Origin:
    """The one URL learners open (`YUO_ORIGIN`); passkeys are bound to its host. Default: this machine."""
    return Origin.parse(
        os.environ.get("YUO_ORIGIN", f"http://localhost:{os.environ.get('YUO_PORT', '18765')}")
    )


def extra_hosts_from_env() -> frozenset[str]:
    """More Host header values to accept (`YUO_ALLOWED_HOSTS`, comma separated), e.g. a LAN name."""
    return frozenset(h.strip() for h in os.environ.get("YUO_ALLOWED_HOSTS", "").split(",") if h.strip())


def announce_setup_code(code: str, origin: Origin) -> None:
    """To the console only, never the log: whoever runs the server reads it there."""
    print(
        f"\n  Yuo has no sign-in yet. Open {origin.url}/setup and enter this one-time code:\n\n      {code}\n\n"
        "  It works once and expires in 24 hours; `yuo setup-code` prints a new one.\n",
        file=sys.stderr,
        flush=True,
    )


def desktop_mode() -> bool:
    """The desktop app (`yuo desktop`): one person on their own machine, loopback only, signed in by the launch link."""
    return os.environ.get("YUO_MODE") == "desktop"


def secret_store(root: Path) -> SecretStore:
    stores: list[SecretStore] = [EnvFileStore()]
    key_file = os.environ.get("YUO_SECRETS_KEY_FILE")
    if key_file is None and desktop_mode():
        try:
            stores.append(KeyringStore())  # Windows Credential Manager, macOS Keychain, Secret Service
            return ChainStore(*stores)
        except StartupError:
            # no keychain (a Linux desktop without Secret Service): an encrypted file whose key sits
            # beside it, readable by this user only; protects copies of the file, not this account
            key = root / "secrets.key"
            if not key.exists():
                key.write_bytes(os.urandom(32).hex().encode())
                key.chmod(0o600)
            key_file = str(key)
            log.info("secrets.file_store", reason="no OS keychain")
    if key_file:
        if not Path(key_file).is_file():  # refuse to run the server version with secrets but no key
            raise StartupError(
                f"the secrets key file {key_file} is missing: create it (see packaging/container)"
            )
        try:
            stores.append(EncryptedFileStore.from_key_file(root / "secrets.bin", Path(key_file)))
        except PermissionError as e:
            raise StartupError(
                f"cannot read the secrets key file {key_file}: give it to the user Yuo runs as"
            ) from e
    else:
        try:
            stores.append(KeyringStore())
        except StartupError:
            log.info("secrets.no_keychain", hint="set YUO_SECRETS_KEY_FILE for the encrypted file store")
    return ChainStore(*stores)


def llm_ports(secrets: SecretStore, prices: Any = None, meter: Any = None) -> dict[str, LLMPort]:
    from yuo.adapters.llm.vendor import vendor_port
    from yuo.setup.providers import PROVIDERS

    ports: dict[str, LLMPort] = {}
    if key := secrets.get("openrouter"):
        ports["openrouter"] = OpenAICompatAdapter("openrouter", OPENROUTER, key)
    if url := os.environ.get("YUO_OPENAI_COMPAT_URL"):  # Ollama, llama.cpp, vLLM
        ports["local"] = OpenAICompatAdapter("local", url, secrets.get("local"))
    for vendor in PROVIDERS.values():  # direct vendor keys entered in the wizard or Settings
        if key := secrets.get(f"vendor:{vendor.id}"):
            ports[vendor.adapter] = vendor_port(vendor, key, vendor_price(prices, vendor.adapter))
    # always there: the program may be installed (with Yuo's help) while Yuo runs; readiness is checked
    # before any generation (Service.require_ai_ready)
    for cli in (ClaudeCLIAdapter(), CodexCLIAdapter()):
        if meter is not None:
            cli.on_meter = meter.reporter(cli.name.removesuffix("-cli"))
        ports[cli.name] = cli
    return ports


def vendor_price(prices: Any, adapter: str) -> Any:
    """The per-token price of a direct key's models, for its budget ledger; None without a price list."""
    if prices is None:
        return None
    return lambda model: prices.per_token(adapter, model)


@dataclass
class Runtime:
    writer: Writer
    readers: ReadPool
    service: Service
    worker: JobWorker
    tutor: TutorWorker

    def close(self) -> None:
        self.tutor.stop()
        self.worker.stop()
        self.readers.close()
        self.writer.close()


@dataclass
class Media:
    """The video side; every field optional: without a renderer lessons stay reading lessons."""

    renderer: Any = None
    voices: dict[str, Any] | None = None
    ffmpeg: Any = None
    blobs: Any = None
    media_dir: Path | None = None


def transcriber_from_env(root: Path, ffmpeg: Any = None) -> Any:
    """Speech to text for recorded lectures: faster-whisper on this machine, installed on first use
    (`YUO_WHISPER_MODEL`, default small; `YUO_WHISPER_THREADS`, default 2; `YUO_WHISPER=off` turns it off)."""
    from yuo.adapters.transcribe.local import LocalWhisper

    if os.environ.get("YUO_WHISPER", "").lower() == "off":
        return None
    return LocalWhisper(
        root / "whisper",
        model=os.environ.get("YUO_WHISPER_MODEL", "small"),
        threads=int(os.environ.get("YUO_WHISPER_THREADS", "2")),
        decoder=ffmpeg.program() if ffmpeg is not None else None,
    )


def media_from_env(root: Path) -> Media:
    from yuo.adapters.renderer.remotion import RemotionRenderer
    from yuo.adapters.tools.ffmpeg import FFmpeg
    from yuo.adapters.tts.kokoro import KokoroTTS
    from yuo.db.blobs import BlobStore

    package = Path(os.environ.get("YUO_RENDERER_DIR", Path(__file__).resolve().parents[1] / "renderer"))
    renderer = RemotionRenderer(
        package,
        root / "render",
        chrome=os.environ.get("YUO_CHROME"),
        chrome_libs=os.environ.get("YUO_CHROME_LIBS"),
        heavy_lock=os.environ.get("YUO_HEAVY_LOCK"),
        sandbox=os.environ.get("YUO_RENDER_SANDBOX", "auto"),  # `spool` in the container (compose)
    )
    ffmpeg = FFmpeg()
    voices: dict[str, Any] = {
        "kokoro": KokoroTTS(Path(os.environ.get("YUO_KOKORO_DIR", root / "models" / "kokoro")))
    }
    return Media(renderer, voices, ffmpeg, BlobStore(root / "blobs"), root / "media")


def start(
    db: Path, ports: dict[str, LLMPort], prices: Any, *, worker: bool = True, media: Media | None = None
) -> Runtime:
    writer, readers = Writer(db), ReadPool(db)
    writer.run(xt.register_all)  # built-in exercise types

    def cap() -> int | None:
        with readers.connection() as c:
            usd = settings.effective(c, "budget.cap_usd_month", {})[0]
        return None if usd is None else round(float(usd) * 1_000_000)

    runner = StageRunner(writer, readers, with_lanes(ports), BudgetGuard(readers, cap))
    m = media or Media()
    service = Service(
        writer,
        readers,
        runner,
        prices,
        renderer=m.renderer,
        voices=m.voices,
        ffmpeg=m.ffmpeg,
        blobs=m.blobs,
        media_dir=m.media_dir,
    )
    jobs = JobWorker(writer, readers, service.handlers())
    jobs.recover()  # a crash or reboot mid-generation

    def job_changed(job_id: str, status: str) -> None:
        service.broker.publish("job", {"id": job_id, "status": status})

    jobs.on_change = job_changed
    service.worker = jobs
    tutor = TutorWorker(service.run_tutor_turn)
    service.tutor_worker = tutor
    if worker:
        jobs.start()
        tutor.start()
    return Runtime(writer, readers, service, jobs, tutor)


def waitlist_url() -> str | None:
    """The hosted waitlist form: only a link the wizard opens, no call from the app."""
    url = os.environ.get("YUO_WAITLIST_URL", "")
    return url if url.startswith("https://") else None


def wire_setup(service: Service, root: Path, secrets: SecretStore) -> None:
    """The wizard's parts: the machine probe, AI access that connects without a restart, updates."""
    from yuo.adapters import cli_access, machine, release_feed
    from yuo.adapters.llm.openai_compat import check_openrouter_key, list_models
    from yuo.adapters.llm.vendor import vendor_models, vendor_port
    from yuo.app import setup_answers
    from yuo.app.access import Access
    from yuo.app.updates import Updates

    service.prober = lambda: machine.probe(root)
    service.answers_file = root / setup_answers.FILE_NAME
    service.access = Access(
        service.writer,
        service.readers,
        secrets,
        service.runner.ports,
        openrouter=lambda key: OpenAICompatAdapter("openrouter", OPENROUTER, key),
        local=lambda url: OpenAICompatAdapter("local", url, None),
        check_key=check_openrouter_key,
        list_models=list_models,
        vendor=lambda p, key: vendor_port(p, key, vendor_price(service.prices, p.adapter)),
        vendor_models=vendor_models,
    )
    service.cli = cli_access.CliAccess()
    service.access.cli_found = service.cli.found
    if "local" not in service.runner.ports and (url := service.setting("ai.local_url")):
        service.access._connect("local", OpenAICompatAdapter("local", url, None))

    def enabled() -> bool:
        return bool(service.setting("updates.check"))

    service.updates = Updates(
        root,
        VERSION,
        os.environ.get("YUO_UPDATE_FEED") or None,
        fetch=release_feed.fetch,
        download=lambda url, target, sha, size: release_feed.download(url, target, sha, size),
        enabled=enabled,
        desktop=desktop_mode(),
        exit_process=request_exit,
    )


# --- desktop ----------------------------------------------------------------------------------

EXIT_CODE = 0
_server: Any = None  # the uvicorn.Server `yuo desktop` runs, so the app can ask it to stop


def request_exit(code: int) -> None:
    """Stop serving and leave with `code` (75: the launcher installs the staged update and starts again)."""
    global EXIT_CODE
    EXIT_CODE = code
    if _server is not None:
        _server.should_exit = True


class Desktop:
    """Glue: `desktop.json` tells a second start (and the launcher) where this server listens, the
    control token lets that start ask for a new sign-in link, and the browser opens signed in."""

    def __init__(self, root: Path, origin: Origin) -> None:
        import secrets as pysecrets

        self.root = root
        self.origin = origin
        self.control_token = pysecrets.token_urlsafe(32)
        self.auth: Any = None
        self.file = root / "desktop.json"
        self._opened_at = 0.0
        self._auto_reopened = False

    def link(self) -> str:
        return f"{self.origin.url}/#launch={self.auth.issue_launch_code()}"

    def started(self) -> None:
        import json
        import threading

        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "url": self.origin.url,
                    "pid": os.getpid(),
                    "version": VERSION,
                    "control": self.control_token,
                    # the launcher's id for this start: on Windows the process it started is a small
                    # launcher in front of Python, so the pid it knows is not this one
                    "launch": os.environ.get("YUO_LAUNCH_ID", ""),
                }
            ),
            encoding="utf-8",
        )
        tmp.chmod(0o600)
        tmp.replace(self.file)
        print(f"\n  Yuo is running at {self.origin.url}\n  Keep this window open while you use Yuo; close it to stop.\n",
              file=sys.stderr, flush=True)  # fmt: skip
        if os.environ.get("YUO_NO_BROWSER") != "1":
            threading.Thread(target=self._open_when_serving, daemon=True).start()
        else:
            print(
                f"  Open this link to sign in (works once, for ten minutes):\n  {self.link()}\n",
                file=sys.stderr,
                flush=True,
            )

    def _open_when_serving(self) -> None:
        """Opens the browser once the server answers (lifespan start-up runs before the port is open)."""
        import time
        import urllib.request

        for _ in range(60):
            try:
                with urllib.request.urlopen(self.origin.url + "/api/health", timeout=2):  # noqa: S310 (loopback)
                    break
            except OSError:
                time.sleep(0.5)
        self.open_browser()

    def open_browser(self) -> None:
        import time
        import webbrowser

        self._opened_at = time.monotonic()
        webbrowser.open(self.link())

    def reopen(self, auto: bool) -> bool:
        """A signed-out tab asks for a signed-in one (the first link can get lost, for example behind a
        browser's first-run screens). Only opens a browser on this computer, as this user, so it gives
        nothing away; once automatically per start, and at most every 5 s from the button."""
        import time

        if os.environ.get("YUO_NO_BROWSER") == "1" or time.monotonic() - self._opened_at < 5:
            return False
        if auto:
            if self._auto_reopened:
                return False
            self._auto_reopened = True
        self.open_browser()
        return True

    def stopped(self) -> None:
        self.file.unlink(missing_ok=True)

    def quit(self) -> None:
        request_exit(0)


def web_dir() -> Path | None:
    """The built web app (`npm run build`); the container sets `YUO_WEB_DIR`."""
    path = Path(os.environ.get("YUO_WEB_DIR", Path(__file__).resolve().parents[1] / "web" / "dist"))
    return path if (path / "index.html").exists() else None


def build() -> FastAPI:
    logs.configure(
        os.environ.get("YUO_LOG_LEVEL", "INFO"), json=os.environ.get("YUO_LOG_FORMAT") != "console"
    )
    check_sqlite_version()
    root = data_dir()
    root.mkdir(parents=True, exist_ok=True)
    lock = InstallLock(root)
    lock.acquire()  # one server per install; `yuo restore` waits for it to stop
    db = root / "yuo.db"
    migrate(db, VERSION)
    secrets = secret_store(root)
    prices = OpenRouterPrices(root / "cache" / "openrouter-prices.json")
    meter = PlanMeter(root / "cache" / "plan-meter.json")
    ports = llm_ports(secrets, prices, meter)
    media = media_from_env(root)
    log.info("adapters", llm=sorted(ports), video=media.renderer.available() or "ok")
    runtime = start(db, ports, prices, worker=False, media=media)
    runtime.service.plan_meter = meter
    runtime.service.ctx.transcriber = transcriber_from_env(root, media.ffmpeg)

    def health() -> dict[str, Any]:
        with runtime.readers.connection() as c:
            schema = c.execute("PRAGMA user_version").fetchone()[0]
        adapters = sorted(runtime.service.runner.ports)  # the wizard can connect more while running
        return {"schema_version": schema, "sqlite": sqlite3.sqlite_version, "adapters": adapters}

    origin = origin_from_env()
    desktop = Desktop(root, origin) if desktop_mode() else None
    auth = Auth(runtime.writer, runtime.readers, origin, desktop=desktop is not None)
    runtime.service.ensure_learner()
    wire_setup(runtime.service, root, secrets)
    if desktop is not None:
        desktop.auth = auth
    elif code := auth.setup_code_on_start():
        announce_setup_code(code, origin)
    app = create_app(
        version=VERSION,
        health=health,
        service=runtime.service,
        auth=auth,
        extra_hosts=extra_hosts_from_env(),
        desktop=desktop,
        waitlist_url=waitlist_url(),
    )
    web.mount(app, web_dir())
    upkeep = Maintenance(db, runtime.writer, root / "backups")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        runtime.worker.start()
        runtime.tutor.start()
        upkeep.start()
        if desktop is not None:
            desktop.started()
        try:
            yield
        finally:
            if desktop is not None:
                desktop.stopped()
            upkeep.stop()
            runtime.close()
            lock.release()

    app.router.lifespan_context = lifespan
    return app


_app: FastAPI | None = None


def __getattr__(name: str) -> FastAPI:
    # `uvicorn yuo.main:app` builds the app on first access, so importing this module has no side effects;
    # uvicorn reads the attribute more than once, and one process must build one app (the install lock)
    global _app
    if name == "app":
        if _app is None:
            _app = build()
        return _app
    raise AttributeError(name)
