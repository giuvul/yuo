"""Video lessons: the narration script, its timeline, and its captions.

A video is a narration script (scenes of spoken sentences) plus a TSX scene module the author model writes.
Each sentence is one caption: the WebVTT track comes from the same segments as the audio, so captions are a
separate track the player can turn off, never pixels in the frame.
"""

import difflib
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from yuo.core.media import SceneTiming, Segment, Timeline

FPS = 30
LEAD_S, SEG_GAP_S, SCENE_GAP_S, TAIL_S = 0.6, 0.35, 0.9, 1.5  # prototype timing


@dataclass(frozen=True, slots=True)
class Length:
    spoken: str
    words: tuple[int, int]  # asked for in the brief
    scenes: tuple[int, int]


# `short` is the length that was measured (Qwen 7, Sonnet 8); longer videos are not measured yet.
LENGTHS = {
    "short": Length("about 90 to 120 seconds", (220, 300), (4, 6)),
    "medium": Length("about 4 to 5 minutes", (550, 720), (6, 9)),
    "long": Length("about 7 to 8 minutes", (900, 1150), (8, 12)),
}


class ScriptScene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(description="lowercase identifier, unique in the video")
    label: str = Field(description="short scene title shown at the top of the frame")
    segments: list[str] = Field(description="one spoken sentence each; each is also one caption")


