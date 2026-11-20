"""Cost estimator: plan units x token profile x current price, as a range.

Profiles: the local ledger once it holds at least `MIN_SAMPLES` runs of a unit for the same adapter and
model (calibration), else the shipped profile. Prices come from a `PriceSource` (OpenRouter's models list,
cached with a date); subscriptions show a notional cost and are never billed.
"""

import json
import re
import sqlite3
import statistics
from dataclasses import dataclass, field
from functools import cache
from importlib.resources import files
from typing import Any, Protocol

from yuo.core.llm import Binding, Role

MIN_SAMPLES = 5
# Lesson recipe: one reading lesson through the gate plus its practice set (yuo/app/items.py
# practice_mix): single choice, a rotating structured type and a flashcard, plus a short answer in every
# third lesson; flashcards need no support and only the first two types are blind-solved.
# Review bank: one writer call per lesson for 11 questions, all answered blind by the reviewer in one
# more call. Since 0.8.1 a lesson's practice items are answered blind in one call too (about two of them).
# Weights in single blind solves, measured on claude-cli opus over real items (
# 2026-11-15): a single solve 3,700 tokens in and 280 out; a batch of three 1.65 times its cost, a batch of
# eleven 2.6 times. A practice batch of about two is counted as 1.4.
BANK_BLIND_SOLVES = 2.6
PRACTICE_BLIND_SOLVES = 1.4
LESSON_UNITS: dict[str, float] = {
    "lesson_body": 1,
    "review": 1,
    "items_generate": 3 + 1 / 3,
    "items_support": 2 + 1 / 3,
    "blind_solve": PRACTICE_BLIND_SOLVES + BANK_BLIND_SOLVES,
    "review_bank": 1,
}
PATH_UNITS: dict[str, float] = {"tree_outline": 1}
# Video per lesson, as calls: the author with its validity repairs and its repair rounds, three critics
# a round since 2026-10-29. Recalibrated 2026-11-15 from a live Sonnet ledger
# (.dev/eval/video-sonnet-20261028T162021: 26 author calls and 26 critic rounds for 7 short topics, 6 videos
# made, about 3.7 author calls and 1.85 rounds per video; 1.85 x 3 critics = 5.6). Before: 6 and 9, which
# put one short video at about 39% of a Claude Pro window instead of the measured 24-26%.
VIDEO_UNITS: dict[str, float] = {
    "video_scene": 4,
    "video_review": 6,
}
VIDEO_HIGH: dict[str, float] = {
    "video_scene": 10,
    "video_review": 12,
}  # the high end: every repair round used
# token profiles are for short videos (the measured length); longer ones write and read proportionally more
VIDEO_SCALE = {"short": 1.0, "medium": 2.4, "long": 3.8}
# A lesson on a YouTube video (yuo/app/video_links.py), as tokens: the searches are written from the lesson;
# the ranking reads three transcripts cut to
# 9,000 characters each (about 2,300 tokens) plus the lesson, and answers a short JSON; the writer and the
# reviewer each read the chosen stretch (at most 20,000 characters; 8 to 15 minutes of speech is about 2,000
# to 3,500 tokens). (p10, median, p90) per lesson [ASSUMPTION until the ledger has samples].
YOUTUBE_TOKENS: dict[str, tuple[tuple[int, int], tuple[int, int], tuple[int, int]]] = {
    "video_query": ((500, 40), (650, 70), (900, 120)),  # the searches, written from the lesson
    "video_pick": ((5_000, 100), (7_700, 150), (16_000, 400)),  # the high end: a second round of three
    "lesson_transcript": ((2_000, 0), (3_500, 0), (5_000, 0)),
    "review_transcript": ((2_000, 0), (3_500, 0), (5_000, 0)),
}
# a subscription's notional price per token, from the binding's lesson profile, counts output as this many inputs
OUTPUT_WEIGHT = 5
# A failed review triggers one more lesson_body + review (2 of 6 lessons in a live run). The high end of
# the range includes one such round per lesson; the low end assumes none.
FIX_ROUND_UNITS: dict[str, int] = {"lesson_body": 1, "review": 1}
# Without measured p10, the low end is this share of the median [ASSUMPTION until the ledger has samples]
P10_SHARE = 0.7
UNIT_ROLE: dict[str, Role] = {
    "tree_outline": "generator",
    "lesson_body": "generator",
    "review": "reviewer",
    "items_generate": "generator",
    "items_support": "generator",
    "blind_solve": "reviewer",
    "review_bank": "generator",
    "video_scene": "generator",
    "video_review": "generator",  # the author model is its own critic
    "video_pick": "utility",
    "video_query": "utility",
    "lesson_transcript": "generator",
    "review_transcript": "reviewer",
}


class PriceSource(Protocol):
    def per_token(self, adapter: str, model: str) -> tuple[float, float] | None:
        """USD per input and per output token, or None when the model is not billed per token."""
        ...


