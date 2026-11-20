"""Settings registry: one typed definition per CFG key, values in `setting_value`.

Every user-facing setting carries its suggestion, explanation, example and impact tags; a fitness test fails
when one is missing. Most specific level wins: lesson > path > learner > installation.
"""

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from pydantic import TypeAdapter

from yuo.core import clock
from yuo.core.enums import DataClass
from yuo.core.errors import InvalidInput
from yuo.core.ids import new_id

Level = Literal["installation", "learner", "path", "lesson"]
Impact = Literal["cost", "time", "learning", "privacy"]
ORDER: tuple[Level, ...] = ("lesson", "path", "learner", "installation")


@dataclass(frozen=True, slots=True)
class SettingDef:
    key: str
    cfg: str
    levels: tuple[Level, ...]
    default: Any
    type: Any  # a type TypeAdapter accepts
    explanation: str
    example: str
    suggestion: str
    impact: tuple[Impact, ...]
    data_class: DataClass = DataClass.CONFIG
    weakens_learning: str | None = None


REGISTRY: dict[str, SettingDef] = {}


def define(d: SettingDef) -> SettingDef:
    REGISTRY[d.key] = d
    return d


MODEL_PRESET = define(
    SettingDef(
        "model.preset",
        "CFG-01",
        ("installation",),
        "auto",
        Literal["auto", "claude", "codex", "open", "custom"],
        explanation="Which models write, review and tutor. 'auto' uses a Claude or Codex subscription when one is "
        "signed in, else Qwen 3.8 27B, the minimum tested model.",
        example="Claude: lessons by Sonnet, reviews by Opus, no extra cost on a Claude plan. Open: Qwen 3.8 27B "
        "everywhere, about 0.03 USD per lesson through a gateway or free on a local GPU.",
        suggestion="auto, because it picks the best model you already have access to",
        impact=("cost", "learning", "privacy"),
    )
)
REVIEWER_INDEPENDENCE = define(
    SettingDef(
        "review.independent",
        "CFG-03",
        ("installation",),
        True,
        bool,
        explanation="Review each lesson with a different model or provider than the one that wrote it.",
        example="On: a Sonnet lesson is checked by Opus or Qwen, which catch errors Sonnet makes itself.",
        suggestion="on, because a second model finds about one error in five frontier lessons",
        impact=("learning", "cost"),
        weakens_learning="Off: the writer reviews itself and misses more of its own mistakes.",
    )
)
READING_LENGTH = define(
    SettingDef(
        "lesson.reading_length",
        "CFG-12",
        ("learner", "path"),
        "medium",
        Literal["short", "medium", "long"],
        explanation="How long a reading lesson is.",
        example="Short: about 5 minutes. Long: about 15 minutes, with two worked examples.",
        suggestion="medium, a good fit for a 20-minute session",
        impact=("time", "learning", "cost"),
    )
)
BUDGET_CAP = define(
    SettingDef(
        "budget.cap_usd_month",
        "CFG-51",
        ("installation",),
        None,
        float | None,
        explanation="Generation pauses when billed model spend this month reaches the cap. Subscriptions do not count.",
        example="5 USD: about 250 DeepSeek lessons, or 150 Qwen lessons with video.",
        suggestion="a cap you would not mind spending; Yuo shows the estimate before each path",
        impact=("cost",),
    )
)
CUSTOM_INSTRUCTIONS = define(
    SettingDef(
        "custom_instructions",
        "CFG-60",
        ("learner", "path"),
        "",
        str,
        explanation="Extra wishes passed to lesson writing and the tutor, as data below Yuo's own rules.",
        example="'Use Python examples; I'm preparing for interviews' makes exercises interview-style.",
        suggestion="leave empty, or one or two sentences about your goal",
        impact=("learning", "privacy"),
        data_class=DataClass.FREE_TEXT,
    )
)


