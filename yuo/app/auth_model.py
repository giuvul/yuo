"""Sign-in types the API needs without the database layer (the import contract): the origin, a session, errors."""

from dataclasses import dataclass
from urllib.parse import urlsplit

from yuo.core.errors import InvalidInput


class AuthError(Exception):
    """A sign-in step was refused; the message is safe to show."""


class Throttled(AuthError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("too many failed attempts; try again later or use a passkey")
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class Origin:
    """The install's one canonical origin: passkeys are bound to its host name."""

    url: str  # scheme://host[:port], no path

    @classmethod
    def parse(cls, url: str) -> Origin:
        parts = urlsplit(url.strip().rstrip("/"))
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.path or parts.query:
            raise InvalidInput(f"the origin must look like https://host[:port], not {url!r}")
        if parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise InvalidInput("a non-local origin must use https (passkeys and secure cookies need it)")
        return cls(f"{parts.scheme}://{parts.netloc}")

    @property
    def host(self) -> str:
        return urlsplit(self.url).hostname or ""

    @property
    def netloc(self) -> str:
        return urlsplit(self.url).netloc

    @property
    def secure(self) -> bool:
        return self.url.startswith("https://")


@dataclass(frozen=True, slots=True)
class Session:
    id: str
    device_id: str
    learner_id: str
    token: str | None = None  # only right after sign-in, to set the cookie