@dataclass(frozen=True, slots=True)
class Profile:
    median_in: int
    median_out: int
    p90_in: int
    p90_out: int
    notional_median: float | None
    source: str  # shipped | ledger
    p10_in: int = 0
    p10_out: int = 0


@dataclass
class Line:
    unit: str
    count: float
    adapter: str
    model: str
    low: float
    high: float
    billed: bool
    source: str


@dataclass
class Estimate:
    low_usd: float = 0.0  # billed: p10 of every unit, no fix rounds
    high_usd: float = 0.0  # billed: p90 of every unit plus one fix round per lesson
    notional_usd: float = 0.0  # subscription calls at API prices (not billed)
    lines: list[Line] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # units with no profile or no price
    notional_by_cli: dict[str, float] = field(default_factory=dict)
    lessons: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "low_usd": round(self.low_usd, 4),
            "high_usd": round(self.high_usd, 4),
            "notional_usd": round(self.notional_usd, 4),
            "missing": self.missing,
            "lines": [vars(line) for line in self.lines],
            "plan_usage": plan_usage(self.notional_by_cli, self.lessons),
        }


@cache
def _plans() -> list[dict[str, Any]]:
    data = json.loads(files("yuo.data").joinpath("plan_limits.json").read_text(encoding="utf-8"))
    return list(data["plans"])


def plan_usage(notional_by_cli: dict[str, float], lessons: int) -> list[dict[str, Any]]:
    """Subscription calls as a share of each plan's 5-hour window and week (plan_limits.json): what the
    learner sees instead of an API price they do not pay. A limit the plan does not have or the vendor does
    not publish is null (Codex: Pro has no 5-hour window; OpenAI publishes no weekly size)."""
    rows = []
    for plan in _plans():
        usd = notional_by_cli.get(plan["cli"], 0.0)
        if usd <= 0:
            continue
        window, week = plan.get("window_usd"), plan.get("week_usd")
        rows.append({
            "cli": plan["cli"], "plan": plan["plan"], "label": plan["label"],
            "window_pct": round(100 * usd / window, 1) if window else None,
            "week_pct": round(100 * usd / week, 2) if week else None,
            "lessons_per_window": (int(lessons * window / usd) if lessons else 0) if window else None,
            "lessons_per_week": (int(lessons * week / usd) if lessons else 0) if week else None,
        })  # fmt: skip
    return rows


@cache
def _shipped() -> list[dict[str, Any]]:
    data = json.loads(files("yuo.data").joinpath("cost_profiles.json").read_text(encoding="utf-8"))
    return list(data["profiles"])


def _ledger(c: sqlite3.Connection, adapter: str, model: str, unit: str) -> Profile | None:
    rows = c.execute(
        "SELECT sum(b.in_tokens), sum(b.out_tokens), sum(b.cost_micros) FROM stage_run s "
        "JOIN budget_entry b ON b.stage_run_id = s.id WHERE s.adapter = ? AND s.model_requested = ? AND s.stage = ? "
        "AND s.status = 'succeeded' GROUP BY s.id",
        (adapter, model, unit),
    ).fetchall()
    if len(rows) < MIN_SAMPLES:
        return None
    ins, outs = sorted(r[0] for r in rows), sorted(r[1] for r in rows)

    def rank(xs: list[int], q: float) -> int:
        return xs[min(len(xs) - 1, round(q * (len(xs) - 1)))]

    notional = statistics.median(r[2] for r in rows) / 1e6 if adapter.endswith("-cli") else None
    return Profile(
        round(statistics.median(ins)),
        round(statistics.median(outs)),
        rank(ins, 0.9),
        rank(outs, 0.9),
        notional,
        "ledger",
        rank(ins, 0.1),
        rank(outs, 0.1),
    )


def profile(c: sqlite3.Connection, adapter: str, model: str, unit: str) -> Profile | None:
    if (p := _ledger(c, adapter, model, unit)) is not None:
        return p
    for e in _shipped():
        if (e["adapter"], e["model"], e["unit"]) == (adapter, model, unit):
            return Profile(
                e["median_in"],
                e["median_out"],
                e["p90_in"],
                e["p90_out"],
                e.get("usd_notional_median"),
                "shipped",
                e.get("p10_in", round(e["median_in"] * P10_SHARE)),
                e.get("p10_out", round(e["median_out"] * P10_SHARE)),
            )
    if adapter.startswith("api:"):  # a direct vendor key: nothing measured for this route yet
        return _borrowed(model, unit)
    return None


def _shape(model: str) -> str:
    return re.sub(r"[^a-z0-9]", "", model.lower().rsplit("/", 1)[-1])


