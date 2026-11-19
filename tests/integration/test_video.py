"""The video pipeline on a scripted model: the review loop (author, compile, narration, stills, critics, repairs from
the best round), publishing with a WebVTT track, the reading fallback, pronunciations, and one real render."""

import json
import os
import sqlite3
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests import fakes
from tests.fakes_media import FakeFFmpeg, FakeRenderer, FakeVoice
from tests.integration.test_renderer import CHROME, LIBS, needs_renderer
from tests.integration.test_slice import NoPrices, drain, lessons_of
from yuo.adapters.renderer.remotion import RemotionRenderer
from yuo.adapters.tools.ffmpeg import FFmpeg
from yuo.app.forms import PathForm
from yuo.core.ids import new_id
from yuo.core.llm import Role
from yuo.core.media import MediaError
from yuo.db.blobs import BlobStore
from yuo.main import Media, Runtime, start

ROOT = Path(__file__).resolve().parents[2]
KOKORO = Path(os.environ.get("YUO_KOKORO_DIR", ".dev/models/kokoro"))


def major(still: str = "s0-0") -> dict[str, Any]:
    return {"overall": 5, "issues": [{"still": still, "severity": "major", "problem": "the label is cut off",
                                      "fix": "make the box wider"}]}  # fmt: skip


@pytest.fixture
def llm() -> fakes.FakeLLM:
    return fakes.FakeLLM()


@pytest.fixture
def voice() -> FakeVoice:
    return FakeVoice()


@pytest.fixture
def renderer() -> FakeRenderer:
    return FakeRenderer()


@pytest.fixture
def rt(
    db_path: Path, tmp_path: Path, llm: fakes.FakeLLM, voice: FakeVoice, renderer: FakeRenderer
) -> Iterator[Runtime]:
    media = Media(
        renderer, {"kokoro": voice}, FakeFFmpeg(), BlobStore(tmp_path / "blobs"), tmp_path / "media"
    )
    r = start(db_path, {"openrouter": llm}, NoPrices(), worker=False, media=media)
    roles: tuple[tuple[Role, str], ...] = (
        ("generator", "qwen/qwen3.8-27b"),
        ("reviewer", "deepseek/deepseek-v4-pro"),
        ("grader", "qwen/qwen3.8-27b"),
        ("utility", "qwen/qwen3.8-27b"),
    )
    for role, model in roles:
        r.service.bind(role, "openrouter", model)
    r.service.put_setting("video.length", "short", "installation")
    r.service.put_setting("generation.buffer", 1, "installation")
    yield r
    r.close()


def first_video(rt: Runtime) -> tuple[str, dict[str, Any] | None]:
    path_id, _ = rt.service.create_path(PathForm(title="SQL", subject="SQL", goal="joins"))
    drain(rt)
    lesson = lessons_of(rt, path_id)[0]
    return lesson["id"], rt.service.video_of(lesson["id"])


def test_a_published_lesson_gets_a_reviewed_video_with_a_caption_track(
    rt: Runtime, llm: fakes.FakeLLM, db_path: Path, renderer: FakeRenderer
) -> None:
    llm.script["video_visual"] = [major()]  # round 0: one major issue; round 1 is clean
    lesson_id, video = first_video(rt)
    assert video is not None and video["state"] == "ready"
    assert set(video["assets"]) == {"video", "subtitles", "poster"}
    assert renderer.renders == 1  # only the best round is rendered in full
    stages = llm.stages()
    assert stages.count("video_author") == 2 and stages.count("video_visual") == 2
    assert stages.count("video_ground") == stages.count("video_text") >= 1  # same inputs: a cache hit
    ground = next(r for s, r in llm.calls if s == "video_ground").messages[-1].content
    assert ground.startswith("Lesson:\n") and "Video, per sentence:" in ground
    fix = [r for s, r in llm.calls if s == "video_author"][1].messages[-1].content
    assert "the label is cut off -> fix: make the box wider" in fix and "Your current version" in fix
    vtt, _ = rt.service.asset_file(video["assets"]["subtitles"])
    cues = [ln for ln in vtt.read_text().splitlines() if ln and "-->" not in ln and not ln.isdigit()][1:]
    script = fakes.video_script()
    assert cues == [g for s in script["scenes"] for g in s["segments"]]  # one cue per sentence
    c = sqlite3.connect(db_path)
    spec, narration = c.execute(
        "SELECT spec, narration FROM rendition_version WHERE id = ?", (video["version_id"],)
    ).fetchone()
    rounds = json.loads(spec)["rounds"]
    assert [r["blocker_major"] for r in rounds] == [1, 0] and json.loads(spec)["best_round"] == 1
    assert json.loads(narration)["scenes"][0]["segments"][0]["text"] == script["scenes"][0]["segments"][0]
    visual = next(r for s, r in llm.calls if s == "video_visual")
    assert visual.messages[-1].images and visual.messages[-1].images[0].endswith("sheet_00.jpg")
    assert rt.service.lesson_view(lesson_id)["state"] == "ready"


