"""Routes for the environment wizard, learner onboarding, AI access, updates and the desktop app."""

import hmac
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from yuo.api.schemas import PlanUsageOut
from yuo.core.errors import YuoError
from yuo.core.llm import LLMError
from yuo.setup.consent import CONSENT_TEXT, CONSENT_VERSION
from yuo.setup.providers import PROVIDERS

LANG = r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$"


class Gpu(BaseModel):
    name: str
    memory_gb: float | None
    kind: str


class LocalServer(BaseModel):
    name: str
    url: str
    models: list[str]


class Bench(BaseModel):
    cpu_gflops: float | None
    seconds: float


class ProbeOut(BaseModel):
    os: str
    os_version: str
    arch: str
    cpu: str | None
    cores: int | None
    memory_gb: float | None
    gpus: list[Gpu]
    disk_free_gb: float | None
    clis: dict[str, str | None]
    servers: list[LocalServer]
    bench: Bench


class ReasonOut(BaseModel):
    code: str  # no_subscription, cli_found, gpu_memory, unified_memory, gpu_memory_short,
    # unified_memory_short, no_gpu, local_free, api_billed
    values: dict[str, Any]


class EstimateLineOut(BaseModel):
    unit: str
    count: float
    adapter: str
    model: str
    low: float
    high: float
    billed: bool
    source: str


class PresetEstimateOut(BaseModel):
    low_usd: float
    high_usd: float
    notional_usd: float
    missing: list[str]
    lines: list[EstimateLineOut]
    plan_usage: list[PlanUsageOut]
    lessons: int


class OptionOut(BaseModel):
    preset: Literal["claude", "codex", "local", "open"]
    estimate: PresetEstimateOut


class RecommendationOut(BaseModel):
    preset: Literal["claude", "codex", "local", "open"]
    reasons: list[ReasonOut]
    needs: list[str]  # consent, openrouter_key, local_server, local_model
    alternatives: list[Literal["claude", "codex", "local", "open"]]
    options: list[OptionOut]  # the recommendation first, each with its estimate for a typical path
    probe: ProbeOut


class AccessOut(BaseModel):
    openrouter: bool  # a key is set (never returned)
    local_url: str | None
    local: bool
    clis: list[str]
    consent: dict[str, bool]
    vendors: list[str] = Field(
        description="Vendors with a direct key connected (the keys are never returned)"
    )


ProviderId = Literal[
    "anthropic", "openai", "gemini", "mistral", "deepseek", "xai", "qwen"
]  # yuo/setup/providers.py


class ProviderOut(BaseModel):
    id: ProviderId
    label: str
    keys_url: str
    key_prefix: str
    suggested_main: str | None
    suggested_reviewer: str | None
    connected: bool


class VendorKeyIn(BaseModel):
    key: str = Field(min_length=8, max_length=400)


class ModelsOut(BaseModel):
    models: list[str]


ModelSource = ProviderId | Literal["openrouter"]


class OpenRouterModelOut(BaseModel):
    id: str
    name: str
    in_usd_per_m: float | None = Field(description="USD per million input tokens")
    out_usd_per_m: float | None = Field(description="USD per million output tokens")
    context: int | None


class OpenRouterModelsOut(BaseModel):
    models: list[OpenRouterModelOut]


class VendorModelsIn(BaseModel):
    provider: ModelSource
    main: str = Field(min_length=1, max_length=200, description="Writes lessons, tutors, grades")
    reviewer: str = Field(min_length=1, max_length=200, description="Checks lessons; best a different model")


class CliTaskOut(BaseModel):
    state: Literal["idle", "running", "waiting_code", "waiting_browser", "waiting_device", "done", "failed"]
    url: str | None  # the vendor's sign-in page, when the program asks for a code
    code: str | None  # waiting_device: the one-time code to enter on that page
    error: str | None


