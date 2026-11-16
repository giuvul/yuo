"""Tutor policies: resolved on the server, never from the client's word.

A policy says what the model may see (the answer key, the solution, the hint ladder), what it may do,
whether its replies are checked for leaks before display, and whether a reply counts as help on the
item. The layered control, strongest first:

1. context redaction: before an attempt the model never sees the key (tests and practice alike);
2. a deterministic guess detector answers "is it B?" with a template, without calling the model;
3. a model leak checker on every other reply in checked modes, failing closed to a safe fallback;
4. the prompt (Socratic style), the least reliable layer.
"""

from dataclasses import dataclass
from typing import Literal

from yuo.core.enums import TutorMode

POLICY_VERSION = 1

# "trying": a review question with a wrong try that is not resolved yet
ItemState = Literal["none", "unanswered", "trying", "answered"]


@dataclass(frozen=True, slots=True)
class Policy:
    id: str
    mode: TutorMode
    instruction: str
    key: bool  # the answer key and the worked solution are in the model's context
    hints: bool  # the pre-generated hint ladder (all rungs but the last) is in the context
    item: bool  # the item itself is in the context
    checked: bool  # replies pass the leak checker before display (needs an item)
    guess_guard: bool  # guesses get the template reply, the model is not called
    records_help: bool  # a delivered reply on an item marks the response as tutor-assisted
    proactive: bool  # nudges may appear while this policy applies
    actions: bool  # the tutor may propose path changes and remember things
    sealed: bool = False  # the thread is the test attempt's: no other context, no memory writes


_NO_LEAK = (
    "You must not state, confirm, deny or eliminate any option, solve the question, or give a hint so "
    "specific that only one answer fits. Saying that a wrong guess is wrong also reveals the answer. If "
    "asked, say kindly why you cannot, and offer what you can do."
)

