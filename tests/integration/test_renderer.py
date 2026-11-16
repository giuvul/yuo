"""The Remotion renderer adapter on this machine: lint, compile, stills and the network sandbox.

Skipped where the renderer package, Node or a Chromium for it is missing (CI installs them).
"""

import http.server
import json
import os
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest

from yuo.adapters.renderer.remotion import RemotionRenderer, lint
from yuo.core.media import Narration, SceneTiming, Segment, Timeline, VideoTheme

ROOT = Path(__file__).resolve().parents[2]
PW = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", Path.home() / ".cache" / "ms-playwright"))
CHROME = next(
    iter(sorted(PW.glob("chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"))),
    None,
)
LIBS = PW / "deps" / "root" / "usr" / "lib" / "x86_64-linux-gnu"

SCENE = """import React from 'react';
import {useBeats, Center, Pop} from '../kit';
import {C} from '../theme';
import type {SceneDef, SceneProps} from '../kit';

const Intro: React.FC<SceneProps> = ({segs}) => {
  const {at} = useBeats(segs);
  PAYLOAD
  return <Center><Pop p={at(0)}><div style={{fontSize: 64, color: C.text}}>Hello</div></Pop></Center>;
};
export const SCENES: Record<string, SceneDef> = {intro: {label: 'Intro', component: Intro}};
"""


def renderer() -> RemotionRenderer:
    return RemotionRenderer(
        ROOT / "renderer",
        ROOT / ".dev" / "render-test",
        chrome=str(CHROME) if CHROME else None,
        chrome_libs=str(LIBS) if LIBS.exists() else None,
    )


needs_renderer = pytest.mark.skipif(
    renderer().available() is not None or CHROME is None, reason="renderer, Node, sandbox or Chromium missing"
)


@pytest.fixture
def narration(tmp_path: Path) -> Narration:
    wav = tmp_path / "n.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=24000:cl=mono",
            "-t",
            "3",
            str(wav),
        ],
        check=True,
    )
    tl = Timeline("T", 30, 90, (SceneTiming("intro", "Intro", 0, 90, (Segment("Hello there.", 10, 70),)),))
    return Narration(wav, tl, 3.0, 12)


class Beacon(http.server.BaseHTTPRequestHandler):
    hits: ClassVar[list[str]] = []

    def do_GET(self) -> None:
        Beacon.hits.append(self.path)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_: object) -> None:
        pass


@pytest.fixture
def beacon() -> Iterator[int]:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Beacon)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    Beacon.hits = []
    yield srv.server_address[1]
    srv.shutdown()


def test_the_lint_names_what_is_not_allowed() -> None:
    bad = SCENE.replace("PAYLOAD", "fetch('http://x'); const t = Date.now();").replace(
        "import {C}", "import fs from 'fs';\nimport {C}"
    )
    errors = lint(bad)
    assert any("'fs' is not allowed" in e for e in errors)
    assert any("no network access" in e for e in errors) and any("deterministic" in e for e in errors)
    assert lint(SCENE.replace("PAYLOAD", "")) == []


@pytest.mark.parametrize(
    "payload",
    [
        "const a = '#05070f';",
        'const a = "#fff";',
        "const a = `#3b2a7aCC`;",
        "const a = 'linear-gradient(90deg, #ffaa00, transparent)';",
        "const a = 'rgba(8, 12, 26, 0.5)';",
        "const a = 'hsl(200 50% 50%)';",
        "const a = 'white';",
    ],
)
def test_the_lint_rejects_colour_literals(payload: str) -> None:
    """A scene takes every colour from the theme, so it works light and dark."""
    errors = lint(SCENE.replace("PAYLOAD", payload))
    assert len(errors) == 1 and "no colour literals" in errors[0] and "alpha(C.read, 0.3)" in errors[0]


def test_theme_colours_and_text_that_looks_like_hex_pass_the_lint() -> None:
    ok = "const a = alpha(C.read, 0.3); const b = `${C.bad}`; const t = 'Order #1234 and C# code, #add';"
    assert lint(SCENE.replace("PAYLOAD", ok).replace("import {C}", "import {C, alpha}")) == []


