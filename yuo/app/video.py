"""Video by default: the whole-video review loop after a lesson passes its gate. A part of the application service (yuo.app.context).

One job per lesson video:
1. the author model writes the narration script and the TSX scene module, checked by the script rules and the
   compile (errors shown with their lines, up to two repairs);
2. the narration: unknown words get pronunciations (an LLM stage), then one clip per sentence (cached);
3. stills with the reviewers' caption overlay and the in-page layout probe; the visual critic (contact sheets),
   the consistency critic (on-screen text and source) and the grounded critic (facts against the lesson), all
   the author model;
4. up to 3 repair rounds on an API (1 on a local model), each from the best round so far, until no blocker or
   major issue is left or a repair does not improve on the best round; a repair gets the blocker and major
   issues only and may change only the scenes they are in;
5. the best round rendered to MP4 with the captions as a separate WebVTT track. The chosen draft is
   kept until the video is published, so a render that fails (a full disk, a restart) is tried again from it
   instead of from a new first draft.
A video that never compiles fails the rendition, and the lesson stays a reading lesson.

The video theme (light or dark) is resolved once when the job starts; the author sees that palette, and
the stills and the MP4 use it.
"""

import dataclasses
import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from yuo.app import video_stages as vs
from yuo.app.context import AppContext, Part
from yuo.app.ports import Models, PathInputs
from yuo.content import video as cv
from yuo.content.lesson_body import plain_text
from yuo.core import audio, clock
from yuo.core.enums import DataClass, EntityKind
from yuo.core.errors import InvalidInput, NotFound
from yuo.core.hashing import bytes_hash, content_hash
from yuo.core.ids import new_id
from yuo.core.media import VIDEO_THEMES, MediaError, Narration, TTSPort, VideoTheme
from yuo.generation import progress
from yuo.generation.jobs import MAX_ATTEMPTS, Job, enqueue
from yuo.generation.runner import BudgetExceeded, StageFailed, StageSpec
from yuo.setup import settings

if TYPE_CHECKING:
    from yuo.core.llm import Binding, Effort

log = structlog.get_logger(__name__)


MAX_FIX_API, MAX_FIX_LOCAL = 3, 1  # up to 3 repair rounds on an API, at most 1 on a local model
LESSON_CHARS = 12000
AUTHOR_TOKENS = {"short": 16000, "medium": 28000, "long": 40000}
RESUME_TRIES = 2  # renders from one kept draft before the loop starts over (a draft that never renders)


def video_theme(c: sqlite3.Connection, path_id: str, learner_id: str) -> VideoTheme:
    """The theme a new video of this path is made in: the setting, or for 'match_app' the UI theme,
    or when that follows the device, the look the device last showed."""
    chosen = settings.effective(c, "video.theme", {"path": path_id, "learner": learner_id})[0]
    if chosen in VIDEO_THEMES:
        return chosen  # type: ignore[no-any-return]
    ui = settings.effective(c, "ui.theme", {"learner": learner_id})[0]
    if ui in VIDEO_THEMES:
        return ui  # type: ignore[no-any-return]
    device = settings.effective(c, "ui.device_scheme", {"learner": learner_id})[0]
    return device if device in VIDEO_THEMES else "light"


@dataclass(slots=True)
class Best:
    score: float
    round: int
    draft: vs.VideoDraft
    run_id: str
    narration: Narration
    issues: list[dict[str, str]]


@dataclass(slots=True)
class Kept:
    """The draft a failed render left; its narration is rebuilt (the clips are cached)."""

    score: float
    round: int
    draft: vs.VideoDraft
    run_id: str
    issues: list[dict[str, str]]
    rounds: list[dict[str, Any]]
    theme: VideoTheme | None  # None: kept before themes, render in the current one


