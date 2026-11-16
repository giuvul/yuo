"""Video stages: the author (script + TSX scene module), the two critics, and pronunciations.

The prompts are the configuration that scored 7 with Qwen 3.8 27B and 8 with Sonnet: the
coded system prompt with the kit, theme and an example module, the design rules and the accuracy rules.
The author also gets the lesson it illustrates, as source material (a topic line alone gave weaker videos).
Coded repairs are full rewrites from the best round (edit repairs not re-measured).
"""

import json
import re
from collections.abc import Callable
from importlib import resources
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from yuo.content.video import LENGTHS, VideoScript, script_rules
from yuo.core.enums import Stage
from yuo.core.llm import Message
from yuo.generation.runner import StageSpec


def _data(name: str) -> str:
    return resources.files("yuo.data").joinpath("video", name).read_text(encoding="utf-8")


# --- author ---------------------------------------------------------------------------------------

BRIEF = """Make a narrated explainer video for a learner at level `{difficulty}` who is new to the topic.
Length: {spoken} when read aloud ({words_lo} to {words_hi} spoken words in total), {scenes_lo} to {scenes_hi}
scenes, each scene 2 to 5 segments; a segment is ONE spoken sentence (it is also the subtitle).
Narration: accurate, concrete (use a worked example), conversational, no filler; the last scene recaps.
Write the narration in language `{lang}`.
Visuals must explain, not repeat the narration: prefer diagrams, steps, charts and worked examples
over text slides, and make each element appear on the sentence that talks about it."""

CODED_SYSTEM = """You write video lessons as React components for Remotion 4 (1920x1080, 30 fps).
You produce two things:
1. A narration script as JSON: {{"title": str, "scenes": [{{"id": str, "label": str, "segments": [str, ...]}}]}}.
   Scene ids are lowercase identifiers. Each segment is one spoken sentence.
2. One TypeScript/TSX module that exports `SCENES: Record<string, SceneDef>` with one entry per scene id.
   Each component receives `segs` (frame where each segment starts, relative to the scene) and `ends`.
   Use `useBeats(segs)` so each visual lands on the sentence that talks about it.
   The scene area is 1920 x 780 px (the frame draws the label and progress bar around it; the bottom of the
   frame stays free for the player's subtitles).

Rules for the module:
- Allowed imports ONLY: 'react', 'remotion', '../kit', '../theme'. No other packages, no fetch, no
  network, no window/document access, no timers, no randomness (renders must be deterministic).
- It must compile with TypeScript strict mode.
- Draw with SVG and styled divs. Keep all text inside the 1920 x 780 area and legible (>= 26 px).

The kit (src/kit.tsx):
```tsx
{kit}
```
The theme (src/theme.ts):
```ts
{theme}
```
An example module (two scenes from another lesson, for style and API use):
```tsx
{example}
```
Reply with exactly two fenced blocks and nothing else: first ```json (the script), then ```tsx (the module).

{design}

{accuracy}"""

AUTHOR_TEMPLATE = """{brief}

Topic: {topic}

The lesson this video belongs to (source material: keep to it, and to standard textbook knowledge):
{lesson}"""

FIX_TEMPLATE = """{brief}

Topic: {topic}

Your current version:
```json
{script}
```
```tsx
{tsx}
```

Reviewers watched the rendered video (still names are <scene id>-<sentence index>) and found these problems.
Fix every one, keep what works, and keep the narration unless a problem is in it:
{issues}
{scope}
Reply with the complete corrected output in the same format as before: ```json, then ```tsx."""


class VideoDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    script: VideoScript
    tsx: str


_FENCE = re.compile(r"```(json|tsx|typescript|ts|jsx)?[ \t]*\n(.*?)```", re.S)


def parse_draft(text: str) -> dict[str, Any]:
    blocks = {(lang or "").lower(): body for lang, body in _FENCE.findall(text)}
    tsx = blocks.get("tsx") or blocks.get("typescript") or blocks.get("ts") or blocks.get("jsx")
    if "json" not in blocks or tsx is None:
        raise ValueError(
            "reply with exactly two fenced blocks: first ```json (the script), then ```tsx (the module)"
        )
    try:
        script = json.loads(blocks["json"])
    except json.JSONDecodeError as e:
        raise ValueError(f"the ```json script does not parse: {e.msg} at line {e.lineno}") from e
    return {"script": script, "tsx": tsx}


def with_context(tsx: str, errors: list[str]) -> list[str]:
    """Compiler errors with the lines around them (models fail to fix errors given by number only)."""
    lines = tsx.split("\n")
    out = []
    for e in errors:
        m = re.match(r"scene\.tsx\((\d+),(\d+)\)", e)
        if not m:
            out.append(e)
            continue
        n = int(m.group(1))
        around = [
            f"    {i:4d}{'>' if i == n else ' '} {lines[i - 1]}"
            for i in range(max(1, n - 2), min(len(lines), n + 2) + 1)
        ]
        out.append(e + "\n" + "\n".join(around))
    return out


