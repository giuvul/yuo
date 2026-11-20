"""Lessons built on a YouTube video (setting video.source): the search, the model's ranking, the lesson written
from the chosen stretch, the source a package carries, "Another video", the reading fallback and the check for
videos that are gone."""

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests import fakes
from tests.fakes_media import FakeFFmpeg, FakeRenderer, FakeTranscriber, FakeVoice, FakeYouTube
from tests.integration.test_slice import NoPrices, create, drain, lessons_of
from yuo.core.errors import Conflict
from yuo.core.llm import Role
from yuo.db.blobs import BlobStore
from yuo.main import Media, Runtime, start
from yuo.sharing import package as pk


@pytest.fixture
def llm() -> fakes.FakeLLM:
    return fakes.FakeLLM()


@pytest.fixture
def yt() -> FakeYouTube:
    return FakeYouTube()


@pytest.fixture
def rt(db_path: Path, tmp_path: Path, llm: fakes.FakeLLM, yt: FakeYouTube) -> Iterator[Runtime]:
    media = Media(
        FakeRenderer(),
        {"kokoro": FakeVoice()},
        FakeFFmpeg(),
        BlobStore(tmp_path / "blobs"),
        tmp_path / "media",
    )
    r = start(db_path, {"openrouter": llm}, NoPrices(), worker=False, media=media)
    roles: tuple[tuple[Role, str], ...] = (
        ("generator", "deepseek/deepseek-v4-pro"),
        ("reviewer", "qwen/qwen3.8-27b"),
        ("grader", "deepseek/deepseek-v4-pro"),
        ("utility", "deepseek/deepseek-v4-pro"),
    )
    for role, model in roles:
        r.service.bind(role, "openrouter", model)
    r.service.online_videos = yt
    yield r
    r.close()


def renditions(db_path: Path) -> int:
    return int(sqlite3.connect(db_path).execute("SELECT count(*) FROM rendition").fetchone()[0])


def test_a_lesson_is_written_from_the_chosen_stretch_of_a_youtube_video(
    rt: Runtime, llm: fakes.FakeLLM, yt: FakeYouTube, db_path: Path
) -> None:
    rt.service.put_setting("video.source", "youtube", "installation")
    path_id = create(rt)
    first = lessons_of(rt, path_id)[0]
    view = rt.service.lesson_view(first["id"])
    # the model ranked video 2 first, minutes 1:00 to 9:30
    assert view["youtube"] == {
        "video_id": "vid2aaaaaa",
        "title": "Video 2 on joins",
        "channel": "Channel 2",
        "start_s": 60,
        "end_s": 570,
        "gone": False,
        "note": None,
    }
    assert view["video_unavailable"] is None and view["video"] is None
    assert renditions(db_path) == 0  # no video made by Yuo
    stages = llm.stages()
    assert stages[1:5] == ["video_query", "video_pick", "lesson", "review"]
    assert yt.searches[:2] == ["sql left join explained", "sql joins tutorial"]  # the model's searches
    lesson_prompt = next(r for s, r in llm.calls if s == "lesson").messages[-1].content
    assert "Beyond the video:" in lesson_prompt and "in vid2aaaaaa a left join" in lesson_prompt
    assert "part 50 " not in lesson_prompt and "part 60 " in lesson_prompt  # only the stretch from 1:00
    review_prompt = next(r for s, r in llm.calls if s == "review").messages[-1].content
    assert "in vid2aaaaaa a left join" in review_prompt
    pick_prompt = next(r for s, r in llm.calls if s == "video_pick").messages[-1].content
    assert pick_prompt.count("<video n=") == 3  # three transcripts read
    c = sqlite3.connect(db_path)
    assert c.execute(
        "SELECT s.kind, s.url, s.data_class, vs.locator FROM lesson l JOIN lesson_version_source vs ON "
        "vs.lesson_version_id = l.current_version_id JOIN source s ON s.id = vs.source_id WHERE l.id = ?",
        (first["id"],),
    ).fetchone() == ("video", "https://www.youtube.com/watch?v=vid2aaaaaa", "C", "t=60-570")
    assert c.execute("SELECT count(*) FROM egress_record WHERE adapter = 'youtube'").fetchone()[0] == len(
        yt.searches
    )


def test_another_video_takes_the_next_ranked_one_without_a_new_search(
    rt: Runtime, llm: fakes.FakeLLM, yt: FakeYouTube, db_path: Path
) -> None:
    rt.service.put_setting("video.source", "youtube", "installation")
    path_id = create(rt)
    lesson = lessons_of(rt, path_id)[0]["id"]
    searches, picks = len(yt.searches), llm.stages().count("video_pick")
    rt.service.another(lesson)
    drain(rt)
    view = rt.service.lesson_view(lesson)
    assert view["youtube"]["video_id"] == "vid1aaaaaa" and (
        view["youtube"]["start_s"],
        view["youtube"]["end_s"],
    ) == (
        0,
        660,
    )
    assert len(yt.searches) == searches and llm.stages().count("video_pick") == picks
    ext = json.loads(
        sqlite3.connect(db_path).execute("SELECT extensions FROM path WHERE id = ?", (path_id,)).fetchone()[0]
    )
    assert ext["yuo"]["video_avoid"] == {"channels": ["UC2"]}  # the turned-down channel goes last next time
    # the ranked list is used up: the next one is a new search without the videos already seen
    rt.service.another(lesson)
    drain(rt)
    assert len(yt.searches) == searches + 2  # the lesson's two searches again
    assert rt.service.lesson_view(lesson)["youtube"]["note"] == "none"  # the fourth alone was not ranked