def test_the_author_sees_the_palette_of_the_chosen_theme() -> None:
    light, dark = renderer().kit("light")["theme"], renderer().kit("dark")["theme"]
    assert "bg: '#eef1f8'" in light and "#0b1020" not in light
    assert "bg: '#0b1020'" in dark and "export const alpha" in dark and "./themes/" not in dark


@needs_renderer
def test_stills_come_out_in_the_chosen_theme(narration: Narration, tmp_path: Path) -> None:
    def ground(theme: VideoTheme) -> float:
        """The mean brightness of a corner pixel of the first still (0 black, 255 white)."""
        stills = renderer().stills(SCENE.replace("PAYLOAD", ""), narration, tmp_path / theme, theme)
        rgb = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-i", str(stills.dir / "intro-0.jpg"), "-vf", "crop=2:2:10:10,scale=1:1",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True, check=True,
        ).stdout  # fmt: skip
        return sum(rgb) / 3

    assert ground("light") > 200 and ground("dark") < 50


@needs_renderer
def test_compile_errors_point_at_the_scene_module() -> None:
    errors = renderer().check(SCENE.replace("PAYLOAD", "const n: number = 'x';"))
    assert errors and errors[0].startswith("scene.tsx(") and "TS2322" in errors[0]
    assert renderer().check(SCENE.replace("PAYLOAD", "")) == []


@needs_renderer
def test_a_scene_cannot_reach_the_network_from_the_sandbox(
    narration: Narration, beacon: int, tmp_path: Path
) -> None:
    # past the lint on purpose: the sandbox and the CSP must hold on their own
    sneaky = f"(self as any)['fe' + 'tch']('http://127.0.0.1:{beacon}/leak').catch(() => 0);"
    stills = renderer().stills(SCENE.replace("PAYLOAD", sneaky), narration, tmp_path / "stills")
    assert len(stills.sheets) == 1 and stills.probe[0]["name"] == "intro-0"
    assert Beacon.hits == []
    assert json.loads((tmp_path / "stills" / "probe.json").read_text())[0]["text"] == "Hello there."
    assert not list((ROOT / ".dev" / "render-test").glob("render-*"))  # workspaces are removed


def test_a_render_the_system_killed_is_retried_later() -> None:
    from yuo.adapters.renderer.remotion import _check
    from yuo.core.media import MediaError

    for code in (-9, -15, 137, 143):
        with pytest.raises(MediaError) as e:
            _check(subprocess.CompletedProcess([], code, "", ""))
        assert e.value.retryable and e.value.kind == "resources"
    with pytest.raises(MediaError) as e:
        _check(subprocess.CompletedProcess([], 1, "", "TypeError: x is undefined"))
    assert not e.value.retryable and "TypeError" in str(e.value)
    _check(subprocess.CompletedProcess([], 0, "", ""))


@needs_renderer
def test_frames_and_the_browser_profile_stay_in_the_workspace(narration: Narration, tmp_path: Path) -> None:
    """A long video's frames filled the container's 512 MB /tmp (ENOSPC) at the final
    render. With the system temp folder unusable, a render still works: everything temporary is in the
    workspace."""

    class NoTmp(RemotionRenderer):
        def env(self) -> dict[str, str]:
            return super().env() | {"TMPDIR": str(tmp_path / "not-a-folder")}

    (tmp_path / "not-a-folder").write_text("a file, so nothing can be written under it")
    r = NoTmp(
        ROOT / "renderer",
        ROOT / ".dev" / "render-test",
        chrome=str(CHROME) if CHROME else None,
        chrome_libs=str(LIBS) if LIBS.exists() else None,
    )
    out = tmp_path / "out.mp4"
    r.render(SCENE.replace("PAYLOAD", ""), narration, out)
    assert out.stat().st_size > 1000
    # the narration is speech: 64 kbit/s, not the 320 kbit/s default that was most of a video's size
    rate = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=bit_rate",
            "-of",
            "csv=p=0",
            out,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert 0 < int(rate) <= 72_000
