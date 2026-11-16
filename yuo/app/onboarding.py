"""The environment wizard and learner onboarding: probe, recommendation, estimate, the learner's profile.

A part of the application service (yuo.app.context). The probe result and the onboarding milestones live in `installation.env_profile`; the
learner's choices (theme, session length, interests) are ordinary settings, so Settings shows and changes
them later.
"""

import json
import sqlite3
from typing import Any
from zoneinfo import available_timezones

from yuo.app import setup_answers
from yuo.app.context import AppContext, Part
from yuo.app.ports import Learners
from yuo.core import clock
from yuo.core.errors import Conflict, InvalidInput
from yuo.generation import estimate as est
from yuo.setup import models, providers, recommend, settings
from yuo.setup.probe import Probe

LANG = r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$"


class Onboarding(Part):
    """The wizard's part of the service; `prober`, `access` and `plan_meter` are set on the context by main."""

    def __init__(self, ctx: AppContext, *, learners: Learners) -> None:
        super().__init__(ctx)
        self.learners = learners

    def _profile(self, c: sqlite3.Connection) -> dict[str, Any]:
        row = c.execute("SELECT env_profile FROM installation ORDER BY created_at LIMIT 1").fetchone()
        return json.loads(row[0]) if row else {}

    def _save_profile(self, change: dict[str, Any]) -> None:
        self.learners.ensure_learner()  # makes the installation row

        def unit(c: sqlite3.Connection) -> None:
            merged = self._profile(c) | change
            c.execute("UPDATE installation SET env_profile = json(?)", (json.dumps(merged),))

        self.writer.run(unit)

    # --- the machine -------------------------------------------------------------------------------

    def run_probe(self) -> Probe:
        if self.prober is None:
            raise Conflict("no machine probe in this process")
        p = self.prober()
        self._save_profile({"probe": p.as_json(), "probed_at": clock.now()})
        return p

    def last_probe(self) -> Probe | None:
        with self.readers.connection() as c:
            data = self._profile(c).get("probe")
        return Probe.from_json(data) if data else None

    def recommendation(self) -> dict[str, Any]:
        p = self.last_probe() or self.run_probe()
        has_key = bool(self.access and self.access.status()["openrouter"])
        r = recommend.recommend(p, has_openrouter_key=has_key)
        options = []
        for preset in [r.preset, *r.alternatives]:
            e = self.estimate_for(preset)
            options.append({"preset": preset, "estimate": e})
        return r.as_dict() | {"options": options, "probe": p.as_json()}

    def estimate_for(self, preset: str, lessons: int = 20) -> dict[str, Any]:
        """In onboarding: what a typical path costs with this preset, before it is chosen."""
        with self.readers.connection() as c:
            result: dict[str, Any] = est.estimate(
                c, models.preset_bindings(preset), self.prices, lessons=lessons
            ).as_dict()
        return result | {"lessons": lessons}

    def vendor_estimate(
        self, provider_id: str, main: str, reviewer: str, lessons: int = 20
    ) -> dict[str, Any]:
        """For a direct vendor key: the chosen models' cost for a typical path, before binding them."""
        adapter = _adapter(provider_id)
        with self.readers.connection() as c:
            result: dict[str, Any] = est.estimate(
                c, models.split_bindings(adapter, main, reviewer), self.prices, lessons=lessons
            ).as_dict()
        return result | {"lessons": lessons}

    def bind_vendor(self, provider_id: str, main: str, reviewer: str) -> None:
        """Binds a direct key's models: `main` for every role, `reviewer` for the reviewer. The models must be
        ones the vendor lists for the key; for OpenRouter, ones in its public models list."""
        if provider_id == "openrouter":
            available = {m["id"] for m in self.openrouter_models()}
        else:
            available = set(self.access.vendor_models(provider_id))
        for model in (main, reviewer):
            if model not in available:
                raise InvalidInput(f"{model} is not among the models this {provider_id} key can use")
        adapter = _adapter(provider_id)
        self.writer.run(lambda c: models.bind_split(c, adapter, main, reviewer))

    def openrouter_models(self) -> list[dict[str, Any]]:
        """OpenRouter's text models with prices ([] when this process has no price list)."""
        catalog = getattr(self.prices, "catalog", None)
        return catalog() if catalog is not None else []

    def plan_meter_view(self) -> dict[str, Any]:
        return self.plan_meter.snapshot() if self.plan_meter is not None else {"claude": None, "codex": None}

    # --- onboarding milestones ---------------------------------------------------------------------

    def onboarding(self) -> dict[str, Any]:
        with self.readers.connection() as c:
            prof = self._profile(c)
            bound = (
                c.execute("SELECT 1 FROM adapter_binding WHERE port = 'llm' LIMIT 1").fetchone() is not None
            )
            paths = c.execute("SELECT count(*) FROM path").fetchone()[0]
        return {
            "probed": "probe" in prof,
            "models_chosen": bound,
            "profile_done": "profile_at" in prof,
            "has_path": paths > 0,
            "done": "onboarded_at" in prof,
        }

    def finish_onboarding(self) -> None:
        self._save_profile({"onboarded_at": clock.now()})
        self.discard_setup_answers()  # used once: the wizard is done

    def setup_answers(self) -> dict[str, Any]:
        """What an AI assistant collected before Yuo started, for the wizard to start from (SETUP.md)."""
        if self.answers_file is None:
            return {}
        with self.readers.connection() as c:
            if "onboarded_at" in self._profile(c):
                return {}
        return setup_answers.read(self.answers_file)

    def discard_setup_answers(self) -> None:
        if self.answers_file is not None:
            setup_answers.discard(self.answers_file)

    # --- the learner -------------------------------------------------------------------------------

    def me(self) -> dict[str, Any]:
        learner = self.learners.ensure_learner()
        with self.readers.connection() as c:
            row = c.execute(
                "SELECT display_name, ui_lang, default_content_lang, tz FROM learner WHERE id = ?", (learner,)
            ).fetchone()
            scopes: dict[settings.Level, str | None] = {"learner": learner}
            return {
                "display_name": row[0],
                "ui_lang": row[1],
                "content_lang": row[2],
                "tz": row[3],
                "theme": settings.effective(c, "ui.theme", scopes)[0],
                "session_minutes": settings.effective(c, "session.minutes", scopes)[0],
                "interests": settings.effective(c, "learner.interests", scopes)[0],
            }

    def update_me(self, change: dict[str, Any]) -> dict[str, Any]:
        learner = self.learners.ensure_learner()
        if "tz" in change and change["tz"] not in available_timezones():
            raise InvalidInput(f"unknown time zone {change['tz']!r}")
        columns = {"display_name": "display_name", "ui_lang": "ui_lang", "content_lang": "default_content_lang",
                   "tz": "tz"}  # fmt: skip
        keyed = {"theme": "ui.theme", "session_minutes": "session.minutes", "interests": "learner.interests"}
        values = {k: settings.validate(keyed[k], v) for k, v in change.items() if k in keyed}

        def unit(c: sqlite3.Connection) -> None:
            for k, col in columns.items():
                if k in change:
                    c.execute(f"UPDATE learner SET {col} = ? WHERE id = ?", (change[k], learner))
            for k, v in values.items():
                settings.put(c, keyed[k], v, "learner", learner)

        self.writer.run(unit)
        self._save_profile({"profile_at": clock.now()})
        return self.me()


def _adapter(provider_id: str) -> str:
    """`openrouter` is reached with the OpenRouter key; every other id is a direct vendor key."""
    return "openrouter" if provider_id == "openrouter" else providers.PROVIDERS[provider_id].adapter
