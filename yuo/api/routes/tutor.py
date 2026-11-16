"""The tutor: context, messages, memory, proposals and nudges."""

from typing import Any, Literal

from fastapi import APIRouter

from yuo.api import schemas as S
from yuo.api.bodies import (
    MemoryEdit,
    MemoryIn,
    TutorContextIn,
    TutorEdit,
    TutorMessageIn,
)


def router(svc: Any) -> APIRouter:
    r = APIRouter()

    @r.post("/api/tutor/context", response_model=S.TutorContextOut)
    def post_tutor_context(body: TutorContextIn) -> dict[str, Any]:
        """The policy, thread and chips for a screen, before sending (the dock shows why it is quiet)."""
        result: dict[str, Any] = svc.tutor_context(body.model_dump(mode="json"))
        return result

    @r.post("/api/tutor/messages", status_code=202, response_model=S.TutorMessageOut)
    def post_tutor_message(body: TutorMessageIn) -> dict[str, Any]:
        result: dict[str, Any] = svc.send_message(body.id, body.text, body.context.model_dump(mode="json"))
        return result

    @r.patch("/api/tutor/messages/{message_id}", response_model=S.TutorMessageOut)
    def patch_tutor_message(message_id: str, body: TutorEdit) -> dict[str, Any]:
        """Edit a message while it is still queued."""
        result: dict[str, Any] = svc.edit_message(message_id, body.text)
        return result

    @r.delete("/api/tutor/messages/{message_id}", response_model=S.TutorMessageOut)
    def delete_tutor_message(message_id: str) -> dict[str, Any]:
        """Take back a queued message, or cancel a reply that is still being written."""
        result: dict[str, Any] = svc.withdraw_message(message_id)
        return result

    @r.post("/api/tutor/messages/{message_id}/retry", response_model=S.RequeuedOut)
    def post_tutor_retry(message_id: str) -> dict[str, Any]:
        result: dict[str, Any] = svc.retry_reply(message_id)
        return result

    @r.get("/api/tutor/conversations", response_model=list[S.ConversationOut])
    def get_conversations(path_id: str | None = None) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = svc.conversations(path_id)
        return result

    @r.get("/api/tutor/messages", response_model=list[S.TutorMessageOut])
    def get_tutor_messages(conversation_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        """One thread, or the 'All' timeline across threads without `conversation_id`."""
        result: list[dict[str, Any]] = svc.messages(conversation_id, limit=max(1, min(limit, 500)))
        return result

    @r.get("/api/tutor/memory", response_model=list[S.MemoryOut])
    def get_memory() -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = svc.memory()
        return result

    @r.post("/api/tutor/memory", status_code=201, response_model=S.MemoryCreated)
    def post_memory(body: MemoryIn) -> dict[str, str]:
        return {"memory_id": svc.add_memory(body.kind, body.text)}

    @r.patch("/api/tutor/memory/{memory_id}", status_code=204)
    def patch_memory(memory_id: str, body: MemoryEdit) -> None:
        svc.edit_memory(memory_id, body.text)

    @r.delete("/api/tutor/memory/{memory_id}", status_code=204)
    def delete_memory(memory_id: str) -> None:
        svc.delete_memory(memory_id)

    @r.get("/api/paths/{path_id}/proposals", response_model=list[S.ProposalOut])
    def get_proposals(path_id: str) -> list[dict[str, Any]]:
        """Decide one by sending a `tutor.proposal_decided` event through the outbox."""
        result: list[dict[str, Any]] = svc.proposals(path_id)
        return result

    @r.get("/api/proposals/{proposal_id}", response_model=S.ProposalOut)
    def get_proposal(proposal_id: str) -> dict[str, Any]:
        result: dict[str, Any] = svc.proposal(proposal_id)
        return result

    @r.get("/api/nudges", response_model=list[S.NudgeOut])
    def get_nudges() -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = svc.nudges()
        return result

    @r.post("/api/nudges/{nudge_id}/{action}", status_code=204)
    def post_nudge(nudge_id: str, action: Literal["dismiss", "accept", "mute"]) -> None:
        svc.decide_nudge(nudge_id, action)

    return r