LOCAL_URL = re.compile(r"^http://(127\.0\.0\.1|localhost|\[::1\]):\d{2,5}/v1$")
RANGES: dict[str, tuple[float, float]] = {
    "generation.buffer": (1, 10),
    "skill_test.pass_mark": (0.5, 1.0),
    "reviews.max_per_day": (0, 500),
    "review.bank_size": (4, 20),
    "review.desired_retention": (0.7, 0.97),
    "review.max_interval_days": (0, 365),
    "streak.grace_days": (0, 3),
    "session.minutes": (5, 120),
}


def validate(key: str, value: Any) -> Any:
    d = REGISTRY[key]
    v = TypeAdapter(d.type).validate_python(value)
    if key in RANGES and not RANGES[key][0] <= v <= RANGES[key][1]:
        raise InvalidInput(f"{key} must be between {RANGES[key][0]} and {RANGES[key][1]}")
    if key == "learner.interests" and len(v) > 500:
        raise InvalidInput("learner.interests: at most 500 characters")
    if key == "ai.local_url" and v is not None and not LOCAL_URL.match(v):
        raise InvalidInput("ai.local_url must be a loopback address like http://127.0.0.1:11434/v1")
    if key == "tutor.name" and not 1 <= len(v.strip()) <= 30:
        raise InvalidInput("the tutor's name is 1 to 30 characters")
    if key == "custom_instructions" and len(v) > 1000:
        raise InvalidInput("custom instructions are limited to about 1,000 characters")
    return v


def effective(c: sqlite3.Connection, key: str, scopes: dict[Level, str | None]) -> tuple[Any, Level | None]:
    """The value in force and the level it comes from (None = the default)."""
    d = REGISTRY[key]
    for level in ORDER:
        if level not in d.levels or (level not in scopes and level != "installation"):
            continue
        ref = None if level == "installation" else scopes.get(level)
        row = c.execute(
            "SELECT value FROM setting_value WHERE key = ? AND scope = ? AND scope_ref IS ?",
            (key, level, ref),
        ).fetchone()
        if row is not None:
            return json.loads(row[0]), level
    return d.default, None


def put(
    c: sqlite3.Connection,
    key: str,
    value: Any,
    level: Level,
    ref: str | None = None,
    device_id: str | None = None,
) -> None:
    d = REGISTRY[key]
    if level not in d.levels:
        raise InvalidInput(f"{key} cannot be set at {level} level")
    v = json.dumps(validate(key, value))
    old = c.execute(
        "SELECT value FROM setting_value WHERE key = ? AND scope = ? AND scope_ref IS ?", (key, level, ref)
    ).fetchone()
    now = clock.now()
    if old is None:
        c.execute(
            "INSERT INTO setting_value (id, key, scope, scope_ref, value, data_class, updated_at, "
            "updated_by_device_id) VALUES (?, ?, ?, ?, json(?), ?, ?, ?)",
            (new_id(), key, level, ref, v, d.data_class.value, now, device_id),
        )
    else:
        c.execute(
            "UPDATE setting_value SET value = json(?), updated_at = ?, updated_by_device_id = ? "
            "WHERE key = ? AND scope = ? AND scope_ref IS ?",
            (v, now, device_id, key, level, ref),
        )
    if level == "installation":
        c.execute(
            "INSERT INTO setting_audit (id, key, old, new, device_id, at) VALUES (?, ?, ?, json(?), ?, ?)",
            (new_id(), key, old[0] if old else None, v, device_id, now),
        )


# --- learning loop --------------------------------------------------------------------------

