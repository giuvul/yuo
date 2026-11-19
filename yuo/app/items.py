"""The item pipeline for every exercise type: generate -> support -> shuffle -> blind solve -> gate ->
publish. Used by lesson practice, skill-test banks and placement tests.

Choice options are shuffled before the blind solve (models put the key first). Types a model cannot
answer blind (flashcards, short answers) skip the blind solve; their deterministic checks still run.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

import structlog

from yuo.app.stages import blind_batch_answers, blind_batch_spec, item_spec, support_spec
from yuo.assessment import types as xt
from yuo.core import clock
from yuo.core.enums import CheckVerdict, DataClass, EntityKind
from yuo.core.hashing import content_hash
from yuo.core.ids import new_id
from yuo.core.llm import Binding
from yuo.generation.runner import StageFailed, StageRunner
from yuo.generation.structured import StructuredFailure

log = structlog.get_logger(__name__)


@dataclass
class ItemContext:
    path_id: str
    skill_id: str
    lang: str
    difficulty: str
    objectives: list[dict[str, Any]]  # id, code, statement
    skill_title: str
    skill_summary: str
    data_class: DataClass
    use: str  # practice | test | placement
    body: list[dict[str, Any]] | None = None
    origin_lesson_version_id: str | None = None
    material: dict[str, Any] | None = None  # the learner's own excerpts (lesson_material), when built on them


ITEM_MATERIAL_BUDGET = 4000  # tokens of the learner's material in each item call


@dataclass
class _Blind:
    """The blind solver's verdict on one draft: PASS without a run when the type is not blind-solvable."""

    verdict: CheckVerdict = CheckVerdict.PASS
    details: dict[str, Any] = field(default_factory=dict)
    run_id: str | None = None


@dataclass
class _Draft:
    type: xt.ExerciseType
    code: str
    payload: dict[str, Any]
    support: xt.Support
    run_id: str
    seed: str


def make_items(
    runner: StageRunner,
    writer: Any,
    job_id: str,
    ctx: ItemContext,
    wanted: list[tuple[str, str]],
    gen: Binding,
    rev: Binding,
    *,
    independent: bool,
    avoid: list[str] | None = None,
    attempts: int = 2,
) -> list[str | None]:
    """Write items (type key, code), then check every blind-solvable one in a single reviewer call and publish
    those the solver agreed with; rejected ones are written again, up to `attempts` rounds, and checked
    together again. Returns each item's published version id, or None when every attempt was rejected.
    A practice set or a test bank thus costs one blind call per round instead of one per item (2026-11-15)."""
    codes = {o["code"] for o in ctx.objectives}
    base: dict[str, Any] = {
        "lang": ctx.lang,
        "body": ctx.body,
        "skill_title": ctx.skill_title,
        "skill_summary": ctx.skill_summary,
        "objectives": [{"code": o["code"], "statement": o["statement"]} for o in ctx.objectives],
        "avoid": avoid or [],
    } | ({"excerpts": ctx.material} if ctx.material else {})
    # under "only my material" the blind solver answers with the excerpts: a question they do not answer fails
    strict = (
        {k: v for k, v in ctx.material.items() if k != "exam_style"}
        if ctx.material and ctx.material["adherence"] == "only"
        else None
    )
    out: list[str | None] = [None] * len(wanted)
    pending = list(range(len(wanted)))
    for attempt in range(attempts):
        drafts: dict[int, _Draft] = {}
        for k in pending:
            type_key, code = wanted[k]
            t = xt.get(type_key)
            try:
                item = runner.run(
                    job_id,
                    item_spec(t, codes),
                    gen,
                    base | {"instructions": t.instructions},
                    data_class=ctx.data_class,
                    variant_nonce=f"try-{attempt}" if attempt else None,
                )
                payload = item.value.model_dump(mode="json")
                support = xt.Support(hints=[], solution=payload.get("back", ""), explanations=[])
                if t.needs_support:
                    support = runner.run(
                        job_id,
                        support_spec(t, payload),
                        gen,
                        {"lang": ctx.lang, "type": t.key, "item": payload},
                        data_class=ctx.data_class,
                        upstream=[item.output_hash],
                    ).value
            except StageFailed as e:
                if e.retryable:
                    raise
                log.warning("item.draft_failed", code=code, type=type_key, error=str(e)[:200])
                continue
            payload, support = xt.shuffle_choices(t, payload, support, seed=item.output_hash)
            drafts[k] = _Draft(t, code, payload, support, item.stage_run_id, item.output_hash)
        solvable = [k for k, d in drafts.items() if d.type.blind_solvable]
        verdicts: dict[int, _Blind] = {k: _Blind() for k in drafts if k not in solvable}
        if solvable:
            try:
                checked = _blind_check(runner, job_id, rev, [drafts[k] for k in solvable], material=strict)
                verdicts |= dict(zip(solvable, checked, strict=True))
            except StageFailed as e:
                if e.retryable:
                    raise
                log.warning("item.blind_failed", codes=[drafts[k].code for k in solvable], error=str(e)[:200])
        for k, blind in verdicts.items():
            ok = writer.run(lambda c, d=drafts[k], b=blind: _write(c, ctx, d, b, independent=independent))
            if ok:
                out[k] = str(ok)
        pending = [k for k in pending if out[k] is None]
        if not pending:
            break
    for k in pending:
        log.warning("item.rejected", code=wanted[k][1], type=wanted[k][0])
    return out


