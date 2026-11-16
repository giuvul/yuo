"""Sign-in for the server version: passkeys, a password as the fallback, recovery codes, sessions.

One learner per install, so there is no user name: a credential belongs to the learner. A fresh install
has no credential; the first one is enrolled with a one-time setup code that only the person who runs the
server can see (printed at startup, and by `yuo setup-code`), so nobody else can claim a public install. A new
code is issued at every start while no credential exists, and on demand from the command line, which is also
the way back in when every credential and recovery code is lost.

Sessions are opaque random tokens; only their SHA-256 is stored. Each session belongs to a device, and revoking
a device ends its sessions. Passkey challenges live in memory for five minutes (one process owns the install).
Password and recovery-code guesses are throttled; passkey sign-in is not (nothing to guess), so a flood of bad
guesses cannot lock the owner out.
"""

import base64
import hashlib
import json
import secrets
import sqlite3
import threading
import time
from datetime import timedelta
from typing import Any

import structlog
import webauthn
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from yuo.app.auth_model import AuthError, Origin, Session, Throttled
from yuo.core import clock
from yuo.core.errors import InvalidInput, NotFound
from yuo.core.ids import new_id
from yuo.db.connection import ReadPool, Writer
from yuo.learning.events import SERVER_DEVICE_LABEL

log = structlog.get_logger(__name__)

SESSION_DAYS = 30  # sliding: extended on use, at most once an hour
SETUP_CODE_HOURS = 24
CHALLENGE_S = 300
LAUNCH_CODE_S = 600  # desktop: the link the launcher opens works once, for ten minutes
MIN_PASSWORD = 10
RECOVERY_CODES = 10
GUESSES = 10  # password or recovery-code failures allowed per window, for the whole install
GUESS_WINDOW_S = 900
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _code(groups: int, size: int) -> str:
    return "-".join("".join(secrets.choice(_ALPHABET) for _ in range(size)) for _ in range(groups))


def _norm(code: str) -> str:
    """Codes are typed by people: case, spaces and dashes do not matter."""
    return "".join(ch for ch in code.upper() if ch in _ALPHABET)


def _b64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