define(
    SettingDef(
        "generation.buffer",
        "CFG-15",
        ("installation", "learner", "path"),
        3,
        int,
        explanation="How many lessons Yuo keeps ready ahead of you, so you rarely wait for one.",
        example="3: after you finish a lesson, the next three are already written or being written.",
        suggestion="3, enough for a few sessions without generating far ahead of your progress",
        impact=("cost", "time"),
    )
)
define(
    SettingDef(
        "skill_test.pass_mark",
        "CFG-17",
        ("installation", "learner"),
        0.8,
        float,
        explanation="The score a skill test needs to mark the skill mastered and unlock the skills after it.",
        example="80 %: four of five questions right passes; three of five sends you a short extra lesson first.",
        suggestion="80 %, strict enough that unlocked skills rest on solid ground",
        impact=("learning", "time"),
        weakens_learning="A low pass mark unlocks later skills before the earlier ones are solid.",
    )
)
define(
    SettingDef(
        "reviews.max_per_day",
        "CFG-18",
        ("installation", "learner"),
        50,
        int,
        explanation="The most review questions Yuo asks in one day; the rest wait for the next day.",
        example="50: a busy week never turns into a pile of 300 reviews on Monday.",
        suggestion="50, about 10 minutes of reviews",
        impact=("time", "learning"),
        weakens_learning="A very low cap lets reviews fall behind, and you forget more.",
    )
)
define(
    SettingDef(
        "review.bank_size",
        "CFG-18a",
        ("installation", "path"),
        11,
        int,
        explanation="How many review questions Yuo writes for each lesson. About a quarter of them connect the "
        "lesson with an earlier one.",
        example="11: eight questions on the lesson itself and three that combine it with another lesson.",
        suggestion="11, enough for several review sessions without repeating a question",
        impact=("cost", "learning"),
    )
)
define(
    SettingDef(
        "review.desired_retention",
        "CFG-18b",
        ("installation", "learner"),
        0.9,
        float,
        explanation="How likely you should still be to remember something when Yuo brings it back for review. "
        "A higher value means shorter gaps and more reviews.",
        example="90 %: a review comes back when you would still get about nine of ten right.",
        suggestion="90 %, the usual balance between remembering and time spent",
        impact=("time", "learning"),
        weakens_learning="A low value leaves long gaps, and you forget more between reviews.",
    )
)
define(
    SettingDef(
        "review.max_interval_days",
        "CFG-18c",
        ("installation", "learner"),
        0,
        int,
        explanation="The longest gap between two reviews of the same idea, in days. 0 means no limit.",
        example="14: nothing waits longer than two weeks, however well you know it.",
        suggestion="0 (no limit); set 14 if you study daily and want everything to stay fresh",
        impact=("time", "learning"),
    )
)
define(
    SettingDef(
        "mastery.decay",
        "CFG-33",
        ("installation", "learner"),
        True,
        bool,
        explanation="A mastered skill shows 'needs review' when its reviews are overdue and you are likely to have "
        "forgotten part of it.",
        example="On: a skill you mastered in March and never reviewed shows 'needs review' in June.",
        suggestion="on, so the tree shows what you still know, not only what you once passed",
        impact=("learning",),
    )
)
define(
    SettingDef(
        "practice.solution_after",
        "CFG-36",
        ("installation", "learner"),
        "attempt",
        Literal["attempt", "any_time"],
        explanation="When the worked solution of a practice question can be opened.",
        example="After one attempt: you answer first, then see the solution. Any time: the solution is always there.",
        suggestion="after one attempt, because trying first helps you remember",
        impact=("learning",),
        weakens_learning="Any time: reading the solution before trying teaches less.",
    )
)
define(
    SettingDef(
        "gamification",
        "CFG-74",
        ("installation", "learner"),
        "full",
        Literal["off", "minimal", "full"],
        explanation="How much of XP, levels, streaks and achievements Yuo shows.",
        example="Minimal: the tree shows progress, but no XP or streaks.",
        suggestion="full, unless streaks make you anxious rather than motivated",
        impact=("learning",),
    )
)
define(
    SettingDef(
        "streak.grace_days",
        "CFG-75",
        ("installation", "learner"),
        1,
        int,
        explanation="Days you can miss each week without breaking your streak.",
        example="1: skipping Wednesday keeps a 10-day streak alive; skipping Wednesday and Thursday resets it.",
        suggestion="1, so one busy day does not undo a habit",
        impact=("learning",),
    )
)
define(
    SettingDef(
        "practice.types",
        "CFG-79",
        ("installation", "learner", "path"),
        None,
        list[str] | None,
        explanation="Which kinds of practice questions Yuo writes. Empty means all installed types.",
        example="Without flashcards: practice uses choice, gap-fill, ordering, matching and short answers only.",
        suggestion="all types, because variety checks a skill from several sides",
        impact=("learning", "cost"),
    )
)


