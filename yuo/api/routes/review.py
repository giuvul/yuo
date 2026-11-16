"""Reviews: due cards, the review hub and sessions."""

from typing import Any

from fastapi import APIRouter

from yuo.api import schemas as S


def router(svc: Any) -> APIRouter:
    r = APIRouter()

    @r.get("/api/reviews", response_model=S.DueOut)
    def get_reviews(path_id: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = svc.due_reviews(path_id)
        return result

    @r.post("/api/reviews/start", response_model=S.AssessmentOut)
    def post_reviews(path_id: str | None = None, skill_id: str | None = None) -> dict[str, Any]:
        """Due reviews; with `skill_id`, that skill's cards due or not (an accepted extra review)."""
        result: dict[str, Any] = svc.start_reviews(path_id, skill_id)
        return result

    @r.get("/api/paths/{path_id}/review", response_model=S.ReviewHubOut)
    def get_review_hub(path_id: str) -> dict[str, Any]:
        """Memory of what the learner has studied in this path, and what a review session would cover."""
        result: dict[str, Any] = svc.review_hub(path_id)
        return result

    @r.post("/api/paths/{path_id}/review/sessions", response_model=S.ReviewSessionOut)
    def post_review_session(path_id: str, body: S.ReviewSessionIn) -> dict[str, Any]:
        """A review session: the open one if there is one, else a new one of `size` questions."""
        result: dict[str, Any] = svc.start_review_session(
            path_id, body.size, skill_id=body.skill_id, branch_id=body.branch_id
        )
        return result

    @r.get("/api/review/attempts/{attempt_id}", response_model=S.ReviewResultOut)
    def get_review_result(attempt_id: str) -> dict[str, Any]:
        result: dict[str, Any] = svc.review_result(attempt_id)
        return result

    @r.get("/api/review/attempts/{attempt_id}/items/{item_version_id}", response_model=S.Graded)
    def get_review_feedback(attempt_id: str, item_version_id: str) -> dict[str, Any]:
        """What may be shown about a question now (after "Show answer", or when a session is resumed)."""
        result: dict[str, Any] = svc.review_feedback(attempt_id, item_version_id)
        return result

    return r
