"""YouTube for lessons built on an existing video: search, a video's details, its captions, and whether it is still
there.

- Search goes through the YouTube Data API when the learner gave a key (100 searches a day on a free key), else
  through yt-dlp's search, which needs no key.
- Captions come from youtube-transcript-api. It reads YouTube's web player data, not a published API: YouTube
  may refuse it, mostly from cloud servers. `YUO_YOUTUBE_PROXY` (an http or https proxy URL) routes it through a
  proxy.
- When YouTube refuses the captions (it does from most cloud servers), the video's sound alone is downloaded with
  yt-dlp (YouTube still serves it there) and Yuo transcribes it on this machine (yuo.app.video_links). The picture
  is never downloaded, and the sound is deleted once transcribed.
- Whether a video can still be shown is asked of YouTube's oEmbed endpoint, which needs no key.
"""

import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import structlog

from yuo.core.online_video import Candidate, Line, OnlineVideoError, Transcript

log = structlog.get_logger(__name__)

API = "https://www.googleapis.com/youtube/v3"
OEMBED = "https://www.youtube.com/oembed"
TIMEOUT = 20.0
AUDIO_MAX_BYTES = 200 * 1024 * 1024  # a sound track larger than this is not downloaded (hours of video)
KEY_CHECK_VIDEO = "jNQXAC9IVRw"  # the first video on YouTube: a stable id to check a key with (1 unit)
_DURATION = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def iso_duration_ms(value: str | None) -> int | None:
    """`PT1H2M3S` as milliseconds."""
    m = _DURATION.fullmatch(value or "")
    if not m or not any(m.groups()):
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 3600 + mi * 60 + s) * 1000


def _api_error(r: httpx.Response) -> OnlineVideoError:
    try:
        reasons = {e.get("reason") for e in r.json()["error"]["errors"]}
    except Exception:
        reasons = set()
    if reasons & {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}:
        return OnlineVideoError("quota", "the YouTube key's daily searches are used up")
    if r.status_code in (400, 401, 403):
        return OnlineVideoError("bad_key", f"YouTube refused the key ({r.status_code})")
    return OnlineVideoError("network", f"YouTube answered {r.status_code}")