# --- tutor ----------------------------------------------------------------------------------

define(
    SettingDef(
        "tutor.proactivity",
        "CFG-34",
        ("installation", "learner"),
        "coach",
        Literal["off", "quiet", "coach", "active"],
        explanation="Whether the tutor speaks first. It only does so between activities (after an answer, a lesson "
        "or a test), never during a test or a video, and always says why.",
        example="Coach: after two wrong answers on the same idea, a one-line offer to look at it together; at most "
        "one every 10 minutes and three per session.",
        suggestion="coach, a few well-timed offers without interrupting",
        impact=("learning",),
    )
)
define(
    SettingDef(
        "tutor.test_policy",
        "CFG-35",
        ("installation", "learner"),
        "locked",
        Literal["locked", "hints"],
        explanation="What the tutor may do during a skill test. Locked: it only explains the wording of a "
        "question. Hints with cost: it may give one small nudge, and the answer counts as helped.",
        example="Locked: 'What does equilibrium mean here?' is answered; 'Is it C?' is not.",
        suggestion="locked, so a passed test shows what you can do on your own",
        impact=("learning",),
        weakens_learning="Hints with cost: a test passed with nudges says less about what you know.",
    )
)
define(
    SettingDef(
        "tutor.name",
        "CFG-37",
        ("installation", "learner"),
        "Tutor",
        str,
        explanation="The name the tutor uses for itself.",
        example="'Ada': replies are signed Ada, nothing else changes.",
        suggestion="any short name you like",
        impact=("learning",),
    )
)
define(
    SettingDef(
        "tutor.tone",
        "CFG-37",
        ("installation", "learner"),
        "neutral",
        Literal["neutral", "warm", "direct"],
        explanation="How the tutor sounds. The rules it follows are the same in every tone.",
        example="Direct: short answers without pleasantries. Warm: more encouragement.",
        suggestion="neutral",
        impact=("learning",),
    )
)
define(
    SettingDef(
        "tutor.memory",
        "CFG-39",
        ("installation", "learner"),
        True,
        bool,
        explanation="The tutor remembers lasting things about you (goals, preferences, misconceptions) across "
        "conversations. You can see, edit and delete every entry.",
        example="On: after you mention an interview, later answers use interview-style examples.",
        suggestion="on; check the entries now and then in Tutor memory",
        impact=("learning", "privacy"),
        data_class=DataClass.FREE_TEXT,
    )
)
define(
    SettingDef(
        "tutor.muted_triggers",
        "CFG-34",
        ("installation", "learner"),
        [],
        list[Literal["repeated_error", "fast_guessing", "unsent_notes", "failed_test"]],
        explanation="Kinds of tutor suggestions you asked not to see again ('Don't suggest this').",
        example="fast_guessing: no more 'slow down' offers when you answer quickly.",
        suggestion="empty; mute a kind from the suggestion itself when it does not help you",
        impact=("learning",),
    )
)


# --- video ----------------------------------------------------------------------------------

