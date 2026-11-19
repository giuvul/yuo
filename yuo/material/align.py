"""Which slide a lecture recording is on at each moment: its transcript matched to a slide deck by the words
they share, in the lecture's order (a lecture goes through its slides forwards, sometimes skipping some).

Pure functions: no database, no model. A transcript chunk has a time span but no times per paragraph, so its
paragraphs share the span in proportion to their length.
"""

import math
import re
from collections import Counter

_WORD = re.compile(r"\w{4,}")
_SLIDE = re.compile(r"^\[Slide (\d+)(?::[^\]]*)?\]\s*$", re.M)
MIN_SCORE = 0.08  # below this a paragraph is not about any slide (an aside, a question from the room)


def slides_of(chunks: list[str]) -> dict[int, str]:
    """The text of every slide, from slide chunks (each slide starts with its "[Slide N: title]" label)."""
    out: dict[int, str] = {}
    for text in chunks:
        marks = list(_SLIDE.finditer(text))
        for k, m in enumerate(marks):
            end = marks[k + 1].start() if k + 1 < len(marks) else len(text)
            out[int(m.group(1))] = text[m.start() : end]
    return out


def paragraphs(chunks: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Transcript chunks (start ms, end ms, text) as paragraphs with their share of the chunk's span."""
    out = []
    for start, end, text in chunks:
        paras = [p for p in text.split("\n\n") if p.strip()]
        total = sum(len(p) for p in paras) or 1
        at = float(start)
        for p in paras:
            nxt = at + (end - start) * len(p) / total
            out.append((round(at), round(nxt), p))
            at = nxt
    return out


def _words(text: str) -> Counter[str]:
    return Counter(w.lower() for w in _WORD.findall(text) if not w.isdigit())


def align(paras: list[tuple[int, int, str]], slides: dict[int, str]) -> list[tuple[int, int, int, int]]:
    """Runs of the lecture on one slide: (start ms, end ms, slide, slide), in order.
    Each paragraph gets the best slide no earlier than the previous paragraph's (dynamic programming over the
    shared words, weighted by how rare a word is in the deck); paragraphs about no slide are left out."""
    if not paras or not slides:
        return []
    numbers = sorted(slides)
    bags = [_words(slides[n]) for n in numbers]
    df = Counter(w for b in bags for w in b)
    idf = {w: math.log((1 + len(bags)) / (1 + d)) + 1 for w, d in df.items()}

    def vec(b: Counter[str]) -> tuple[dict[str, float], float]:
        v = {w: (1 + math.log(c)) * idf.get(w, 0.0) for w, c in b.items() if w in idf}
        return v, math.sqrt(sum(x * x for x in v.values())) or 1.0

    sv = [vec(b) for b in bags]
    score = []
    for _, _, text in paras:
        pv, pn = vec(_words(text))
        score.append([sum(x * s[0].get(w, 0.0) for w, x in pv.items()) / (pn * s[1]) for s in sv])
    n, m = len(paras), len(numbers)
    best = [[0.0] * m for _ in range(n)]
    back = [[0] * m for _ in range(n)]
    for i in range(n):
        run, arg = -1.0, 0  # the best of the previous row up to slide j
        for j in range(m):
            if i and best[i - 1][j] > run:
                run, arg = best[i - 1][j], j
            gain = score[i][j] if score[i][j] >= MIN_SCORE else 0.0
            best[i][j] = (run if i else 0.0) + gain
            back[i][j] = arg
    j = max(range(m), key=lambda k: best[n - 1][k])
    path = [0] * n
    for i in range(n - 1, -1, -1):
        path[i] = j
        j = back[i][j]
    runs: list[tuple[int, int, int, int]] = []
    for i, (start, end, _) in enumerate(paras):
        if score[i][path[i]] < MIN_SCORE:
            continue
        slide = numbers[path[i]]
        if runs and runs[-1][3] == slide and start - runs[-1][1] < 120_000:
            a, _, first, _ = runs[-1]
            runs[-1] = (a, end, first, slide)
        else:
            runs.append((start, end, slide, slide))
    return runs


def slides_at(runs: list[tuple[int, int, int, int]], start: int, end: int) -> tuple[int, int] | None:
    """The slides shown between two moments of the lecture, or None."""
    hit = [r for r in runs if r[0] < end and r[1] > start]
    return (min(r[2] for r in hit), max(r[3] for r in hit)) if hit else None