class VideoScript(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    scenes: list[ScriptScene]

    def sentences(self) -> list[str]:
        return [s for sc in self.scenes for s in sc.segments]


def script_rules(script: VideoScript, length: str = "short") -> list[str]:
    L = LENGTHS[length]
    problems = []
    if not L.scenes[0] - 1 <= len(script.scenes) <= L.scenes[1] + 1:
        problems.append(f"use {L.scenes[0]} to {L.scenes[1]} scenes, not {len(script.scenes)}")
    ids = [s.id for s in script.scenes]
    if len(set(ids)) != len(ids):
        problems.append("scene ids must be unique")
    for s in script.scenes:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", s.id):
            problems.append(f"scene id {s.id!r} must be a lowercase identifier")
        if not 1 <= len(s.segments) <= 6:
            problems.append(f"scene {s.id}: use 2 to 5 sentences, not {len(s.segments)}")
        for g in s.segments:
            if not g.strip():
                problems.append(f"scene {s.id}: an empty sentence")
            elif len(g) > 300:
                problems.append(
                    f"scene {s.id}: a sentence over 300 characters (one caption must fit two lines)"
                )
    words = sum(len(g.split()) for g in script.sentences())
    lo, hi = round(L.words[0] * 0.8), round(L.words[1] * 1.15)  # a little slack before a repair round
    if not lo <= words <= hi:
        problems.append(f"the narration has {words} words; write {L.words[0]} to {L.words[1]}")
    return problems


def build_timeline(script: VideoScript, durations: list[float]) -> Timeline:
    """Frame-exact timeline from each sentence's audio length (the order of `script.sentences()`)."""

    def f(s: float) -> int:
        return round(s * FPS)

    t = LEAD_S
    k = 0
    scenes: list[SceneTiming] = []
    for si, sc in enumerate(script.scenes):
        if si:
            t += SCENE_GAP_S
        start = t
        segs = []
        for gi, text in enumerate(sc.segments):
            if gi:
                t += SEG_GAP_S
            d = durations[k]
            k += 1
            segs.append(Segment(text, f(t), f(t + d)))
            t += d
        scenes.append(
            SceneTiming(
                sc.id,
                sc.label,
                f(start - (0 if si == 0 else SCENE_GAP_S / 2)),
                f(t + SCENE_GAP_S / 2),
                tuple(segs),
            )
        )
    total = f(t + TAIL_S)
    first, last = scenes[0], scenes[-1]
    scenes[0] = SceneTiming(first.id, first.label, 0, first.end, first.segments)
    scenes[-1] = SceneTiming(last.id, last.label, scenes[-1].start, total, last.segments)
    return Timeline(script.title, FPS, total, tuple(scenes))


def gaps(script: VideoScript) -> list[float]:
    """Silence before each sentence, matching `build_timeline` (the audio is assembled with the same gaps)."""
    out = []
    for si, sc in enumerate(script.scenes):
        for gi in range(len(sc.segments)):
            out.append(LEAD_S if si == 0 and gi == 0 else SEG_GAP_S if gi else SCENE_GAP_S)
    return out


def _ts(frame: int, fps: int) -> str:
    ms = round(frame * 1000 / fps)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def webvtt(timeline: Timeline) -> str:
    """One cue per sentence. Cues sit at the bottom, over the area the frame keeps free."""
    lines = ["WEBVTT", ""]
    n = 1
    for sc in timeline.scenes:
        for g in sc.segments:
            lines += [
                str(n),
                f"{_ts(g.start, timeline.fps)} --> {_ts(g.end, timeline.fps)} line:88%",
                _vtt_text(g.text),
                "",
            ]
            n += 1
    return "\n".join(lines)


def _vtt_text(text: str) -> str:
    # cue text is not markup: escape what WebVTT would read as tags or entities
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("-->", "→")


# --- review: the layout probe, and what the critics are shown ---------------------------

SEVERITY = {"blocker": 5.0, "major": 2.0, "minor": 0.5}
PROBE_WEIGHT = {
    "clipped": 3, "overflow": 2, "overlap": 2, "empty": 3, "crosses_edge": 1.5, "line_through_text": 1,
    "small_text": 1, "text_only": 1, "sparse": 0.5,
}  # fmt: skip


def probe_issues(probe: list[dict[str, Any]]) -> tuple[list[dict[str, str]], float]:
    """Layout defects the in-page probe found, merged across stills, and their score (lower is better)."""
    agg: dict[tuple[str, str], dict[str, Any]] = {}
    for f in probe:
        for i in (f.get("probe") or {}).get("issues", []):
            key = (i["kind"], i["text"][:40]) if i.get("text") else (i["kind"], f["name"])
            a = agg.setdefault(key, {"kind": i["kind"], "detail": i["detail"], "stills": []})
            a["stills"].append(f["name"])
    issues, score = [], 0.0
    for a in agg.values():
        w = PROBE_WEIGHT.get(a["kind"], 1)
        score += w
        st = a["stills"]
        where = st[0] if len(st) == 1 else f"{st[0]} .. {st[-1]} ({len(st)} stills)"
        issues.append(
            {
                "source": "layout",
                "still": where,
                "severity": "major" if w >= 2 else "minor",
                "problem": a["detail"],
                "fix": "",
            }
        )
    return issues, round(score, 1)


def still_map(probe: list[dict[str, Any]]) -> str:
    return "\n".join(
        f'sheet {k // 6}, still {k % 6 + 1} = {f["name"]}: "{f["text"]}"' for k, f in enumerate(probe)
    )


def on_screen(probe: list[dict[str, Any]]) -> str:
    out = []
    for f in probe:
        ts = sorted((f.get("probe") or {}).get("texts", []), key=lambda t: (round(t["y"] / 40), t["x"]))
        out.append(
            f'[{f["name"]}] narration: "{f["text"]}"\n    on screen: ' + " | ".join(t["t"] for t in ts)
        )
    return "\n".join(out)


def fix_lines(issues: list[dict[str, str]], limit: int = 30) -> list[str]:
    order = {"blocker": 0, "major": 1, "minor": 2}
    ranked = sorted(issues, key=lambda i: order[i["severity"]])[:limit]
    return [
        f"- [{i['severity']}] {i['still']}: {i['problem']}" + (f" -> fix: {i['fix']}" if i.get("fix") else "")
        for i in ranked
    ]


# --- scoped repairs ---------------------------------------------------------
# A repair used to get every issue, minor ones included, and rewrite the whole module: 41-55% of the code
# changed per round and new major issues appeared in scenes nobody had flagged. Now a repair gets the blocker
# and major issues only and the scenes they are in, and every round records how much it changed.


def still_scenes(still: str, scene_ids: list[str]) -> list[str] | None:
    """The scenes a still reference names ("intro-0", or a layout range "a-0 .. c-2 (9 stills)"); None when it
    names no known scene (the whole video)."""

    def one(name: str) -> int | None:
        # the text critic writes "[scene-2]", the form it is shown the on-screen text in
        name = name.split(" (")[0].strip().strip("[]\"'` ")
        hits = [
            k for k, s in enumerate(scene_ids) if name.startswith(s + "-") and name[len(s) + 1 :].isdigit()
        ]
        return hits[0] if hits else None

    ends = [one(p) for p in still.split(" .. ")]
    known = [e for e in ends if e is not None]
    if len(known) < len(ends):
        return None
    return scene_ids[min(known) : max(known) + 1]


def repair_scope(
    issues: list[dict[str, str]], scene_ids: list[str]
) -> tuple[list[dict[str, str]], list[str] | None]:
    """The issues a repair gets (blocker and major) and the scenes it may change (None: any)."""
    heavy = [i for i in issues if i["severity"] in ("blocker", "major")]
    scenes: set[str] = set()
    for i in heavy:
        got = still_scenes(i["still"], scene_ids)
        if got is None:
            return heavy, None
        scenes.update(got)
    return heavy, [s for s in scene_ids if s in scenes]


def churn(
    base: VideoScript, base_tsx: str, new: VideoScript, new_tsx: str, scope: list[str] | None
) -> dict[str, Any]:
    """How much a repair changed: the share of code lines, the scenes whose narration or label changed, and
    those of them outside its scope (scene code is not split per scene, so only the line share covers it)."""
    a, b = base_tsx.splitlines(), new_tsx.splitlines()
    same = sum(blk.size for blk in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())
    old = {s.id: s for s in base.scenes}
    changed = [s.id for s in new.scenes if s.id not in old or old[s.id] != s]
    changed += [i for i in old if i not in {s.id for s in new.scenes}]
    return {
        "changed_lines": round(1 - same / max(len(a), 1), 2),
        "narration_changed": changed,
        "outside_scope": [] if scope is None else [s for s in changed if s not in scope],
    }