def _blind_check(
    runner: StageRunner,
    job_id: str,
    rev: Binding,
    drafts: list[_Draft],
    upstream: list[str] | None = None,
    *,
    material: dict[str, Any] | None = None,
) -> list[_Blind]:
    """Every draft answered blind in one reviewer call; a miss rejects the item (no correct key was
    disputed in 14 cases). With `material`, the solver answers from those excerpts only."""
    types = [d.type for d in drafts]
    blind = runner.run(
        job_id,
        blind_batch_spec(types),
        rev,
        {"types": [t.key for t in types], "items": [d.type.view(d.payload, seed=d.seed) for d in drafts]}
        | ({"excerpts": material} if material else {}),
        data_class=DataClass.FREE_TEXT if material else DataClass.CONTENT,
        upstream=upstream or [d.seed for d in drafts],
        role="reviewer",
    )
    out = []
    for d, solved in zip(drafts, blind_batch_answers(blind.value, len(drafts)), strict=True):
        score = d.type.grade(d.payload, solved["answer"])
        verdict = CheckVerdict.PASS if score is not None and score >= 0.999 else CheckVerdict.FAIL
        out.append(_Blind(verdict, {"blind": solved, "key": d.type.correct(d.payload)}, blind.stage_run_id))
    return out


def _write(
    c: sqlite3.Connection,
    ctx: ItemContext,
    d: _Draft,
    blind: _Blind,
    *,
    independent: bool,
    objective_codes: list[str] | None = None,
) -> str | None:
    """Write an item version with its checks; publish it when the blind solver agreed. `objective_codes`
    links several objectives (a cross-lesson review question); the default is the payload's one."""
    t, code, payload, support, run_id, verdict = d.type, d.code, d.payload, d.support, d.run_id, blind.verdict
    row = c.execute("SELECT id FROM item WHERE path_id = ? AND code = ?", (ctx.path_id, code)).fetchone()
    item_id = row[0] if row else new_id()
    if row is None:
        c.execute(
            "INSERT INTO item (id, skill_id, path_id, code, type_key, state, current_version_id, extensions) "
            "VALUES (?, ?, ?, ?, ?, 'in_review', NULL, json(?))",
            (item_id, ctx.skill_id, ctx.path_id, code, t.key, json.dumps({"yuo": {"use": ctx.use}})),
        )
    sup = support.model_dump(mode="json")
    no = c.execute(
        "SELECT coalesce(max(version_no), 0) + 1 FROM item_version WHERE item_id = ?", (item_id,)
    ).fetchone()[0]
    vid = new_id()
    c.execute(
        "INSERT INTO item_version (id, item_id, version_no, version_hash, lang, translation_of_version_hash, "
        "derived_from_version_id, difficulty, payload, support, origin_lesson_version_id, resets_review, status, "
        "published_at, created_at, authorship, acquired_via, author_kind, author_ref, produced_by_stage_run_id, "
        "upstream, licence, personal_inputs) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, json(?), json(?), ?, 0, "
        "'in_review', NULL, ?, 'generated', 'local', 'system', NULL, ?, NULL, NULL, ?)",
        (
            vid,
            item_id,
            no,
            content_hash({"payload": payload, "support": sup}),
            ctx.lang,
            ctx.difficulty,
            json.dumps(payload, ensure_ascii=False),
            json.dumps(sup, ensure_ascii=False),
            ctx.origin_lesson_version_id,
            clock.now(),
            run_id,
            int(ctx.data_class is DataClass.FREE_TEXT),
        ),
    )
    for src in (ctx.material or {}).get("sources", []):  # the pages of the learner's material it came from
        c.execute(
            "INSERT OR IGNORE INTO item_version_source (item_version_id, section_id) VALUES (?, ?)",
            (vid, src["section_id"]),
        )
    for check in ("schema", "support_consistency", "leak"):
        _check(c, vid, check, CheckVerdict.PASS, {}, run_id)
    if t.blind_solvable:
        _check(c, vid, "answer_key", verdict, blind.details, blind.run_id, independent=independent)
    if verdict is not CheckVerdict.PASS:
        c.execute("UPDATE item_version SET status = 'rejected' WHERE id = ?", (vid,))
        return None
    by_code = {o["code"]: o["id"] for o in ctx.objectives}
    for objective_code in objective_codes or [payload["objective_code"]]:
        c.execute(
            "INSERT INTO item_version_objective (item_version_id, objective_id) VALUES (?, ?)",
            (vid, by_code[objective_code]),
        )
    now = clock.now()
    c.execute("UPDATE item_version SET status = 'passed', published_at = ? WHERE id = ?", (now, vid))
    c.execute("UPDATE item SET current_version_id = ?, state = 'ready' WHERE id = ?", (vid, item_id))
    c.execute(
        "INSERT INTO publication (id, head_kind, head_id, version_id, at, by) VALUES (?, 'item', ?, ?, ?, 'gate')",
        (new_id(), item_id, vid, now),
    )
    return vid