class YouTube:
    def __init__(
        self,
        key: Callable[[], str | None],
        *,
        client: httpx.Client | None = None,
        proxy: str | None = None,
    ) -> None:
        self._key = key
        self._http = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True)
        self._proxy = proxy if proxy is not None else os.environ.get("YUO_YOUTUBE_PROXY") or None

    # --- search ----------------------------------------------------------------------------------

    def search(self, query: str, lang: str, limit: int) -> list[Candidate]:
        key = self._key()
        return self._api_search(key, query, lang, limit) if key else self._keyless_search(query, limit)

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            r = self._http.get(f"{API}/{path}", params=params)
        except httpx.HTTPError as e:
            raise OnlineVideoError("network", str(e)) from e
        if r.status_code != 200:
            raise _api_error(r)
        out: dict[str, Any] = r.json()
        return out

    def _api_search(self, key: str, query: str, lang: str, limit: int) -> list[Candidate]:
        found = self._get(
            "search",
            {
                "part": "snippet",
                "type": "video",
                "q": query,
                "maxResults": min(limit, 50),
                "relevanceLanguage": lang,
                "safeSearch": "strict",
                "videoEmbeddable": "true",
                "key": key,
            },
        )
        ids = [i["id"]["videoId"] for i in found.get("items", []) if i.get("id", {}).get("videoId")]
        if not ids:
            return []
        details = self._get(
            "videos",
            {"part": "snippet,contentDetails,statistics,status", "id": ",".join(ids), "key": key},
        )
        by_id = {v["id"]: v for v in details.get("items", [])}
        out = []
        for vid in ids:
            v = by_id.get(vid)
            if v is None:
                continue
            sn, st = v.get("snippet", {}), v.get("status", {})
            views = v.get("statistics", {}).get("viewCount")
            out.append(
                Candidate(
                    video_id=vid,
                    title=sn.get("title", ""),
                    channel=sn.get("channelTitle", ""),
                    channel_id=sn.get("channelId", ""),
                    duration_ms=iso_duration_ms(v.get("contentDetails", {}).get("duration")),
                    views=int(views) if views is not None else None,
                    published_at=(sn.get("publishedAt") or "")[:10] or None,
                    embeddable=bool(st.get("embeddable", True)),
                    for_kids=bool(st.get("madeForKids", False)),
                )
            )
        return out

    def _keyless_search(self, query: str, limit: int) -> list[Candidate]:
        import yt_dlp  # type: ignore[import-untyped]  # slow to import: only when a search runs without a key

        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
        }
        if self._proxy:
            opts["proxy"] = self._proxy
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        except Exception as e:  # yt-dlp raises its own DownloadError for every refusal
            text = str(e)
            kind = "blocked" if "bot" in text or "429" in text or "403" in text else "network"
            raise OnlineVideoError(kind, text[:300]) from e
        out = []
        for entry in (info or {}).get("entries") or []:
            if not entry or not entry.get("id") or entry.get("live_status") in ("is_live", "is_upcoming"):
                continue
            duration = entry.get("duration")
            out.append(
                Candidate(
                    video_id=entry["id"],
                    title=entry.get("title") or "",
                    channel=entry.get("channel") or entry.get("uploader") or "",
                    channel_id=entry.get("channel_id") or "",
                    duration_ms=int(duration * 1000) if duration else None,
                    views=entry.get("view_count"),
                )
            )
        return out

    def check_key(self, key: str) -> None:
        """OnlineVideoError(kind="bad_key") when YouTube refuses the key; costs one unit of its quota."""
        self._get("videos", {"part": "id", "id": KEY_CHECK_VIDEO, "key": key})

    # --- captions --------------------------------------------------------------------------------

    def transcript(self, video_id: str, langs: list[str]) -> Transcript:
        import youtube_transcript_api as yta
        from youtube_transcript_api.proxies import GenericProxyConfig

        proxy = GenericProxyConfig(http_url=self._proxy, https_url=self._proxy) if self._proxy else None
        api = yta.YouTubeTranscriptApi(proxy_config=proxy)
        try:
            listed = api.list(video_id)
            try:
                found = listed.find_manually_created_transcript(langs)
            except yta.NoTranscriptFound:
                found = listed.find_generated_transcript(langs)
            fetched = found.fetch()
        except (yta.RequestBlocked, yta.IpBlocked, yta.PoTokenRequired) as e:
            raise OnlineVideoError("blocked", "YouTube refused this server's request for captions") from e
        except (yta.NoTranscriptFound, yta.TranscriptsDisabled) as e:
            raise OnlineVideoError("no_transcript", "the video has no captions in these languages") from e
        except (yta.VideoUnavailable, yta.VideoUnplayable, yta.AgeRestricted, yta.InvalidVideoId) as e:
            raise OnlineVideoError("unavailable", "the video cannot be played") from e
        except yta.CouldNotRetrieveTranscript as e:
            raise OnlineVideoError("network", str(e)[:300]) from e
        except httpx.HTTPError as e:
            raise OnlineVideoError("network", str(e)[:300]) from e
        except Exception as e:  # requests' own errors (the library uses requests)
            raise OnlineVideoError("network", f"{type(e).__name__}: {str(e)[:300]}") from e
        lines = [
            Line(
                round(s.start * 1000), round((s.start + s.duration) * 1000), s.text.replace("\n", " ").strip()
            )
            for s in fetched.snippets
            if s.text.strip()
        ]
        return Transcript(fetched.language_code, fetched.is_generated, lines)

    # --- the sound, to transcribe when the captions are refused --------------------------------------

    def audio(self, video_id: str, folder: Path) -> Path:
        """The video's sound track (the smallest that is good enough for speech) in `folder`."""
        import yt_dlp

        folder.mkdir(parents=True, exist_ok=True)
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "format": "bestaudio[abr<=96]/bestaudio/worst",
            "outtmpl": str(folder / f"{video_id}.%(ext)s"),
            "noplaylist": True,
            "max_filesize": AUDIO_MAX_BYTES,
        }
        if self._proxy:
            opts["proxy"] = self._proxy
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
                path = Path(ydl.prepare_filename(info))
        except Exception as e:  # yt-dlp's DownloadError for every refusal
            text = str(e)
            if "unavailable" in text.lower() or "private" in text.lower():
                raise OnlineVideoError("unavailable", "the video cannot be played") from e
            kind = "blocked" if "bot" in text or "429" in text or "403" in text else "network"
            raise OnlineVideoError(kind, text[:300]) from e
        if not path.exists():
            raise OnlineVideoError("network", "the video's sound was not downloaded")
        return path

    # --- still there? ----------------------------------------------------------------------------

    def available(self, video_id: str) -> tuple[str, str] | None:
        try:
            r = self._http.get(
                OEMBED, params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"}
            )
        except httpx.HTTPError as e:
            raise OnlineVideoError("network", str(e)) from e
        if r.status_code in (400, 401, 403, 404):  # removed, private, or not allowed in other sites
            return None
        if r.status_code != 200:
            raise OnlineVideoError("network", f"YouTube answered {r.status_code}")
        data = r.json()
        return str(data.get("title", "")), str(data.get("author_name", ""))
