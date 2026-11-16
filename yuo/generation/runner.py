"""Stage runner: every model call is a stage run keyed by the hash of all its inputs.

- The manifest holds everything the stage reads; its JCS hash is `input_hash`.
- A succeeded run with the same hash is reused, unless a quality check rejected what it produced.
- Raw responses are stored (`stage_output.raw`); every call gets a `budget_entry`, every call to a
  remote adapter an `egress_record`.
- The budget guard pauses generation at the cap before a call, never after.
Model calls never run inside a writer unit.
"""

import dataclasses
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import structlog
from pydantic import BaseModel

from yuo.core import clock
from yuo.core.enums import DataClass, RunStatus, Stage
from yuo.core.errors import YuoError
from yuo.core.hashing import content_hash
from yuo.core.ids import new_id
from yuo.core.llm import Binding, Completion, LLMError, LLMPort, Message
from yuo.core.logs import metrics
from yuo.db.connection import ReadPool, Writer
from yuo.generation import progress
from yuo.generation.structured import Parse, Rules, StructuredFailure, generate_structured

log = structlog.get_logger(__name__)


class BudgetExceeded(YuoError):
    pass


class StageFailed(YuoError):
    def __init__(self, message: str, *, retryable: bool = False, stage_run_id: str | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.stage_run_id = stage_run_id


@dataclass(frozen=True)
class StageSpec[T: BaseModel]:
    stage: Stage
    output: type[T]
    prompt_key: str
    prompt_version: int
    template: str  # the prompt text before inputs are filled in; hashed into the manifest
    build: Callable[[dict[str, Any]], list[Message]]
    rules: Rules[T] | None = None
    code_version: str = "1"
    # output cap for this stage, under the binding's: a runaway reply (whitespace until max_tokens,
    # seen with Qwen) then costs little and the repair round still answers
    max_tokens: int | None = None
    parse: Parse | None = None  # a text-format reply (the video author's fenced script and module)
    repair_rounds: int = 1
    timeout_s: float | None = None  # per call; None keeps the port default (a long video module needs more)


@dataclass
class StageOutcome[T]:
    value: T
    stage_run_id: str
    output_hash: str
    cached: bool
    completions: list[Completion] = field(default_factory=list)


class BudgetGuard:
    """Billed spend this calendar month (UTC) against the cap; notional subscription cost never counts."""

    def __init__(self, readers: ReadPool, cap_micros: Callable[[], int | None]) -> None:
        self._readers = readers
        self._cap = cap_micros

    def spent_micros(self) -> int:
        month = clock.now()[:7]
        with self._readers.connection() as c:
            row = c.execute(
                "SELECT coalesce(sum(cost_micros), 0) FROM budget_entry WHERE estimated = 0 AND substr(at, 1, 7) = ?",
                (month,),
            ).fetchone()
        return int(row[0])

    def check(self) -> None:
        cap = self._cap()
        if cap is not None and self.spent_micros() >= cap:
            raise BudgetExceeded(f"monthly budget cap reached ({cap / 1e6:.2f} USD): generation is paused")


def manifest(
    spec: StageSpec[Any],
    binding: Binding,
    port: LLMPort,
    inputs: dict[str, Any],
    *,
    upstream: list[str],
    fix_round: int,
    variant_nonce: str | None,
) -> dict[str, Any]:
    return {
        "stage": spec.stage.value,
        "stage_code_version": spec.code_version,
        "prompt_key": spec.prompt_key,
        "prompt_version": spec.prompt_version,
        "prompt_body_hash": content_hash(spec.template),
        "adapter": port.name,
        "adapter_version": port.version,
        "model_requested": binding.model,
        "gen_params": {
            "temperature": binding.temperature,
            "effort": binding.effort,
            "max_tokens": binding.max_tokens,
            "mode": binding.mode.value,
            "providers": list(binding.providers),
            "avoid": list(binding.avoid),
        },
        "inputs": inputs,
        "upstream": sorted(upstream),
        "fix_round": fix_round,
        "variant_nonce": variant_nonce,
    }


_REJECTED = " OR ".join(
    f"EXISTS (SELECT 1 FROM {t} v WHERE v.produced_by_stage_run_id = s.id AND v.status = 'rejected')"
    for t in ("lesson_version", "item_version", "rendition_version")
)


class StageRunner:
    def __init__(
        self, writer: Writer, readers: ReadPool, ports: dict[str, LLMPort], budget: BudgetGuard
    ) -> None:
        self.writer = writer
        self.readers = readers
        self.ports = ports
        self.budget = budget

    def port(self, binding: Binding) -> LLMPort:
        try:
            return self.ports[binding.adapter]
        except KeyError:
            raise StageFailed(f"no adapter configured for {binding.adapter!r}") from None

    def _cached(self, input_hash: str) -> tuple[str, str, Any] | None:
        with self.readers.connection() as c:
            row = c.execute(
                "SELECT s.id, s.output_hash, o.parsed FROM stage_run s JOIN stage_output o ON o.hash = s.output_hash "
                f"WHERE s.input_hash = ? AND s.status = 'succeeded' AND s.cache_hit_of_stage_run_id IS NULL "
                f"AND NOT ({_REJECTED}) ORDER BY s.finished_at DESC LIMIT 1",
                (input_hash,),
            ).fetchone()
        return (row[0], row[1], json.loads(row[2])) if row else None

    def run[T: BaseModel](
        self,
        job_id: str,
        spec: StageSpec[T],
        binding: Binding,
        inputs: dict[str, Any],
        *,
        data_class: DataClass = DataClass.CONTENT,
        upstream: list[str] | None = None,
        fix_round: int = 0,
        variant_nonce: str | None = None,
        role: str | None = None,
    ) -> StageOutcome[T]:
        port = self.port(binding)
        progress.step(spec.stage.value)
        if spec.max_tokens is not None and spec.max_tokens < binding.max_tokens:
            binding = dataclasses.replace(binding, max_tokens=spec.max_tokens)
        m = manifest(
            spec,
            binding,
            port,
            inputs,
            upstream=upstream or [],
            fix_round=fix_round,
            variant_nonce=variant_nonce,
        )
        input_hash = content_hash(m)
        run_id = new_id()
        base = {
            "id": run_id,
            "job_id": job_id,
            "stage": spec.stage.value,
            "manifest": json.dumps(m, ensure_ascii=False),
            "input_hash": input_hash,
            "adapter": port.name,
            "adapter_version": port.version,
            "model": binding.model,
            "effort": binding.effort,
            "role": role or binding.role,
            "data_class": data_class.value,
        }
        if (hit := self._cached(input_hash)) is not None:
            prior, output_hash, parsed = hit
            now = clock.now()
            self.writer.run(
                lambda c: _insert_run(
                    c,
                    base,
                    status=RunStatus.SUCCEEDED,
                    output_hash=output_hash,
                    cache_hit=prior,
                    started=now,
                    finished=now,
                )
            )
            metrics.inc("stage.cache_hit")
            return StageOutcome(spec.output.model_validate(parsed), run_id, output_hash, cached=True)

        self.budget.check()
        started = clock.now()
        try:
            self.writer.run(lambda c: _insert_run(c, base, status=RunStatus.RUNNING, started=started))
        except sqlite3.IntegrityError as e:  # the in-flight unique index: someone is already doing this work
            raise StageFailed(f"{spec.stage}: identical stage already running", retryable=True) from e

        messages = spec.build(inputs)
        bytes_out = sum(len(msg.content.encode()) for msg in messages)
        try:
            result = generate_structured(
                port,
                binding,
                spec.output,
                messages,
                rules=spec.rules,
                schema_name=spec.stage.value,
                repair_rounds=spec.repair_rounds,
                parse=spec.parse,
                timeout_s=spec.timeout_s,
            )
        except StructuredFailure as f:
            self._finish_failed(
                run_id, port, f.completions, f"invalid output after repair: {f}", data_class, bytes_out, spec
            )
            raise StageFailed(f"{spec.stage}: invalid output after repair: {f}", stage_run_id=run_id) from f
        except LLMError as e:
            self._finish_failed(run_id, port, [], f"{e.kind}: {e}", data_class, bytes_out, spec)
            raise StageFailed(f"{spec.stage}: {e}", retryable=e.retryable, stage_run_id=run_id) from e

        last = result.completions[-1]
        raw = {"calls": [c.raw for c in result.completions], "validation_errors": result.errors}
        parsed = result.value.model_dump(mode="json")
        output_hash = content_hash(parsed)

        def finish(c: sqlite3.Connection) -> None:
            c.execute(
                "INSERT INTO stage_output (hash, schema_id, schema_version, raw, parsed, data_class, created_at) "
                "VALUES (?, ?, 1, json(?), json(?), ?, ?) ON CONFLICT(hash) DO NOTHING",
                (
                    output_hash,
                    spec.output.__name__,
                    json.dumps(raw, ensure_ascii=False, default=str),
                    json.dumps(parsed, ensure_ascii=False),
                    data_class.value,
                    clock.now(),
                ),
            )
            c.execute(
                "UPDATE stage_run SET status = 'succeeded', output_hash = ?, model_resolved = ?, provider = ?, "
                "finished_at = ? WHERE id = ?",
                (output_hash, last.model_resolved, last.provider, clock.now(), run_id),
            )
            _ledger(c, run_id, port, result.completions, data_class, bytes_out, spec.stage)

        self.writer.run(finish)
        metrics.inc("stage.run")
        log.info(
            "stage.succeeded",
            stage=spec.stage.value,
            adapter=port.name,
            model=binding.model,
            repaired=result.repaired,
            cost_micros=sum(c.usage.cost_micros for c in result.completions),
        )
        return StageOutcome(result.value, run_id, output_hash, cached=False, completions=result.completions)

    def _finish_failed(
        self,
        run_id: str,
        port: LLMPort,
        completions: list[Completion],
        error: str,
        data_class: DataClass,
        bytes_out: int,
        spec: StageSpec[Any],
    ) -> None:
        """A failed stage still records what it cost and what left the machine."""

        def unit(c: sqlite3.Connection) -> None:
            c.execute(
                "UPDATE stage_run SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
                (error[:2000], clock.now(), run_id),
            )
            if completions:
                _ledger(c, run_id, port, completions, data_class, bytes_out, spec.stage)

        self.writer.run(unit)
        metrics.inc("stage.failed")


def _insert_run(
    c: sqlite3.Connection,
    b: dict[str, Any],
    *,
    status: RunStatus,
    started: str,
    output_hash: str | None = None,
    cache_hit: str | None = None,
    finished: str | None = None,
) -> None:
    c.execute(
        "INSERT INTO stage_run (id, job_id, stage, input_manifest, input_hash, output_hash, status, resource, adapter, "
        "adapter_version, model_requested, model_resolved, provider, reasoning_effort, role, "
        "cache_hit_of_stage_run_id, data_class, started_at, finished_at, error) "
        "VALUES (?, ?, ?, json(?), ?, ?, ?, NULL, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, NULL)",
        (
            b["id"],
            b["job_id"],
            b["stage"],
            b["manifest"],
            b["input_hash"],
            output_hash,
            status.value,
            b["adapter"],
            b["adapter_version"],
            b["model"],
            b["effort"],
            b["role"],
            cache_hit,
            b["data_class"],
            started,
            finished,
        ),
    )


def _ledger(
    c: sqlite3.Connection,
    run_id: str,
    port: LLMPort,
    completions: list[Completion],
    data_class: DataClass,
    bytes_out: int,
    stage: Stage,
) -> None:
    now = clock.now()
    for comp in completions:
        u = comp.usage
        c.execute(
            "INSERT INTO budget_entry (id, stage_run_id, message_id, adapter, provider, in_tokens, out_tokens, "
            "reasoning_tokens, cost_micros, cost_currency, price_ref, estimated, at) "
            "VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, 'USD', ?, ?, ?)",
            (
                new_id(),
                run_id,
                port.name,
                comp.provider,
                u.in_tokens,
                u.out_tokens,
                u.reasoning_tokens,
                u.cost_micros,
                "notional" if u.notional else "provider-reported",
                int(u.notional),
                now,
            ),
        )
    if getattr(port, "remote", True):
        c.execute(
            "INSERT INTO egress_record (id, adapter, data_classes, bytes_out, purpose, stage_run_id, message_id, at) "
            "VALUES (?, ?, json(?), ?, ?, ?, NULL, ?)",
            (
                new_id(),
                port.name,
                json.dumps(sorted({data_class.value})),
                bytes_out * len(completions),
                stage.value,
                run_id,
                now,
            ),
        )
