"""Lessons, practice, hints, the event outbox, skill tests, notes and lesson media."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from yuo.api import schemas as S
from yuo.api.bodies import (
    EventsIn,
    NoteEdit,
    NoteIn,
)
from yuo.api.routes import session_device


def router(svc: Any) -> APIRouter:
    r = APIRouter()

    @r.post("/api/lessons/{lesson_id}/generate", status_code=202, response_model=S.JobStarted)
    def post_generate(lesson_id: str) -> dict[str, str]:
        return {"job_id": svc.request_lesson(lesson_id)}

    @r.post("/api/lessons/{lesson_id}/accept", status_code=202, response_model=S.JobStarted)
    def post_accept(lesson_id: str) -> dict[str, str]:
        """Publish a failed lesson's best draft as it is, with the reviewer's notes shown in it."""
        return {"job_id": svc.accept_lesson_draft(lesson_id)}

    @r.post("/api/lessons/{lesson_id}/video", status_code=202, response_model=S.JobStarted)
    def post_video_again(lesson_id: str) -> dict[str, str]:
        """Make a lesson's video again after it failed."""
        return {"job_id": svc.retry_video(lesson_id)}

    @r.post("/api/lessons/{lesson_id}/youtube/another", status_code=202, response_model=S.JobStarted)
    def post_another_video(lesson_id: str) -> dict[str, str]:
        """Turn down the lesson's YouTube video (or look again when none was found): the next one found, and
        the lesson written again for it."""
        return {"job_id": svc.another(lesson_id)}

    @r.get("/api/lessons/{lesson_id}", response_model=S.LessonOut)
    def get_lesson(lesson_id: str) -> dict[str, Any]:
        result: dict[str, Any] = svc.lesson_view(lesson_id)
        return result

    @r.post("/api/lessons/{lesson_id}/practice", response_model=S.PracticeOut)
    def post_practice(lesson_id: str) -> dict[str, Any]:
        result: dict[str, Any] = svc.start_practice(lesson_id)
        return result

    @r.get("/api/items/{item_version_id}/hints/{level}", response_model=S.HintOut)
    def get_hint(item_version_id: str, level: int) -> dict[str, Any]:
        result: dict[str, Any] = svc.hint(item_version_id, level)
        return result

    @r.post("/api/events", response_model=S.IngestOut)
    def post_events(body: EventsIn, request: Request) -> dict[str, Any]:
        # signed in: events count for the session's device, whatever an older outbox recorded
        result: dict[str, Any] = svc.ingest(session_device(request) or body.device_id, body.events)
        return result

    @r.post("/api/skills/{skill_id}/test", response_model=S.AssessmentOut | S.JobStarted)
    def post_skill_test(skill_id: str) -> dict[str, Any]:
        """A skill test, or a job id while its item bank is still being written (poll the job, then retry)."""
        result: dict[str, Any] = svc.start_skill_test(skill_id)
        return result

    @r.post("/api/items/{item_id}/report", status_code=204)
    def post_item_report(item_id: str, body: S.ReportIn) -> None:
        svc.report_item(item_id, body.reason)

    @r.get("/api/lessons/{lesson_id}/notes", response_model=list[S.NoteOut])
    def get_notes(lesson_id: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = svc.notes(lesson_id)
        return result

    @r.post("/api/notes", status_code=201, response_model=S.NoteCreated)
    def post_note(body: NoteIn) -> dict[str, str]:
        return {
            "note_id": svc.add_note(
                body.text,
                lesson_version_id=body.lesson_version_id,
                bid=body.bid,
                rendition_version_id=body.rendition_version_id,
                t_s=body.t_s,
            )
        }

    @r.patch("/api/notes/{note_id}", status_code=204)
    def patch_note(note_id: str, body: NoteEdit) -> None:
        svc.edit_note(note_id, body.text)

    @r.delete("/api/notes/{note_id}", status_code=204)
    def delete_note(note_id: str) -> None:
        svc.delete_note(note_id)

    @r.get("/api/items/{item_version_id}/reveal", response_model=S.RevealOut)
    def get_reveal(item_version_id: str) -> dict[str, Any]:
        result: dict[str, Any] = svc.reveal(item_version_id)
        return result

    @r.get("/api/assets/{digest}", response_class=FileResponse)
    def get_asset(digest: str) -> FileResponse:
        """A stored file (video, captions, poster) by its content hash; immutable, so cached for a year.
        Range requests work, so the player can seek."""
        if len(digest) != 64 or not all(ch in "0123456789abcdef" for ch in digest):
            raise HTTPException(404)
        path, media_type = svc.asset_file(digest)
        return FileResponse(
            path, media_type=media_type, headers={"Cache-Control": "public, max-age=31536000, immutable"}
        )

    @r.get("/api/renditions/{version_id}/export", response_class=FileResponse)
    def get_video_export(version_id: str) -> FileResponse:
        """The MP4 with the captions as a soft subtitle track, as a download."""
        path = svc.video_export(version_id)
        return FileResponse(path, media_type="video/mp4", filename=f"yuo-lesson-{version_id[:8]}.mp4")

    return r