class Video(Part):
    """A part of the application service (yuo.app.context), built with what it calls on the others."""

    def __init__(self, ctx: AppContext, *, models: Models, paths: PathInputs) -> None:
        super().__init__(ctx)
        self.models = models
        self.paths = paths

    # --- when a video is wanted ------------------------------------------------------------------

    def video_unavailable(self) -> str | None:
        """None when videos can be made here, else a reason code (see `RendererPort.available`; `not_set_up`
        when no renderer is configured at all)."""
        if self.renderer is None or self.blobs is None:
            return "not_set_up"
        if (why := self.renderer.available()) is not None:
            return why
        return None

    def queue_video(self, c: sqlite3.Connection, lesson_id: str) -> str | None:
        """Inside a unit, after a lesson is published: a rendition job when video is on and possible."""
        path_id = c.execute("SELECT path_id FROM lesson WHERE id = ?", (lesson_id,)).fetchone()[0]
        fmt = settings.effective(c, "video.format", {"path": path_id})[0]
        if fmt == "reading" or self.video_unavailable() is not None:
            return None
        row = c.execute(
            "SELECT id, state FROM rendition WHERE lesson_id = ? AND kind = 'video'", (lesson_id,)
        ).fetchone()
        if row is None:
            rid = new_id()
            c.execute(
                "INSERT INTO rendition (id, lesson_id, kind, state, current_version_id) VALUES (?, ?, 'video', 'queued', NULL)",
                (rid, lesson_id),
            )
        else:
            rid = row[0]
            c.execute("UPDATE rendition SET state = 'queued' WHERE id = ?", (rid,))
        return enqueue(c, "rendition", EntityKind.RENDITION, rid, requested_by="system", priority=-1)

    def retry_video(self, lesson_id: str) -> str:
        """The learner asks for a lesson's video again after it failed (videos lost to a
        render container that was taken for stopped). Returns the job, or the one already running."""

        def unit(c: sqlite3.Connection) -> str:
            row = c.execute(
                "SELECT id, state FROM rendition WHERE lesson_id = ? AND kind = 'video'", (lesson_id,)
            ).fetchone()
            if row is None:
                raise NotFound(lesson_id)
            busy = c.execute(
                "SELECT id FROM generation_job WHERE target_id = ? AND status IN ('queued','running','waiting_resource')",
                (row[0],),
            ).fetchone()
            if busy:
                return str(busy[0])
            if (why := self.video_unavailable()) is not None:
                raise InvalidInput(f"videos cannot be made here: {why}")
            c.execute("UPDATE rendition SET state = 'queued' WHERE id = ?", (row[0],))
            return enqueue(c, "rendition", EntityKind.RENDITION, row[0], requested_by="learner")

        job = self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return job

    # --- the job ---------------------------------------------------------------------------------

    def handle_rendition(self, job: Job) -> None:
        rid = job.target_id
        try:
            self._video(job, rid)
        except (BudgetExceeded, MediaError) as e:
            retry = isinstance(e, BudgetExceeded) or e.retryable
            # a budget stop waits without using an attempt; anything else on the last attempt is final
            last = not isinstance(e, BudgetExceeded) and job.attempt >= MAX_ATTEMPTS
            self._set_rendition(rid, "queued" if retry and not last else "failed")
            log.warning("video.failed", rendition=rid, error=str(e)[:300], retry=retry and not last)
            # the job ends as the video does: failed (with its reason, in the jobs list) or queued again
            raise StageFailed(str(e), retryable=retry) from e
        except StageFailed:
            self._set_rendition(rid, "queued" if job.attempt < MAX_ATTEMPTS else "failed")
            raise
        except Exception:
            self._set_rendition(rid, "failed")
            raise

    def _set_rendition(self, rid: str, state: str) -> None:
        self.writer.run(lambda c: c.execute("UPDATE rendition SET state = ? WHERE id = ?", (state, rid)))

    def _video(self, job: Job, rid: str) -> None:
        if (why := self.video_unavailable()) is not None:
            # the render container may still be starting (an update restarts both): try again later
            raise MediaError(
                f"videos cannot be made here: {why}", retryable=why == "no_container", kind="resources"
            )
        assert self.renderer is not None
        with self.readers.connection() as c:
            r = c.execute(
                "SELECT r.lesson_id, l.path_id, l.skill_id, l.current_version_id, v.title, v.body, s.title AS skill, "
                "p.learner_id FROM rendition r JOIN lesson l ON l.id = r.lesson_id "
                "JOIN lesson_version v ON v.id = l.current_version_id JOIN skill s ON s.id = l.skill_id "
                "JOIN path p ON p.id = l.path_id WHERE r.id = ?",
                (rid,),
            ).fetchone()
            path, dclass = self.paths.path_inputs(c, r["path_id"])
            length = str(settings.effective(c, "video.length", {"path": r["path_id"]})[0])
            theme = video_theme(c, r["path_id"], r["learner_id"])
        voice = self.voices.get("kokoro")  # the one voice: local, no cost, nothing leaves the machine
        if voice is None:
            raise MediaError("the kokoro voice is not set up")
        self._set_rendition(rid, "generating")
        gen = self.models.binding("generator")
        port = self.runner.port(gen)
        base = {
            "topic": f"{r['title']} (skill: {r['skill']})",
            "lesson": plain_text(json.loads(r["body"]))[:LESSON_CHARS],
            "difficulty": path["difficulty"],
            "lang": path["lang"],
            "length": length,
            **self.renderer.kit(theme),
        }
        spec = vs.author_spec(length, self.renderer.check, AUTHOR_TOKENS[length])
        max_fix = MAX_FIX_API if port.remote else MAX_FIX_LOCAL
        work = self.media_dir / "work" / rid
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)

        if (kept := self._kept_draft(rid, r["current_version_id"])) is not None:
            log.info("video.resumed", rendition=rid, round=kept.round, score=kept.score)
            progress.step("narration")
            narration = self._narrate(job, kept.draft.script, voice, base["topic"], work, dclass)
            chosen = Best(kept.score, kept.round, kept.draft, kept.run_id, narration, kept.issues)
            self._publish_video(job, rid, r, chosen, kept.rounds, voice, work, kept.theme or theme)
            if not self.keep_video_work:
                shutil.rmtree(work, ignore_errors=True)
            return

        def author(k: int, inputs: dict[str, Any]) -> tuple[vs.VideoDraft, str] | None:
            try:
                out = self.runner.run(
                    job.id, spec, gen, inputs, data_class=dclass, fix_round=k, role="generator"
                )
            except StageFailed as e:
                if e.retryable:
                    raise
                log.info("video.author_failed", rendition=rid, round=k, error=str(e)[:300])
                return None
            return out.value, out.stage_run_id

        first = author(0, base | {"base": None, "issues": []})
        if first is None:
            raise MediaError("the scene module never compiled; the lesson stays a reading lesson")
        rounds: list[dict[str, Any]] = []
        best: Best | None = None
        draft, run_id = first
        for k in range(max_fix + 1):
            progress.rounds(k + 1, max_fix + 1)
            changed: dict[str, Any] = {}
            if k > 0:  # repair the best round so far: a worse round does not derail the loop
                assert best is not None
                b = best.draft
                # the blocker and major issues only, scoped to their scenes
                heavy_issues, scope = cv.repair_scope(best.issues, [s.id for s in b.script.scenes])
                got = author(
                    k,
                    base
                    | {
                        "base": {"script": b.script.model_dump(), "tsx": b.tsx},
                        "issues": cv.fix_lines(heavy_issues),
                        "scope": scope,
                    },
                )
                if got is None:
                    rounds.append({"round": k, "error": "the repair produced no valid module"})
                    break  # a failed repair is no improvement: stop with the best round
                draft, run_id = got
                changed = {"scope": scope} | cv.churn(b.script, b.tsx, draft.script, draft.tsx, scope)
            progress.step("narration")
            narration = self._narrate(job, draft.script, voice, base["topic"], work, dclass)
            progress.step("stills")
            stills = self.renderer.stills(draft.tsx, narration, work / f"round_{k}", theme)
            lint, lint_score = cv.probe_issues(stills.probe)
            critiques = self._critics(job, gen, draft, stills, base["topic"], base["lesson"])
            issues = lint + [
                {"source": src, **i.model_dump()}
                for src, crit in critiques.items()
                if crit
                for i in crit.issues
            ]
            score = lint_score + sum(cv.SEVERITY[i["severity"]] for i in issues if i["source"] != "layout")
            heavy = sum(i["severity"] in ("blocker", "major") for i in issues)
            rounds.append(
                {
                    "round": k,
                    "score": round(score, 1),
                    "lint": lint_score,
                    "blocker_major": heavy,
                    "visual_overall": critiques["visual"].overall if critiques["visual"] else None,
                    "text_overall": critiques["text"].overall if critiques["text"] else None,
                    "audio_s": narration.seconds,
                    **changed,
                }
            )
            log.info(
                "video.round", rendition=rid, round=k, score=round(score, 1), blocker_major=heavy,
                changed_lines=changed.get("changed_lines"), outside_scope=changed.get("outside_scope"),
            )  # fmt: skip
            if best is not None and score >= best.score:
                break  # this repair did not improve on the best round: another one rarely does
            best = Best(score, k, draft, run_id, narration, issues)
            if heavy == 0:
                break
        assert best is not None
        self._publish_video(job, rid, r, best, rounds, voice, work, theme)
        if not self.keep_video_work:  # the eval keeps the stills for its judge
            shutil.rmtree(work, ignore_errors=True)

    # --- narration ---------------------------------------------------------------------------------

    def _narrate(
        self, job: Job, script: cv.VideoScript, voice: TTSPort, topic: str, work: Path, dclass: DataClass
    ) -> Narration:
        sentences = script.sentences()
        unknown = getattr(voice, "unknown_words", None)  # a local voice that reads phonemes (Kokoro)
        if unknown is not None and (words := unknown(sentences)):
            out = self.runner.run(
                job.id,
                vs.pronounce_spec(words),
                self.models.binding("utility"),
                {"topic": topic, "words": words},
                role="utility",
            )
            voice.learn({p.word: p.ipa for p in out.value.words})  # type: ignore[attr-defined]
            progress.step("narration")
        cache = self.media_dir / "tts-cache" / voice.name
        cache.mkdir(parents=True, exist_ok=True)
        clips, cost = [], 0.0
        for text in sentences:
            key = hashlib.sha256(f"{voice.name}:{getattr(voice, 'voice', '')}:{text}".encode()).hexdigest()[
                :24
            ]
            wav = cache / f"{key}.wav"
            if not wav.exists():
                tmp = wav.with_suffix(".part.wav")
                cost += voice.synthesize(text, tmp)
                tmp.replace(wav)
            clips.append(wav)
        if cost:
            self._ledger_tts(voice, cost)
        out_wav = work / f"narration-{content_hash(sentences)[:12]}.wav"
        durations = audio.assemble(clips, cv.gaps(script), cv.TAIL_S, out_wav)
        timeline = cv.build_timeline(script, durations)
        return Narration(
            out_wav, timeline, timeline.duration_frames / timeline.fps, sum(map(len, sentences)), round(cost)
        )

    def _ledger_tts(self, voice: TTSPort, cost_micros: float) -> None:
        self.writer.run(
            lambda c: c.execute(
                "INSERT INTO budget_entry (id, stage_run_id, message_id, adapter, provider, in_tokens, out_tokens, "
                "reasoning_tokens, cost_micros, cost_currency, price_ref, estimated, at) VALUES (?, NULL, NULL, ?, ?, "
                "0, 0, 0, ?, 'USD', 'plan rate', 1, ?)",
                (new_id(), voice.name, voice.name, round(cost_micros), clock.now()),
            )
        )

    # --- critics -----------------------------------------------------------------------------------

    def _critics(
        self, job: Job, gen: Binding, draft: vs.VideoDraft, stills: Any, topic: str, lesson: str
    ) -> dict[str, vs.Critique | None]:
        out: dict[str, vs.Critique | None] = {}
        visual: dict[str, Any] = {
            "still_map": cv.still_map(stills.probe),
            "sheets": [str(p) for p in stills.sheets],
            "sheet_hashes": [
                bytes_hash(p.read_bytes()) for p in stills.sheets
            ],  # the manifest sees the images
        }
        text: dict[str, Any] = {"topic": topic, "on_screen": cv.on_screen(stills.probe), "tsx": draft.tsx}
        jobs: dict[str, tuple[StageSpec[vs.Critique], dict[str, Any]]] = {
            "visual": (vs.VISUAL_CRITIC, visual),
            "text": (vs.TEXT_CRITIC, text),
            "ground": (vs.GROUND_CRITIC, text | {"lesson": lesson}),  # facts against the reviewed lesson
        }
        for name, (spec, inputs) in jobs.items():
            # the author model as its own critic; efforts: low visual, medium text
            effort: Effort | None = (
                None if gen.effort in (None, "none") else ("low" if name == "visual" else "medium")
            )
            critic = dataclasses.replace(gen, temperature=0.2, effort=effort, role="reviewer")
            try:
                out[name] = self.runner.run(job.id, spec, critic, inputs, role="reviewer").value
            except StageFailed as e:
                if e.retryable:
                    raise
                log.info("video.critic_failed", critic=name, error=str(e)[:200])
                out[name] = None
        return out

    # --- publish -----------------------------------------------------------------------------------

    def _publish_video(
        self,
        job: Job,
        rid: str,
        r: sqlite3.Row,
        best: Best,
        rounds: list[dict[str, Any]],
        voice: TTSPort,
        work: Path,
        theme: VideoTheme,
    ) -> None:
        assert self.renderer is not None and self.blobs is not None
        score, k, draft, run_id, narration = best.score, best.round, best.draft, best.run_id, best.narration
        mp4 = work / "video.mp4"
        self._keep_draft(rid, r["current_version_id"], best, rounds, theme)
        progress.step("render")
        render_s = self.renderer.render(draft.tsx, narration, mp4, theme)
        vtt = cv.webvtt(narration.timeline).encode()
        poster = work / "poster.jpg"
        self.ffmpeg.poster(mp4, poster)
        files = {
            "video": (mp4.read_bytes(), "video/mp4", "video"),
            "subtitles": (vtt, "text/vtt", "subtitles"),
            "poster": (poster.read_bytes(), "image/jpeg", "image"),
        }
        hashes = {
            role: (self.blobs.put(data), mt, kind, len(data)) for role, (data, mt, kind) in files.items()
        }

        renderer = self.renderer

        def unit(c: sqlite3.Connection) -> None:
            now = clock.now()
            lang = c.execute(
                "SELECT lang FROM lesson_version WHERE id = ?", (r["current_version_id"],)
            ).fetchone()[0]
            no = c.execute(
                "SELECT coalesce(max(version_no), 0) + 1 FROM rendition_version WHERE rendition_id = ?",
                (rid,),
            ).fetchone()[0]
            vid = new_id()
            spec = {
                "script": draft.script.model_dump(),
                "tsx": draft.tsx,
                "best_round": k,
                "rounds": rounds,
                "score": score,
                "theme": theme,  # the palette the MP4 was rendered in
            }
            c.execute(
                "INSERT INTO rendition_version (id, rendition_id, version_no, version_hash, lesson_version_id, lang, renderer, "
                "spec_kind, spec, narration, theme_id, voice, duration_s, derived_from_version_id, status, published_at, "
                "created_at, authorship, acquired_via, author_kind, author_ref, produced_by_stage_run_id, upstream, licence, "
                "personal_inputs) VALUES (?, ?, ?, ?, ?, ?, ?, 'agent_code', json(?), json(?), NULL, ?, ?, NULL, 'passed', ?, ?, "
                "'generated', 'local', 'system', NULL, ?, NULL, NULL, 0)",
                (
                    vid, rid, no, content_hash(spec), r["current_version_id"], lang,
                    f"{renderer.name}@{renderer.version}", json.dumps(spec, ensure_ascii=False),
                    json.dumps(narration.timeline.to_json(), ensure_ascii=False), f"{voice.name}:{getattr(voice, 'voice', '')}",
                    narration.seconds, now, now, run_id,
                ),
            )  # fmt: skip
            for role, (digest, mt, kind, size) in hashes.items():
                c.execute(
                    "INSERT INTO asset (hash, media_type, kind, bytes, stored_at, retention_class, evicted_at, data_class, "
                    "created_at) VALUES (?, ?, ?, ?, ?, 'renewable', NULL, 'C', ?) ON CONFLICT(hash) DO NOTHING",
                    (digest, mt, kind, size, now, now),
                )
                c.execute(
                    "INSERT INTO rendition_asset (rendition_version_id, role, lang, recipe_hash, asset_hash) VALUES (?, ?, ?, ?, ?)",
                    (
                        vid,
                        role,
                        lang,
                        content_hash({"spec": spec, "role": role, "render_s": round(render_s)}),
                        digest,
                    ),
                )
            c.execute("UPDATE rendition SET current_version_id = ?, state = 'ready' WHERE id = ?", (vid, rid))
            c.execute(
                "INSERT INTO publication (id, head_kind, head_id, version_id, at, by) VALUES (?, 'rendition', ?, ?, ?, 'gate')",
                (new_id(), rid, vid, now),
            )

        self.writer.run(unit)
        self._kept_file(rid).unlink(missing_ok=True)
        log.info(
            "video.published",
            rendition=rid,
            round=k,
            score=score,
            seconds=narration.seconds,
            render_s=round(render_s),
        )

    # --- the kept draft ---------------------------------------------------------------------------

    def _kept_file(self, rid: str) -> Path:
        return self.media_dir / "kept-drafts" / f"{rid}.json"

    def _keep_draft(
        self, rid: str, lesson_version: str, best: Best, rounds: list[dict[str, Any]], theme: VideoTheme
    ) -> None:
        f = self._kept_file(rid)
        tries = 0
        if f.exists():  # a resumed render: keep its count
            tries = int(json.loads(f.read_text()).get("tries", 0))
        f.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "lesson_version": lesson_version,
            "draft": best.draft.model_dump(),
            "round": best.round,
            "score": best.score,
            "run_id": best.run_id,
            "issues": best.issues,
            "rounds": rounds,
            "theme": theme,  # the theme it was reviewed in: a retried render keeps it
            "tries": tries,
        }
        tmp = f.with_suffix(".part")
        tmp.write_text(json.dumps(rec, ensure_ascii=False))
        tmp.replace(f)

    def _kept_draft(self, rid: str, lesson_version: str) -> Kept | None:
        """The draft a failed render left, for this lesson version, while it has tries left."""
        f = self._kept_file(rid)
        if not f.exists():
            return None
        try:
            rec = json.loads(f.read_text())
            draft = vs.VideoDraft.model_validate(rec["draft"])
        except (ValueError, KeyError) as e:
            log.warning("video.kept_unreadable", rendition=rid, error=str(e)[:200])
            f.unlink(missing_ok=True)
            return None
        if rec.get("lesson_version") != lesson_version or int(rec.get("tries", 0)) >= RESUME_TRIES:
            f.unlink(missing_ok=True)  # the lesson changed, or this draft keeps failing: start over
            return None
        rec["tries"] = int(rec.get("tries", 0)) + 1
        f.write_text(json.dumps(rec, ensure_ascii=False))
        theme = rec.get("theme")
        return Kept(
            float(rec["score"]), int(rec["round"]), draft, str(rec["run_id"]), rec["issues"], rec["rounds"],
            theme if theme in VIDEO_THEMES else None,
        )  # fmt: skip

    # --- reading ---------------------------------------------------------------------------------

    def video_of(self, lesson_id: str) -> dict[str, Any] | None:
        with self.readers.connection() as c:
            row = c.execute(
                "SELECT r.id, r.state, r.current_version_id, v.duration_s, v.lang FROM rendition r LEFT JOIN rendition_version v "
                "ON v.id = r.current_version_id WHERE r.lesson_id = ? AND r.kind = 'video'",
                (lesson_id,),
            ).fetchone()
            if row is None:
                return None
            state = row["state"]
            if (
                state in ("queued", "generating", "in_review")
                and not c.execute(
                    "SELECT 1 FROM generation_job WHERE target_id = ? AND status IN ('queued','running','waiting_resource')",
                    (row["id"],),
                ).fetchone()
            ):
                # nothing works on it any more (its last attempt failed, or a state left by an older version):
                # the learner sees it failed and can ask for it again, not "being made" for ever
                state = "failed"
            assets = {
                a[0]: a[1]
                for a in c.execute(
                    "SELECT role, asset_hash FROM rendition_asset WHERE rendition_version_id = ?",
                    (row["current_version_id"],),
                )
            }
        return {
            "rendition_id": row["id"],
            "state": state,
            "version_id": row["current_version_id"],
            "duration_s": row["duration_s"],
            "lang": row["lang"],
            "assets": assets,
        }

    def asset_file(self, digest: str) -> tuple[Path, str]:
        assert self.blobs is not None
        with self.readers.connection() as c:
            row = c.execute(
                "SELECT media_type FROM asset WHERE hash = ? AND evicted_at IS NULL", (digest,)
            ).fetchone()
        path = self.blobs.path(digest)
        if row is None or not path.exists():
            raise NotFound(digest)
        return path, str(row[0])

    def video_export(self, rendition_version_id: str) -> Path:
        """The MP4 with the captions as a soft subtitle track, made on request and kept."""
        assert self.blobs is not None
        with self.readers.connection() as c:
            assets = {
                a[0]: a[1]
                for a in c.execute(
                    "SELECT role, asset_hash FROM rendition_asset WHERE rendition_version_id = ?",
                    (rendition_version_id,),
                )
            }
        if "video" not in assets or "subtitles" not in assets:
            raise NotFound(rendition_version_id)
        out = self.media_dir / "exports" / f"{rendition_version_id}.mp4"
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            vtt = self.media_dir / "exports" / f"{rendition_version_id}.vtt"
            shutil.copy(self.blobs.path(assets["subtitles"]), vtt)
            self.ffmpeg.with_subtitles(self.blobs.path(assets["video"]), vtt, out.with_suffix(".part.mp4"))
            out.with_suffix(".part.mp4").replace(out)
        return out
