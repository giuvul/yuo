"""The API's routers, one per feature; `yuo.api.app.create_app` includes them.

Each module's `router(svc, ...)` builds an `APIRouter` whose handlers call the application service handed in by
the composition root, never `db`.
"""

from fastapi import Request


def session_device(request: Request) -> str | None:
    """The signed-in session's device, or None when sign-in is off (scripted-model tests)."""
    s = getattr(request.state, "session", None)
    return s.device_id if s is not None else None
