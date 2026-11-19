"""HTTP API. Routers call the application service handed in by the composition root, never `db`."""

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from yuo.api import auth as auth_routes
from yuo.api import onboarding as onboarding_routes
from yuo.api.routes import erasure, jobs, material, paths, review, setup, sharing, stream, study, tutor
from yuo.core.errors import AiNotReady, Conflict, InvalidInput, NotFound
from yuo.core.logs import metrics


def create_app(
    *,
    version: str,
    health: Callable[[], dict[str, Any]],
    service: Any = None,
    auth: Any = None,
    extra_hosts: frozenset[str] = frozenset(),
    desktop: Any = None,
    waitlist_url: str | None = None,
) -> FastAPI:
    """`service` is `yuo.app.service.Service`, typed loosely so this module does not import the db layer.

    `auth` (`yuo.app.auth.Auth`) turns on sign-in and the request guards (yuo.api.auth); the composition root
    always passes it. Without it (scripted-model tests) every route is open and devices are registered by the client."""
    app = FastAPI(title="Yuo", version=version, docs_url="/api/docs", openapi_url="/api/openapi.json")
    svc = service
    if auth is not None:
        auth_routes.install(app, auth, extra_hosts=extra_hosts)

    # errors raised on purpose carry their status (yuo.core.errors); any other exception is a bug: a logged 500
    @app.exception_handler(NotFound)
    async def not_found(_: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse({"detail": str(exc) or "not found"}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(_: Request, exc: Conflict) -> JSONResponse:
        return JSONResponse({"detail": str(exc) or "not possible now"}, status_code=409)

    @app.exception_handler(InvalidInput)
    async def invalid(_: Request, exc: InvalidInput) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(AiNotReady)
    async def ai_not_ready(_: Request, exc: AiNotReady) -> JSONResponse:
        # the app turns this into a step: install the program, or sign in
        return JSONResponse(
            {
                "detail": "the chosen AI access is not ready",
                "code": "ai_not_ready",
                "cli": exc.cli,
                "reason": exc.reason,
            },
            status_code=409,
        )

    @app.get("/api/health")
    def get_health() -> dict[str, Any]:
        return {"status": "ok", "version": version, **health(), "metrics": metrics.snapshot()}

    if svc is None:
        return app
    onboarding_routes.install(app, svc, desktop)

    # one router per feature; their relative order does not matter (no path of one shadows another's)
    app.include_router(setup.router(svc, desktop, waitlist_url))
    app.include_router(paths.router(svc))
    app.include_router(material.router(svc))
    app.include_router(study.router(svc))
    app.include_router(jobs.router(svc))
    app.include_router(review.router(svc))
    app.include_router(tutor.router(svc))
    app.include_router(erasure.router(svc))
    app.include_router(sharing.router(svc))
    app.include_router(stream.router(svc))
    return app