define(
    SettingDef(
        "video.format",
        "CFG-14",
        ("installation", "learner", "path"),
        "when_possible",
        Literal["reading", "when_possible", "always"],
        explanation="Whether lessons also get a narrated video. A video that cannot be made leaves the reading "
        "lesson in place; 'always' retries such lessons later instead of giving up.",
        example="When possible: most lessons get a 5-minute video next to the text; a few stay text only.",
        suggestion="when possible, because seeing a diagram drawn while it is explained helps most topics",
        impact=("learning", "cost", "time"),
    )
)
YOUTUBE_DISCLAIMER = (
    "Yuo reads the captions of public YouTube videos to write the lesson and shows the video in YouTube's own "
    "player. YouTube's terms do not allow reading its pages by automated means: you turn this on at your own "
    "risk and are responsible for your use of it."
)
define(
    SettingDef(
        "video.source",
        "CFG-87",
        ("installation", "learner", "path"),
        "generated",
        Literal["generated", "youtube"],
        explanation="Where a lesson's video comes from. 'Made by Yuo' writes and renders a new video. 'From "
        "YouTube' finds an existing video for the lesson, picks the part that teaches it, and writes the lesson "
        "from what the video says: it costs about 10 to 25% more than a reading lesson, where a video made by Yuo costs "
        "about ten times the lesson, and it needs no video renderer. " + YOUTUBE_DISCLAIMER,
        example="From YouTube: a lesson on SQL joins comes with minutes 2:10 to 9:45 of a joins tutorial, and the "
        "reading follows what the video explains.",
        suggestion="from YouTube when you want videos but keep usage low; made by Yuo for topics YouTube covers "
        "poorly",
        impact=("cost", "learning", "privacy"),
    )
)
define(
    SettingDef(
        "video.youtube_languages",
        "CFG-88",
        ("installation", "learner", "path"),
        "also_english",
        Literal["mine", "also_english"],
        explanation="Which YouTube videos a lesson may use: only videos in the path's language, or also videos "
        "in English. The lesson text is always in the path's language.",
        example="Also English: an Italian path can use an English video on Spark; the reading stays in Italian.",
        suggestion="also English, because most technical videos are in English",
        impact=("learning",),
    )
)
define(
    SettingDef(
        "video.length",
        "CFG-13",
        ("installation", "learner", "path"),
        "medium",
        Literal["short", "medium", "long"],
        explanation="How long a lesson's video is. Longer videos cover more of the lesson and take longer to make.",
        example="Short: about 2 minutes, the main idea with one worked example. Medium: about 5 minutes.",
        suggestion="medium for most lessons; short when you mostly read and want a quick visual",
        impact=("time", "cost", "learning"),
    )
)
define(
    SettingDef(
        "video.captions",
        "CFG-78",
        ("installation", "learner"),
        True,
        bool,
        explanation="Show the narration as captions under the video. They are a separate track you can turn on "
        "or off in the player at any time; they are never part of the picture.",
        example="Off: the video plays without captions; the player's CC button turns them back on.",
        suggestion="on, because reading along helps with new terms",
        impact=("learning",),
    )
)
define(
    SettingDef(
        "video.notes_bubble",
        "CFG-83",
        ("installation", "learner"),
        True,
        bool,
        explanation="A small floating button over a lesson video where you jot questions as they come up, each "
        "with the moment of the video, and send them all to the tutor when you are done.",
        example="Off: no floating button; notes on the lesson still work as before.",
        suggestion="on, so a question does not interrupt the video",
        impact=("learning",),
    )
)
define(
    SettingDef(
        "video.theme",
        "CFG-32",
        ("installation", "learner", "path"),
        "match_app",
        Literal["match_app", "light", "dark"],
        explanation="The colours new videos are made in. 'Match app' uses the app's light or dark look at the "
        "moment the video is made; the colours are part of the video, so a finished video keeps them.",
        example="Dark: every new video has a deep navy background, even while the app is light.",
        suggestion="match app, so videos look like the rest of Yuo",
        impact=("learning",),  # readability, as for the app theme
    )
)
define(
    SettingDef(
        "ui.device_scheme",
        "CFG-84",
        ("learner",),
        "light",
        Literal["light", "dark"],
        explanation="Whether your device showed Yuo light or dark the last time you used it. The app records "
        "it by itself while the app theme follows your device, so videos set to 'match app' can match it.",
        example="Your phone switches to dark at night: videos made after that visit come out dark.",
        suggestion="leave it to the app",
        impact=("learning",),
    )
)