class CliOut(BaseModel):
    """A subscription's command-line program on the machine that runs Yuo."""

    cli: Literal["claude", "codex"]
    name: str
    needed: bool  # the chosen models run through it
    installed: bool
    version: str | None
    logged_in: bool | None  # None: the program did not say
    account: str | None  # the plan or the sign-in method
    ready: bool
    reason: Literal["not_installed", "not_logged_in"] | None
    detail: str | None
    os: Literal["windows", "macos", "linux"]
    container: bool  # Yuo runs in a container: commands are run inside it
    can_install: bool  # Yuo can run the vendor's installer itself
    can_login: bool  # Yuo can start the sign-in itself
    code_login: bool  # the sign-in gives a link and takes a code here; else the program opens a browser
    install_command: str
    login_command: str
    docs_url: str
    install: CliTaskOut
    login: CliTaskOut


class AiReadyOut(BaseModel):
    ready: bool
    clis: list[CliOut]  # the programs the chosen models need


class CliCodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=2000)


class MeterOut(BaseModel):
    """A subscription's plan as its CLI last reported it; the whole account, other devices included."""

    window_pct: float | None
    week_pct: float | None
    window_resets_at: str | None
    week_resets_at: str | None
    limited: bool
    observed_at: str


class PlanMeterOut(BaseModel):
    claude: MeterOut | None
    codex: MeterOut | None


class KeyIn(BaseModel):
    key: str = Field(min_length=8, max_length=200)


class KeyOut(BaseModel):
    limit_remaining: float | None  # credit left on the key; None: no limit set
    free_tier: bool


class LocalIn(BaseModel):
    url: str = Field(max_length=100)


class LocalOut(BaseModel):
    models: list[str]


class ConsentTextOut(BaseModel):
    cli: str
    version: int
    text: str  # the English original; the web app shows its translation


class OnboardingOut(BaseModel):
    probed: bool
    models_chosen: bool
    profile_done: bool
    has_path: bool
    done: bool


class MeOut(BaseModel):
    display_name: str
    ui_lang: str
    content_lang: str
    tz: str
    theme: Literal["system", "light", "dark"]
    session_minutes: int
    interests: str


class MeIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=60)
    ui_lang: str | None = Field(default=None, pattern=LANG, max_length=35)
    content_lang: str | None = Field(default=None, pattern=LANG, max_length=35)
    tz: str | None = Field(default=None, max_length=64)
    theme: Literal["system", "light", "dark"] | None = None
    session_minutes: int | None = Field(default=None, ge=5, le=120)
    interests: str | None = Field(default=None, max_length=500)


class AnswersProfileOut(BaseModel):
    display_name: str | None = None
    ui_lang: str | None = None
    content_lang: str | None = None
    tz: str | None = None
    session_minutes: int | None = None
    interests: str | None = None


class AnswersPathOut(BaseModel):
    title: str
    goal: str
    goal_type: Literal["exam", "practical", "understanding", "curiosity"]
    custom_instructions: str


class SetupAnswersOut(BaseModel):
    """What an AI assistant collected before Yuo started (SETUP.md); both parts absent when there is nothing."""

    profile: AnswersProfileOut | None = None
    first_path: AnswersPathOut | None = None


class UpdateOut(BaseModel):
    current: str
    feed: bool  # this build knows where releases are published
    latest: str | None
    published_at: str | None
    notes_url: str | None
    available: bool
    staged: str | None  # downloaded and checked, installed on restart
    can_install: bool  # desktop; servers pull the new image


class LinkOut(BaseModel):
    url: str


class OpenIn(BaseModel):
    auto: bool = Field(default=False, description="Asked by a signed-out tab on its own, not by a click")


