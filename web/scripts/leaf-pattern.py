"""The ambient background's leaf pattern (Grove.module.css, `.leaves`): curved sprigs, drawn once here.

Each sprig is a cubic Bezier stem drawn as a tapered filled shape, with leaves set on the curve and turned with
it. Six variants (an S-bend, an arc with pairs, a forked branch, a drooping branch, a seedling, a fern) sit on a
jittered grid in one square tile, centred on their grid point, all leaning about 30 degrees clockwise (a small
tilt around that, some mirrored), sized differently, no two neighbours the same variant. Anything crossing an edge is drawn again on the opposite side, so the tile repeats
without a seam (the layer drifts by exactly one tile).

    python3 web/scripts/leaf-pattern.py            # prints the CSS `mask:` value
    python3 web/scripts/leaf-pattern.py --svg      # prints the tile SVG (for a preview)

Deterministic (a fixed seed): the same pattern comes out every time. "make the branches
more curvy rather than perfectly straight, and add a few variants so it is less repetitive".
"""

import math
import random
import sys
from urllib.parse import quote

TILE = 700  # px; the layer drifts by one tile
LEAN = 30  # degrees clockwise from vertical: the direction every sprig grows in, with the drift
TILT = 20  # degrees: each sprig varies at most this much around LEAN
GRID = 5  # sprigs per row and column
SEED = 11
LEAF_SCALE = 1.45  # leaves relative to the stems

Point = tuple[float, float]
Curve = list[Point]

# A leaf along +x with its base at the origin: a soft asymmetric blade with a slightly lifted tip.
LEAF = "M0 0C3 -5 9 -7.5 16 -3 11 3 5 4 0 0z"


def bez(p: Curve, t: float) -> Point:
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = p
    u = 1 - t
    return (
        u**3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t**3 * x3,
        u**3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * y3,
    )


def tangent(p: Curve, t: float) -> float:
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = p
    u = 1 - t
    dx = 3 * u * u * (x1 - x0) + 6 * u * t * (x2 - x1) + 3 * t * t * (x3 - x2)
    dy = 3 * u * u * (y1 - y0) + 6 * u * t * (y2 - y1) + 3 * t * t * (y3 - y2)
    return math.atan2(dy, dx)


def num(v: float) -> str:
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


