"""Media fakes for tests and the browser-test server: a voice that writes silence and a renderer that checks
nothing, makes no stills of substance, and (optionally) writes a real, playable test-pattern MP4."""

import subprocess
from pathlib import Path
from typing import Any

from yuo.core.audio import write_wav
from yuo.core.media import Narration, Stills


class FakeVoice:
    name, version, remote, voice = "fake-voice", "1", False, "v"

    def __init__(self) -> None:
        self.lexicon: dict[str, str] = {}
        self.unknown: list[str] = []
        self.said: list[str] = []

    def unknown_words(self, texts: list[str]) -> list[str]:
        return [w for w in self.unknown if w not in self.lexicon]

    def learn(self, pronunciations: dict[str, str]) -> None:
        self.lexicon.update(pronunciations)

    def synthesize(self, text: str, out: Path) -> float:
        import numpy as np

        self.said.append(text)
        write_wav(out, np.zeros(int(24000 * len(text.split()) * 0.3), dtype=np.float32), 24000)
        return 0.0


class FakeRenderer:
    name, version = "fake-renderer", "1"

    def __init__(self, *, playable: bool = False) -> None:
        self.fail_check = 0
        self.renders = 0
        self.playable = playable
        self.themes: list[str] = []  # every theme asked of kit, stills and render, in order

    def available(self) -> str | None:
        return None

    def kit(self, theme: str = "dark") -> dict[str, str]:
        self.themes.append(theme)
        return {"kit": "// kit", "theme": f"// {theme} theme"}

    def check(self, tsx: str) -> list[str]:
        if self.fail_check > 0:
            self.fail_check -= 1
            return ["scene.tsx(3,5): error TS2322: Type 'string' is not assignable to type 'number'."]
        return []

    def stills(self, tsx: str, narration: Narration, out: Path, theme: str = "dark") -> Stills:
        self.themes.append(theme)
        out.mkdir(parents=True, exist_ok=True)
        sheet = out / "sheet_00.jpg"
        sheet.write_bytes(b"\xff\xd8fake")
        probe = [
            {
                "name": f"{s.id}-{i}",
                "text": g.text,
                "probe": {"issues": [], "texts": [{"t": s.label, "x": 1, "y": 1}]},
            }
            for s in narration.timeline.scenes
            for i, g in enumerate(s.segments)
        ]
        return Stills(out, (sheet,), probe)

    def render(self, tsx: str, narration: Narration, out: Path, theme: str = "dark") -> float:
        self.renders += 1
        self.themes.append(theme)
        if not self.playable:
            out.write_bytes(b"fake mp4")
            return 1.0
        secs = f"{narration.seconds:.2f}"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30", "-f", "lavfi",
             "-i", "sine=frequency=440", "-t", secs, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)],
            check=True,
        )  # fmt: skip
        return 1.0


class FakeFFmpeg:
    def poster(self, video: Path, out: Path, at_s: float = 3.0) -> None:
        out.write_bytes(b"\xff\xd8poster")

    def with_subtitles(self, video: Path, vtt: Path, out: Path, lang: str = "eng") -> None:
        out.write_bytes(video.read_bytes())


class FakeYouTube:
    """YouTube for lessons built on a video: four candidates, each with a transcript; `refuse` makes the
    captions fail with that kind (blocked, no_transcript); `audio` writes a small file standing for the sound,
    unless `refuse_audio` names a kind."""

    def __init__(self) -> None:
        from yuo.core.online_video import Candidate

        self.searches: list[str] = []
        self.transcripts: list[str] = []
        self.refuse: str | None = None
        self.refuse_audio: str | None = None
        self.sounds: list[str] = []
        self.gone: set[str] = set()
        self.found = [
            Candidate(f"vid{n}aaaaaa", f"Video {n} on joins", f"Channel {n}", f"UC{n}", 12 * 60_000, 1000 * n)
            for n in range(1, 5)
        ]

    def search(self, query: str, lang: str, limit: int) -> list[Any]:
        self.searches.append(query)
        return self.found[:limit]

    def transcript(self, video_id: str, langs: list[str]) -> Any:
        from yuo.core.online_video import Line, OnlineVideoError, Transcript

        self.transcripts.append(video_id)
        if self.refuse:
            raise OnlineVideoError(self.refuse)
        lines = [
            Line(
                s * 1000,
                (s + 10) * 1000,
                f"in {video_id} a left join keeps every row of the left table, part {s}",
            )
            for s in range(0, 720, 10)
        ]
        return Transcript(langs[-1], True, lines)

    def audio(self, video_id: str, folder: Path) -> Path:
        from yuo.core.online_video import OnlineVideoError

        self.sounds.append(video_id)
        if self.refuse_audio:
            raise OnlineVideoError(self.refuse_audio)
        folder.mkdir(parents=True, exist_ok=True)
        out = folder / f"{video_id}.webm"
        out.write_text(video_id)
        return out

    def available(self, video_id: str) -> tuple[str, str] | None:
        return None if video_id in self.gone else (f"Renamed {video_id}", "New channel")


class FakeTranscriber:
    """Speech recognition: each sound file "says" a left-join sentence every 10 seconds for 12 minutes, in
    `language` (or the one per video in `languages`)."""

    def __init__(self, language: str = "en") -> None:
        self.language = language
        self.languages: dict[str, str] = {}
        self.heard: list[str] = []
        self.calls: list[dict[str, Any]] = []

    def available(self) -> str | None:
        return None

    def transcribe(self, audio: Path, **kw: Any) -> list[Any]:
        from yuo.core.documents import Segment

        video_id = audio.read_text()
        self.heard.append(video_id)
        self.calls.append(kw)
        if kw.get("on_language"):
            kw["on_language"](self.languages.get(video_id, self.language))
        return [
            Segment(
                s * 1000, (s + 10) * 1000, f" heard in {video_id}: a left join keeps every left row, part {s}"
            )
            for s in range(0, 720, 10)
        ]