def install(app: FastAPI, svc: Any, desktop: Any = None) -> None:
    @app.exception_handler(LLMError)
    async def llm_refused(_: Request, exc: LLMError) -> JSONResponse:
        return JSONResponse(
            {"detail": str(exc), "kind": exc.kind}, status_code=400 if exc.kind == "auth" else 502
        )

    @app.exception_handler(YuoError)
    async def failed(_: Request, exc: YuoError) -> JSONResponse:
        # NotFound, Conflict and InvalidInput are YuoErrors too, but their own handlers (yuo.api.app) win
        return JSONResponse({"detail": str(exc)}, status_code=502)

    for build in (_machine, _access_routes, _vendor_routes, _cli_routes, _learner, _update_routes):
        app.include_router(build(svc))
    if desktop is not None:
        app.include_router(_desktop(desktop))


# --- what several routers need: each part is optional in a process (tests, the desktop app) --------------


def _access(svc: Any) -> Any:
    if svc.access is None:
        raise HTTPException(404, "AI access is not set up in this process")
    return svc.access


def _vendors(svc: Any) -> None:
    if not _access(svc).vendors_enabled:
        raise HTTPException(404, "direct vendor keys are not set up in this process")


def _cli(svc: Any) -> Any:
    if svc.cli is None:
        raise HTTPException(404, "this process does not manage subscription programs")
    return svc.cli


def _cli_view(svc: Any, cli: str, *, fresh: bool = False) -> dict[str, Any]:
    view: dict[str, Any] = _cli(svc).view(cli, fresh=fresh)
    return view | {"needed": cli in svc.cli_needed()}


def _updates(svc: Any) -> Any:
    if svc.updates is None:
        raise HTTPException(404, "updates are not set up in this process")
    return svc.updates


def _machine(svc: Any) -> APIRouter:
    """The machine and the recommendation."""
    r = APIRouter()

    @r.post("/api/setup/probe", response_model=ProbeOut)
    def post_probe() -> dict[str, Any]:
        result: dict[str, Any] = svc.run_probe().as_json()
        return result

    @r.get("/api/setup/recommendation", response_model=RecommendationOut)
    def get_recommendation() -> dict[str, Any]:
        result: dict[str, Any] = svc.recommendation()
        return result

    @r.get("/api/setup/estimate/{preset}", response_model=PresetEstimateOut)
    def get_preset_estimate(
        preset: Literal["claude", "codex", "local", "open"], lessons: int = 20
    ) -> dict[str, Any]:
        if not 1 <= lessons <= 200:
            raise HTTPException(422, "lessons must be 1 to 200")
        result: dict[str, Any] = svc.estimate_for(preset, lessons)
        return result

    return r


def _access_routes(svc: Any) -> APIRouter:
    """AI access: OpenRouter and a local server."""
    r = APIRouter()

    @r.get("/api/setup/access", response_model=AccessOut)
    def get_access() -> dict[str, Any]:
        result: dict[str, Any] = _access(svc).status()
        return result

    @r.put("/api/setup/access/openrouter", response_model=KeyOut)
    def put_openrouter(body: KeyIn) -> dict[str, Any]:
        result: dict[str, Any] = _access(svc).set_openrouter_key(body.key)
        return result

    @r.delete("/api/setup/access/openrouter", status_code=204)
    def delete_openrouter() -> None:
        _access(svc).remove_openrouter_key()

    @r.put("/api/setup/access/local", response_model=LocalOut)
    def put_local(body: LocalIn) -> dict[str, Any]:
        return {"models": _access(svc).set_local(body.url)}

    return r


