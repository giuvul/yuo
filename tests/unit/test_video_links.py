"""Lessons built on a YouTube video: the search words, which candidates are read, the transcript as the model reads
it, the ranking's rules, and the YouTube adapter's answers mapped to the learner's notes."""

from typing import Any

import httpx
import pytest

from yuo.adapters import youtube as ya
from yuo.app import video_links as vl
from yuo.core.online_video import Candidate, Line, OnlineVideoError


def cand(n: int, **kw: Any) -> Candidate:
    return Candidate(f"v{n}", f"t{n}", f"c{n}", f"UC{n}", **({"duration_ms": 10 * 60_000} | kw))


def test_the_search_words_are_the_lesson_then_its_skill_then_the_path_when_short() -> None:
    assert (
        vl.search_query("Left joins", "Joins in SQL", "SQL for analysts") == "Left joins in SQL for analysts"
    )
    long = vl.search_query("Window functions with partitions and frames", "Window functions", "SQL")
    assert long == "Window functions with partitions and frames"
    assert vl.search_query("Joins: another look", "Joins", "SQL") == "Joins SQL"


def test_prerank_keeps_embeddable_lesson_length_videos_and_puts_turned_down_channels_last() -> None:
    found = [
        cand(1, duration_ms=60_000),  # too short
        cand(2, embeddable=False),
        cand(3, for_kids=True),
        cand(4),
        cand(5, duration_ms=None),
        cand(6),
        cand(7, duration_ms=4 * 3_600_000),  # too long
    ]
    assert [c.video_id for c in vl.prerank(found, avoid={"UC4"}, exclude={"v6"})] == ["v5", "v4"]


def test_a_long_transcript_is_cut_to_the_stretch_richest_in_the_lessons_words() -> None:
    lines = [
        Line(s * 1000, (s + 15) * 1000, "intro chatter about nothing at all") for s in range(0, 1800, 15)
    ]
    lines[60] = Line(900_000, 915_000, "a left join keeps rows; left join versus inner join")
    text = vl.condensed(lines, {"left", "join"}, budget=600)
    assert "left join" in text and text.startswith("[...]") and len(text) <= 620
    short = vl.condensed(lines[:4], set())
    assert short.startswith("[0:00] intro") and "[...]" not in short


def test_the_stretch_holds_only_its_lines_with_times() -> None:
    lines = [Line(s * 1000, (s + 10) * 1000, f"p{s}") for s in range(0, 600, 10)]
    text = vl.stretch(lines, 120_000, 240_000)
    assert text.startswith("[2:00] p120") and "p110" not in text and "p240" not in text
    assert vl.mmss(3_725_000) == "1:02:05" and vl.parse_time("1:02:05") == 3_725_000
    assert vl.parse_time("9:30") == 570_000 and vl.parse_time("nine") is None


def test_the_ranking_rules() -> None:
    rules = vl.pick_rules(2, [600_000, None])
    ok = vl.VideoPick(videos=[vl.PickedVideo(n=1, start="1:00", end="9:00", coverage="full")])
    assert rules(ok) == []
    bad = vl.VideoPick(
        videos=[
            vl.PickedVideo(n=3, start="0:00", end="1:00", coverage="full"),
            vl.PickedVideo(n=1, start="9:00", end="1:00", coverage="full"),
            vl.PickedVideo(n=1, start="11:00", end="12:00", coverage="partial"),
            vl.PickedVideo(n=2, start="soon", end="later", coverage="partial"),
        ]
    )
    assert rules(bad) == [
        "video 3 is not in the list (1 to 2)",
        "video 1: the end comes before the start",
        "video 1 is listed twice",
        "video 1: the start is past the end of the video (10:00)",
        "video 2: start and end are m:ss times",
    ]


def youtube(handler: Any, key: str | None = "AIzaTEST") -> ya.YouTube:
    return ya.YouTube(lambda: key, client=httpx.Client(transport=httpx.MockTransport(handler)), proxy="")


def test_a_search_with_a_key_reads_the_videos_details() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/search"):
            assert req.url.params["relevanceLanguage"] == "it" and req.url.params["videoEmbeddable"] == "true"
            return httpx.Response(200, json={"items": [{"id": {"videoId": "a"}}, {"id": {"videoId": "b"}}]})
        assert req.url.params["id"] == "a,b"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "b",
                        "snippet": {
                            "title": "B",
                            "channelTitle": "Ch",
                            "channelId": "UCb",
                            "publishedAt": "2026-01-02T00:00:00Z",
                        },
                        "contentDetails": {"duration": "PT1H2M3S"},
                        "statistics": {"viewCount": "42"},
                        "status": {"embeddable": True, "madeForKids": False},
                    }
                ]
            },
        )

    found = youtube(handler).search("joins", "it", 5)
    assert found == [Candidate("b", "B", "Ch", "UCb", 3_723_000, 42, "2026-01-02", True, False)]


@pytest.mark.parametrize(
    ("status", "reason", "kind"),
    [(403, "quotaExceeded", "quota"), (400, "keyInvalid", "bad_key"), (500, "backendError", "network")],
)
def test_the_apis_refusals_become_the_learners_notes(status: int, reason: str, kind: str) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"errors": [{"reason": reason}]}})

    with pytest.raises(OnlineVideoError) as e:
        youtube(handler).search("joins", "en", 5)
    assert e.value.kind == kind


def test_a_video_that_is_gone_or_not_embeddable_is_not_available() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        vid = req.url.params["url"].rsplit("=", 1)[1]
        if vid == "ok":
            return httpx.Response(200, json={"title": "T", "author_name": "A"})
        return httpx.Response(401 if vid == "private" else 404)

    yt = youtube(handler, key=None)
    assert yt.available("ok") == ("T", "A")
    assert yt.available("private") is None and yt.available("gone") is None
    assert ya.iso_duration_ms("PT45S") == 45_000 and ya.iso_duration_ms("P1DT1S") == 86_401_000
    assert ya.iso_duration_ms("") is None
