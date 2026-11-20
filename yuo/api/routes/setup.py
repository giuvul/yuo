"""Setup, devices, the estimate and settings."""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request

from yuo.api import onboarding as onboarding_routes
from yuo.api import schemas as S
from yuo.api.bodies import (
    DeviceIn,
    PresetIn,
    SettingIn,
)
from yuo.api.routes import session_device


def router(svc: Any, desktop: Any, waitlist_url: str | None) -> APIRouter:
    r = APIRouter()

    @r.get("/api/setup", response_model=S.SetupOut)
    def get_setup() -> dict[str, Any]:
        learner = svc.ensure_learner()
        resolved = svc.resolved_models()
        bindings = {
            role: {"adapter": b.adapter, "model": b.model}
            | ({"resolved": r} if (r := resolved.get((b.adapter, b.model))) else {})
            for role, b in svc.bindings().items()
        }
        return {
            "learner_id": learner,
            "bindings": bindings,
            "warnings": svc.warnings(),
            "desktop": desktop is not None,
            "waitlist_url": waitlist_url,
            "video_unavailable": svc.video_unavailable(),
        }

    @r.post("/api/setup/preset", response_model=S.SetupOut)
    def post_preset(body: PresetIn) -> dict[str, Any]:
        if body.preset in ("claude", "codex") and svc.access is not None:
            if body.consent:
                svc.access.record_consent(svc.ensure_learner(), body.preset, True)
            elif not svc.access.has_consent(body.preset):
                raise HTTPException(409, "agree to the subscription consent text first")
        svc.apply_preset(body.preset)
        return get_setup()

    @r.post("/api/setup/vendor-models", response_model=S.SetupOut)
    def post_vendor_models(body: onboarding_routes.VendorModelsIn) -> dict[str, Any]:
        """A direct vendor key's models: `main` for every role, `reviewer` for the reviewer."""
        if svc.access is None:
            raise HTTPException(404, "AI access is not set up in this process")
        svc.bind_vendor(body.provider, body.main, body.reviewer)
        return get_setup()

    @r.post("/api/devices", response_model=S.DeviceOut)
    def post_device(body: DeviceIn, request: Request) -> dict[str, str]:
        """With sign-in on, the device is the session's (made at sign-in); this returns it."""
        did = session_device(request)
        return {"device_id": did or svc.register_device(body.label, request.headers.get("user-agent", ""))}

    @r.get("/api/estimate", response_model=S.EstimateOut)
    def get_estimate(
        lessons: int = 20, videos: Literal["youtube", "generated", "reading"] | None = None
    ) -> dict[str, Any]:
        """`videos`: the kind chosen on the New path form; none: the learner's settings."""
        if not 1 <= lessons <= 200:
            raise HTTPException(422, "lessons must be 1 to 200")
        result: dict[str, Any] = svc.estimate(lessons, videos=videos).as_dict()
        return result

    @r.get("/api/settings", response_model=list[S.SettingOut])
    def get_settings(path_id: str | None = None) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = svc.settings_view(path_id)
        return result

    @r.put("/api/settings/{key}", status_code=204)
    def put_setting(key: str, body: SettingIn) -> None:
        svc.put_learner_setting(key, body.value, body.level, body.ref)

    return r
