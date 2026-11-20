"""What the application's feature parts share.

`Service` used to be one object mixed from seven classes, each reaching any attribute of the others. It is now a
facade over feature parts (`Onboarding`, `Sharing`, `Video`, `Review`, `NextSteps`, `Tutor`, `Study`), each
built with what it needs: the shared `AppContext` (ports and infrastructure), and the other parts it calls,
typed as the Protocols in `yuo.app.ports`.

The context is one mutable object held by reference: the composition root (yuo.main) and tests set the
late-bound ports (`access`, `cli`, `updates`, `prober`, `plan_meter`, the workers) on the service after it is
built, and every part sees them at once.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, overload

from yuo.app.broker import Broker
from yuo.core.media import RendererPort, TTSPort
from yuo.db.blobs import BlobStore
from yuo.db.connection import ReadPool, Writer
from yuo.generation import estimate as est
from yuo.generation.runner import StageRunner
from yuo.learning import projections as pj
from yuo.setup.probe import Probe


@dataclass(eq=False)
class AppContext:
    writer: Writer
    readers: ReadPool
    runner: StageRunner
    prices: est.PriceSource
    scheduler: pj.Scheduler
    broker: Broker = field(default_factory=Broker)
    renderer: RendererPort | None = None
    voices: dict[str, TTSPort] = field(default_factory=dict)
    ffmpeg: Any = None
    blobs: BlobStore | None = None
    media_dir: Path = Path(".dev") / "media"
    keep_video_work: bool = False
    # set after construction by the composition root (or a test)
    worker: Any = None  # generation.jobs.JobWorker
    tutor_worker: Any = None  # app.tutor.TutorWorker
    prober: Callable[[], Probe] | None = None  # the machine probe
    access: Any = None  # adapters.access.Access: keys, local server, direct vendors
    updates: Any = None  # adapters.updates.Updates
    plan_meter: Any = None  # the subscription CLIs' last plan readings
    cli: Any = None  # adapters.cli_access.CliAccess: are the subscription CLIs installed and signed in
    transcriber: Any = None  # core.documents.Transcriber: speech to text for recorded lectures
    online_videos: Any = None  # core.online_video.OnlineVideos: YouTube, for lessons built on a video
    answers_file: Path | None = None  # setup-answers.json in the data folder (yuo.app.setup_answers)


class Shared[T]:
    """A field of the part's `AppContext`, read and written through the part, so a port set later stays live."""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    @overload
    def __get__(self, obj: None, objtype: type | None = None) -> Shared[T]: ...
    @overload
    def __get__(self, obj: Part, objtype: type | None = None) -> T: ...
    def __get__(self, obj: Part | None, objtype: type | None = None) -> T | Shared[T]:
        if obj is None:
            return self
        value: T = getattr(obj.ctx, self.name)
        return value

    def __set__(self, obj: Part, value: T) -> None:
        setattr(obj.ctx, self.name, value)


class Part:
    """A feature part of the application service: it reaches the shared ports as plain attributes."""

    writer: Shared[Writer] = Shared()
    readers: Shared[ReadPool] = Shared()
    runner: Shared[StageRunner] = Shared()
    prices: Shared[est.PriceSource] = Shared()
    scheduler: Shared[pj.Scheduler] = Shared()
    broker: Shared[Broker] = Shared()
    renderer: Shared[RendererPort | None] = Shared()
    voices: Shared[dict[str, TTSPort]] = Shared()
    ffmpeg: Shared[Any] = Shared()
    blobs: Shared[BlobStore | None] = Shared()
    media_dir: Shared[Path] = Shared()
    keep_video_work: Shared[bool] = Shared()
    worker: Shared[Any] = Shared()
    tutor_worker: Shared[Any] = Shared()
    prober: Shared[Callable[[], Probe] | None] = Shared()
    access: Shared[Any] = Shared()
    updates: Shared[Any] = Shared()
    plan_meter: Shared[Any] = Shared()
    cli: Shared[Any] = Shared()
    answers_file: Shared[Path | None] = Shared()
    online_videos: Shared[Any] = Shared()

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