def _vendor_routes(svc: Any) -> APIRouter:
    """Direct vendor keys."""
    r = APIRouter()

    @r.get("/api/setup/providers", response_model=list[ProviderOut])
    def get_providers() -> list[dict[str, Any]]:
        if not _access(svc).vendors_enabled:
            return []
        connected = set(_access(svc).status()["vendors"])
        return [
            {"id": p.id, "label": p.label, "keys_url": p.keys_url, "key_prefix": p.key_prefix,
             "suggested_main": p.suggested.get("main"), "suggested_reviewer": p.suggested.get("reviewer"),
             "connected": p.id in connected}
            for p in PROVIDERS.values()
        ]  # fmt: skip

    @r.put("/api/setup/access/vendor/{provider}", response_model=ModelsOut)
    def put_vendor_key(provider: ProviderId, body: VendorKeyIn) -> dict[str, Any]:
        _vendors(svc)
        """Checks the key by listing the vendor's models (free), keeps it in the secret store, connects it."""
        return {"models": _access(svc).set_vendor_key(provider, body.key)}

    @r.delete("/api/setup/access/vendor/{provider}", status_code=204)
    def delete_vendor_key(provider: ProviderId) -> None:
        _vendors(svc)
        _access(svc).remove_vendor_key(provider)

    @r.get("/api/setup/access/vendor/{provider}/models", response_model=ModelsOut)
    def get_vendor_models(provider: ProviderId) -> dict[str, Any]:
        _vendors(svc)
        return {"models": _access(svc).vendor_models(provider)}

    @r.get("/api/setup/access/openrouter/models", response_model=OpenRouterModelsOut)
    def get_openrouter_models() -> dict[str, Any]:
        """OpenRouter's public models list (cached for a day), for choosing the models an OpenRouter key uses.
        No search on OpenRouter's side: the page filters the list."""
        try:
            return {"models": svc.openrouter_models()}
        except LLMError as e:
            raise HTTPException(502, "OpenRouter could not be reached to list its models") from e

    @r.get("/api/setup/estimate-vendor", response_model=PresetEstimateOut)
    def get_vendor_estimate(
        provider: ModelSource, main: str, reviewer: str, lessons: int = 20
    ) -> dict[str, Any]:
        if not 1 <= lessons <= 200:
            raise HTTPException(422, "lessons must be 1 to 200")
        result: dict[str, Any] = svc.vendor_estimate(provider, main, reviewer, lessons)
        return result

    return r


def _cli_routes(svc: Any) -> APIRouter:
    """Subscription programs (Claude, Codex): readiness, install, sign-in, the plan meter, consent."""
    r = APIRouter()

    @r.get("/api/setup/ai-ready", response_model=AiReadyOut)
    def get_ai_ready(fresh: bool = False) -> dict[str, Any]:
        """Can generation start? False when a chosen subscription program is missing or signed out."""
        result: dict[str, Any] = svc.ai_readiness(fresh=fresh)
        return result

    @r.get("/api/setup/cli/{cli}", response_model=CliOut)
    def get_cli(cli: Literal["claude", "codex"], fresh: bool = False) -> dict[str, Any]:
        return _cli_view(svc, cli, fresh=fresh)

    @r.post("/api/setup/cli/{cli}/install", response_model=CliOut, status_code=202)
    def post_cli_install(cli: Literal["claude", "codex"]) -> dict[str, Any]:
        """Run the vendor's own installer on the machine that runs Yuo (where that is possible)."""
        _cli(svc).start_install(cli)
        return _cli_view(svc, cli)

    @r.post("/api/setup/cli/{cli}/login", response_model=CliOut, status_code=202)
    def post_cli_login(cli: Literal["claude", "codex"]) -> dict[str, Any]:
        """Start the program's sign-in; poll the CLI until `login.url` (paste a code) or `logged_in`."""
        _cli(svc).start_login(cli)
        return _cli_view(svc, cli)

    @r.post("/api/setup/cli/{cli}/login/code", response_model=CliOut)
    def post_cli_code(cli: Literal["claude", "codex"], body: CliCodeIn) -> dict[str, Any]:
        _cli(svc).submit_code(cli, body.code)
        return _cli_view(svc, cli)

    @r.delete("/api/setup/cli/{cli}/login", response_model=CliOut)
    def delete_cli_login(cli: Literal["claude", "codex"]) -> dict[str, Any]:
        _cli(svc).cancel_login(cli)
        return _cli_view(svc, cli, fresh=True)

    @r.get("/api/setup/plan-meter", response_model=PlanMeterOut)
    def get_plan_meter() -> dict[str, Any]:
        result: dict[str, Any] = svc.plan_meter_view()
        return result

    @r.get("/api/setup/consent/{cli}", response_model=ConsentTextOut)
    def get_consent(cli: Literal["claude", "codex"]) -> dict[str, Any]:
        return {"cli": cli, "version": CONSENT_VERSION, "text": CONSENT_TEXT[cli]}

    return r