def test_a_module_that_never_compiles_leaves_the_reading_lesson(
    rt: Runtime, renderer: FakeRenderer, llm: fakes.FakeLLM
) -> None:
    renderer.fail_check = 99
    lesson_id, video = first_video(rt)
    assert video is not None and video["state"] == "failed" and video["version_id"] is None
    assert rt.service.lesson_view(lesson_id)["state"] == "ready"
    authors = [r for s, r in llm.calls if s == "video_author"]
    assert len(authors) == 3  # one call and two repairs
    assert "lines around" not in authors[1].messages[-1].content  # (the fake module has no line 3 context)
    assert "TS2322" in authors[1].messages[-1].content


def test_a_repair_that_does_not_improve_ends_the_loop(rt: Runtime, llm: fakes.FakeLLM, db_path: Path) -> None:
    """in 12 of 15 videos all four rounds ran and in 7 an earlier round won. A repair no
    better than the best round ends the loop, and the best round is the one published."""
    worse = {"overall": 3, "issues": [major()["issues"][0]] * 3}
    llm.script["video_visual"] = [major(), worse, major(), major()]
    _, video = first_video(rt)
    assert video is not None and video["state"] == "ready"
    assert len([s for s in llm.stages() if s == "video_author"]) == 2  # one repair, then it stops
    spec = json.loads(
        sqlite3.connect(db_path)
        .execute("SELECT spec FROM rendition_version WHERE id = ?", (video["version_id"],))
        .fetchone()[0]
    )
    assert spec["best_round"] == 0 and [r["round"] for r in spec["rounds"]] == [0, 1]


def test_a_repair_gets_the_heavy_issues_and_only_their_scenes(
    rt: Runtime, llm: fakes.FakeLLM, db_path: Path
) -> None:
    """A repair used to get every issue, minors included, and rewrote 41-55% of the module each round."""
    minor = {"still": "s0-1", "severity": "minor", "problem": "the colour is a bit dull", "fix": "brighter"}
    llm.script["video_visual"] = [{"overall": 5, "issues": [major("s2-0")["issues"][0], minor]}]
    script = fakes.video_script()
    script["scenes"][3]["label"] = "Renamed"  # the repair also touches a scene outside its scope
    llm.script["video_author"] = [fakes.video_reply(), fakes.video_reply(script)]
    _, video = first_video(rt)
    fix = [r for s, r in llm.calls if s == "video_author"][1].messages[-1].content
    assert "Change only these scenes: s2 " in fix
    assert "the label is cut off" in fix and "the colour is a bit dull" not in fix
    assert video is not None
    rounds = json.loads(
        sqlite3.connect(db_path)
        .execute("SELECT spec FROM rendition_version WHERE id = ?", (video["version_id"],))
        .fetchone()[0]
    )["rounds"]
    assert rounds[1]["scope"] == ["s2"] and rounds[1]["outside_scope"] == ["s3"]
    assert 0 <= rounds[1]["changed_lines"] < 0.5


def test_repair_scope_follows_the_stills() -> None:
    from yuo.content import video as cv

    ids = ["intro", "two-part", "recap"]
    assert cv.still_scenes("two-part-3", ids) == ["two-part"]
    assert cv.still_scenes("[two-part-3]", ids) == ["two-part"]  # the text critic's form
    assert cv.still_scenes("intro-0 .. recap-1 (7 stills)", ids) == ids
    assert cv.still_scenes("the whole video", ids) is None
    issues = [{"still": "recap-0", "severity": "blocker", "problem": "x", "fix": ""},
              {"still": "intro-1", "severity": "minor", "problem": "y", "fix": ""}]  # fmt: skip
    assert cv.repair_scope(issues, ids) == ([issues[0]], ["recap"])
    issues.append({"still": "everywhere", "severity": "major", "problem": "z", "fix": ""})
    assert cv.repair_scope(issues, ids)[1] is None  # an issue about the whole video: any scene may change


