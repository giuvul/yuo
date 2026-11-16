"""Media fakes for tests and the browser-test server: a voice that writes silence and a renderer that checks
nothing, makes no stills of substance, and (optionally) writes a real, playable test-pattern MP4."""

import subprocess
from pathlib import Path

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
