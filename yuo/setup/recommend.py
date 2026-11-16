"""The recommendation screen's rule: which models to use on this machine, and why.

1. A subscription CLI on this machine: its preset (Claude Code first, then Codex).
2. Otherwise Qwen 3.8 27B for every role: on this machine when it has 24 GB of GPU memory, or 32 GB or more
   of Apple unified memory (the 18 GB q4 build plus the context); otherwise through OpenRouter.

Reasons are codes with values, so the web app words them in the learner's language.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from yuo.setup.probe import Probe

LOCAL_MODEL = "qwen3.8:27b"
MIN_VRAM_GB = 24
MIN_UNIFIED_GB = 32

Preset = Literal["claude", "codex", "local", "open"]


@dataclass(frozen=True, slots=True)
class Reason:
    code: str
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Recommendation:
    preset: Preset
    reasons: list[Reason]
    needs: list[str]  # what is left to do: consent, openrouter_key, local_server, local_model
    alternatives: list[Preset]

    def as_dict(self) -> dict[str, Any]:
        return {
            "preset": self.preset,
            "reasons": [{"code": r.code, "values": r.values} for r in self.reasons],
            "needs": self.needs,
            "alternatives": self.alternatives,
        }


def local_capable(p: Probe) -> Reason | None:
    if (vram := p.max_vram_gb) is not None and vram >= MIN_VRAM_GB:
        return Reason("gpu_memory", {"gb": vram, "min": MIN_VRAM_GB})
    if (unified := p.unified_memory_gb) is not None and unified >= MIN_UNIFIED_GB:
        return Reason("unified_memory", {"gb": unified, "min": MIN_UNIFIED_GB})
    return None


def recommend(p: Probe, *, has_openrouter_key: bool = False) -> Recommendation:
    local = local_capable(p)
    others: list[Preset] = [x for x in ("claude", "codex") if x in p.clis]
    others += ["local"] if local else []
    others.append("open")
    # a subscription whose program is not on this machine yet is still offered, last: Yuo helps install it
    others += [x for x in ("claude", "codex") if x not in p.clis]
    if "claude" in p.clis:
        return Recommendation("claude", [Reason("cli_found", {"cli": "claude"})], ["consent"], others[1:])
    if "codex" in p.clis:
        return Recommendation("codex", [Reason("cli_found", {"cli": "codex"})], ["consent"], others[1:])
    if local:
        server = next((s for s in p.servers if s.name == "ollama"), None)
        needs = [] if server else ["local_server"]
        if server is None or LOCAL_MODEL not in server.models:
            needs.append("local_model")
        return Recommendation(
            "local",
            [Reason("no_subscription"), local, Reason("local_free")],
            needs,
            [x for x in others if x != "local"],
        )
    short = (
        Reason("gpu_memory_short", {"gb": p.max_vram_gb, "min": MIN_VRAM_GB})
        if p.max_vram_gb is not None
        else Reason("unified_memory_short", {"gb": p.unified_memory_gb, "min": MIN_UNIFIED_GB})
        if p.unified_memory_gb is not None
        else Reason("no_gpu")
    )
    return Recommendation(
        "open",
        [Reason("no_subscription"), short, Reason("api_billed")],
        [] if has_openrouter_key else ["openrouter_key"],
        [x for x in others if x != "open"],
    )