def _borrowed(model: str, unit: str) -> Profile | None:
    """Tokens are a property of the model and the task, not the route: the same model's shipped profile through
    OpenRouter, else the median of every API-billed shipped profile for the unit ("typical")."""
    rows = [e for e in _shipped() if e["unit"] == unit and not e["adapter"].endswith("-cli")]
    same = [e for e in rows if _shape(e["model"]) == _shape(model)]
    pick = same or rows
    if not pick:
        return None

    def med(k: str) -> int:
        return round(float(statistics.median(e[k] for e in pick)))

    return Profile(
        med("median_in"), med("median_out"), med("p90_in"), med("p90_out"), None, "shipped" if same else "typical",
        round(med("median_in") * P10_SHARE), round(med("median_out") * P10_SHARE),
    )  # fmt: skip


def estimate(
    c: sqlite3.Connection,
    bindings: dict[Role, Binding],
    prices: PriceSource,
    *,
    lessons: int,
    include_path: bool = True,
    video: str | None = None,  # None: no video made by Yuo, else the video length
    youtube: bool = False,  # lessons built on YouTube videos
) -> Estimate:
    est = Estimate(lessons=lessons)
    plan: dict[str, float] = {u: n * lessons for u, n in LESSON_UNITS.items()}
    if include_path:
        plan |= PATH_UNITS
    if video is not None:
        plan |= {u: n * lessons for u, n in VIDEO_UNITS.items()}  # narration: the local voice, no cost
    for unit, count in plan.items():
        b = bindings[UNIT_ROLE[unit]]
        if b.adapter == "local":  # a model on this machine: nothing billed, no notional price either
            est.lines.append(Line(unit, count, b.adapter, b.model, 0.0, 0.0, False, "local"))
            continue
        p = profile(c, b.adapter, b.model, unit)
        if p is None:
            est.missing.append(f"{unit} ({b.model}): no cost profile")
            continue
        price = prices.per_token(b.adapter, b.model)
        if price is None:  # subscription CLI or local model: nothing billed
            scale = VIDEO_SCALE[video] if video is not None and unit in VIDEO_UNITS else 1.0
            notional = (p.notional_median or 0.0) * count * scale
            est.notional_usd += notional
            est.notional_by_cli[b.adapter] = est.notional_by_cli.get(b.adapter, 0.0) + notional
            est.lines.append(Line(unit, count, b.adapter, b.model, notional, notional, False, p.source))
            continue
        pin, pout = price
        fix = FIX_ROUND_UNITS.get(unit, 0) * lessons
        scale = VIDEO_SCALE[video] if video is not None and unit in VIDEO_UNITS else 1.0
        low = count * scale * (p.p10_in * pin + p.p10_out * pout)
        high = count * scale * (p.p90_in * pin + p.p90_out * pout) + fix * (
            p.median_in * pin + p.median_out * pout
        )
        if unit in VIDEO_HIGH:  # the high end assumes every repair round runs
            high = high * VIDEO_HIGH[unit] / VIDEO_UNITS[unit]
        est.low_usd += low
        est.high_usd += high
        est.lines.append(Line(unit, count, b.adapter, b.model, low, high, True, p.source))
    if youtube:
        _youtube(c, est, bindings, prices, lessons)
    return est


def _youtube(
    c: sqlite3.Connection, est: Estimate, bindings: dict[Role, Binding], prices: PriceSource, lessons: int
) -> None:
    """The YouTube part of a lesson: tokens are known (YOUTUBE_TOKENS); a subscription's notional price per token
    comes from the same binding's lesson profile."""
    for unit, (p10, med, p90) in YOUTUBE_TOKENS.items():
        b = (
            bindings.get(UNIT_ROLE[unit]) or bindings["generator"]
        )  # the utility role falls back to the writer
        if b.adapter == "local":
            est.lines.append(Line(unit, lessons, b.adapter, b.model, 0.0, 0.0, False, "local"))
            continue
        price = prices.per_token(b.adapter, b.model)
        if price is None:
            base = profile(c, b.adapter, b.model, "lesson_body")
            if base is None or not base.notional_median:
                est.missing.append(f"{unit} ({b.model}): no cost profile")
                continue
            rate = base.notional_median / (base.median_in + OUTPUT_WEIGHT * base.median_out)
            notional = lessons * rate * (med[0] + OUTPUT_WEIGHT * med[1])
            est.notional_usd += notional
            est.notional_by_cli[b.adapter] = est.notional_by_cli.get(b.adapter, 0.0) + notional
            est.lines.append(Line(unit, lessons, b.adapter, b.model, notional, notional, False, "assumed"))
            continue
        pin, pout = price
        low = lessons * (p10[0] * pin + p10[1] * pout)
        high = lessons * (p90[0] * pin + p90[1] * pout)
        est.low_usd += low
        est.high_usd += high
        est.lines.append(Line(unit, lessons, b.adapter, b.model, low, high, True, "assumed"))
