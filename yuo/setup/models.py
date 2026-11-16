"""Model bindings per role: presets, capability defaults, independence check."""

import json
import sqlite3
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Any, cast

from yuo.core.errors import Conflict
from yuo.core.ids import new_id
from yuo.core.llm import Binding, Effort, Role, StructuredMode

ROLES: tuple[Role, ...] = ("generator", "reviewer", "tutor", "grader", "utility")


@dataclass(frozen=True, slots=True)
class Capability:
    adapter: str
    model: str
    mode: StructuredMode
    verified: bool
    roles: dict[str, dict[str, Any]]
    avoid: tuple[str, ...] = ()


@cache
def _data() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        files("yuo.data").joinpath("capabilities.json").read_text(encoding="utf-8")
    )
    return loaded


def capability(adapter: str, model: str) -> Capability | None:
    for m in _data()["models"]:
        if m["adapter"] == adapter and m["model"] == model:
            return Capability(
                adapter,
                model,
                StructuredMode(m["mode"]),
                m["verified"],
                m["roles"],
                tuple(m.get("avoid", ())),
            )
    return None


def presets() -> dict[str, dict[str, list[str]]]:
    return cast(dict[str, dict[str, list[str]]], _data()["presets"])


def apply_preset(c: sqlite3.Connection, preset: str) -> None:
    roles = presets()[preset]
    c.execute("DELETE FROM adapter_binding WHERE port = 'llm'")
    for role, (adapter, model) in roles.items():
        bind(c, cast(Role, role), adapter, model)


def bind(
    c: sqlite3.Connection, role: Role, adapter: str, model: str, *, priority: int = 0, **settings: Any
) -> None:
    c.execute(
        "DELETE FROM adapter_binding WHERE port = 'llm' AND role = ? AND priority = ?", (role, priority)
    )
    c.execute(
        "INSERT INTO adapter_binding (id, port, adapter, role, priority, scope, settings, secret_ref, enabled) "
        "VALUES (?, 'llm', ?, ?, ?, 'installation', json(?), NULL, 1)",
        (new_id(), adapter, role, priority, json.dumps({"model": model, **settings})),
    )


def resolve(c: sqlite3.Connection, role: Role) -> Binding:
    row = c.execute(
        "SELECT adapter, settings FROM adapter_binding WHERE port = 'llm' AND role = ? AND enabled = 1 "
        "ORDER BY priority LIMIT 1",
        (role,),
    ).fetchone()
    if row is None:
        raise Conflict(f"no model bound to the {role} role: choose a preset in Settings")
    return _binding(role, row[0], json.loads(row[1]))


def preset_bindings(preset: str) -> dict[Role, Binding]:
    """What a preset would bind, without binding it (the estimate on the recommendation screen)."""
    return {
        cast(Role, role): _binding(cast(Role, role), adapter, {"model": model})
        for role, (adapter, model) in presets()[preset].items()
    }


def split_bindings(adapter: str, main: str, reviewer: str) -> dict[Role, Binding]:
    """One adapter with a main model for every role and its own reviewer (a direct vendor key)."""
    return {
        role: _binding(role, adapter, {"model": reviewer if role == "reviewer" else main}) for role in ROLES
    }


def bind_split(c: sqlite3.Connection, adapter: str, main: str, reviewer: str) -> None:
    c.execute("DELETE FROM adapter_binding WHERE port = 'llm'")
    for role in ROLES:
        bind(c, role, adapter, reviewer if role == "reviewer" else main)


def _binding(role: Role, adapter: str, settings: dict[str, Any]) -> Binding:
    model = settings["model"]
    cap = capability(adapter, model)
    defaults = (cap.roles.get(role) or {}) if cap else {}
    mode = settings.get("mode") or (cap.mode.value if cap else "prompt")
    return Binding(
        adapter=adapter,
        model=model,
        mode=StructuredMode(mode),
        providers=tuple(settings.get("providers") or defaults.get("providers") or ()),
        avoid=tuple(settings.get("avoid") or (cap.avoid if cap else ())),
        effort=cast(Effort | None, settings.get("effort", defaults.get("effort"))),
        max_tokens=int(settings.get("max_tokens") or defaults.get("max_tokens") or 8000),
        temperature=settings.get("temperature", 0.7),
        role=role,
    )


def independence_warning(generator: Binding, reviewer: Binding) -> str | None:
    """Warn when the reviewer is the same model as the writer."""
    if (generator.adapter, generator.model) == (reviewer.adapter, reviewer.model):
        return (
            f"The reviewer is the same model as the writer ({generator.model}); it will miss more of its own "
            "mistakes. Bind a different reviewer model in Settings when you can."
        )
    return None


def untested_warning(binding: Binding) -> str | None:
    """Only the measured models have tested lesson quality."""
    cap = capability(binding.adapter, binding.model)
    if cap is None or not cap.verified:
        return f"{binding.model} has not been tested with Yuo: lesson quality may be lower."
    return None