def test_the_video_is_made_in_one_theme_that_follows_the_app(
    rt: Runtime, renderer: FakeRenderer, db_path: Path
) -> None:
    """Videos were always navy. 'Match app' is the default; with the app theme
    following a device that has not reported yet, the video is light, and the author, stills and render agree."""
    _, video = first_video(rt)
    assert video is not None and set(renderer.themes) == {"light"}
    spec = (
        sqlite3.connect(db_path)
        .execute("SELECT spec FROM rendition_version WHERE id = ?", (video["version_id"],))
        .fetchone()[0]
    )
    assert json.loads(spec)["theme"] == "light"


def test_the_video_theme_resolves_from_the_settings(rt: Runtime) -> None:
    from yuo.app.video import video_theme

    path_id, _ = rt.service.create_path(PathForm(title="SQL", subject="SQL", goal="joins"))
    with rt.service.readers.connection() as c:
        learner = c.execute("SELECT learner_id FROM path WHERE id = ?", (path_id,)).fetchone()[0]

    def theme() -> str:
        with rt.service.readers.connection() as c:
            return video_theme(c, path_id, learner)

    assert theme() == "light"  # match app, app follows the device, nothing reported yet
    rt.service.put_setting("ui.device_scheme", "dark", "learner", learner)
    assert theme() == "dark"  # the device showed the app dark
    rt.service.put_setting("ui.theme", "light", "learner", learner)
    assert theme() == "light"  # the app is always light
    rt.service.put_setting("video.theme", "dark", "learner", learner)
    assert theme() == "dark"  # an explicit video theme wins
    rt.service.put_setting("video.theme", "light", "path", path_id)
    assert theme() == "light"  # and a path can set its own


def test_unknown_words_get_a_pronunciation_first(rt: Runtime, llm: fakes.FakeLLM, voice: FakeVoice) -> None:
    voice.unknown = ["Debezium"]
    first_video(rt)
    assert "pronounce" in llm.stages() and voice.lexicon == {"Debezium": "tɛst"}


def test_reading_only_makes_no_video(rt: Runtime, llm: fakes.FakeLLM) -> None:
    rt.service.put_setting("video.format", "reading", "installation")
    _, video = first_video(rt)
    assert video is None and "video_author" not in llm.stages()


@needs_renderer
@pytest.mark.skipif(not (KOKORO / "kokoro-v1.0.onnx").exists(), reason="Kokoro model files missing")
def test_a_real_render_with_kokoro(db_path: Path, tmp_path: Path, llm: fakes.FakeLLM) -> None:
    from yuo.adapters.tts.kokoro import KokoroTTS

    renderer = RemotionRenderer(
        ROOT / "renderer", tmp_path / "render", chrome=str(CHROME), chrome_libs=str(LIBS)
    )
    media = Media(
        renderer, {"kokoro": KokoroTTS(KOKORO)}, FFmpeg(), BlobStore(tmp_path / "blobs"), tmp_path / "media"
    )
    rt = start(db_path, {"openrouter": llm}, NoPrices(), worker=False, media=media)
    try:
        for role in ("generator", "reviewer", "grader", "utility"):
            rt.service.bind(role, "openrouter", "qwen/qwen3.8-27b")
        rt.service.put_setting("video.length", "short", "installation")
        rt.service.put_setting("generation.buffer", 1, "installation")
        llm.script["video_author"] = [fakes.video_reply(fakes.video_script(scenes=3, per_scene=3, words=200))]
        _, video = first_video(rt)
        assert video is not None and video["state"] == "ready", rt.service.active_jobs()
        mp4, mt = rt.service.asset_file(video["assets"]["video"])
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "default=nw=1:nk=1", str(mp4)],
            capture_output=True, text=True, check=True,
        ).stdout.split()  # fmt: skip
        assert mt == "video/mp4" and sorted(out) == [
            "audio",
            "video",
        ]  # no subtitle stream in the published file
        exported = rt.service.video_export(video["version_id"])
        streams = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "default=nw=1:nk=1", str(exported)],
            capture_output=True, text=True, check=True,
        ).stdout.split()  # fmt: skip
        assert "subtitle" in streams  # the export carries a soft subtitle track
        assert abs(video["duration_s"] - FFmpeg().duration(mp4)) < 1.0
    finally:
        rt.close()


@pytest.mark.skipif(not (KOKORO / "kokoro-v1.0.onnx").exists(), reason="the Kokoro model is not installed")
def test_kokoro_says_a_lone_symbol_and_passes_over_a_stray_one() -> None:
    from yuo.adapters.tts.kokoro import KokoroTTS

    k = KokoroTTS(KOKORO)
    ps, unknown = k.phonemes("client / server, a = b | c")  # the overnight run failed on a lone '/'
    assert unknown == [] and all(k.phonemes(w)[0] in ps for w in ("slash", "equals"))
    assert k.phonemes("TCP/IP")[1] == []


