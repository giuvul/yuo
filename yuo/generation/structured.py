"""Structured generation for every adapter: native or prompt mode from the capability file,
always validated here, one repair round with the validator's messages, then the stage fails.

Semantic rules (answer leaks, DAGs, option ids) run after schema validation and count as failures too:
they belong to the gate, but catching them before the repair round is cheaper than a second stage run.
"""

import copy
import dataclasses
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from yuo.core.llm import Binding, Completion, LLMPort, Message, Request, StructuredMode

type Rules[T] = Callable[[T], list[str]]
type Parse = Callable[
    [str], dict[str, Any]
]  # a text reply to the output model's fields; ValueError = bad reply


class StructuredFailure(Exception):
    def __init__(self, errors: list[str], completions: list[Completion]) -> None:
        super().__init__("; ".join(errors)[:500])
        self.errors = errors
        self.completions = completions


@dataclass
class StructuredResult[T]:
    value: T
    completions: list[Completion] = field(default_factory=list)
    repaired: bool = False
    errors: list[list[str]] = field(default_factory=list)  # validation errors per failed attempt


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON Schema in the strict subset providers accept: every object closed, every property required."""
    schema = copy.deepcopy(model.model_json_schema())

    def walk(node: Any) -> None:
        """`node` is a schema; maps of names to schemas (properties, $defs) are walked by value."""
        if isinstance(node, list):
            for v in node:
                walk(v)
            return
        if not isinstance(node, dict):
            return
        for key in ("title", "default", "discriminator"):  # `discriminator` is OpenAPI, not JSON Schema
            node.pop(key, None)
        if "oneOf" in node:  # strict modes accept anyOf only; the `type` const keeps the branches apart
            node["anyOf"] = node.pop("oneOf")
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"])
        for key, v in node.items():
            if key in ("properties", "$defs"):
                for sub in v.values():
                    walk(sub)
            elif key in ("items", "anyOf", "oneOf", "allOf", "prefixItems", "additionalProperties", "not"):
                walk(v)

    walk(schema)
    return schema


def _extract_json(text: str) -> Any:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start >= 0 and end > start:
            return json.loads(t[start : end + 1])
        raise


def _check[T: BaseModel](
    model: type[T], completion: Completion, rules: Rules[T] | None, parse: Parse | None = None
) -> tuple[T | None, list[str]]:
    if parse is not None:  # a text format (fenced blocks), not JSON: the parser says what is wrong
        try:
            data = parse(completion.text)
        except ValueError as e:
            hint = " (output was cut off at max_tokens)" if completion.finish == "length" else ""
            return None, [f"{e}{hint}"]
        try:
            value = model.model_validate(data)
        except ValidationError as e:
            return None, [
                f"{'.'.join(map(str, err['loc'])) or '<root>'}: {err['msg']}" for err in e.errors()[:20]
            ]
        problems = rules(value) if rules else []
        return value, problems
    try:
        data = completion.parsed if completion.parsed is not None else _extract_json(completion.text)
    except json.JSONDecodeError as e:
        hint = " (output was cut off at max_tokens)" if completion.finish == "length" else ""
        return None, [f"the reply is not valid JSON: {e.msg}{hint}"]
    try:
        value = model.model_validate(data)
    except ValidationError as e:
        return None, [
            f"{'.'.join(map(str, err['loc'])) or '<root>'}: {err['msg']}" for err in e.errors()[:20]
        ]
    problems = rules(value) if rules else []
    return (value, problems) if problems else (value, [])


def generate_structured[T: BaseModel](
    port: LLMPort,
    binding: Binding,
    model: type[T],
    messages: list[Message],
    *,
    rules: Rules[T] | None = None,
    schema_name: str = "output",
    repair_rounds: int = 1,
    parse: Parse | None = None,
    timeout_s: float | None = None,
) -> StructuredResult[T]:
    """`parse` set: the reply is a text format the stage's prompt describes (fenced blocks), not JSON."""
    schema = strict_schema(model)
    msgs = list(messages)
    if binding.mode is StructuredMode.PROMPT and parse is None:
        instruction = (
            "Reply with one JSON object only, no prose and no code fences. "
            f"It must match this JSON Schema:\n{json.dumps(schema, ensure_ascii=False)}"
        )
        if msgs and msgs[0].role == "system":
            msgs[0] = Message("system", f"{msgs[0].content}\n\n{instruction}")
        else:
            msgs.insert(0, Message("system", instruction))
    completions: list[Completion] = []
    history: list[list[str]] = []
    for attempt in range(repair_rounds + 1):
        request = Request(
            messages=tuple(msgs),
            model=binding.model,
            max_tokens=binding.max_tokens,
            temperature=binding.temperature,
            effort=binding.effort,
            providers=binding.providers,
            avoid=binding.avoid,
            json_schema=schema if binding.mode is StructuredMode.NATIVE and parse is None else None,
            schema_name=schema_name,
        )
        if timeout_s is not None:
            request = dataclasses.replace(request, timeout_s=timeout_s)
        completion = port.generate(request)
        completions.append(completion)
        value, errors = _check(model, completion, rules, parse)
        if value is not None and not errors:
            return StructuredResult(value, completions, repaired=attempt > 0, errors=history)
        history.append(errors)
        if attempt == repair_rounds:
            raise StructuredFailure(errors, completions)
        msgs += [
            Message("assistant", completion.text or "(empty reply)"),
            Message(
                "user",
                "Your reply has these problems:\n- "
                + "\n- ".join(errors)
                + (
                    "\nReply again with the complete, corrected output in the same format."
                    if parse is not None
                    else "\nReply again with the corrected JSON object only."
                ),
            ),
        ]
    raise AssertionError("unreachable")