def _check(
    c: sqlite3.Connection,
    version_id: str,
    check: str,
    verdict: CheckVerdict,
    details: dict[str, Any],
    run_id: str | None,
    *,
    independent: bool | None = None,
) -> None:
    c.execute(
        'INSERT INTO quality_check (id, subject_kind, subject_version_id, "check", verdict, fix_round, '
        "independent, details, stage_run_id, at) VALUES (?, ?, ?, ?, ?, 0, ?, json(?), ?, ?)",
        (
            new_id(),
            EntityKind.ITEM_VERSION.value,
            version_id,
            check,
            verdict.value,
            None if independent is None else int(independent),
            json.dumps(details, ensure_ascii=False),
            run_id,
            clock.now(),
        ),
    )


# Lesson practice mix (default: all installed types, automatic weights): one single-choice item,
# one rotating structured type, one flashcard; a short answer every third lesson.
ROTATION = ("cloze", "multi", "ordering", "matching")
TEST_TYPES = ("mcq", "multi", "cloze", "ordering", "matching")  # graded at once, so a test can finish


def practice_mix(position: int, enabled: list[str] | None = None) -> list[str]:
    mix = ["mcq", ROTATION[position % len(ROTATION)], "flashcard"]
    if position % 3 == 2:
        mix.append("short_answer")
    return [k for k in mix if enabled is None or k in enabled] or ["mcq"]


@dataclass
class Checked:
    """One already written choice item for `publish_bank`."""

    code: str
    payload: dict[str, Any]
    support: xt.Support
    seed: str
    objective_codes: list[str]


def publish_bank(
    runner: StageRunner,
    writer: Any,
    job_id: str,
    ctx: ItemContext,
    t: xt.ExerciseType,
    drafts: list[Checked],
    rev: Binding,
    *,
    run_id: str,
    upstream: str,
    independent: bool,
) -> list[str | None]:
    """Shuffle, blind-solve and publish already written choice items (the review bank writes many in one call),
    with one blind call for all of them. Returns each item's published version id, or None when the blind
    solver disagreed with the key."""
    if not drafts:
        return []
    shuffled = [
        _Draft(t, d.code, *xt.shuffle_choices(t, d.payload, d.support, seed=d.seed), run_id, d.seed)
        for d in drafts
    ]
    checked = _blind_check(runner, job_id, rev, shuffled, [upstream])
    out: list[str | None] = []
    for d, s, blind in zip(drafts, shuffled, checked, strict=True):
        ok = writer.run(
            lambda c, d=d, s=s, b=blind: _write(
                c, ctx, s, b, independent=independent, objective_codes=d.objective_codes
            )
        )
        out.append(str(ok) if ok else None)
    return out


__all__ = [
    "TEST_TYPES",
    "Checked",
    "ItemContext",
    "StructuredFailure",
    "make_items",
    "practice_mix",
    "publish_bank",
]