define(
    SettingDef(
        "material.transcription",
        "CFG-85",
        ("installation",),
        "accurate",
        Literal["faster", "accurate"],
        explanation="How your recorded lectures are transcribed on this computer. Faster uses a smaller speech "
        "model: about three times quicker, with a few more mistakes in short words and notation (in a test, 97% of "
        "the words matched).",
        example="Faster: a 90-minute lecture takes about 8 minutes instead of about 23 on a 4-core server.",
        suggestion="more accurate; faster when you add many hours of recordings at once",
        impact=("time", "learning"),
    )
)

# --- desktop, onboarding, themes, updates --------------------------------------------------------
define(
    SettingDef(
        "ui.theme",
        "CFG-31",
        ("installation", "learner"),
        "system",
        Literal["system", "light", "dark"],
        explanation="How the app looks: follow your device's light or dark setting, or always one of them.",
        example="Dark: the app stays dark even when your device switches to light during the day.",
        suggestion="system, so the app matches the rest of your device",
        impact=("learning",),  # readability: dark at night, light in daylight
    )
)
define(
    SettingDef(
        "session.minutes",
        "CFG-63",
        ("installation", "learner", "path"),
        20,
        int,
        explanation="How long you usually have for one sitting. Yuo uses it to size what it suggests next: a "
        "lesson and the reviews that are due.",
        example="20 minutes: about one lesson and ten reviews.",
        suggestion="20, a sitting that fits most days",
        impact=("learning", "time"),
    )
)
define(
    SettingDef(
        "learner.interests",
        "CFG-65",
        ("installation", "learner"),
        "",
        str,
        explanation="Your job, hobbies or background, in a few words. Examples and exercises draw on them. "
        "It is sent to the model with your lessons, as information about you, never as instructions.",
        example="Football and logistics: joins explained with a league table and a delivery schedule.",
        suggestion="two or three things you know well",
        impact=("learning", "privacy"),
        data_class=DataClass.FREE_TEXT,
    )
)
define(
    SettingDef(
        "ai.local_url",
        "CFG-50",
        ("installation",),
        None,
        str | None,
        explanation="The address of a model server on this machine (Ollama, LM Studio, llama.cpp). Models there "
        "cost nothing per use and nothing you study leaves the machine.",
        example="http://127.0.0.1:11434/v1 for Ollama.",
        suggestion="found by the setup wizard when one is running",
        impact=("cost", "privacy"),
    )
)


class GenerationPause(TypedDict):
    scope: Literal["all", "videos"]
    until: str | None  # an ISO timestamp, or None: until resumed


define(
    SettingDef(
        "generation.pause",
        "CFG-86",
        ("installation",),
        None,
        GenerationPause | None,
        explanation="Stops Yuo writing ahead for a while, to save your subscription or credit: lessons, review "
        "questions and videos (or only videos) wait, and go on from where they stopped when you resume.",
        example="Videos only, until tomorrow: lessons keep coming, videos wait.",
        suggestion="off; pause when you need your subscription for something else",
        impact=("cost", "time"),
    )
)
define(
    SettingDef(
        "updates.check",
        "CFG-52",
        ("installation",),
        True,
        bool,
        explanation="Look once a day for a new Yuo release. The check downloads a small file listing the latest "
        "version; nothing about you or your learning is sent. Installing is always your choice.",
        example="Off: you learn about new versions from the project page only.",
        suggestion="on, so you get fixes",
        impact=("privacy",),
    )
)
