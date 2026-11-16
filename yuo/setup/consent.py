"""Subscription consent: the text a learner agrees to before Yuo runs their Claude Code or Codex."""

# The text the learner agrees to, versioned by its hash. The web app shows a translation of it; the
# record keeps the hash of this English original and its version.
CONSENT_VERSION = 2  # 2: Codex no longer called unverified (2026-11-15)
CONSENT_TEXT = {
    "claude": (
        "Yuo will run the Claude Code app installed on this computer, signed in with your own account, to write "
        "lessons and answer as your tutor. Yuo never reads or stores your Claude sign-in. This use counts "
        "against your subscription's limits, and Anthropic may bill use by third-party tools as extra usage; "
        "Yuo stops and tells you when it sees an extra-usage answer. You can switch to another model at any "
        "time in Settings."
    ),
    "codex": (
        "Yuo will run the Codex app installed on this computer, signed in with your own account, to write "
        "lessons and answer as your tutor. Yuo never reads or stores your ChatGPT sign-in. This use counts "
        "against your plan's limits. You can switch to another model at any time in Settings."
    ),
}
