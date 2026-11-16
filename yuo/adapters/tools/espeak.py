"""espeak-ng, run only as a separate program: IPA for a word the Kokoro lexicon does not know."""

import shutil
import subprocess


class Espeak:
    def __init__(self, binary: str | None = None) -> None:
        self.binary = binary or shutil.which("espeak-ng")

    def available(self) -> bool:
        return self.binary is not None

    def ipa(self, word: str, voice: str = "en-us") -> str | None:
        if self.binary is None:
            return None
        p = subprocess.run(
            [self.binary, "-q", "--ipa=3", "-v", voice, word],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        out = p.stdout.strip().replace("_", "")
        return out if p.returncode == 0 and out else None
