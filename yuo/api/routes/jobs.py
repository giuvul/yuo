"""Generation jobs and the spending ledger."""

from typing import Any

from fastapi import APIRouter

from yuo.api import schemas as S


def router(svc: Any) -> APIRouter:
    r = APIRouter()

    @r.post("/api/jobs/{job_id}/retry", status_code=202, response_model=S.JobStarted)
    def post_job_retry(job_id: str) -> dict[str, str]:
        """Start a failed lesson or video job again."""
        return {"job_id": svc.retry_job(job_id)}

    @r.get("/api/jobs/history", response_model=S.JobHistoryOut)
    def get_job_history(before: str | None = None, limit: int = 50) -> dict[str, Any]:
        """Finished jobs (done, failed, cancelled), newest first, a page at a time."""
        result: dict[str, Any] = svc.job_history(before, limit)
        return result

    @r.get("/api/jobs/{job_id}", response_model=S.JobOut)
    def get_job(job_id: str) -> dict[str, Any]:
        result: dict[str, Any] = svc.job(job_id)
        return result

    @r.get("/api/ledger")
    def get_ledger() -> dict[str, Any]:
        result: dict[str, Any] = svc.ledger()
        return result

    @r.get("/api/jobs", response_model=list[S.JobRef])
    def get_jobs() -> list[dict[str, Any]]:
        """Jobs queued, running, waiting, or failed in the last day and not done since (job status UI)."""
        result: list[dict[str, Any]] = svc.active_jobs()
        return result

    @r.get("/api/generation/pause", response_model=S.GenerationPause)
    def get_pause() -> dict[str, Any]:
        """Whether background generation is paused, what waits, and what is still finishing its step."""
        result: dict[str, Any] = svc.generation_pause()
        return result

    @r.put("/api/generation/pause", response_model=S.GenerationPause)
    def put_pause(body: S.PauseIn) -> dict[str, Any]:
        """Pause lessons and videos written ahead (or only videos), until a time or until resumed; scope null
        resumes."""
        result: dict[str, Any] = svc.set_generation_pause(body.scope, body.until)
        return result

    return r
