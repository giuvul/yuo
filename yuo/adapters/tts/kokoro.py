"""Kokoro text-to-speech on the licence-clean path.

misaki's English lexicon turns text into phonemes; the Kokoro v1.0 ONNX model runs on onnxruntime directly
(no kokoro-onnx: its tokenizer imports phonemizer and espeakng-loader, GPL in process). A word misaki does not
know is looked up in a pronunciation lexicon the pipeline fills per path (an LLM stage); then espeak-ng is
asked as a separate program when it is installed; a word still unknown fails the narration with its name, so
it is never read out wrongly in silence.

The model files (`kokoro-v1.0.onnx`, `voices-v1.0.bin`) are downloaded by the installer, checked by hash.
"""

import json
import re
import threading
import unicodedata
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np

from yuo.adapters.tools.espeak import Espeak
from yuo.core.audio import write_wav
from yuo.core.media import MediaError

MODEL_SHA256 = {
    "kokoro-v1.0.onnx": "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}
MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/{name}"


def fetch_models(model_dir: Path) -> list[str]:
    """Download the voice model files that are missing, each checked against its pinned SHA-256 before it is
    kept. Returns the names downloaded."""
    import hashlib
    import urllib.request

    model_dir.mkdir(parents=True, exist_ok=True)
    got = []
    for name, sha in MODEL_SHA256.items():
        target = model_dir / name
        if target.exists():
            continue
        tmp = model_dir / f".{name}.part"
        digest = hashlib.sha256()
        with urllib.request.urlopen(MODEL_URL.format(name=name), timeout=60) as r, tmp.open("wb") as f:  # noqa: S310 (fixed https URL)
            while chunk := r.read(1 << 20):
                digest.update(chunk)
                f.write(chunk)
        if digest.hexdigest() != sha:
            tmp.unlink(missing_ok=True)
            raise MediaError(f"{name}: checksum mismatch, download refused")
        tmp.replace(target)
        got.append(name)
    return got


# General American IPA (espeak-ng, an LLM) to Kokoro's phoneme set
IPA_MAP = (
    ("eɪ", "A"), ("aɪ", "I"), ("oʊ", "O"), ("əʊ", "O"), ("aʊ", "W"), ("ɔɪ", "Y"), ("dʒ", "ʤ"), ("tʃ", "ʧ"),
    ("ɝ", "ɜɹ"), ("ɚ", "əɹ"), ("r", "ɹ"), ("g", "ɡ"), ("ɫ", "l"), ("ː", ""), ("'", "ˈ"), (".", ""),
)  # fmt: skip


# a symbol standing alone between words, said as the word (misaki has no reading for it)
SYMBOL_WORDS = {
    "/": "slash", "=": "equals", "->": "to", "→": "to", "<-": "from", "←": "from", "*": "times", "×": "times",
    "<": "less than", ">": "greater than", "≤": "at most", "≥": "at least", "≠": "is not", "~": "about",
}  # fmt: skip
_SYMBOL = re.compile(
    r"(?<!\S)(" + "|".join(sorted(map(re.escape, SYMBOL_WORDS), key=len, reverse=True)) + r")(?!\S)"
)


def ipa_to_kokoro(ipa: str) -> str:
    out = ipa.strip().strip("/[]").split("\n")[0].replace(" ", "")
    for a, b in IPA_MAP:
        out = out.replace(a, b)
    return out


class Unknown(MediaError):
    def __init__(self, words: list[str]) -> None:
        super().__init__(f"no pronunciation for: {', '.join(words)}", kind="pronunciation")
        self.words = words


class KokoroTTS:
    name = "kokoro"
    version = "1"
    remote = False

    def __init__(
        self,
        model_dir: Path,
        *,
        voice: str = "af_heart",
        speed: float = 1.0,
        espeak: Espeak | None = None,
    ) -> None:
        self.model_dir = model_dir
        self.voice = voice
        self.speed = speed
        self.espeak = espeak if espeak is not None else Espeak()
        cfg = json.loads(resources.files("yuo.data").joinpath("kokoro.json").read_text(encoding="utf-8"))
        self.vocab: dict[str, int] = cfg["vocab"]
        self.sample_rate: int = cfg["sample_rate"]
        self.max_phonemes: int = cfg["max_phonemes"]
        self.lexicon: dict[str, str] = {}  # word -> Kokoro phonemes, set per path by the pipeline
        self._g2p: Any = None
        self._sess: Any = None
        self._voices: Any = None
        self._lock = threading.Lock()

    def available(self) -> str | None:
        missing = [f for f in MODEL_SHA256 if not (self.model_dir / f).exists()]
        return f"the Kokoro voice model is not installed ({', '.join(missing)})" if missing else None

    # --- text to phonemes --------------------------------------------------------------------------

    def _load_g2p(self) -> Any:
        if self._g2p is None:
            from misaki import en

            self._g2p = en.G2P(trf=False, british=False, fallback=self._fallback)
        return self._g2p

    def _fallback(self, token: Any) -> tuple[str | None, int]:
        word = token.text
        if word in self.lexicon:
            return self.lexicon[word], 1
        if word.lower() in self.lexicon:
            return self.lexicon[word.lower()], 1
        ipa = self.espeak.ipa(word)
        if ipa:
            return ipa_to_kokoro(ipa), 1
        return None, 0

    def phonemes(self, text: str) -> tuple[str, list[str]]:
        """Kokoro phonemes for a sentence and the words no source could pronounce."""
        text = _SYMBOL.sub(lambda m: SYMBOL_WORDS[m.group(1)], unicodedata.normalize("NFKC", text))
        with self._lock:
            ps, tokens = self._load_g2p()(text)
        # a token with no letters or digits (a stray symbol) is passed over, as the pronunciation stage does
        unknown = [
            t.text for t in tokens if (not t.phonemes or "❓" in t.phonemes) and re.search(r"\w", t.text)
        ]
        return ps.replace("❓", ""), unknown

    def learn(self, pronunciations: dict[str, str]) -> None:
        """General American IPA per word (the pronunciation stage), kept for this voice."""
        self.lexicon.update({w: ipa_to_kokoro(ipa) for w, ipa in pronunciations.items() if ipa.strip()})

    def unknown_words(self, texts: list[str]) -> list[str]:
        seen: dict[str, None] = {}
        for t in texts:
            for w in self.phonemes(t)[1]:
                if re.search(r"\w", w):
                    seen[w] = None
        return list(seen)

    # --- phonemes to audio -------------------------------------------------------------------------

    def _load_model(self) -> None:
        if self._sess is None:
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 2  # the 4 GB VPS also renders and serves
            self._sess = ort.InferenceSession(
                str(self.model_dir / "kokoro-v1.0.onnx"), opts, providers=["CPUExecutionProvider"]
            )
            self._voices = np.load(self.model_dir / "voices-v1.0.bin")

    def synthesize(self, text: str, out: Path) -> float:
        ps, unknown = self.phonemes(text)
        if unknown:
            raise Unknown(unknown)
        tokens = [self.vocab[p] for p in ps if p in self.vocab]
        if not tokens:
            raise MediaError(f"nothing to say in {text!r}")
        chunks = _split(tokens, self.max_phonemes)
        with self._lock:
            self._load_model()
            style_bank = self._voices[self.voice]
            audio = []
            for chunk in chunks:
                style = style_bank[min(len(chunk), len(style_bank)) - 1]
                wavform = self._sess.run(
                    None,
                    {
                        "tokens": np.array([[0, *chunk, 0]], dtype=np.int64),
                        "style": np.asarray(style, dtype=np.float32),
                        "speed": np.array([self.speed], dtype=np.float32),
                    },
                )[0]
                audio.append(np.asarray(wavform, dtype=np.float32).reshape(-1))
        write_wav(out, np.concatenate(audio), self.sample_rate)
        return 0.0


def _split(tokens: list[int], limit: int) -> list[list[int]]:
    return [tokens[i : i + limit] for i in range(0, len(tokens), limit)]