def test_refused_captions_leave_a_reading_lesson_with_the_reason(
    rt: Runtime, yt: FakeYouTube, db_path: Path
) -> None:
    rt.service.put_setting("video.source", "youtube", "installation")
    yt.refuse = "blocked"
    path_id = create(rt)
    lesson = lessons_of(rt, path_id)[0]
    view = rt.service.lesson_view(lesson["id"])
    assert view["body"] and view["youtube"]["video_id"] is None and view["youtube"]["note"] == "blocked"
    assert len(yt.transcripts) == 1  # refused once: the captions rest, the next lessons do not ask again
    assert yt.sounds == []  # no speech recognition on this installation: nothing to transcribe the sound with
    assert renditions(db_path) == 0  # a reading lesson: no video made by Yuo in its place


def test_refused_captions_are_replaced_by_the_videos_sound_transcribed_here(
    rt: Runtime, llm: fakes.FakeLLM, yt: FakeYouTube, db_path: Path, tmp_path: Path
) -> None:
    heard = FakeTranscriber()
    rt.service.ctx.transcriber = heard
    rt.service.put_setting("video.source", "youtube", "installation")
    yt.refuse = "blocked"
    path_id = create(rt)
    first = lessons_of(rt, path_id)[0]
    view = rt.service.lesson_view(first["id"])
    assert view["youtube"]["video_id"] == "vid2aaaaaa" and view["youtube"]["note"] is None
    assert len(yt.transcripts) == 1  # the captions were asked once, then rest
    pick_prompt = next(r for s, r in llm.calls if s == "video_pick").messages[-1].content
    assert pick_prompt.count("<video n=") == 2  # fewer videos a round when each is transcribed
    lesson_prompt = next(r for s, r in llm.calls if s == "lesson").messages[-1].content
    assert "heard in vid2aaaaaa: a left join" in lesson_prompt
    assert heard.calls[0]["fast"] is True and heard.calls[0]["lang"] is None
    assert not list((tmp_path / "media" / "youtube" / "sound").iterdir())  # the sound is deleted
    assert (tmp_path / "media" / "youtube" / "heard" / "vid2aaaaaa.json").exists()
    # "Another video" takes the second ranked one, already heard: not transcribed again
    count = len(heard.heard)
    rt.service.another(first["id"])
    drain(rt)
    assert rt.service.lesson_view(first["id"])["youtube"]["video_id"] == "vid1aaaaaa"
    assert len(heard.heard) == count


def test_a_heard_video_in_another_language_is_dropped(
    rt: Runtime, yt: FakeYouTube, llm: fakes.FakeLLM
) -> None:
    heard = FakeTranscriber()
    heard.languages = {"vid1aaaaaa": "de"}
    rt.service.ctx.transcriber = heard
    rt.service.put_setting("video.source", "youtube", "installation")
    yt.refuse = "blocked"
    yt.found[2] = type(yt.found[2])(
        "vid9aaaaaa", "Long lecture", "Ch", "UC9", 90 * 60_000, 10
    )  # too long to hear
    path_id = create(rt)
    first = lessons_of(rt, path_id)[0]
    pick_prompt = next(r for s, r in llm.calls if s == "video_pick").messages[-1].content
    assert "vid1aaaaaa" not in pick_prompt and "heard in vid2aaaaaa" in pick_prompt
    assert "vid9aaaaaa" not in yt.sounds  # longer than LISTEN_MAX_MS: not downloaded
    assert rt.service.lesson_view(first["id"])["youtube"]["video_id"] is not None


def test_made_by_yuo_never_asks_youtube(rt: Runtime, yt: FakeYouTube, db_path: Path) -> None:
    path_id = create(rt)
    assert yt.searches == [] and renditions(db_path) == 3
    assert rt.service.lesson_view(lessons_of(rt, path_id)[0]["id"])["youtube"] is None
    with pytest.raises(Conflict):
        rt.service.another(lessons_of(rt, path_id)[0]["id"])


def test_a_package_carries_the_video_and_not_the_learners_turned_down_channels(
    rt: Runtime, tmp_path: Path
) -> None:
    rt.service.put_setting("video.source", "youtube", "installation")
    path_id = create(rt)
    rt.service.another(lessons_of(rt, path_id)[0]["id"])
    drain(rt)
    out = tmp_path / "pkg"
    rt.service.export_package(path_id, out, profile="full")
    read = pk.read(out)
    keys = {s["key"]: s for s in read.records["source"]}
    assert keys["youtube:vid1aaaaaa"]["url"] == "https://www.youtube.com/watch?v=vid1aaaaaa"
    uses = [u for rec in read.records["lesson"] for v in rec["versions"] for u in v.get("sources", [])]
    assert {"key": "youtube:vid1aaaaaa", "locator": "t=0-660"} in uses
    path = read.records["path"][0]
    assert "video_avoid" not in json.dumps(path)
    imported = rt.service.import_package(out, mode="new")  # the copy shows the same video, same stretch
    copy = rt.service.lesson_view(lessons_of(rt, imported)[0]["id"])["youtube"]
    assert (copy["video_id"], copy["start_s"], copy["end_s"]) == ("vid1aaaaaa", 0, 660)