POLICIES: dict[str, Policy] = {
    p.id: p
    for p in (
        Policy(
            "free",
            TutorMode.FREE,
            "The learner is browsing their path. Help them plan, explain topics, and suggest changes as "
            "proposals they accept or reject; never claim to have changed anything yourself.",
            key=False,
            hints=False,
            item=False,
            checked=False,
            guess_guard=False,
            records_help=False,
            proactive=True,
            actions=True,
        ),
        Policy(
            "lesson",
            TutorMode.LESSON,
            "The learner is reading a lesson. Explain, give examples, and answer questions about it. Keep "
            "to what the lesson teaches unless asked to go further.",
            key=False,
            hints=False,
            item=False,
            checked=False,
            guess_guard=False,
            records_help=False,
            proactive=True,
            actions=True,
        ),
        Policy(
            "practice.before_attempt",
            TutorMode.PRACTICE,
            "The learner is PRACTISING and has NOT answered this question yet. You do not know the answer. "
            "Be Socratic: ask a guiding question, point to the idea in the lesson, or use a hint from the "
            "ladder below. " + _NO_LEAK + " Once they submit an answer, the full solution unlocks.",
            key=False,
            hints=True,
            item=True,
            checked=True,
            guess_guard=True,
            records_help=True,
            proactive=True,
            actions=False,
        ),
        Policy(
            "practice.after_attempt",
            TutorMode.PRACTICE,
            "The learner has answered this practice question; the answer key and solution are below. "
            "Explain why the right answer is right and why their choice was or was not, contrast the "
            "distractors, and end with a short follow-up question when useful.",
            key=True,
            hints=True,
            item=True,
            checked=False,
            guess_guard=False,
            records_help=False,
            proactive=True,
            actions=True,
        ),
        Policy(
            "test.locked",
            TutorMode.TEST_LOCKED,
            "The learner is taking a SKILL TEST in LOCKED mode. You do not know the answer key and must not "
            "work it out for them. You may only clarify the wording of the question, explain vocabulary "
            "used in it, and help with problems in the app. " + _NO_LEAK + " Help is locked during the "
            "test; they can review the topic afterwards.",
            key=False,
            hints=False,
            item=True,
            checked=True,
            guess_guard=True,
            records_help=False,
            proactive=False,
            actions=False,
            sealed=True,
        ),
        Policy(
            "test.hints",
            TutorMode.TEST_HINTS,
            "The learner is taking a SKILL TEST with HINTS WITH COST. You do not know the answer key. You "
            "may clarify the wording and give ONE small conceptual nudge that points to what to think about, "
            "never to an option. A nudge costs the learner credit, so start it with '[hint]'. " + _NO_LEAK,
            key=False,
            hints=False,
            item=True,
            checked=True,
            guess_guard=True,
            records_help=True,
            proactive=False,
            actions=False,
            sealed=True,
        ),
        Policy(
            "placement",
            TutorMode.TEST_LOCKED,
            "The learner is taking a PLACEMENT test that decides what they can skip. You may only clarify the "
            "wording of the question. " + _NO_LEAK,
            key=False,
            hints=False,
            item=True,
            checked=True,
            guess_guard=True,
            records_help=False,
            proactive=False,
            actions=False,
            sealed=True,
        ),
        Policy(
            "test.debrief",
            TutorMode.LESSON,
            "The learner has finished a test. Talk about the topics it covered and what to study next. Do "
            "not reveal the answers to its questions: the same questions can come back in a retake.",
            key=False,
            hints=False,
            item=False,
            checked=False,
            guess_guard=False,
            records_help=False,
            proactive=True,
            actions=True,
        ),
        Policy(
            "review.before_recall",
            TutorMode.REVIEW,
            "The learner is recalling a review card and has not answered yet. Do not help with the card: "
            "recall without help is what makes the review work. You may only take a report that the card "
            "is broken or unclear. " + _NO_LEAK,
            key=False,
            hints=False,
            item=True,
            checked=True,
            guess_guard=True,
            records_help=False,
            proactive=False,
            actions=False,
        ),
        Policy(
            "review.after_recall",
            TutorMode.REVIEW,
            "The learner has answered this review card; the answer is below. Explain it, offer a memory aid, "
            "and suggest an edit to the card if it is unclear.",
            key=True,
            hints=False,
            item=True,
            checked=False,
            guess_guard=False,
            records_help=False,
            proactive=True,
            actions=True,
        ),
        Policy(
            "review.coach",
            TutorMode.REVIEW,
            "The learner is REVIEWING a question from an earlier lesson and it is NOT resolved yet (they have "
            "not found the right answer and have not asked to see it). You do not know the answer. Coach the "
            "recall, keep the effort with the learner: ask one guiding question, name the principle at work, "
            "or give an analogy on a DIFFERENT case than the question's. You may use a hint from the ladder "
            "below. If options they already tried are listed, you may explain why those are wrong. "
            + _NO_LEAK
            + " Never rule the other options in or out. Once the question is resolved you can explain it fully.",
            key=False,
            hints=True,
            item=True,
            checked=True,
            guess_guard=True,
            records_help=True,
            proactive=False,
            actions=False,
        ),
        Policy(
            "review.resolved",
            TutorMode.REVIEW,
            "The learner has resolved this review question; the answer key and the reasons are below. Explain "
            "freely why the right answer holds, contrast it with the option they chose, and connect it to "
            "the lesson. If their mistake shows a misconception worth keeping in mind, offer to remember it.",
            key=True,
            hints=True,
            item=True,
            checked=False,
            guess_guard=False,
            records_help=False,
            proactive=True,
            actions=True,
        ),
        Policy(
            "setup",
            TutorMode.SETUP,
            "The learner is in the settings. Explain what settings do and suggest values with the trade-off; "
            "they change settings themselves.",
            key=False,
            hints=False,
            item=False,
            checked=False,
            guess_guard=False,
            records_help=False,
            proactive=False,
            actions=False,
        ),
    )
}

Screen = Literal[
    "home",
    "path",
    "tree",
    "lesson",
    "reading",
    "practice",
    "test",
    "placement",
    "review",
    "progress",
    "settings",
    "setup",
    "other",
]


def resolve(
    *,
    screen: str,
    purpose: str | None,
    attempt_open: bool,
    item_state: ItemState,
    test_policy: str,
    bank: bool = False,
) -> Policy:
    """The policy for one turn. `purpose`, `attempt_open` and `item_state` come from the server's own
    records for the attempt and item the client named, never from the client's claim."""
    if purpose in ("skill_test", "placement"):
        if not attempt_open:
            return POLICIES["test.debrief"]
        if purpose == "placement":
            return POLICIES["placement"]
        return POLICIES["test.hints" if test_policy == "hints" else "test.locked"]
    if purpose == "review" and bank and item_state != "none":
        # a review session over the question bank: coach without spoilers until the question is resolved
        return POLICIES["review.resolved" if item_state == "answered" else "review.coach"]
    if purpose == "review" and item_state != "none":
        return POLICIES["review.after_recall" if item_state == "answered" else "review.before_recall"]
    if purpose == "practice" and item_state != "none":
        return POLICIES["practice.after_attempt" if item_state == "answered" else "practice.before_attempt"]
    if screen in ("settings", "setup"):
        return POLICIES["setup"]
    if screen in ("lesson", "reading", "practice"):
        return POLICIES["lesson"]
    return POLICIES["free"]
