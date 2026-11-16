"""AI access from the wizard: an OpenRouter key, direct vendor keys, a model server on this machine,
subscription consent.

A key entered in the browser is checked with OpenRouter's free key endpoint, kept in the secret store (OS
keychain on desktops) and connected at once: the stage runner's port table gains the adapter, so
no restart. The key never comes back out through the API; the status says only whether one is set.

A direct vendor key (yuo/setup/providers.py) is checked by listing the vendor's models (free), stored as
`vendor:<id>` and connected as the `api:<id>` adapter; the learner then picks models from that list.

Subscription CLIs: the consent text is shown before a Claude or Codex preset applies, and the
learner's yes is recorded with the hash of the text they saw.
"""

import sqlite3
from collections.abc import Callable
from typing import Any

from yuo.core import clock
from yuo.core.errors import InvalidInput, NotFound
from yuo.core.hashing import bytes_hash
from yuo.core.ids import new_id
from yuo.core.llm import LLMPort
from yuo.db.connection import ReadPool, Writer
from yuo.generation.lanes import LanedPort, Slots
from yuo.setup import settings
from yuo.setup.consent import CONSENT_TEXT, CONSENT_VERSION
from yuo.setup.providers import PROVIDERS, Provider, check_key_format


class Access:
    def __init__(
        self,
        writer: Writer,
        readers: ReadPool,
        secrets: Any,  # SecretStore
        ports: dict[str, LLMPort],  # the stage runner's table, changed in place
        *,
        openrouter: Callable[[str], LLMPort],
        local: Callable[[str], LLMPort],
        check_key: Callable[[str], dict[str, Any]],
        list_models: Callable[[str], list[str]],
        vendor: Callable[[Provider, str], LLMPort] | None = None,
        vendor_models: Callable[[Provider, str], list[str]] | None = None,
    ) -> None:
        self.writer = writer
        self.readers = readers
        self.secrets = secrets
        self.ports = ports
        self._openrouter = openrouter
        self._local = local
        self._check_key = check_key
        self._list_models = list_models
        self.vendors_enabled = vendor is not None and vendor_models is not None
        self._vendor = vendor or _no_vendor
        self._vendor_models = vendor_models or _no_vendor
        # is a subscription CLI on this machine? (set by main; the adapters are registered either way)
        self.cli_found: Callable[[str], bool] = lambda name: True

    def status(self) -> dict[str, Any]:
        with self.readers.connection() as c:
            url = settings.effective(c, "ai.local_url", {})[0]
            consents = {
                r[0].removeprefix("subscription-cli:"): r[1]
                for r in c.execute(
                    "SELECT subject, granted FROM consent_record WHERE subject LIKE 'subscription-cli:%' "
                    'ORDER BY "at"'
                )
            }
        return {
            "openrouter": "openrouter" in self.ports,
            "local_url": url,
            "local": "local" in self.ports,
            "clis": sorted(
                n.removesuffix("-cli")
                for n in self.ports
                if n.endswith("-cli") and self.cli_found(n.removesuffix("-cli"))
            ),
            "consent": {k: bool(v) for k, v in consents.items()},
            "vendors": sorted(p.id for p in PROVIDERS.values() if p.adapter in self.ports),
        }

    def _connect(self, name: str, port: LLMPort) -> None:
        self.ports[name] = LanedPort(port, Slots(4))

    # --- OpenRouter ------------------------------------------------------------------------------

    def set_openrouter_key(self, key: str) -> dict[str, Any]:
        key = key.strip()
        if not key.startswith("sk-or-") or len(key) > 200 or any(ch.isspace() for ch in key):
            raise InvalidInput("that does not look like an OpenRouter key (it starts with sk-or-)")
        info = self._check_key(key)  # LLMError(kind="auth") when refused
        self.secrets.set("openrouter", key)
        self._connect("openrouter", self._openrouter(key))
        return info

    def remove_openrouter_key(self) -> None:
        self.secrets.delete("openrouter")
        self.ports.pop("openrouter", None)

    # --- direct vendor keys ----------------------------------------------------------------------

    def _provider(self, provider_id: str) -> Provider:
        if (p := PROVIDERS.get(provider_id)) is None or not self.vendors_enabled:
            raise NotFound(provider_id)
        return p

    def set_vendor_key(self, provider_id: str, key: str) -> list[str]:
        """Checks the key by listing the vendor's models (LLMError kind="auth" when refused), keeps it, connects
        it, and returns the models it may use."""
        p = self._provider(provider_id)
        key = check_key_format(p, key)
        models = self._vendor_models(p, key)
        self.secrets.set(f"vendor:{p.id}", key)
        self._connect(p.adapter, self._vendor(p, key))
        return models

    def remove_vendor_key(self, provider_id: str) -> None:
        p = self._provider(provider_id)
        self.secrets.delete(f"vendor:{p.id}")
        self.ports.pop(p.adapter, None)

    def vendor_models(self, provider_id: str) -> list[str]:
        """The models the stored key may use (asks the vendor again); [] when no key is stored."""
        p = self._provider(provider_id)
        if not (key := self.secrets.get(f"vendor:{p.id}")):
            return []
        return self._vendor_models(p, key)

    # --- a model server on this machine ----------------------------------------------------------

    def set_local(self, url: str) -> list[str]:
        settings.validate("ai.local_url", url)
        models = self._list_models(url)  # LLMError when nothing answers
        self.writer.run(lambda c: settings.put(c, "ai.local_url", url, "installation"))
        self._connect("local", self._local(url))
        return models

    # --- subscription consent ------------------------------------------------------------

    def record_consent(self, learner_id: str, cli: str, granted: bool) -> None:
        text = CONSENT_TEXT[cli]

        def unit(c: sqlite3.Connection) -> None:
            c.execute(
                "INSERT INTO consent_record (id, learner_id, subject, text_hash, granted, at) VALUES (?, ?, ?, ?, ?, ?)",
                (new_id(), learner_id, f"subscription-cli:{cli}", bytes_hash(f"v{CONSENT_VERSION}\n{text}".encode()),
                 int(granted), clock.now()),
            )  # fmt: skip

        self.writer.run(unit)

    def has_consent(self, cli: str) -> bool:
        with self.readers.connection() as c:
            row = c.execute(
                'SELECT granted FROM consent_record WHERE subject = ? ORDER BY "at" DESC LIMIT 1',
                (f"subscription-cli:{cli}",),
            ).fetchone()
        return bool(row and row[0])


def _no_vendor(provider: Provider, key: str) -> Any:
    raise NotFound(provider.id)
