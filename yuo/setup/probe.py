"""What the environment wizard knows about this machine: the probe's result.

Gathered by `yuo.adapters.machine` (local reads and loopback calls only, nothing leaves the machine).
Each reading is best-effort: a part that cannot be read is `None`, never a guess, and the recommendation
treats it as absent. Stored in `installation.env_profile` so the recommendation can be shown again.
"""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Gpu:
    name: str
    memory_gb: float | None
    kind: str  # nvidia | amd | apple


@dataclass
class LocalServer:
    name: str
    url: str  # the OpenAI-compatible base URL
    models: list[str]


@dataclass
class Bench:
    cpu_gflops: float | None = None  # float32 matrix multiply, all cores (numpy)
    seconds: float = 0.0


@dataclass
class Probe:
    os: str  # windows | macos | linux
    os_version: str
    arch: str
    cpu: str | None
    cores: int | None
    memory_gb: float | None
    gpus: list[Gpu]
    disk_free_gb: float | None
    clis: dict[str, str | None]  # name -> version, for the ones found
    servers: list[LocalServer]
    bench: Bench = field(default_factory=Bench)

    @property
    def unified_memory_gb(self) -> float | None:
        """Apple silicon shares memory with the GPU."""
        return self.memory_gb if self.os == "macos" and self.arch == "arm64" else None

    @property
    def max_vram_gb(self) -> float | None:
        known = [g.memory_gb for g in self.gpus if g.kind != "apple" and g.memory_gb is not None]
        return max(known) if known else None

    def as_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Probe:
        return cls(
            **(
                d
                | {
                    "gpus": [Gpu(**g) for g in d["gpus"]],
                    "servers": [LocalServer(**s) for s in d["servers"]],
                    "bench": Bench(**d.get("bench", {})),
                }
            )
        )