def draft_rules(length: str, check: Callable[[str], list[str]]) -> Callable[[VideoDraft], list[str]]:
    def rules(d: VideoDraft) -> list[str]:
        problems = script_rules(d.script, length)
        missing = [s.id for s in d.script.scenes if not re.search(rf"\b{re.escape(s.id)}\s*:", d.tsx)]
        if missing:
            problems.append(f"SCENES has no entry for scene id(s): {', '.join(missing)}")
        if problems:
            return problems
        return with_context(d.tsx, check(d.tsx))

    return rules


def _system(i: dict[str, Any]) -> str:
    return CODED_SYSTEM.format(
        kit=i["kit"],
        theme=i["theme"],
        example=_data("example_scene.tsx"),
        design=_data("rules_design.md"),
        accuracy=_data("rules_accuracy.md"),
    )


def brief(i: dict[str, Any]) -> str:
    L = LENGTHS[i["length"]]
    return BRIEF.format(
        difficulty=i["difficulty"],
        lang=i["lang"],
        spoken=L.spoken,
        words_lo=L.words[0],
        words_hi=L.words[1],
        scenes_lo=L.scenes[0],
        scenes_hi=L.scenes[1],
    )


def _scope(scenes: list[str] | None) -> str:
    if not scenes:
        return ""
    return (
        f"\nChange only these scenes: {', '.join(scenes)} (their components and, if a problem is in it, their "
        "narration). Every other scene, its component and its narration must stay exactly as they are, character "
        "for character: they were reviewed and are fine.\n"
    )


def _author_messages(i: dict[str, Any]) -> list[Message]:
    if i.get("base") is None:
        user = AUTHOR_TEMPLATE.format(brief=brief(i), topic=i["topic"], lesson=i["lesson"])
    else:
        user = FIX_TEMPLATE.format(
            brief=brief(i),
            topic=i["topic"],
            script=json.dumps(i["base"]["script"], ensure_ascii=False, indent=1),
            tsx=i["base"]["tsx"],
            issues="\n".join(i["issues"]),
            scope=_scope(i.get("scope")),
        )
    return [Message("system", _system(i)), Message("user", user)]


def author_spec(length: str, check: Callable[[str], list[str]], max_tokens: int) -> StageSpec[VideoDraft]:
    return StageSpec(
        Stage.VIDEO_SCENE,
        VideoDraft,
        "video_author",
        1,
        CODED_SYSTEM + AUTHOR_TEMPLATE + FIX_TEMPLATE + BRIEF,
        _author_messages,
        rules=draft_rules(length, check),
        max_tokens=max_tokens,
        parse=parse_draft,
        repair_rounds=2,  # one call and up to two validity repairs
        timeout_s=1200,  # a whole video module on the Claude CLI ran past 600 s
    )


# --- critics --------------------------------------------------------------------------------------


class Issue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    still: str
    severity: Literal["blocker", "major", "minor"]
    problem: str
    fix: str


class Critique(BaseModel):
    model_config = ConfigDict(extra="forbid")
    overall: int = Field(ge=1, le=10)
    issues: list[Issue]


VIS_SYSTEM = """You are a strict reviewer of short educational explainer videos (visual designer and teacher).
You get contact sheets: each image is a 2x3 grid of stills read left to right, top to bottom, one still per
narration sentence, ~2 s into the sentence; the subtitle at the bottom is the sentence being spoken. Grey
tiles after the last still are padding. A list maps every still to its name and sentence.
Find every concrete defect a viewer would notice:
- text that is unreadable, too small, overlapping, cut off, or crossed by lines or arrows;
- empty or near-empty frames, or frames with only a heading while the sentence explains something;
- a visual that does not show what the sentence says, or shows it before it is said;
- a picture, graph or construction the narration promises but the screen does not show;
- numbers or labels on screen that are wrong or contradict the narration;
- confusing layout (crowded, unbalanced, elements on top of each other).
For each defect: `still` = the still name from the list, severity (blocker = wrong or unreadable,
major = clearly hurts understanding, minor = polish), `problem`, and a concrete `fix` for the author
(what to draw, move, enlarge or shorten). Do not report things that are fine. `overall` 1-10: would you
publish this as a lesson (5 usable but plain, 8 good)."""