def test_the_monthly_check_marks_a_removed_video_and_refreshes_the_others(
    rt: Runtime, yt: FakeYouTube, db_path: Path
) -> None:
    rt.service.put_setting("video.source", "youtube", "installation")
    path_id = create(rt)
    lesson = lessons_of(rt, path_id)[0]["id"]
    assert rt.service.check_videos() == 0  # all checked today
    yt.gone = {"vid2aaaaaa"}
    assert rt.service.check_videos(older_than_days=-1) == 1
    assert rt.service.lesson_view(lesson)["youtube"]["gone"] is True
    yt.gone = set()
    rt.service.check_videos(older_than_days=-1)
    view = rt.service.lesson_view(lesson)["youtube"]
    assert (
        view["gone"] is False and view["title"] == "Renamed vid2aaaaaa" and view["channel"] == "New channel"
    )


def test_a_new_path_can_choose_its_own_videos(rt: Runtime, db_path: Path) -> None:
    path_id = create(rt, videos="youtube")  # the general setting stays "made by Yuo"
    assert rt.service.lesson_view(lessons_of(rt, path_id)[0]["id"])["youtube"]["video_id"] == "vid2aaaaaa"
    assert renditions(db_path) == 0
    other = create(rt, title="SQL 2", videos="reading")
    view = rt.service.lesson_view(lessons_of(rt, other)[0]["id"])
    assert view["youtube"] is None and view["video"] is None and renditions(db_path) == 0


def test_the_estimate_follows_the_kind_of_videos(rt: Runtime) -> None:
    reading, youtube = (rt.service.estimate(20, videos=v) for v in ("reading", "youtube"))
    units = {line.unit for line in youtube.lines}
    assert {"video_pick", "lesson_transcript", "review_transcript"} <= units and "video_scene" not in units
    assert "video_pick" not in {line.unit for line in rt.service.estimate(20, videos="generated").lines}
    assert reading.high_usd * 1.1 < youtube.high_usd < reading.high_usd * 1.3  # "about 10 to 25% more"
    assert "video_pick" not in {
        line.unit for line in rt.service.estimate(20).lines
    }  # the settings: made by Yuo
    rt.service.put_setting("video.source", "youtube", "installation")
    assert rt.service.estimate(20).high_usd == youtube.high_usd
    rt.service.put_setting("video.format", "reading", "installation")
    assert rt.service.estimate(20).high_usd == reading.high_usd


def test_on_a_subscription_youtube_is_a_small_part_of_the_plan_and_made_videos_a_large_one(
    rt: Runtime,
) -> None:
    for role in ("generator", "reviewer", "grader", "utility"):
        rt.service.bind(role, "claude-cli", "sonnet")
    reading, youtube, made = (rt.service.estimate(20, videos=v) for v in ("reading", "youtube", "generated"))
    assert not youtube.missing and not made.missing
    assert 1.05 < youtube.notional_usd / reading.notional_usd < 1.25
    assert made.notional_usd > 3 * reading.notional_usd
    assert youtube.as_dict()["plan_usage"][0]["week_pct"] < made.as_dict()["plan_usage"][0]["week_pct"]


def test_when_no_video_of_the_first_three_fits_the_next_ones_get_a_second_round(
    rt: Runtime, llm: fakes.FakeLLM, yt: FakeYouTube
) -> None:
    rt.service.put_setting("video.source", "youtube", "installation")
    llm.script["video_pick"] = [
        {"videos": []},
        {"videos": [{"n": 1, "start": "2:00", "end": "8:00", "coverage": "full"}]},
    ]
    path_id = create(rt)
    view = rt.service.lesson_view(lessons_of(rt, path_id)[0]["id"])["youtube"]
    assert (view["video_id"], view["start_s"], view["end_s"]) == (
        "vid4aaaaaa",
        120,
        480,
    )  # the fourth, read second


def test_searches_fall_back_to_the_titles_when_the_model_cannot_write_them(
    rt: Runtime, llm: fakes.FakeLLM, yt: FakeYouTube
) -> None:
    rt.service.put_setting("video.source", "youtube", "installation")
    llm.script["video_query"] = [{"queries": [{"text": "x", "lang": "xx"}]}] * 3  # never valid
    path_id = create(rt)
    view = rt.service.lesson_view(lessons_of(rt, path_id)[0]["id"])
    assert view["youtube"]["video_id"] == "vid2aaaaaa"
    # the first lesson searched its titles once; the next lessons' searches come from the model again
    assert yt.searches[0].endswith("SQL") and yt.searches[1:3] == [
        "sql left join explained",
        "sql joins tutorial",
    ]
