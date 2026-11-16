"""Sign-in routes and the request guards.

Every request: the Host header must name this install (DNS rebinding). Every `/api` request except health and
the sign-in flow: a live session cookie. Every unsafe method (POST, PUT, PATCH, DELETE): the custom header
`X-Yuo-Request: 1` (a cross-site form cannot send it without a CORS preflight, which is never granted) and, when
the browser sends one, an `Origin` equal to the install's origin. The session cookie is `HttpOnly`,
`SameSite=Strict`, and `Secure` with the `__Host-` prefix on https.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from yuo.app.auth_model import AuthError, Session, Throttled

PUBLIC = {"/api/health", "/api/auth/state", "/api/auth/launch", "/api/desktop/link", "/api/desktop/open"}
PUBLIC_PREFIXES = ("/api/auth/setup", "/api/auth/sign-in/")
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
LOOPBACK = {"localhost", "127.0.0.1", "[::1]"}
CSRF_HEADER = "x-yuo-request"


class SetupIn(BaseModel):
    code: str = Field(min_length=4, max_length=64)
    device_label: str = Field(default="browser", max_length=80)


class LaunchIn(BaseModel):
    code: str = Field(min_length=16, max_length=64)


class PasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=1024)
    device_label: str = Field(default="browser", max_length=80)


class NewPasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class RecoveryIn(BaseModel):
    code: str = Field(min_length=4, max_length=64)
    device_label: str = Field(default="browser", max_length=80)


class PasskeyIn(BaseModel):
    challenge_id: str = Field(max_length=64)
    credential: dict[str, Any]
    label: str = Field(default="Passkey", max_length=80)


class PasskeySignInIn(BaseModel):
    challenge_id: str = Field(max_length=64)
    credential: dict[str, Any]
    device_label: str = Field(default="browser", max_length=80)


class AuthStateOut(BaseModel):
    signed_in: bool
    desktop: bool  # starting Yuo signs in (the launch link); no passkey or password to set up
    enrolled: bool
    methods: list[str]
    device_id: str | None
    recovery_codes_left: int | None  # only when signed in


class SignedInOut(BaseModel):
    device_id: str


class OptionsOut(BaseModel):
    challenge_id: str
    options: dict[str, Any]  # PublicKeyCredential{Creation,Request}Options as JSON, for the browser


class RecoveryCodesOut(BaseModel):
    codes: list[str]  # shown once


class CredentialOut(BaseModel):
    id: str
    kind: str
    label: str
    created_at: str
    last_used_at: str | None


class DeviceListOut(BaseModel):
    id: str
    label: str
    user_agent: str
    first_seen: str
    last_seen: str
    sessions: int
    current: bool


def _host(request: Request) -> str:
    return request.headers.get("host", "").lower()


def install(app: FastAPI, auth: Any, *, extra_hosts: frozenset[str] = frozenset()) -> None:
    origin = auth.origin
    cookie = "__Host-yuo_session" if origin.secure else "yuo_session"
    hosts = {origin.netloc.lower(), *(h.lower() for h in extra_hosts)}

    def host_ok(host: str) -> bool:
        if host in hosts:
            return True
        name = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        return name in LOOPBACK  # a rebinding page cannot make the browser send these

    @app.middleware("http")
    async def guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if not host_ok(_host(request)):
            return JSONResponse({"detail": "unknown host"}, status_code=421)
        path = request.url.path
        if request.method in UNSAFE:
            sent = request.headers.get("origin")
            if request.headers.get(CSRF_HEADER) != "1" or (sent is not None and sent != origin.url):
                return JSONResponse({"detail": "cross-site request refused"}, status_code=403)
        request.state.session = auth.session(request.cookies.get(cookie))
        public = path in PUBLIC or path.startswith(PUBLIC_PREFIXES) or not path.startswith("/api/")
        if not public and request.state.session is None:
            return JSONResponse({"detail": "sign in first"}, status_code=401)
        return await call_next(request)

    @app.exception_handler(AuthError)
    async def refused(_: Request, exc: AuthError) -> JSONResponse:
        if isinstance(exc, Throttled):
            return JSONResponse(
                {"detail": str(exc)}, status_code=429, headers={"Retry-After": str(exc.retry_after)}
            )
        return JSONResponse({"detail": str(exc)}, status_code=400)

    app.include_router(_routes(auth, cookie))


def _routes(auth: Any, cookie: str) -> APIRouter:
    """Sign-in, sign-out, passkeys, the password, recovery codes, credentials and devices."""
    origin = auth.origin
    r = APIRouter()

    def signed_in(response: Response, session: Session) -> dict[str, str]:
        response.set_cookie(
            cookie, session.token or "", max_age=30 * 86400, path="/", secure=origin.secure,
            httponly=True, samesite="strict",
        )  # fmt: skip
        return {"device_id": session.device_id}

    def current(request: Request) -> Session:
        s: Session | None = request.state.session
        if s is None:
            raise HTTPException(401, "sign in first")
        return s

    def ua(request: Request) -> str:
        return request.headers.get("user-agent", "")

    @r.get("/api/auth/state", response_model=AuthStateOut)
    def get_state(request: Request) -> dict[str, Any]:
        s: Session | None = request.state.session
        return {
            "signed_in": s is not None,
            "desktop": auth.desktop,
            "enrolled": auth.enrolled(),
            "methods": auth.methods(),
            "device_id": s.device_id if s else None,
            "recovery_codes_left": auth.recovery_codes_left() if s else None,
        }

    @r.post("/api/auth/setup", response_model=SignedInOut)
    def post_setup(body: SetupIn, request: Request, response: Response) -> dict[str, str]:
        """Redeem the one-time setup code from the server's log; then add a passkey or a password."""
        return signed_in(response, auth.redeem_setup_code(body.code, body.device_label, ua(request)))

    @r.post("/api/auth/launch", response_model=SignedInOut)
    def post_launch(body: LaunchIn, request: Request, response: Response) -> dict[str, str]:
        """The code from the link the launcher opened (URL fragment), traded for a session."""
        if not auth.desktop:
            raise HTTPException(404, "not found")
        return signed_in(response, auth.redeem_launch_code(body.code, "this computer", ua(request)))

    @r.post("/api/auth/sign-in/password", response_model=SignedInOut)
    def post_sign_in_password(body: PasswordIn, request: Request, response: Response) -> dict[str, str]:
        return signed_in(response, auth.sign_in_password(body.password, body.device_label, ua(request)))

    @r.post("/api/auth/sign-in/recovery", response_model=SignedInOut)
    def post_sign_in_recovery(body: RecoveryIn, request: Request, response: Response) -> dict[str, str]:
        return signed_in(response, auth.sign_in_recovery(body.code, body.device_label, ua(request)))

    @r.post("/api/auth/sign-in/passkey/options", response_model=OptionsOut)
    def post_sign_in_options() -> dict[str, Any]:
        result: dict[str, Any] = auth.passkey_sign_in_options()
        return result

    @r.post("/api/auth/sign-in/passkey", response_model=SignedInOut)
    def post_sign_in_passkey(body: PasskeySignInIn, request: Request, response: Response) -> dict[str, str]:
        session = auth.sign_in_passkey(body.challenge_id, body.credential, body.device_label, ua(request))
        return signed_in(response, session)

    @r.post("/api/auth/sign-out", status_code=204)
    def post_sign_out(request: Request, response: Response) -> None:
        auth.sign_out(current(request).id)
        response.delete_cookie(cookie, path="/", secure=origin.secure, httponly=True, samesite="strict")

    @r.post("/api/auth/passkeys/options", response_model=OptionsOut)
    def post_passkey_options() -> dict[str, Any]:
        result: dict[str, Any] = auth.passkey_registration_options()
        return result

    @r.post("/api/auth/passkeys", status_code=201, response_model=CredentialOut)
    def post_passkey(body: PasskeyIn) -> dict[str, Any]:
        pid = auth.add_passkey(body.challenge_id, body.credential, body.label)
        found: dict[str, Any] = next(c for c in auth.credentials() if c["id"] == pid)
        return found

    @r.put("/api/auth/password", status_code=204)
    def put_password(body: NewPasswordIn) -> None:
        auth.set_password(body.password)

    @r.post("/api/auth/recovery-codes", response_model=RecoveryCodesOut)
    def post_recovery_codes() -> dict[str, list[str]]:
        """Ten new codes; the old ones stop working. Shown once: the learner keeps them somewhere safe."""
        return {"codes": auth.new_recovery_codes()}

    @r.get("/api/auth/credentials", response_model=list[CredentialOut])
    def get_credentials() -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = auth.credentials()
        return result

    @r.delete("/api/auth/credentials/{credential_id}", status_code=204)
    def delete_credential(credential_id: str) -> None:
        auth.remove_credential(credential_id)

    @r.get("/api/auth/devices", response_model=list[DeviceListOut])
    def get_devices(request: Request) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = auth.devices(current(request).device_id)
        return result

    @r.delete("/api/auth/devices/{device_id}", status_code=204)
    def delete_device(device_id: str) -> None:
        """Signs the device out everywhere; its queued events are refused from then on."""
        auth.revoke_device(device_id)

    return r