TXT_SYSTEM = """You are a strict expert reviewer of a short educational explainer video. You cannot see the
video; you get, for every narration sentence, the text that is on screen at that moment (in reading order),
and the source that draws the visuals. The on-screen list holds only the words extracted from the rendered
frame: boxes, lines, arrows and shapes are drawn but not listed, so read the source for the structure and
do not report the list format itself. Find:
- factual, numeric or terminology errors in the narration or on screen (check every number: recompute
  sums, products, sequence numbers, points on curves, equations);
- on-screen numbers or labels that contradict the narration or each other;
- labels shown before the sentence that introduces them, or never explained;
- sentences that promise a picture, graph or example that the screen does not show (judge from the
  on-screen text and the source);
- teaching gaps: a step a newcomer cannot follow, a missing worked example.
For each problem: `still` = the sentence name in brackets, severity (blocker = factually wrong,
major = misleading or missing visual, minor = polish), `problem`, and a concrete `fix` for the author.
Do not report things that are fine. `overall` 1-10: would you publish it (5 usable, 8 good)."""


def _visual_messages(i: dict[str, Any]) -> list[Message]:
    return [
        Message("system", VIS_SYSTEM),
        Message("user", "Stills:\n" + i["still_map"], images=tuple(i["sheets"])),
    ]


def _text_messages(i: dict[str, Any]) -> list[Message]:
    user = f"Topic: {i['topic']}\n\nPer sentence:\n{i['on_screen']}\n\nSource of the visuals:\n{i['tsx'][:40000]}"
    return [Message("system", TXT_SYSTEM), Message("user", user)]


GROUND_SYSTEM = """You check an educational explainer video against the lesson it was made from. The lesson
passed an expert review: treat it as the reference, not your own memory. You get the lesson, then for every
narration sentence the text on screen at that moment, then the source that draws the visuals.
Go through the video sentence by sentence and check every factual statement in the narration and on screen
(definitions, names, which part does what, order of steps, directions, relations, numbers) against the lesson:
- blocker: the video contradicts the lesson (says something the lesson says is different or false);
- major: a worked example or diagram breaks a rule the lesson states (recompute numbers, sequence numbers,
  totals, points on curves with the lesson's rules; the example may use its own numbers, but they must obey
  the lesson's rules and stay consistent from scene to scene);
- minor: a specific factual claim the lesson does not cover and that you are not sure is right.
Simplifications and content the lesson supports are fine: do not report them, and report nothing about
design, wording or teaching style. For each problem: `still` = the sentence name in brackets, `problem` =
what the video says and what the lesson says (quote it), `fix` = the corrected statement. `overall` 1-10: how
faithful the video is to the lesson (10 = nothing contradicts it)."""


def _ground_messages(i: dict[str, Any]) -> list[Message]:
    user = (
        f"Lesson:\n{i['lesson']}\n\nVideo, per sentence:\n{i['on_screen']}\n\n"
        f"Source of the visuals:\n{i['tsx'][:40000]}"
    )
    return [Message("system", GROUND_SYSTEM), Message("user", user)]


VISUAL_CRITIC = StageSpec(
    Stage.VIDEO_REVIEW, Critique, "video_visual_critic", 1, VIS_SYSTEM, _visual_messages, max_tokens=14000
)
TEXT_CRITIC = StageSpec(
    Stage.REVIEW, Critique, "video_text_critic", 1, TXT_SYSTEM, _text_messages, max_tokens=14000
)


GROUND_CRITIC = StageSpec(  # the lesson as the reference for accuracy
    Stage.REVIEW, Critique, "video_ground_critic", 1, GROUND_SYSTEM, _ground_messages, max_tokens=14000
)


# --- pronunciations (an LLM stage, cached per path) ---------------------------------------------


class Pronunciation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    word: str
    ipa: str = Field(description="General American IPA with the primary stress mark, no slashes")


class Pronunciations(BaseModel):
    model_config = ConfigDict(extra="forbid")
    words: list[Pronunciation]


PRONOUNCE_TEMPLATE = """Give the General American IPA pronunciation of each word or term below as it is normally
said aloud in a lesson about "{topic}" (acronyms spelled out only if people spell them). One entry per word,
the word exactly as given.
{words}"""


def _pronounce_messages(i: dict[str, Any]) -> list[Message]:
    text = PRONOUNCE_TEMPLATE.format(topic=i["topic"], words="\n".join(f"- {w}" for w in i["words"]))
    return [Message("system", "You are a phonetician."), Message("user", text)]


def _pronounce_rules(words: list[str]) -> Callable[[Pronunciations], list[str]]:
    def rules(p: Pronunciations) -> list[str]:
        got = {x.word for x in p.words if x.ipa.strip()}
        missing = [w for w in words if w not in got]
        return [f"no pronunciation for: {', '.join(missing)}"] if missing else []

    return rules


def pronounce_spec(words: list[str]) -> StageSpec[Pronunciations]:
    return StageSpec(
        Stage.TTS,
        Pronunciations,
        "pronounce",
        1,
        PRONOUNCE_TEMPLATE,
        _pronounce_messages,
        rules=_pronounce_rules(words),
        max_tokens=4000,
    )
