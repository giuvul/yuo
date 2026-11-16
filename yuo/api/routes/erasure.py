"""Erasure: gone from the database, the WAL, free pages and the asset store."""

from typing import Any

from fastapi import APIRouter

from yuo.api import schemas as S


def router(svc: Any) -> APIRouter:
    r = APIRouter()

    @r.delete("/api/tutor/conversations/{conversation_id}", response_model=S.ErasedOut)
    def delete_conversation(conversation_id: str) -> dict[str, Any]:
        """Erase one conversation with its messages and the model runs behind them."""
        return {"counts": svc.erasure.conversation(conversation_id)}

    @r.delete("/api/me/video-history", response_model=S.ErasedOut)
    def delete_video_history() -> dict[str, Any]:
        """Erase which videos were watched and how much of each."""
        return {"counts": svc.erasure.video_history()}

    @r.delete("/api/paths/{path_id}/personal-data", response_model=S.ErasedOut)
    def delete_path_personal_data(path_id: str) -> dict[str, Any]:
        """Erase the learner's data in one path (progress, answers, reviews, conversations, notes, requests and
        lessons written for them); the path and its shared content stay, and personal lessons can be written
        again."""
        return {"counts": svc.erasure.path_personal(path_id)}

    return r