def test_a_render_container_still_starting_means_try_again_later(
    rt: Runtime, renderer: FakeRenderer, db_path: Path
) -> None:
    """An update restarts both containers; videos picked up before the render container's
    first heartbeat failed for good with no_container. Now they wait and retry."""
    rt.service.create_path(PathForm(title="SQL", subject="SQL", goal="joins"))
    c = sqlite3.connect(db_path)
    for _ in range(200):
        if c.execute(
            "SELECT 1 FROM generation_job WHERE kind = 'rendition' AND status = 'queued'"
        ).fetchone():
            break
        assert rt.worker.run_once()
    renderer.available = lambda: "no_container"  # type: ignore[method-assign]
    for _ in range(200):
        if c.execute("SELECT error FROM generation_job WHERE kind = 'rendition'").fetchone()[0]:
            break
        assert rt.worker.run_once()
    job = c.execute("SELECT status, error FROM generation_job WHERE kind = 'rendition'").fetchone()
    assert job[0] == "queued" and "no_container" in job[1]  # waits for a later attempt, not failed
    assert c.execute("SELECT state FROM rendition").fetchone() == ("queued",)
    # every attempt used up: the job fails and so does the video
    for _ in range(3):
        c.execute("UPDATE generation_job SET next_attempt_at = NULL WHERE kind = 'rendition'")
        c.commit()
        rt.worker.run_once()
    assert c.execute("SELECT status FROM generation_job WHERE kind = 'rendition'").fetchone() == ("failed",)
    assert c.execute("SELECT state FROM rendition").fetchone() == ("failed",)

    lesson_id = c.execute("SELECT lesson_id FROM rendition").fetchone()[0]
    # a video left "queued" with no job working on it reads as failed, so the lesson
    # offers to make it again instead of "being made" for ever
    c.execute("UPDATE rendition SET state = 'queued'")
    c.commit()
    assert (rt.service.video_of(lesson_id) or {}).get("state") == "failed"

    # the learner asks again once the render container is there: a new job, the video queued
    renderer.available = lambda: None  # type: ignore[method-assign]
    failed = c.execute("SELECT id FROM generation_job WHERE kind = 'rendition'").fetchone()[0]
    listed = next(j for j in rt.service.active_jobs() if j["id"] == failed)
    assert listed["lesson_id"] == lesson_id  # the jobs list links the lesson
    job_id = rt.service.retry_job(failed)  # from the jobs list
    assert rt.service.retry_video(lesson_id) == job_id  # asking twice does not queue twice
    with pytest.raises(ValueError):
        rt.service.retry_job(job_id)  # only a failed job
    assert c.execute("SELECT state FROM rendition").fetchone() == ("queued",)
    assert c.execute("SELECT status FROM generation_job WHERE id = ?", (job_id,)).fetchone() == ("queued",)
    assert (rt.service.video_of(lesson_id) or {}).get("state") == "queued"  # a job works on it again


def test_a_failed_render_is_tried_again_from_the_chosen_draft(
    rt: Runtime, llm: fakes.FakeLLM, renderer: FakeRenderer, db_path: Path, tmp_path: Path
) -> None:
    """The final render of a four-round video failed (a full temp folder) and the retry
    wrote and reviewed four new drafts. The chosen draft is kept; the retry only renders it."""
    llm.script["video_visual"] = [major()]  # round 0 has a major issue, round 1 is chosen
    real = renderer.render
    renderer.render = lambda *a: (_ for _ in ()).throw(  # type: ignore[method-assign]
        MediaError("ENOSPC: no space left on device")
    )
    lesson_id, video = first_video(rt)
    assert video is not None and video["state"] == "failed"
    kept = tmp_path / "media" / "kept-drafts"
    assert len(list(kept.glob("*.json"))) == 1
    authors = llm.stages().count("video_author")

    renderer.render = real  # type: ignore[method-assign]
    rt.service.retry_video(lesson_id)
    drain(rt)
    video = rt.service.video_of(lesson_id)
    assert video is not None and video["state"] == "ready"
    assert llm.stages().count("video_author") == authors  # no new drafts, no new reviews
    spec = json.loads(
        sqlite3.connect(db_path)
        .execute("SELECT spec FROM rendition_version WHERE id = ?", (video["version_id"],))
        .fetchone()[0]
    )
    assert spec["best_round"] == 1 and [r["blocker_major"] for r in spec["rounds"]] == [1, 0]
    assert not list(kept.glob("*.json"))  # published: nothing kept

    # the jobs list: the failed render is no problem now, the history keeps both
    videos = [j for j in rt.service.active_jobs() if j["kind"] == "rendition"]
    assert videos == []
    done = [j for j in rt.service.job_history()["jobs"] if j["kind"] == "rendition"]
    assert [(j["status"], j["resolved"]) for j in done] == [("succeeded", False), ("failed", True)]
    assert done[1]["lesson_id"] == lesson_id and done[1]["finished_at"] and done[1]["started_at"]
    page = rt.service.job_history(limit=1)
    assert len(page["jobs"]) == 1 and page["next"]
    rest = rt.service.job_history(page["next"], limit=500)
    assert page["jobs"][0]["id"] not in {j["id"] for j in rest["jobs"]} and rest["next"] is None
    assert len(rest["jobs"]) + 1 == len(rt.service.job_history(limit=500)["jobs"])