class Auth:
    def __init__(
        self,
        writer: Writer,
        readers: ReadPool,
        origin: Origin,
        *,
        rp_name: str = "Yuo",
        desktop: bool = False,
    ) -> None:
        self.writer = writer
        self.readers = readers
        self.origin = origin
        self.rp_name = rp_name
        if desktop and origin.host not in ("localhost", "127.0.0.1", "::1", "[::1]"):
            raise InvalidInput("desktop sign-in needs a loopback origin")
        self.desktop = desktop
        self._launch: dict[str, float] = {}  # code hash -> expiry, in memory: this process opens the browser
        self._hasher = PasswordHasher()
        self._challenges: dict[str, tuple[bytes, float, str]] = {}  # id -> (challenge, expiry, purpose)
        self._failures: list[float] = []
        self._lock = threading.Lock()

    # --- state ------------------------------------------------------------------------------------

    def enrolled(self) -> bool:
        with self.readers.connection() as c:
            return c.execute("SELECT 1 FROM auth_credential LIMIT 1").fetchone() is not None

    def methods(self) -> list[str]:
        with self.readers.connection() as c:
            return [r[0] for r in c.execute("SELECT DISTINCT kind FROM auth_credential ORDER BY kind")]

    def _learner(self, c: sqlite3.Connection) -> str:
        row = c.execute("SELECT id FROM learner ORDER BY created_at LIMIT 1").fetchone()
        if row is None:
            raise AuthError("the install has no learner yet")
        return str(row[0])

    # --- setup code -------------------------------------------------------------------------------

    def issue_setup_code(self) -> str:
        """A new one-time code (older unused ones stop working). Shown once; only its hash is kept."""
        code = _code(4, 4)
        now = clock.now()
        expires = clock.to_timestamp(clock.parse_timestamp(now) + timedelta(hours=SETUP_CODE_HOURS))

        def unit(c: sqlite3.Connection) -> None:
            c.execute("UPDATE auth_setup_code SET used_at = ? WHERE used_at IS NULL", (now,))
            c.execute(
                "INSERT INTO auth_setup_code (id, code_hash, created_at, expires_at, used_at) VALUES (?, ?, ?, ?, NULL)",
                (new_id(), _sha(_norm(code)), now, expires),
            )

        self.writer.run(unit)
        return code

    def setup_code_on_start(self) -> str | None:
        """At startup: a code while nothing is enrolled, else None."""
        return None if self.enrolled() else self.issue_setup_code()

    def redeem_setup_code(self, code: str, device_label: str, user_agent: str) -> Session:
        self._check_throttle()
        h, now = _sha(_norm(code)), clock.now()

        def unit(c: sqlite3.Connection) -> str | None:
            row = c.execute(
                "SELECT id FROM auth_setup_code WHERE code_hash = ? AND used_at IS NULL AND expires_at > ?",
                (h, now),
            ).fetchone()
            if row is None:
                return None
            c.execute("UPDATE auth_setup_code SET used_at = ? WHERE id = ?", (now, row[0]))
            return self._learner(c)

        if self.writer.run(unit) is None:
            self._fail()
            raise AuthError("that setup code is not valid (codes work once and expire after a day)")
        log.info("auth.setup_code_used")
        return self._start_session(device_label, user_agent)

    # --- desktop launch link ----------------------------------------------------------------

    def issue_launch_code(self) -> str:
        """Is one person on their own machine, served on loopback only: starting Yuo is the sign-in. The
        launcher opens the browser with this code in the URL fragment (never sent in a request line, so
        never in a log); the page trades it for a session cookie. Works once, for ten minutes."""
        if not self.desktop:
            raise AuthError("launch links are for the desktop app only")
        code = secrets.token_urlsafe(24)
        with self._lock:
            now = time.monotonic()
            self._launch = {h: t for h, t in self._launch.items() if t > now}
            self._launch[_sha(code)] = now + LAUNCH_CODE_S
        return code

    def redeem_launch_code(self, code: str, device_label: str, user_agent: str) -> Session:
        if not self.desktop:
            raise AuthError("launch links are for the desktop app only")
        self._check_throttle()
        with self._lock:
            expiry = self._launch.pop(_sha(code), None)
        if expiry is None or expiry < time.monotonic():
            self._fail()
            raise AuthError("this link has been used or is too old: start Yuo again to get a new one")
        with self.readers.connection() as c:
            device = c.execute(
                "SELECT d.id FROM device d WHERE d.revoked_at IS NULL AND d.label = ? ORDER BY d.last_seen DESC LIMIT 1",
                ("this computer",),
            ).fetchone()
        return self._start_session(device_label, user_agent, device[0] if device else None)

    # --- sessions and devices ---------------------------------------------------------------------

    def _start_session(self, device_label: str, user_agent: str, device_id: str | None = None) -> Session:
        token = secrets.token_urlsafe(32)
        now = clock.now()
        if device_label.strip().lower() == SERVER_DEVICE_LABEL:  # the server's own events use that device
            device_label = "browser"
        expires = clock.to_timestamp(clock.parse_timestamp(now) + timedelta(days=SESSION_DAYS))

        def unit(c: sqlite3.Connection) -> Session:
            did = device_id
            if (
                did is None
                or c.execute("SELECT 1 FROM device WHERE id = ? AND revoked_at IS NULL", (did,)).fetchone()
                is None
            ):
                did = new_id()
                c.execute(
                    "INSERT INTO device (id, label, user_agent, first_seen, last_seen, revoked_at) VALUES (?, ?, ?, ?, ?, NULL)",
                    (did, device_label[:80] or "browser", user_agent[:300], now, now),
                )
            sid = new_id()
            c.execute(
                "INSERT INTO auth_session (id, device_id, token_hash, created_at, expires_at, last_seen_at, revoked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (sid, did, _sha(token), now, expires, now),
            )
            return Session(sid, did, self._learner(c), token)

        return self.writer.run(unit)

    def session(self, token: str | None) -> Session | None:
        """The live session for a cookie value, extended when it is in use; None when missing or ended."""
        if not token:
            return None
        now = clock.now()
        with self.readers.connection() as c:
            row = c.execute(
                "SELECT s.id, s.device_id, s.last_seen_at FROM auth_session s JOIN device d ON d.id = s.device_id "
                "WHERE s.token_hash = ? AND s.revoked_at IS NULL AND d.revoked_at IS NULL AND s.expires_at > ?",
                (_sha(token), now),
            ).fetchone()
            if row is None:
                return None
            learner = self._learner(c)
        sid, did, seen = row
        if seen is None or clock.parse_timestamp(now) - clock.parse_timestamp(seen) > timedelta(hours=1):
            expires = clock.to_timestamp(clock.parse_timestamp(now) + timedelta(days=SESSION_DAYS))

            def touch(c: sqlite3.Connection) -> None:
                c.execute(
                    "UPDATE auth_session SET last_seen_at = ?, expires_at = ? WHERE id = ?",
                    (now, expires, sid),
                )
                c.execute("UPDATE device SET last_seen = ? WHERE id = ?", (now, did))

            self.writer.run(touch)
        return Session(sid, did, learner)

    def sign_out(self, session_id: str) -> None:
        self.writer.run(
            lambda c: c.execute(
                "UPDATE auth_session SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (clock.now(), session_id),
            )
        )

    def devices(self, current_device: str) -> list[dict[str, Any]]:
        with self.readers.connection() as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT d.id, d.label, d.user_agent, d.first_seen, d.last_seen, "
                "(SELECT count(*) FROM auth_session s WHERE s.device_id = d.id AND s.revoked_at IS NULL "
                " AND s.expires_at > ?) AS sessions "
                "FROM device d WHERE d.revoked_at IS NULL AND NOT (d.label = ? AND d.user_agent = 'yuo') "
                "ORDER BY d.last_seen DESC",
                (clock.now(), SERVER_DEVICE_LABEL),
            ).fetchall()
        return [dict(r) | {"current": r["id"] == current_device} for r in rows]

    def revoke_device(self, device_id: str) -> None:
        now = clock.now()

        def unit(c: sqlite3.Connection) -> None:
            if (
                c.execute(
                    "UPDATE device SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL", (now, device_id)
                ).rowcount
                == 0
            ):
                raise NotFound("no such device")
            c.execute(
                "UPDATE auth_session SET revoked_at = ? WHERE device_id = ? AND revoked_at IS NULL",
                (now, device_id),
            )

        self.writer.run(unit)
        log.info("auth.device_revoked", device=device_id)

    # --- throttle ---------------------------------------------------------------------------------

    def _check_throttle(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._failures = [t for t in self._failures if now - t < GUESS_WINDOW_S]
            if len(self._failures) >= GUESSES:
                raise Throttled(int(GUESS_WINDOW_S - (now - self._failures[0])) + 1)

    def _fail(self) -> None:
        with self._lock:
            self._failures.append(time.monotonic())
        log.warning("auth.failed_guess")

    # --- password ---------------------------------------------------------------------------------

    def set_password(self, password: str) -> None:
        if len(password) < MIN_PASSWORD:
            raise AuthError(f"use at least {MIN_PASSWORD} characters")
        h, now = self._hasher.hash(password), clock.now()

        def unit(c: sqlite3.Connection) -> None:
            learner = self._learner(c)
            c.execute("DELETE FROM auth_credential WHERE kind = 'password'")
            c.execute(
                "INSERT INTO auth_credential (id, learner_id, kind, password_hash, public_key, credential_id, sign_count, "
                "transports, label, created_at, last_used_at) VALUES (?, ?, 'password', ?, NULL, NULL, 0, NULL, 'Password', ?, NULL)",
                (new_id(), learner, h, now),
            )

        self.writer.run(unit)

    def sign_in_password(self, password: str, device_label: str, user_agent: str) -> Session:
        self._check_throttle()
        with self.readers.connection() as c:
            row = c.execute(
                "SELECT id, password_hash FROM auth_credential WHERE kind = 'password'"
            ).fetchone()
        try:
            if row is None:
                raise VerificationError
            self._hasher.verify(row[1], password)
        except VerificationError:
            self._fail()
            raise AuthError("wrong password") from None
        self._used(row[0])
        return self._start_session(device_label, user_agent)

    def _used(self, credential_id: str, sign_count: int | None = None) -> None:
        now = clock.now()
        if sign_count is None:
            self.writer.run(
                lambda c: c.execute(
                    "UPDATE auth_credential SET last_used_at = ? WHERE id = ?", (now, credential_id)
                )
            )
        else:
            self.writer.run(
                lambda c: c.execute(
                    "UPDATE auth_credential SET last_used_at = ?, sign_count = ? WHERE id = ?",
                    (now, sign_count, credential_id),
                )
            )

    # --- recovery codes ---------------------------------------------------------------------------

    def new_recovery_codes(self) -> list[str]:
        """Ten fresh codes; the old ones stop working. Shown once."""
        codes = [_code(2, 5) for _ in range(RECOVERY_CODES)]
        now = clock.now()

        def unit(c: sqlite3.Connection) -> None:
            learner = self._learner(c)
            c.execute("DELETE FROM auth_recovery_code")
            c.executemany(
                "INSERT INTO auth_recovery_code (id, learner_id, code_hash, created_at, used_at) VALUES (?, ?, ?, ?, NULL)",
                [(new_id(), learner, _sha(_norm(code)), now) for code in codes],
            )

        self.writer.run(unit)
        return codes

    def recovery_codes_left(self) -> int:
        with self.readers.connection() as c:
            return int(
                c.execute("SELECT count(*) FROM auth_recovery_code WHERE used_at IS NULL").fetchone()[0]
            )

    def sign_in_recovery(self, code: str, device_label: str, user_agent: str) -> Session:
        self._check_throttle()
        h, now = _sha(_norm(code)), clock.now()
        ok = self.writer.run(
            lambda c: (
                c.execute(
                    "UPDATE auth_recovery_code SET used_at = ? WHERE code_hash = ? AND used_at IS NULL",
                    (now, h),
                ).rowcount
            )
        )
        if not ok:
            self._fail()
            raise AuthError("that recovery code is not valid or was already used")
        log.info("auth.recovery_code_used", left=self.recovery_codes_left())
        return self._start_session(device_label, user_agent)

    # --- passkeys ---------------------------------------------------------------------------------

    def _challenge(self, purpose: str, challenge: bytes) -> str:
        cid = secrets.token_urlsafe(16)
        now = time.monotonic()
        with self._lock:
            self._challenges = {k: v for k, v in self._challenges.items() if v[1] > now}
            self._challenges[cid] = (challenge, now + CHALLENGE_S, purpose)
        return cid

    def _take_challenge(self, cid: str, purpose: str) -> bytes:
        with self._lock:
            got = self._challenges.pop(cid, None)
        if got is None or got[1] < time.monotonic() or got[2] != purpose:
            raise AuthError("the passkey request expired; try again")
        return got[0]

    def passkey_registration_options(self) -> dict[str, Any]:
        with self.readers.connection() as c:
            learner = self._learner(c)
            name = c.execute("SELECT display_name FROM learner WHERE id = ?", (learner,)).fetchone()[0]
            existing = [
                r[0] for r in c.execute("SELECT credential_id FROM auth_credential WHERE kind = 'passkey'")
            ]
        options = webauthn.generate_registration_options(
            rp_id=self.origin.host,
            rp_name=self.rp_name,
            user_id=learner.encode(),
            user_name=name or "learner",
            user_display_name=name or "Learner",
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,  # discoverable: no user name to type
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
            exclude_credentials=[PublicKeyCredentialDescriptor(id=_b64(x)) for x in existing],
        )
        cid = self._challenge("register", options.challenge)
        return {"challenge_id": cid, "options": json.loads(webauthn.options_to_json(options))}

    def add_passkey(self, challenge_id: str, credential: dict[str, Any], label: str) -> str:
        challenge = self._take_challenge(challenge_id, "register")
        try:
            v = webauthn.verify_registration_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=self.origin.host,
                expected_origin=self.origin.url,
            )
        except Exception as e:  # the library raises several types for a bad response
            raise AuthError(f"the passkey could not be verified: {e}") from e
        pid, now = new_id(), clock.now()
        transports = credential.get("response", {}).get("transports")

        def unit(c: sqlite3.Connection) -> None:
            c.execute(
                "INSERT INTO auth_credential (id, learner_id, kind, password_hash, public_key, credential_id, sign_count, "
                "transports, label, created_at, last_used_at) VALUES (?, ?, 'passkey', NULL, ?, ?, ?, ?, ?, ?, NULL)",
                (
                    pid, self._learner(c), bytes_to_base64url(v.credential_public_key),
                    bytes_to_base64url(v.credential_id), v.sign_count,
                    json.dumps(transports) if isinstance(transports, list) else None, label[:80] or "Passkey", now,
                ),
            )  # fmt: skip

        self.writer.run(unit)
        log.info("auth.passkey_added")
        return pid

    def passkey_sign_in_options(self) -> dict[str, Any]:
        options = webauthn.generate_authentication_options(
            rp_id=self.origin.host, user_verification=UserVerificationRequirement.PREFERRED
        )
        cid = self._challenge("sign_in", options.challenge)
        return {"challenge_id": cid, "options": json.loads(webauthn.options_to_json(options))}

    def sign_in_passkey(
        self, challenge_id: str, credential: dict[str, Any], device_label: str, user_agent: str
    ) -> Session:
        challenge = self._take_challenge(challenge_id, "sign_in")
        raw_id = str(credential.get("rawId") or credential.get("id") or "")
        with self.readers.connection() as c:
            row = c.execute(
                "SELECT id, public_key, sign_count FROM auth_credential WHERE kind = 'passkey' AND credential_id = ?",
                (raw_id.rstrip("="),),
            ).fetchone()
        if row is None:
            raise AuthError("this passkey is not registered here")
        try:
            v = webauthn.verify_authentication_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=self.origin.host,
                expected_origin=self.origin.url,
                credential_public_key=_b64(row[1]),
                credential_current_sign_count=row[2],
            )
        except Exception as e:
            raise AuthError(f"the passkey could not be verified: {e}") from e
        self._used(row[0], v.new_sign_count)
        return self._start_session(device_label, user_agent)

    # --- credentials ------------------------------------------------------------------------------

    def credentials(self) -> list[dict[str, Any]]:
        with self.readers.connection() as c:
            c.row_factory = sqlite3.Row
            return [
                dict(r)
                for r in c.execute(
                    "SELECT id, kind, label, created_at, last_used_at FROM auth_credential ORDER BY created_at"
                )
            ]

    def remove_credential(self, credential_id: str) -> None:
        def unit(c: sqlite3.Connection) -> None:
            if c.execute("SELECT 1 FROM auth_credential WHERE id = ?", (credential_id,)).fetchone() is None:
                raise NotFound("no such credential")
            if c.execute("SELECT count(*) FROM auth_credential").fetchone()[0] <= 1:
                raise AuthError("this is the only way to sign in; add another one first")
            c.execute("DELETE FROM auth_credential WHERE id = ?", (credential_id,))

        self.writer.run(unit)
