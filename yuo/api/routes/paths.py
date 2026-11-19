"""Paths: create and view, the level check, the "What next?" checkpoint, placement, progress, requests."""

from typing import Any

from fastapi import APIRouter

from yuo.api import schemas as S
from yuo.api.bodies import (
    LevelAnswersIn,
    NextAnswersIn,
    NextChoiceIn,
    PathIn,
    PreviewFeedbackIn,
    RequestIn,
)
from yuo.app.forms import PathForm


def router(svc: Any) -> APIRouter:
    r = APIRouter()

    @r.post("/api/paths", status_code=201, response_model=S.PathCreated)
    def post_path(body: PathIn) -> dict[str, str]:
        path_id, job_id = svc.create_path(PathForm(**body.model_dump()))
        return {"path_id": path_id, "job_id": job_id}

    @r.get("/api/home", response_model=S.HomeOut)
    def get_home() -> dict[str, Any]:
        """The first screen: the next step, what waits today, progress, momentum and one insight."""
        result: dict[str, Any] = svc.home()
        return result

    @r.get("/api/paths", response_model=list[S.PathSummary])
    def get_paths() -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = svc.paths()
        return result

    @r.get("/api/paths/{path_id}", response_model=S.PathOut)
    def get_path(path_id: str) -> dict[str, Any]:
        result: dict[str, Any] = svc.path_view(path_id)
        return result

    @r.patch("/api/paths/{path_id}", response_model=S.PathSummary)
    def patch_path(path_id: str, body: S.PathPatch) -> dict[str, Any]:
        """Rename the path, change its goal or exam date, archive it or bring it back."""
        changes = body.model_dump(exclude_unset=True, mode="json")
        result: dict[str, Any] = svc.update_path(path_id, changes)
        return result

    @r.delete("/api/paths/{path_id}", response_model=S.ErasedOut)
    def delete_path(path_id: str) -> dict[str, Any]:
        """Delete the path with its lessons, questions, files and everything done in it. Not undoable."""
        return {"counts": svc.delete_path(path_id)}

    @r.get("/api/paths/{path_id}/level-check", response_model=S.LevelCheckOut)
    def get_level_check(path_id: str) -> dict[str, Any]:
        result: dict[str, Any] = svc.level_check(path_id)
        return result

    @r.post("/api/paths/{path_id}/level-check/retry", response_model=S.LevelCheckOut)
    def post_level_check_retry(path_id: str) -> dict[str, Any]:
        """Write the level check's questions again after that failed."""
        result: dict[str, Any] = svc.retry_level_check(path_id)
        return result

    @r.post("/api/paths/{path_id}/level-check", response_model=S.LevelCheckOut)
    def post_level_check(path_id: str, body: LevelAnswersIn) -> dict[str, Any]:
        result: dict[str, Any] = svc.answer_level_check(path_id, None if body.skip else body.answers)
        return result

    @r.get("/api/paths/{path_id}/preview", response_model=S.PreviewOut)
    def get_preview(path_id: str) -> dict[str, Any]:
        """The plan the learner checks before it is built."""
        result: dict[str, Any] = svc.preview_view(path_id)
        return result

    @r.post("/api/paths/{path_id}/preview/feedback", response_model=S.PreviewOut)
    def post_preview_feedback(path_id: str, body: PreviewFeedbackIn) -> dict[str, Any]:
        """What is missing, wrong or should go deeper: the plan is revised with it."""
        result: dict[str, Any] = svc.preview_feedback(path_id, body.text)
        return result

    @r.post("/api/paths/{path_id}/preview/undo", response_model=S.PreviewOut)
    def post_preview_undo(path_id: str) -> dict[str, Any]:
        """Back to the plan before the last change."""
        result: dict[str, Any] = svc.undo_feedback(path_id)
        return result

    @r.post("/api/paths/{path_id}/preview/retry", response_model=S.PreviewOut)
    def post_preview_retry(path_id: str) -> dict[str, Any]:
        """Write the plan again after that failed."""
        result: dict[str, Any] = svc.retry_preview(path_id)
        return result

    @r.post("/api/paths/{path_id}/preview/build", response_model=S.PreviewOut)
    def post_preview_build(path_id: str) -> dict[str, Any]:
        """The learner accepts the plan: it is built and the first lessons are written."""
        result: dict[str, Any] = svc.build_preview(path_id)
        return result

    @r.get("/api/paths/{path_id}/next", response_model=S.NextOut)
    def get_next(path_id: str) -> dict[str, Any]:
        """The "What next?" checkpoint: whether it is offered, its questions, quiz and directions."""
        result: dict[str, Any] = svc.next_view(path_id)
        return result

    @r.post("/api/paths/{path_id}/next", response_model=S.NextOut)
    def post_next(path_id: str) -> dict[str, Any]:
        """Open the checkpoint: the questions and the quiz are written."""
        result: dict[str, Any] = svc.start_next(path_id)
        return result

    @r.post("/api/paths/{path_id}/next/answers", response_model=S.NextOut)
    def post_next_answers(path_id: str, body: NextAnswersIn) -> dict[str, Any]:
        """The quiz and the direction answers: the directions are written."""
        answers = [a.model_dump() for a in body.answers]
        result: dict[str, Any] = svc.answer_next(path_id, body.quiz, answers)
        return result

    @r.post("/api/paths/{path_id}/next/others", response_model=S.NextOut)
    def post_next_others(path_id: str) -> dict[str, Any]:
        """None of the directions fits: different ones are written."""
        result: dict[str, Any] = svc.other_directions(path_id)
        return result

    @r.post("/api/paths/{path_id}/next/choose", response_model=S.NextOut)
    def post_next_choose(path_id: str, body: NextChoiceIn) -> dict[str, Any]:
        """The learner confirms a direction: its branches are written and added to the path."""
        result: dict[str, Any] = svc.choose_next(path_id, body.code)
        return result

    @r.post("/api/paths/{path_id}/next/dismiss", response_model=S.NextOut)
    def post_next_dismiss(path_id: str) -> dict[str, Any]:
        """Close the checkpoint without changes."""
        result: dict[str, Any] = svc.dismiss_next(path_id)
        return result

    @r.post("/api/paths/{path_id}/next/retry", response_model=S.NextOut)
    def post_next_retry(path_id: str) -> dict[str, Any]:
        """Run the failed writing step again."""
        result: dict[str, Any] = svc.retry_next(path_id)
        return result

    @r.post("/api/paths/{path_id}/placement", response_model=S.AssessmentOut | S.JobStarted)
    def post_placement(path_id: str) -> dict[str, Any]:
        result: dict[str, Any] = svc.start_placement(path_id)
        return result

    @r.get("/api/paths/{path_id}/progress", response_model=S.ProgressOut)
    def get_progress(path_id: str) -> dict[str, Any]:
        result: dict[str, Any] = svc.progress(path_id)
        return result

    @r.post("/api/paths/{path_id}/requests", status_code=202, response_model=S.RequestOut)
    def post_request(path_id: str, body: RequestIn) -> dict[str, Any]:
        result: dict[str, Any] = svc.request(path_id, body.prompt, body.links, body.skill_id)
        return result

    @r.get("/api/paths/{path_id}/requests", response_model=list[S.RequestRow])
    def get_requests(path_id: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = svc.requests(path_id)
        return result

    return r