def test_a_kept_draft_that_keeps_failing_is_dropped(
    rt: Runtime, llm: fakes.FakeLLM, renderer: FakeRenderer, tmp_path: Path
) -> None:
    renderer.render = lambda *a: (_ for _ in ()).throw(  # type: ignore[method-assign]
        MediaError("TypeError: x is undefined")
    )
    lesson_id, _ = first_video(rt)
    kept = next((tmp_path / "media" / "kept-drafts").glob("*.json"))
    authors = llm.stages().count("video_author")
    for _ in range(2):  # two renders from the kept draft
        rt.service.retry_video(lesson_id)
        drain(rt)
    assert llm.stages().count("video_author") == authors and json.loads(kept.read_text())["tries"] == 2
    rt.service.retry_video(lesson_id)  # then the loop starts over and keeps its new choice
    drain(rt)
    assert json.loads(kept.read_text())["tries"] == 0


def test_notes_from_the_video_reach_the_tutor_with_their_moment(rt: Runtime, llm: fakes.FakeLLM) -> None:
    """The notes bubble: questions jotted at a moment of
    the video, listed with the lesson's notes and sent to the tutor together."""
    rt.service.bind("tutor", "openrouter", "qwen/qwen3.8-27b")
    lesson_id, video = first_video(rt)
    assert video is not None and video["state"] == "ready"
    first = rt.service.add_note("why is B next to C?", rendition_version_id=video["version_id"], t_s=65.4)
    second = rt.service.add_note("what is a semitone?", rendition_version_id=video["version_id"], t_s=12.0)
    notes = rt.service.notes(lesson_id)
    assert [(n["text"], n["t_s"]) for n in notes] == [
        ("why is B next to C?", 65.4),
        ("what is a semitone?", 12.0),
    ]
    assert all(
        n["rendition_version_id"] == video["version_id"] and n["sent_message_id"] is None for n in notes
    )
    sent = rt.service.send_message(
        new_id(), "I left notes on this video.", {"lesson_id": lesson_id, "note_ids": [first, second]}
    )
    assert rt.service.run_tutor_turn()
    prompt = "\n".join(m.content for m in [r for s, r in llm.calls if s == "tutor"][-1].messages)
    assert prompt.index("(at 0:12 in the video) what is a semitone?") < prompt.index(
        "(at 1:05 in the video) why is B next to C?"
    )
    assert {n["sent_message_id"] for n in rt.service.notes(lesson_id)} == {sent["id"]}


def test_a_video_paused_after_its_first_review_goes_on_from_there(
    rt: Runtime, llm: fakes.FakeLLM, renderer: FakeRenderer
) -> None:
    def review_then_pause(request: Any) -> Any:
        rt.service.set_generation_pause("videos", None)  # paused while the call runs: it still finishes
        return major()

    llm.script["video_visual"] = [review_then_pause]
    lesson_id, video = first_video(rt)
    assert video is not None and video["state"] == "queued" and renderer.renders == 0
    assert rt.service.lesson_view(lesson_id)["state"] == "ready"  # lessons keep coming: only videos wait
    assert llm.stages().count("video_author") == 1
    assert rt.service.generation_pause()["waiting"] == 1

    rt.service.set_generation_pause(None, None)
    drain(rt)
    video = rt.service.video_of(lesson_id)
    assert video is not None and video["state"] == "ready" and renderer.renders == 1
    # the same calls as a video that was never paused: the first draft and its review came from the store
    assert llm.stages().count("video_author") == 2 and llm.stages().count("video_visual") == 2
