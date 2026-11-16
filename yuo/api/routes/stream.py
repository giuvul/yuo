"""Server-Sent Events."""

import json
from collections.abc import AsyncIterator
from typing import Any

import anyio
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse


def router(svc: Any) -> APIRouter:
    r = APIRouter()

    @r.get("/api/stream", response_class=StreamingResponse)
    async def get_stream(request: Request, last_event_id: str | None = None) -> StreamingResponse:
        """Server-Sent Events: `tutor.message`, `tutor.delta`, `tutor.progress`, `nudge`, `job`,
        and `reset` when missed events cannot be replayed (reload state over the API). Resume with the
        `Last-Event-ID` header or `?last_event_id=`."""
        broker = svc.broker
        start = request.headers.get("last-event-id") or last_event_id or broker.last_id

        async def events() -> AsyncIterator[str]:
            last = start
            yield "retry: 3000\n\n"
            while not await request.is_disconnected():
                got = await anyio.to_thread.run_sync(broker.wait, last, 15.0)
                if got is None:
                    last = broker.last_id
                    yield f"id: {last}\nevent: reset\ndata: {{}}\n\n"
                elif not got:
                    yield ": ping\n\n"
                for e in got or []:
                    last = e.id
                    yield f"id: {e.id}\nevent: {e.kind}\ndata: {json.dumps(e.data, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return r
