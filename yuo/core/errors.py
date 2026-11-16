"""Error base classes shared by every context."""


class YuoError(Exception):
    """Base for errors Yuo raises on purpose."""


# --- errors the API answers with a status (yuo.api.app maps each one); anything else is a bug and a 500 ---


class NotFound(YuoError, LookupError):
    """The thing asked for does not exist (404)."""


class Conflict(YuoError, LookupError):
    """It exists, but its state does not allow this now (409): not ready yet, busy, already done."""


class InvalidInput(YuoError, ValueError):
    """The request asks for something that can never be valid (422); the message is shown to the learner."""


class StartupError(YuoError):
    """The process cannot start safely; the message is shown to the user as is."""


class IntegrityError(YuoError):
    """A data invariant would be broken."""


class AiNotReady(RuntimeError):
    """The chosen AI access cannot run yet (409 with a code the app turns into a setup step)."""

    def __init__(self, cli: str, reason: str) -> None:
        super().__init__(f"{cli}: {reason}")
        self.cli, self.reason = cli, reason