class Sprig:
    """One variant: its SVG parts and the points it covers (for its centre)."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.points: list[Point] = []
        self.up = 0.0  # degrees the main stem's base-to-tip line leans right of straight up

    def stem(self, p: Curve, w0: float, w1: float = 0.6, n: int = 18) -> None:
        """The stem as a filled outline that thins from w0 at the base to w1 at the tip."""
        left, right = [], []
        for i in range(n + 1):
            t = i / n
            x, y = bez(p, t)
            a = tangent(p, t) + math.pi / 2
            w = (w0 + (w1 - w0) * t) / 2
            left.append((x + w * math.cos(a), y + w * math.sin(a)))
            right.append((x - w * math.cos(a), y - w * math.sin(a)))
            self.points.append((x, y))
        pts = left + right[::-1]
        self.parts.append("<path d='M" + " ".join(f"{num(x)} {num(y)}" for x, y in pts) + "z'/>")

    def leaf(self, x: float, y: float, deg: float, s: float, flip: bool = False) -> None:
        m = " scale(1 -1)" if flip else ""
        self.parts.append(
            f"<use href='#l' transform='translate({num(x)} {num(y)}) rotate({num(deg)}) "
            f"scale({round(s * LEAF_SCALE, 2)}){m}'/>"
        )
        r = math.radians(deg)
        reach = 14 * s * LEAF_SCALE
        self.points.append((x + reach * math.cos(r), y + reach * math.sin(r)))

    def branch(
        self, p: Curve, leaves: list[tuple[float, int, float]], w0: float = 2.8, tip: float = 0.0, lean: float = 48
    ) -> None:
        """leaves: (t, side +1/-1, size); a leaf leans `lean` degrees off the stem toward the tip."""
        if not self.parts:  # the first branch is the main stem: it sets the sprig's direction
            (x0, y0), (x3, y3) = p[0], p[3]
            self.up = math.degrees(math.atan2(x3 - x0, y0 - y3))
        self.stem(p, w0)
        for t, side, s in leaves:
            x, y = bez(p, t)
            a = math.degrees(tangent(p, t))
            self.leaf(x, y, a - lean * side, s, flip=side < 0)
        if tip:
            x, y = bez(p, 1)
            self.leaf(x, y, math.degrees(tangent(p, 1)), tip)

    def centre(self) -> Point:
        xs, ys = [x for x, _ in self.points], [y for _, y in self.points]
        return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2


def variants() -> dict[str, Sprig]:
    v: dict[str, Sprig] = {}
    # a: a gentle S-bend with alternating leaves
    a = Sprig()
    a.branch([(0, 0), (26, -22), (-24, -46), (6, -76)],
             [(0.22, 1, 1.0), (0.4, -1, 1.0), (0.58, 1, 0.9), (0.74, -1, 0.8), (0.88, 1, 0.62)], tip=0.7)
    v["a"] = a
    # b: an arc with opposite pairs
    b = Sprig()
    b.branch([(0, 0), (-10, -30), (20, -58), (52, -60)],
             [(0.3, 1, 0.95), (0.3, -1, 0.95), (0.56, 1, 0.82), (0.56, -1, 0.82), (0.8, 1, 0.66)], tip=0.66)
    v["b"] = b
    # c: a long sweep with a side twig
    c = Sprig()
    main: Curve = [(0, 0), (-4, -34), (40, -52), (34, -92)]
    fork = bez(main, 0.42)
    c.branch(main, [(0.16, 1, 0.95), (0.62, 1, 0.85), (0.76, -1, 0.78), (0.9, 1, 0.6)], w0=3.0, tip=0.65)
    c.branch([fork, (fork[0] - 14, fork[1] - 2), (-16, -44), (-30, -58)], [(0.5, 1, 0.7), (0.74, -1, 0.62)],
             w0=1.5, tip=0.6)
    v["c"] = c
    # d: a drooping branch, its leaves hanging from the outside of the bend
    d = Sprig()
    d.branch([(0, 0), (10, -40), (50, -52), (70, -26)],
             [(0.3, 1, 0.9), (0.46, 1, 0.85), (0.62, 1, 0.8), (0.78, 1, 0.7), (0.5, -1, 0.6)], tip=0.7, lean=60)
    v["d"] = d
    # e: a seedling: a short bent stem and two leaves
    e = Sprig()
    e.branch([(0, 0), (6, -10), (-8, -18), (0, -28)], [(0.95, 1, 0.95), (0.95, -1, 0.8)], w0=2.0)
    v["e"] = e
    # f: a fern: a long wavy stem with many small paired leaves
    f = Sprig()
    f.branch([(0, 0), (-18, -30), (22, -60), (4, -96)],
             [(t, side, 0.62 - 0.32 * t) for t in (0.18, 0.3, 0.42, 0.54, 0.66, 0.78, 0.88) for side in (1, -1)],
             w0=2.2, tip=0.4, lean=62)
    v["f"] = f
    return v  # fmt: skip


def places() -> tuple[list[tuple[str, float, float, int, float]], list[tuple[float, float, int, float]]]:
    """Sprigs on a jittered grid (variant k = (2 row + col) mod 6, so no two neighbours match, across the
    tile's edges too) and a loose leaf near about half of the grid's corners."""
    rnd = random.Random(SEED)  # noqa: S311 (a pattern, not a secret)
    cell = TILE / GRID
    sprigs, loose = [], []
    for i in range(GRID):
        for j in range(GRID):
            k = "abcdef"[(2 * i + j) % 6]
            x = (j + 0.5 + rnd.uniform(-0.17, 0.17)) * cell
            y = (i + 0.5 + rnd.uniform(-0.17, 0.17)) * cell
            tilt = LEAN + rnd.randint(-TILT, TILT)
            flip = rnd.random() < 0.5  # mirrored left to right: variety without changing the direction
            scale = round(rnd.uniform(0.85, 1.12), 2)
            sprigs.append((k, round(x), round(y), tilt, -scale if flip else scale))
            if rnd.random() < 0.55:
                lx = ((j + 1 + rnd.uniform(-0.12, 0.12)) * cell) % TILE
                ly = ((i + 1 + rnd.uniform(-0.12, 0.12)) * cell) % TILE
                loose.append((round(lx), round(ly), rnd.randrange(0, 360), round(rnd.uniform(0.95, 1.2), 2)))
    return sprigs, loose


def svg() -> str:
    vs = variants()
    defs = "".join(f"<g id='{k}'>{''.join(s.parts)}</g>" for k, s in vs.items())
    uses = []
    sprigs, loose = places()
    for k, x, y, r, s in sprigs:
        cx, cy = vs[k].centre()
        up = num(-vs[k].up)  # stand the sprig upright first, then tilt and mirror it
        for dx in (-TILE, 0, TILE):
            for dy in (-TILE, 0, TILE):
                if -90 < x + dx < TILE + 90 and -90 < y + dy < TILE + 90:
                    uses.append(
                        f"<use href='#{k}' transform='translate({x + dx} {y + dy}) rotate({r}) "
                        f"scale({s} {abs(s)}) rotate({up}) translate({num(-cx)} {num(-cy)})'/>"
                    )
    for x, y, r, s in loose:
        for dx in (-TILE, 0, TILE):
            for dy in (-TILE, 0, TILE):
                if -30 < x + dx < TILE + 30 and -30 < y + dy < TILE + 30:
                    uses.append(f"<use href='#l' transform='translate({x + dx} {y + dy}) rotate({r}) scale({s})'/>")
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {TILE} {TILE}'><defs><path id='l' d='{LEAF}'/>"
        f"{defs}</defs>{''.join(uses)}</svg>"
    )


def css() -> str:
    data = quote(svg(), safe=" /:=',.()-")
    return f'url("data:image/svg+xml,{data}") 0 0 / {TILE}px {TILE}px repeat'


if __name__ == "__main__":
    print(svg() if "--svg" in sys.argv else css())