def _learner(svc: Any) -> APIRouter:
    """Onboarding and the learner."""
    r = APIRouter()

    @r.get("/api/onboarding", response_model=OnboardingOut)
    def get_onboarding() -> dict[str, Any]:
        result: dict[str, Any] = svc.onboarding()
        return result

    @r.post("/api/onboarding/done", response_model=OnboardingOut)
    def post_onboarding_done() -> dict[str, Any]:
        svc.finish_onboarding()
        result: dict[str, Any] = svc.onboarding()
        return result

    @r.get("/api/setup/answers", response_model=SetupAnswersOut)
    def get_setup_answers() -> dict[str, Any]:
        """The answers an AI assistant left in the data folder, until the wizard is done (SETUP.md)."""
        result: dict[str, Any] = svc.setup_answers()
        return result

    @r.delete("/api/setup/answers", status_code=204)
    def delete_setup_answers() -> None:
        """The learner chose not to use them: the file is deleted."""
        svc.discard_setup_answers()

    @r.get("/api/me", response_model=MeOut)
    def get_me() -> dict[str, Any]:
        result: dict[str, Any] = svc.me()
        return result

    @r.patch("/api/me", response_model=MeOut)
    def patch_me(body: MeIn) -> dict[str, Any]:
        result: dict[str, Any] = svc.update_me(body.model_dump(exclude_none=True))
        return result

    return r


def _update_routes(svc: Any) -> APIRouter:
    """Updates."""
    r = APIRouter()

    @r.get("/api/update", response_model=UpdateOut)
    def get_update() -> dict[str, Any]:
        result: dict[str, Any] = _updates(svc).status()
        return result

    @r.post("/api/update/check", response_model=UpdateOut)
    def post_update_check() -> dict[str, Any]:
        _updates(svc).check(force=True)
        result: dict[str, Any] = _updates(svc).status()
        return result

    @r.post("/api/update/download", response_model=UpdateOut)
    def post_update_download() -> dict[str, Any]:
        result: dict[str, Any] = _updates(svc).stage()
        return result

    @r.post("/api/update/restart", status_code=202)
    def post_update_restart() -> None:
        _updates(svc).restart()

    return r


def _desktop(desktop: Any) -> APIRouter:
    """The desktop app: its launcher's private routes."""
    r = APIRouter()

    @r.post("/api/desktop/link", response_model=LinkOut)
    def post_link(request: Request) -> dict[str, str]:
        """A second start of Yuo while it runs: the launcher asks this one for a new sign-in link. Public
        route, guarded by the control token from the data folder (readable by this user only)."""
        sent = request.headers.get("x-yuo-control", "")
        if not hmac.compare_digest(sent.encode(), desktop.control_token.encode()):
            raise HTTPException(403, "not allowed")
        return {"url": desktop.link()}

    @r.post("/api/desktop/open", status_code=202, responses={429: {"description": "opened a moment ago"}})
    def post_open(body: OpenIn) -> None:
        """A signed-out tab: open Yuo signed in, in a new tab of this computer's browser. Public route; it
        only makes the server open a fresh sign-in link locally, so the caller learns nothing."""
        if not desktop.reopen(body.auto):
            raise HTTPException(429, "Yuo was opened a moment ago")

    @r.post("/api/desktop/quit", status_code=202)
    def post_quit() -> None:
        desktop.quit()

    return r
